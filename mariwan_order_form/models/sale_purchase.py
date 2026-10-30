from odoo import api, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    mariwan_order_form_id = fields.Many2one('mariwan.order.form', 'Order Form', copy=False, index='btree_not_null',
                                            readonly=True)
    mariwan_payment_type = fields.Selection([('cash', 'Cash'), ('credit', 'Credit')], 'Payment Type',
                                            compute='_compute_mariwan_payment_type', store=True, readonly=False)
    mariwan_credit_override = fields.Boolean('Credit Block Overridden', copy=False, readonly=True, tracking=True)
    mariwan_amount_paid = fields.Monetary('Amount Paid', compute='_compute_mariwan_payment')
    mariwan_delivery_released = fields.Boolean('Delivery Released', compute='_compute_mariwan_payment')

    @api.depends('partner_id')
    def _compute_mariwan_payment_type(self):
        for order in self:
            if order.mariwan_order_form_id:
                order.mariwan_payment_type = order.mariwan_order_form_id.payment_type
            else:
                order.mariwan_payment_type = order.partner_id.commercial_partner_id.mariwan_customer_type or 'cash'

    def _mariwan_required_payment(self):
        self.ensure_one()
        if self.company_id.mariwan_cash_release_rule == 'advance':
            return self.currency_id.round(self.amount_total * self.company_id.mariwan_cash_advance_percent / 100.0)
        return self.amount_total

    @api.depends('invoice_ids.payment_state', 'invoice_ids.amount_residual', 'amount_total')
    def _compute_mariwan_payment(self):
        for order in self:
            invoices = order.invoice_ids.filtered(lambda m: m.state == 'posted')
            paid = sum((m.amount_total - m.amount_residual) * (-1 if m.move_type == 'out_refund' else 1)
                       for m in invoices)
            order.mariwan_amount_paid = paid
            order.mariwan_delivery_released = order.mariwan_payment_type != 'cash' or \
                order.currency_id.compare_amounts(paid, order._mariwan_required_payment()) >= 0

    # ------------------------------------------------------------------
    # Credit control (tasks 2.7 / 6.4, rule R6): standard credit limit, made blocking
    # ------------------------------------------------------------------
    def _mariwan_credit_issue(self):
        self.ensure_one()
        partner = self.partner_id.commercial_partner_id.sudo()
        if self.mariwan_payment_type != 'credit' or self.mariwan_credit_override:
            return False
        today = fields.Date.context_today(self)
        overdue = sum(self.env['account.move.line'].sudo().search([
            ('partner_id', 'child_of', partner.id),
            ('account_type', '=', 'asset_receivable'),
            ('parent_state', '=', 'posted'),
            ('reconciled', '=', False),
            ('date_maturity', '<', today),
            ('company_id', '=', self.company_id.id),
        ]).mapped('amount_residual'))
        if overdue > 0:
            return self.env._("the customer has overdue invoices (%s)", self.currency_id.format(overdue))
        limit = partner.with_company(self.company_id).credit_limit
        if limit and partner.credit + self.amount_total > limit:
            return self.env._("the credit limit %(limit)s would be exceeded (balance %(balance)s + order %(order)s)",
                              limit=self.currency_id.format(limit), balance=self.currency_id.format(partner.credit),
                              order=self.currency_id.format(self.amount_total))
        return False

    def action_confirm(self):
        for order in self:
            issue = order._mariwan_credit_issue()
            if issue:
                raise UserError(self.env._(
                    "Cannot confirm %(order)s: %(issue)s. A Finance Manager can override the credit block.",
                    order=order.name, issue=issue))
        res = super().action_confirm()
        for order in self.filtered('mariwan_order_form_id'):
            form = order.mariwan_order_form_id
            # The Order Form hold becomes the standard delivery reservation (flow B4).
            form.reservation_ids.filtered(lambda r: r.state == 'active').write({'state': 'converted'})
            if form.state not in ('cancel', 'closed'):
                form.state = 'confirmed'
            form._log(self.env._("Sales order %s confirmed.", order._get_html_link()))
        return res

    def action_mariwan_override_credit(self):
        if not self.env.user.has_group('mariwan_order_form.group_finance_manager'):
            raise UserError(self.env._("Only the Finance Manager can override the credit block."))
        for order in self.sudo():
            order.mariwan_credit_override = True
            order.message_post(body=self.env._("Credit block overridden by %s.", self.env.user.name),
                               author_id=self.env.user.partner_id.id)
        return True

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        vals['mariwan_order_form_id'] = self.mariwan_order_form_id.id
        return vals


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    mariwan_line_id = fields.Many2one('mariwan.order.form.line', 'Order Form Line', copy=False,
                                      index='btree_not_null')
    mariwan_delivery_date = fields.Date(related='mariwan_line_id.delivery_date', string='Tentative Delivery')
    mariwan_reservation_status = fields.Selection(related='mariwan_line_id.reservation_status',
                                                  string='Reservation')


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    mariwan_order_form_id = fields.Many2one('mariwan.order.form', 'Order Form', copy=False,
                                            index='btree_not_null', compute='_compute_mariwan_order_form_id',
                                            store=True, readonly=False)
    mariwan_delivery_type = fields.Selection([('warehouse', 'Warehouse'), ('dropship', 'Drop Ship to Customer')],
                                             'Delivery Type', compute='_compute_mariwan_delivery_type', store=True)
    # Task 7.2: import shipment details
    mariwan_container_no = fields.Char('Container / Shipment No.')
    mariwan_port_of_loading = fields.Char('Port of Loading')
    mariwan_eta = fields.Date('ETA')
    mariwan_shipping_company = fields.Char('Shipping Company')
    mariwan_bl_number = fields.Char('Bill of Lading No.')

    @api.depends('order_line.mariwan_line_id', 'order_line.sale_line_id')
    def _compute_mariwan_order_form_id(self):
        for po in self:
            form = po.order_line.mariwan_line_id.order_form_id[:1] \
                or po.order_line.sale_line_id.order_id.mariwan_order_form_id[:1]
            po.mariwan_order_form_id = form or po.mariwan_order_form_id

    @api.depends('picking_type_id.code')
    def _compute_mariwan_delivery_type(self):
        for po in self:
            po.mariwan_delivery_type = 'dropship' if po.picking_type_id.code == 'dropship' else 'warehouse'

    def button_confirm(self):
        # Flow D4: drop-ship order is placed after payment for cash customers.
        for po in self.filtered(lambda p: p.mariwan_delivery_type == 'dropship'):
            for order in po.order_line.sale_line_id.order_id:
                if not order.mariwan_delivery_released:
                    raise UserError(self.env._(
                        "%(po)s: %(so)s is a cash sale; register the customer payment before placing "
                        "the drop-ship order.", po=po.name, so=order.name))
        res = super().button_confirm()
        # Task 7.4: notify the approver when the PO waits for approval.
        approvers = self.env.ref('purchase.group_purchase_manager').all_user_ids.filtered(lambda u: not u.share)
        for po in self.filtered(lambda p: p.state == 'to approve'):
            for user in approvers.filtered(lambda u: po.company_id in u.company_ids)[:3]:
                po.activity_schedule('mail.mail_activity_data_todo', user_id=user.id,
                                     summary=self.env._("Purchase order to approve"))
        self.sudo().mariwan_order_form_id._update_state_from_lines()
        return res

    def button_approve(self, force=False):
        res = super().button_approve(force=force)
        self.activity_ids.filtered(lambda a: a.summary == self.env._("Purchase order to approve")).action_done()
        return res


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    mariwan_line_id = fields.Many2one('mariwan.order.form.line', 'Order Form Line', copy=False,
                                      index='btree_not_null', compute='_compute_mariwan_line_id', store=True,
                                      readonly=False)

    @api.depends('sale_line_id.mariwan_line_id')
    def _compute_mariwan_line_id(self):
        for line in self:
            line.mariwan_line_id = line.sale_line_id.mariwan_line_id or line.mariwan_line_id


class AccountMove(models.Model):
    _inherit = 'account.move'

    # Copied on reversal so credit notes keep the Order Form link (task 10.6).
    mariwan_order_form_id = fields.Many2one('mariwan.order.form', 'Order Form', index='btree_not_null')
