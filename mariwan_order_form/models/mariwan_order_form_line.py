from collections import defaultdict

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_round

FULFILMENT_TYPES = [
    ('stock', 'From Stock'),
    ('import', 'Order for Stock (Import)'),
    ('dropship', 'Drop Ship'),
]

COST_GROUP = 'mariwan_order_form.group_cost_access'


class MariwanOrderFormLine(models.Model):
    _name = 'mariwan.order.form.line'
    _description = 'Order Form Line'
    _order = 'order_form_id, sequence, id'
    _check_company_auto = True

    order_form_id = fields.Many2one('mariwan.order.form', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(related='order_form_id.company_id', store=True)
    currency_id = fields.Many2one(related='order_form_id.currency_id')
    partner_id = fields.Many2one(related='order_form_id.partner_id', store=True, string='Customer')
    warehouse_id = fields.Many2one(related='order_form_id.warehouse_id')
    form_state = fields.Selection(related='order_form_id.state', string='Order Form Status')
    user_id = fields.Many2one(related='order_form_id.user_id', store=True, string='Salesperson')

    # B1 - B6
    product_id = fields.Many2one('product.product', required=True, check_company=True,
                                 domain="[('sale_ok', '=', True)]")
    name = fields.Text('Description', compute='_compute_name', store=True, readonly=False, required=True,
                       precompute=True)
    categ_id = fields.Many2one(related='product_id.categ_id', store=True, string='Category')
    fulfilment_type = fields.Selection(FULFILMENT_TYPES, required=True, compute='_compute_fulfilment_type',
                                       store=True, readonly=False, precompute=True)
    product_uom_id = fields.Many2one('uom.uom', 'Unit', compute='_compute_product_uom_id', store=True,
                                     readonly=False, required=True, precompute=True)
    product_qty = fields.Float('Requested Qty', digits='Product Unit', required=True, default=1.0)

    # B7 - B12: real time, recomputed on every read
    on_hand_qty = fields.Float('On Hand', compute='_compute_availability', digits='Product Unit')
    reserved_other_qty = fields.Float('Reserved (Others)', compute='_compute_availability', digits='Product Unit')
    free_qty = fields.Float('Free', compute='_compute_availability', digits='Product Unit')
    incoming_qty = fields.Float('Incoming', compute='_compute_availability', digits='Product Unit')
    incoming_date = fields.Datetime('Next Arrival', compute='_compute_availability')
    availability_status = fields.Selection([
        ('available', 'Available'), ('partial', 'Partial'), ('not_available', 'Not Available'), ('na', 'N/A'),
    ], compute='_compute_availability', search='_search_availability_status')
    shortage_qty = fields.Float('Shortage', compute='_compute_availability', digits='Product Unit')

    # B13 - B15
    reservation_ids = fields.One2many('mariwan.reservation', 'line_id', 'Reservations')
    reserve_qty = fields.Float('Qty to Reserve', digits='Product Unit', copy=False,
                               help="Quantity to reserve with the Reserve button; empty reserves all available.")
    reserved_qty = fields.Float('Reserved', compute='_compute_reserved_qty', store=True, digits='Product Unit')
    reservation_status = fields.Selection([
        ('none', 'None'), ('reserved', 'Reserved'), ('partial', 'Partially Reserved'), ('released', 'Released'),
    ], compute='_compute_reserved_qty', store=True)
    delivery_date = fields.Date('Tentative Delivery Date', compute='_compute_delivery_date', store=True, readonly=False)

    # B16 - B20: vendor and cost block
    vendor_id = fields.Many2one('res.partner', 'Vendor', compute='_compute_vendor_id', store=True, readonly=False,
                                check_company=True)
    vendor_currency_id = fields.Many2one('res.currency', 'Vendor Currency', compute='_compute_vendor_cost',
                                         store=True, readonly=False, groups=COST_GROUP)
    vendor_unit_cost = fields.Monetary('Vendor Unit Cost', currency_field='vendor_currency_id',
                                       compute='_compute_vendor_cost', store=True, readonly=False, groups=COST_GROUP)
    exchange_rate = fields.Float('Rate', compute='_compute_costs', store=True, digits=(12, 6), groups=COST_GROUP)
    vendor_cost_aed = fields.Monetary('Vendor Cost (AED)', compute='_compute_costs', store=True, groups=COST_GROUP)
    dropship_extra_cost = fields.Monetary(
        'Drop Ship Delivery Costs', groups=COST_GROUP,
        help="Total vendor freight and other direct costs for this drop-ship line (AED).")
    estimated_landed_cost_unit = fields.Monetary('Estimated Landed Cost / Unit', compute='_compute_costs',
                                                 store=True, groups=COST_GROUP)
    actual_landed_cost_unit = fields.Monetary('Actual Landed Cost / Unit', readonly=True, copy=False,
                                              groups=COST_GROUP)
    landed_cost_is_actual = fields.Boolean('Actual Landed Cost', readonly=True, copy=False)
    landed_cost_unit = fields.Monetary('Landed Cost / Unit', compute='_compute_costs', store=True, groups=COST_GROUP)
    total_unit_cost = fields.Monetary('Total Unit Cost', compute='_compute_costs', store=True, groups=COST_GROUP)

    # B21 - B23: pricing from the standard pricelist rule
    pricelist_id = fields.Many2one('product.pricelist', compute='_compute_price', store=True)
    margin_percent = fields.Float('Margin %', compute='_compute_price', store=True, digits=(16, 2), groups=COST_GROUP)
    margin_override = fields.Float('Margin % Override', digits=(16, 2), copy=False, groups=COST_GROUP)
    is_price_overridden = fields.Boolean('Margin Overridden', copy=False, readonly=True)
    override_reason = fields.Char('Override Reason', copy=False)
    can_override_price = fields.Boolean(compute='_compute_can_override_price')
    price_unit = fields.Monetary('Unit Selling Price', compute='_compute_price', store=True)
    price_subtotal = fields.Monetary('Line Total', compute='_compute_price', store=True)
    cost_subtotal = fields.Monetary('Line Cost', compute='_compute_price', store=True, groups=COST_GROUP)
    margin_amount = fields.Monetary('Gross Margin', compute='_compute_price', store=True, groups=COST_GROUP)

    # B24 - B26
    purchase_line_ids = fields.One2many('purchase.order.line', 'mariwan_line_id', 'Purchase Lines')
    po_info = fields.Char('Linked PO', compute='_compute_po_info')
    po_qty_needed = fields.Float(compute='_compute_po_info', digits='Product Unit')
    sale_line_ids = fields.One2many('sale.order.line', 'mariwan_line_id', 'Sale Lines')
    line_status = fields.Selection([
        ('draft', 'Draft'), ('checked', 'Checked'), ('reserved', 'Reserved'),
        ('awaiting_stock', 'Awaiting Stock'), ('awaiting_vendor', 'Awaiting Vendor'),
        ('dispatched', 'Dispatched by Vendor'), ('delivered', 'Delivered'), ('cancel', 'Cancelled'),
    ], compute='_compute_line_status')
    remarks = fields.Char()

    _product_qty_positive = models.Constraint('CHECK(product_qty > 0)', 'The requested quantity must be greater than 0.')

    # ------------------------------------------------------------------
    # Defaults from the product
    # ------------------------------------------------------------------
    @api.depends('product_id')
    def _compute_name(self):
        for line in self:
            if line.product_id:
                line.name = line.product_id.get_product_multiline_description_sale()

    @api.depends('product_id')
    def _compute_fulfilment_type(self):
        for line in self:
            line.fulfilment_type = line.product_id.mariwan_fulfilment_type or 'stock'

    @api.depends('product_id')
    def _compute_product_uom_id(self):
        for line in self:
            line.product_uom_id = line.product_id.uom_id

    @api.depends('order_form_id.delivery_date')
    def _compute_delivery_date(self):
        for line in self:
            line.delivery_date = line.order_form_id.delivery_date

    # ------------------------------------------------------------------
    # Availability engine (task 5.3)
    # ------------------------------------------------------------------
    def _qty_to_product_uom(self, qty):
        self.ensure_one()
        return self.product_uom_id._compute_quantity(qty, self.product_id.uom_id) if self.product_uom_id else qty

    def _qty_from_product_uom(self, qty):
        self.ensure_one()
        return self.product_id.uom_id._compute_quantity(qty, self.product_uom_id) if self.product_uom_id else qty

    def _get_own_native_reserved(self):
        """Quantity reserved by Odoo on the deliveries of this line's own sales order."""
        moves = self.sale_line_ids.move_ids.filtered(
            lambda m: m.state not in ('done', 'cancel') and m.picking_type_id.code == 'outgoing')
        return sum(moves.mapped('quantity'))

    @api.depends('product_id', 'product_qty', 'product_uom_id', 'fulfilment_type', 'order_form_id.warehouse_id',
                 'reservation_ids.state', 'reservation_ids.quantity')
    def _compute_availability(self):
        Reservation = self.env['mariwan.reservation'].sudo()
        Move = self.env['stock.move'].sudo()
        for line in self:
            product = line.product_id
            warehouse = line.order_form_id.warehouse_id
            if not product or not warehouse or not product.is_storable:
                line.update({
                    'on_hand_qty': 0, 'reserved_other_qty': 0, 'free_qty': 0, 'incoming_qty': 0,
                    'incoming_date': False, 'shortage_qty': 0,
                    'availability_status': 'na' if line.fulfilment_type == 'dropship' or (product and not product.is_storable) else False,
                })
                continue
            product_wh = product.with_context(warehouse_id=warehouse.id)
            on_hand = product_wh.qty_available
            native_reserved = on_hand - product_wh.free_qty
            holds = Reservation.search([
                ('product_id', '=', product.id), ('warehouse_id', '=', warehouse.id), ('state', '=', 'active')])
            line_id = line._origin.id
            other_holds = holds.filtered(lambda r: r.line_id.id != line_id)
            reserved_others = max(native_reserved - line._get_own_native_reserved(), 0.0) \
                + sum(other_holds.mapped('quantity'))
            free = max(on_hand - reserved_others, 0.0)
            incoming_move = Move.search([
                ('product_id', '=', product.id),
                ('state', 'not in', ('done', 'cancel', 'draft')),
                ('location_dest_id', 'child_of', warehouse.view_location_id.id),
                ('location_id.usage', 'not in', ('internal', 'transit')),
            ], order='date', limit=1)
            requested = line._qty_to_product_uom(line.product_qty)
            if line.fulfilment_type == 'dropship':
                status = 'na'
            elif product.uom_id.compare(free, requested) >= 0:
                status = 'available'
            elif free > 0:
                status = 'partial'
            else:
                status = 'not_available'
            line.update({
                'on_hand_qty': line._qty_from_product_uom(on_hand),
                'reserved_other_qty': line._qty_from_product_uom(reserved_others),
                'free_qty': line._qty_from_product_uom(free),
                'incoming_qty': line._qty_from_product_uom(product_wh.incoming_qty),
                'incoming_date': incoming_move.date,
                'availability_status': status,
                'shortage_qty': 0.0 if line.fulfilment_type == 'dropship'
                else line._qty_from_product_uom(max(requested - free, 0.0)),
            })

    def _search_availability_status(self, operator, value):
        if operator not in ('in', 'not in'):
            return NotImplemented
        lines = self.search([('form_state', 'in', ('draft', 'checked', 'reserved', 'awaiting_stock',
                                                   'awaiting_vendor', 'quoted'))])
        return [('id', operator, lines.filtered(lambda l: l.availability_status in value).ids)]

    @api.depends('reservation_ids.state', 'reservation_ids.quantity', 'product_qty')
    def _compute_reserved_qty(self):
        for line in self:
            active = line.reservation_ids.filtered(lambda r: r.state == 'active')
            reserved = line._qty_from_product_uom(sum(active.mapped('quantity'))) if line.product_id else 0.0
            line.reserved_qty = reserved
            if reserved and float_compare(reserved, line.product_qty, precision_digits=4) >= 0:
                line.reservation_status = 'reserved'
            elif reserved:
                line.reservation_status = 'partial'
            elif line.reservation_ids.filtered(lambda r: r.state == 'released'):
                line.reservation_status = 'released'
            else:
                line.reservation_status = 'none'

    # ------------------------------------------------------------------
    # Reservation (task 5.5)
    # ------------------------------------------------------------------
    def _reserve(self, all_available=False):
        Reservation = self.env['mariwan.reservation']
        for line in self.filtered(lambda l: l.fulfilment_type != 'dropship' and l.product_id.is_storable):
            delivery_date = line.delivery_date or line.order_form_id.delivery_date
            if not delivery_date:
                raise UserError(self.env._(
                    "Set the tentative delivery date before reserving %s.", line.product_id.display_name))
            can_add = max(min(line.free_qty, line.product_qty) - line.reserved_qty, 0.0)
            qty = can_add if all_available or not line.reserve_qty else line.reserve_qty
            if float_compare(qty, can_add, precision_digits=4) > 0:
                raise UserError(self.env._(
                    "Cannot reserve %(qty)s of %(product)s: only %(free)s can still be reserved "
                    "(free quantity / requested quantity).",
                    qty=qty, product=line.product_id.display_name, free=can_add))
            if qty <= 0:
                continue
            Reservation.create({
                'line_id': line.id,
                'quantity': line._qty_to_product_uom(qty),
                'delivery_date': delivery_date,
            })
            line.reserve_qty = 0.0

    def action_reserve_line(self):
        self.order_form_id._ensure_state(
            ('draft', 'checked', 'reserved', 'awaiting_stock', 'awaiting_vendor', 'quoted'), self.env._("Reserve"))
        self._reserve()
        self.order_form_id._update_state_from_lines()
        return True

    def action_release_line(self):
        self.reservation_ids.filtered(lambda r: r.state == 'active').action_release()
        self.order_form_id._update_state_from_lines()
        return True

    def action_open_availability(self):
        """C: shortage flag popup."""
        self.ensure_one()
        popup = self.env['mariwan.availability.popup'].create({'line_id': self.id})
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Availability - %s", self.product_id.display_name),
            'res_model': 'mariwan.availability.popup',
            'res_id': popup.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ------------------------------------------------------------------
    # Vendor, cost and price (tasks 5.7, 5.8, 8.5)
    # ------------------------------------------------------------------
    @api.depends('product_id', 'fulfilment_type')
    def _compute_vendor_id(self):
        for line in self:
            if line.fulfilment_type == 'stock' or not line.product_id:
                line.vendor_id = False
            elif not line.vendor_id:
                line.vendor_id = line.product_id.seller_ids[:1].partner_id

    @api.depends('product_id', 'fulfilment_type', 'vendor_id', 'product_uom_id')
    def _compute_vendor_cost(self):
        for line in self:
            company_currency = line.company_id.currency_id or self.env.company.currency_id
            if line.fulfilment_type == 'stock' or not line.product_id:
                line.vendor_currency_id = company_currency
                line.vendor_unit_cost = 0.0
                continue
            seller = line.product_id._select_seller(
                partner_id=line.vendor_id or False, quantity=line.product_qty, uom_id=line.product_uom_id
            ).get('supplierinfo') or line.product_id.seller_ids.filtered(
                lambda s: not line.vendor_id or s.partner_id == line.vendor_id)[:1]
            line.vendor_currency_id = seller.currency_id or line.vendor_id.property_purchase_currency_id \
                or company_currency
            price = seller.price if seller else 0.0
            if seller and seller.uom_id and line.product_uom_id:
                price = seller.uom_id._compute_price(price, line.product_uom_id)
            line.vendor_unit_cost = price

    @api.depends('fulfilment_type', 'product_id', 'product_uom_id', 'product_qty', 'vendor_currency_id',
                 'vendor_unit_cost', 'dropship_extra_cost', 'actual_landed_cost_unit', 'landed_cost_is_actual')
    def _compute_costs(self):
        for line in self:
            company = line.company_id or self.env.company
            company_currency = company.currency_id
            date = line.order_form_id.date or fields.Date.context_today(line)
            vendor_currency = line.vendor_currency_id or company_currency
            line.exchange_rate = self.env['res.currency']._get_conversion_rate(
                vendor_currency, company_currency, company, date)
            line.vendor_cost_aed = vendor_currency._convert(line.vendor_unit_cost, company_currency, company, date)
            if line.fulfilment_type == 'stock':
                # Average cost already includes the validated landed costs.
                avg = line.product_id.with_company(company).standard_price
                if line.product_uom_id:
                    avg = line.product_id.uom_id._compute_price(avg, line.product_uom_id)
                line.estimated_landed_cost_unit = 0.0
                line.landed_cost_unit = 0.0
                line.total_unit_cost = avg
                continue
            if line.fulfilment_type == 'dropship':
                estimate = line.dropship_extra_cost / line.product_qty if line.product_qty else 0.0
                line.estimated_landed_cost_unit = estimate
                line.landed_cost_unit = estimate
            else:
                percent = line.product_id.categ_id.mariwan_landed_cost_estimate
                estimate = line.vendor_cost_aed * percent / 100.0
                line.estimated_landed_cost_unit = estimate
                line.landed_cost_unit = line.actual_landed_cost_unit if line.landed_cost_is_actual else estimate
            line.total_unit_cost = line.vendor_cost_aed + line.landed_cost_unit

    @api.depends('order_form_id.partner_id', 'product_id', 'product_qty', 'product_uom_id', 'total_unit_cost',
                 'margin_override', 'is_price_overridden')
    def _compute_price(self):
        """Price from the customer's standard pricelist (task 5.8 / 9.1):
        * fixed-price rule (per-item UAE / GCC price list): that price is used;
        * markup rule: total unit cost x (1 + margin %), rounded per the rule.
        A Pricing Manager override replaces the margin %."""
        for line in self:
            partner = line.order_form_id.partner_id
            pricelist = partner.property_product_pricelist if partner else False
            currency = line.currency_id or self.env.company.currency_id
            line.pricelist_id = pricelist
            cost = line.total_unit_cost
            fixed_price, margin, rounding = None, 0.0, 0.0
            if pricelist and line.product_id:
                date = line.order_form_id.date or fields.Date.context_today(line)
                rule = self.env['product.pricelist.item'].browse(pricelist._get_product_rule(
                    line.product_id, quantity=line.product_qty, uom=line.product_uom_id, date=date))
                if rule.compute_price == 'fixed':
                    fixed_price = pricelist._get_product_price(
                        line.product_id, quantity=line.product_qty, uom=line.product_uom_id, date=date)
                elif rule and rule.compute_price in ('markup', 'discount'):
                    margin = rule.price_markup
                    rounding = rule.price_round
            if line.is_price_overridden:
                fixed_price, margin = None, line.margin_override
            if fixed_price is not None:
                price = currency.round(fixed_price)
                margin = (price / cost - 1) * 100 if cost else 0.0
            else:
                price = cost * (1 + margin / 100.0)
                price = float_round(price, precision_rounding=rounding) if rounding else currency.round(price)
            line.margin_percent = margin
            line.price_unit = price
            line.price_subtotal = currency.round(price * line.product_qty)
            line.cost_subtotal = currency.round(cost * line.product_qty)
            line.margin_amount = line.price_subtotal - line.cost_subtotal

    def _compute_can_override_price(self):
        self.can_override_price = self.env.user.has_group('mariwan_order_form.group_pricing_manager')

    def _update_actual_landed_cost(self):
        """Task 8.5: actual landed cost per unit from validated landed costs on this line's receipts."""
        AdjLine = self.env['stock.valuation.adjustment.lines'].sudo()
        for line in self.filtered(lambda l: l.fulfilment_type == 'import'):
            moves = line.purchase_line_ids.move_ids.filtered(lambda m: m.state == 'done')
            if not moves:
                continue
            adjustments = AdjLine.search([('move_id', 'in', moves.ids), ('cost_id.state', '=', 'done')])
            if not adjustments:
                continue
            qty = sum(moves.mapped('quantity'))
            per_unit = sum(adjustments.mapped('additional_landed_cost')) / qty if qty else 0.0
            per_unit = line.product_id.uom_id._compute_price(per_unit, line.product_uom_id)
            old_price = line.price_unit
            line.write({'actual_landed_cost_unit': per_unit, 'landed_cost_is_actual': True})
            if line.currency_id.compare_amounts(old_price, line.price_unit):
                line.order_form_id._log(self.env._(
                    "Actual landed cost validated for %(product)s: selling price changed from %(old)s to %(new)s.",
                    product=line.product_id.display_name,
                    old=line.currency_id.format(old_price), new=line.currency_id.format(line.price_unit)))

    # ------------------------------------------------------------------
    # Price override control (task 9.2)
    # ------------------------------------------------------------------
    def write(self, vals):
        if 'margin_override' in vals or 'is_price_overridden' in vals:
            if not self.env.su and not self.env.user.has_group('mariwan_order_form.group_pricing_manager'):
                raise UserError(self.env._("Only the Pricing Manager can change the margin."))
            overrides = {line: line.margin_percent for line in self}
            if 'margin_override' in vals and 'is_price_overridden' not in vals:
                vals['is_price_overridden'] = True
            reason = vals.get('override_reason')
            for line in self:
                if vals.get('is_price_overridden', line.is_price_overridden) and not (reason or line.override_reason):
                    raise UserError(self.env._("A reason is required to override the margin of %s.",
                                               line.product_id.display_name))
            res = super().write(vals)
            for line, old in overrides.items():
                line.order_form_id._log(self.env._(
                    "Margin override on %(product)s: %(old)s%% -> %(new)s%%, selling price %(price)s "
                    "(reason: %(reason)s)",
                    price=line.currency_id.format(line.price_unit),
                    product=line.product_id.display_name, old=old, new=line.margin_percent,
                    reason=line.override_reason))
            return res
        return super().write(vals)

    # ------------------------------------------------------------------
    # Purchase and status (tasks 5.10, 6.2)
    # ------------------------------------------------------------------
    @api.depends('purchase_line_ids.order_id.state', 'purchase_line_ids.product_qty', 'shortage_qty')
    def _compute_po_info(self):
        for line in self:
            plines = line.purchase_line_ids.filtered(lambda p: p.order_id.state != 'cancel')
            line.po_info = ', '.join(
                f"{p.order_id.name} ({dict(p.order_id._fields['state'].selection).get(p.order_id.state)}, "
                f"{fields.Date.to_string(p.date_planned.date()) if p.date_planned else '-'})" for p in plines)
            ordered = sum(p.uom_id._compute_quantity(p.product_qty, line.product_uom_id) for p in plines)
            line.po_qty_needed = max(line.shortage_qty - ordered, 0.0) if line.fulfilment_type == 'import' else 0.0

    def _create_purchase_orders(self):
        lines_by_vendor = defaultdict(lambda: self.env['mariwan.order.form.line'])
        for line in self:
            if not line.vendor_id:
                raise UserError(self.env._("Set the vendor on %s first.", line.product_id.display_name))
            lines_by_vendor[(line.order_form_id, line.vendor_id, line.sudo().vendor_currency_id)] |= line
        purchases = self.env['purchase.order']
        for (form, vendor, currency), lines in lines_by_vendor.items():
            po = self.env['purchase.order'].create({
                'partner_id': vendor.id,
                'currency_id': currency.id or form.currency_id.id,
                'picking_type_id': form.warehouse_id.in_type_id.id,
                'origin': form.name,
                'mariwan_order_form_id': form.id,
                'mariwan_delivery_type': 'warehouse',
                'order_line': [Command.create({
                    'product_id': line.product_id.id,
                    'name': line.name,
                    'product_qty': line.po_qty_needed,
                    'uom_id': line.product_uom_id.id,
                    'price_unit': line.sudo().vendor_unit_cost,
                    'tax_ids': [Command.clear()],
                    'date_planned': line.delivery_date or fields.Datetime.now(),
                    'mariwan_line_id': line.id,
                }) for line in lines],
            })
            purchases |= po
            form.message_post(body=self.env._("Draft purchase order %s created for review.", po._get_html_link()))
        return purchases

    def _compute_line_status(self):
        for line in self:
            form_state = line.order_form_id.state
            sale_lines = line.sale_line_ids.filtered(lambda s: s.state == 'sale')
            if form_state == 'cancel':
                status = 'cancel'
            elif sale_lines and sum(sale_lines.mapped('qty_delivered')) >= line.product_qty:
                status = 'delivered'
            elif line.fulfilment_type == 'dropship' and sale_lines:
                dropship = sale_lines.move_ids.picking_id.filtered(lambda p: p.picking_type_code == 'dropship')
                if dropship.filtered(lambda p: p.carrier_tracking_ref or p.mariwan_dispatch_date):
                    status = 'dispatched'
                else:
                    status = 'awaiting_vendor'
            elif line.reserved_qty and line.reservation_status == 'reserved':
                status = 'reserved'
            elif line.fulfilment_type == 'import' and line.purchase_line_ids.filtered(
                    lambda p: p.order_id.state != 'cancel'):
                status = 'awaiting_stock'
            elif line.reserved_qty:
                status = 'reserved'
            elif form_state != 'draft':
                status = 'checked'
            else:
                status = 'draft'
            line.line_status = status

    # ------------------------------------------------------------------
    # Validation rules (task 6.7)
    # ------------------------------------------------------------------
    @api.constrains('fulfilment_type', 'vendor_id')
    def _check_vendor(self):
        for line in self:
            if line.fulfilment_type in ('import', 'dropship') and not line.vendor_id \
                    and line.order_form_id.state not in ('draft', 'cancel'):
                raise ValidationError(self.env._(
                    "Vendor is mandatory for Import and Drop Ship lines (%s).", line.product_id.display_name))

    def _check_line_for_check(self):
        for line in self:
            if line.fulfilment_type in ('import', 'dropship') and not line.vendor_id:
                raise UserError(self.env._(
                    "Vendor is mandatory for Import and Drop Ship lines (%s).", line.product_id.display_name))
            if line.fulfilment_type == 'dropship' and not line.order_form_id.partner_shipping_id:
                raise UserError(self.env._("A delivery address is mandatory for Drop Ship lines."))

    def _check_line_for_quote(self):
        self._check_line_for_check()
        for line in self:
            if line.sudo().total_unit_cost <= 0:
                raise UserError(self.env._(
                    "Cannot quote %s without a cost. Ask a cost-authorised user to enter the vendor cost.",
                    line.product_id.display_name))
