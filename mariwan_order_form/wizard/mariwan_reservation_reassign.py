from odoo import api, fields, models
from odoo.exceptions import UserError


class MariwanReservationReassign(models.TransientModel):
    """Task 6.5: Sales Manager re-assigns held stock to another Order Form line, with a reason."""
    _name = 'mariwan.reservation.reassign'
    _description = 'Re-assign Reservation'

    reservation_id = fields.Many2one('mariwan.reservation', required=True, ondelete='cascade')
    product_id = fields.Many2one(related='reservation_id.product_id')
    quantity = fields.Float('Quantity to Re-assign', digits='Product Unit', required=True,
                            compute='_compute_quantity', store=True, readonly=False)
    target_line_id = fields.Many2one(
        'mariwan.order.form.line', 'Give To', required=True,
        domain="[('product_id', '=', product_id), ('id', '!=', source_line_id),"
               " ('form_state', 'not in', ('cancel', 'closed', 'delivered'))]")
    source_line_id = fields.Many2one(related='reservation_id.line_id')
    reason = fields.Char(required=True)

    @api.depends('reservation_id')
    def _compute_quantity(self):
        for wizard in self:
            wizard.quantity = wizard.reservation_id.quantity

    def action_confirm(self):
        self.ensure_one()
        if not self.env.user.has_group('mariwan_order_form.group_sales_manager'):
            raise UserError(self.env._("Only the Sales Manager can re-assign a reservation."))
        res = self.reservation_id
        if res.state != 'active' or self.quantity <= 0 or self.quantity > res.quantity:
            raise UserError(self.env._("Re-assign a positive quantity up to %s.", res.quantity))
        target = self.target_line_id
        source_form = res.order_form_id
        keep = res.quantity - self.quantity
        res.with_context(mariwan_release_reason=self.env._(
            "Re-assigned to %(form)s: %(reason)s", form=target.order_form_id.name, reason=self.reason)).action_release()
        Reservation = self.env['mariwan.reservation'].sudo()
        if keep > 0:
            Reservation.create({'line_id': res.line_id.id, 'quantity': keep, 'delivery_date': res.delivery_date})
        Reservation.create({
            'line_id': target.id,
            'quantity': self.quantity,
            'delivery_date': target.delivery_date or target.order_form_id.delivery_date or res.delivery_date,
        })
        source_form.reservation_flagged = True
        source_form.activity_schedule(
            'mail.mail_activity_data_todo', user_id=source_form.user_id.id,
            summary=self.env._("Reservation re-assigned"),
            note=self.env._("%(qty)s of %(product)s was re-assigned to %(form)s by %(user)s. Reason: %(reason)s",
                            qty=self.quantity, product=res.product_id.display_name,
                            form=target.order_form_id.name, user=self.env.user.name, reason=self.reason))
        target.order_form_id._update_state_from_lines()
        source_form._update_state_from_lines()
        return {'type': 'ir.actions.act_window_close'}
