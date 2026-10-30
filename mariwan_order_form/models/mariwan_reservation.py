from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class MariwanReservation(models.Model):
    """Stock held for a customer before the sales order exists (tasks 5.5, 6.5, 6.6).

    Once the sales order is confirmed the hold is 'converted': Odoo's own
    delivery reservation takes over."""
    _name = 'mariwan.reservation'
    _description = 'Order Form Reservation'
    _inherit = ['mail.thread']
    _order = 'reserved_on desc, id desc'

    name = fields.Char(required=True, copy=False, readonly=True, default='New')
    line_id = fields.Many2one('mariwan.order.form.line', 'Order Form Line', required=True, ondelete='cascade',
                              index=True)
    order_form_id = fields.Many2one(related='line_id.order_form_id', store=True, index=True)
    company_id = fields.Many2one(related='line_id.company_id', store=True)
    partner_id = fields.Many2one(related='line_id.partner_id', store=True, string='Customer')
    user_id = fields.Many2one(related='line_id.user_id', store=True, string='Salesperson')
    product_id = fields.Many2one(related='line_id.product_id', store=True, index=True)
    warehouse_id = fields.Many2one(related='line_id.order_form_id.warehouse_id', store=True, index=True)
    product_uom_id = fields.Many2one(related='product_id.uom_id', string='Unit')
    quantity = fields.Float('Reserved Qty', digits='Product Unit', required=True, tracking=True,
                            help="In the product's unit of measure.")
    delivery_date = fields.Date('Tentative Delivery Date', required=True, tracking=True)
    hold_until = fields.Date(compute='_compute_hold_until', store=True,
                             help="Tentative delivery date plus the grace period set in the settings.")
    reserved_by = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
    reserved_on = fields.Datetime(default=fields.Datetime.now, readonly=True)
    state = fields.Selection([
        ('active', 'Reserved'), ('converted', 'Converted to Delivery'), ('released', 'Released'),
    ], default='active', required=True, tracking=True, index=True)
    released_by = fields.Many2one('res.users', readonly=True, copy=False)
    released_on = fields.Datetime(readonly=True, copy=False)
    release_reason = fields.Char(tracking=True, copy=False)
    sale_order_id = fields.Many2one('sale.order', compute='_compute_sale_order_id', string='Sales Order')
    expiry_alerted = fields.Boolean(copy=False)

    @api.depends('delivery_date', 'company_id.mariwan_reservation_grace_days')
    def _compute_hold_until(self):
        for res in self:
            res.hold_until = res.delivery_date and res.delivery_date + timedelta(
                days=res.company_id.mariwan_reservation_grace_days)

    def _compute_sale_order_id(self):
        for res in self:
            res.sale_order_id = res.line_id.sale_line_ids.order_id.filtered(lambda s: s.state != 'cancel')[:1]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('mariwan.reservation') or 'New'
        reservations = super().create(vals_list)
        for res in reservations:
            if res.quantity <= 0:
                raise UserError(self.env._("The reserved quantity must be positive."))
            res.order_form_id.message_post(body=self.env._(
                "Reserved %(qty)s %(uom)s of %(product)s until %(date)s.",
                qty=res.quantity, uom=res.product_uom_id.name, product=res.product_id.display_name,
                date=res.hold_until))
        return reservations

    def action_release(self):
        reason = self.env.context.get('mariwan_release_reason') or self.env._("Released by user")
        for res in self.filtered(lambda r: r.state == 'active'):
            res.write({
                'state': 'released',
                'released_by': self.env.uid,
                'released_on': fields.Datetime.now(),
                'release_reason': reason,
            })
            res.order_form_id.message_post(body=self.env._(
                "Released reservation %(name)s: %(qty)s of %(product)s (%(reason)s).",
                name=res.name, qty=res.quantity, product=res.product_id.display_name, reason=reason))
        return True

    def action_reassign(self):
        """Task 6.5: only the Sales Manager can give held stock to another order, with a reason."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._("Re-assign Reservation"),
            'res_model': 'mariwan.reservation.reassign',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_reservation_id': self.id},
        }

    # ------------------------------------------------------------------
    # Daily alerts (task 6.6): visible alert, never a silent release
    # ------------------------------------------------------------------
    def _alert_users(self, form):
        managers = self.env.ref('mariwan_order_form.group_sales_manager').all_user_ids.filtered(
            lambda u: not u.share and form.company_id in u.company_ids)
        return (form.user_id | managers)

    @api.model
    def _cron_alerts(self):
        today = fields.Date.context_today(self)
        expired = self.search([('state', '=', 'active'), ('hold_until', '<', today), ('expiry_alerted', '=', False)])
        for res in expired:
            for user in self._alert_users(res.order_form_id):
                res.order_form_id.activity_schedule(
                    'mail.mail_activity_data_todo', user_id=user.id,
                    summary=self.env._("Reservation %s passed its hold-until date", res.name),
                    note=self.env._("%(qty)s of %(product)s held for %(customer)s since %(date)s. "
                                    "Release or extend it.", qty=res.quantity,
                                    product=res.product_id.display_name, customer=res.partner_id.name,
                                    date=res.hold_until))
            res.expiry_alerted = True
        overdue_forms = self.env['mariwan.order.form'].search([
            ('delivery_date', '<', today),
            ('state', 'not in', ('delivered', 'closed', 'cancel')),
        ])
        for form in overdue_forms:
            summary = self.env._("Tentative delivery date overdue")
            if not form.activity_ids.filtered(lambda a: a.summary == summary):
                form.activity_schedule('mail.mail_activity_data_todo', user_id=form.user_id.id,
                                       summary=summary, date_deadline=today)
