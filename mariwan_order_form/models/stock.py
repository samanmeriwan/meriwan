from odoo import api, fields, models
from odoo.exceptions import UserError


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _mariwan_free_after_holds(self, location_id):
        """Quantity (product UoM) this move may still reserve once the Order Form holds
        of other customers are kept aside, or None when no hold applies."""
        if self.picking_type_id.code != 'outgoing' or location_id.should_bypass_reservation():
            return None
        warehouse = location_id.warehouse_id
        if not warehouse:
            return None
        own_form = self.sale_line_id.order_id.mariwan_order_form_id
        held = self.env['mariwan.reservation'].sudo().search([
            ('product_id', '=', self.product_id.id),
            ('warehouse_id', '=', warehouse.id),
            ('state', '=', 'active'),
            ('order_form_id', '!=', own_form.id),
        ])
        if not held:
            return None
        available = self.env['stock.quant']._get_available_quantity(self.product_id, warehouse.lot_stock_id)
        return max(available - sum(held.mapped('quantity')), 0.0)

    def _update_reserved_quantity_vals(self, need, location_id, lot_id=None, package_id=None, owner_id=None,
                                       strict=True):
        """Rule R2: stock held on an Order Form for one customer is not reserved
        by deliveries of other customers."""
        free = self._mariwan_free_after_holds(location_id)
        if free is not None:
            free = self.product_id.uom_id._compute_quantity(free, self.uom_id)
            if self.uom_id.compare(free, 0) <= 0:
                return [], 0
            need = min(need, free)
        return super()._update_reserved_quantity_vals(need, location_id, lot_id=lot_id, package_id=package_id,
                                                      owner_id=owner_id, strict=strict)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    mariwan_dispatch_date = fields.Date('Vendor Dispatch Date', copy=False,
                                        help="Drop ship: date the vendor dispatched the goods.")
    mariwan_receiver_name = fields.Char('Received By', copy=False)
    mariwan_condition_remarks = fields.Char('Condition Remarks', copy=False)
    mariwan_order_form_id = fields.Many2one('mariwan.order.form', compute='_compute_mariwan_order_form_id',
                                            string='Order Form')
    mariwan_package_count = fields.Integer(
        'Number of Packages', compute='_compute_mariwan_package_count', store=True, readonly=False,
        help="Printed on the delivery challan and packing slip. Defaults to the packed packages, else 1.")

    @api.depends('move_line_ids.result_package_id')
    def _compute_mariwan_package_count(self):
        for picking in self:
            picking.mariwan_package_count = len(picking.move_line_ids.result_package_id) or 1

    def _compute_mariwan_order_form_id(self):
        for picking in self.sudo():
            picking.mariwan_order_form_id = picking.sale_id.mariwan_order_form_id \
                or picking.purchase_id.mariwan_order_form_id

    def button_validate(self):
        self._mariwan_check_cash_payment()
        self._mariwan_check_return_reason()
        return super().button_validate()

    def _mariwan_check_return_reason(self):
        """Flow E3: a customer return needs a reason (Condition Remarks)."""
        missing = self.filtered(lambda p: p.picking_type_code == 'incoming' and p.return_id
                                and not p.mariwan_condition_remarks)
        if missing:
            raise UserError(self.env._(
                "Enter the return reason in Condition Remarks before validating %s.",
                ', '.join(missing.mapped('name'))))

    def _mariwan_check_cash_payment(self):
        """Tasks 6.4 / 10.2 (rule R5): cash customers - delivery released once payment is registered."""
        for picking in self.sudo().filtered(lambda p: p.picking_type_code in ('outgoing', 'dropship') and p.sale_id):
            order = picking.sale_id
            if order.mariwan_payment_type != 'cash' or order.mariwan_delivery_released:
                continue
            raise UserError(self.env._(
                "%(order)s is a cash sale: register the customer payment before validating %(picking)s "
                "(paid %(paid)s of %(total)s, required %(required)s).",
                order=order.name, picking=picking.name,
                paid=order.currency_id.format(order.mariwan_amount_paid),
                total=order.currency_id.format(order.amount_total),
                required=order.currency_id.format(order._mariwan_required_payment())))

    def _action_done(self):
        res = super()._action_done()
        pickings = self.sudo()
        pickings._mariwan_assign_received_stock()
        forms = pickings.sale_id.mariwan_order_form_id | pickings.purchase_id.mariwan_order_form_id
        forms._update_progress()
        return res

    def _mariwan_assign_received_stock(self):
        """Task 6.2 / flow C7: received import stock is reserved first for the waiting customer."""
        Reservation = self.env['mariwan.reservation'].sudo()
        for move in self.move_ids.filtered(lambda m: m.state == 'done' and m.purchase_line_id.mariwan_line_id):
            line = move.purchase_line_id.mariwan_line_id
            if line.order_form_id.state in ('cancel', 'closed', 'delivered') or line.fulfilment_type != 'import':
                continue
            missing = line._qty_to_product_uom(line.product_qty - line.reserved_qty)
            received = move.uom_id._compute_quantity(move.quantity, move.product_id.uom_id)
            qty = min(missing, received)
            if qty <= 0:
                continue
            if line.order_form_id.state == 'confirmed':
                continue  # the sales order delivery reserves it through standard Odoo
            Reservation.create({
                'line_id': line.id,
                'quantity': qty,
                'delivery_date': line.delivery_date or line.order_form_id.delivery_date or fields.Date.today(),
            })
            line.order_form_id._update_state_from_lines()


class StockLandedCost(models.Model):
    _inherit = 'stock.landed.cost'

    def _get_targeted_move_ids(self):
        # With Manufacturing installed, mrp_landed_costs reads mrp_production_ids here, which is
        # restricted to Inventory Administrators: the Accountant must still be able to validate.
        return super(StockLandedCost, self.sudo())._get_targeted_move_ids().with_env(self.env)

    def button_validate(self):
        res = super().button_validate()
        # Task 8.3 / 8.5: the new cost flows to the Order Form.
        lines = self.sudo().valuation_adjustment_lines.move_id.purchase_line_id.mariwan_line_id
        lines._update_actual_landed_cost()
        return res
