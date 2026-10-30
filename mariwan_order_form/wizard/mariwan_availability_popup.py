from odoo import fields, models


class MariwanAvailabilityPopup(models.TransientModel):
    """Task 5.4 / section C: shortage flag popup."""
    _name = 'mariwan.availability.popup'
    _description = 'Order Form Availability Details'

    line_id = fields.Many2one('mariwan.order.form.line', required=True, ondelete='cascade')
    order_form_id = fields.Many2one(related='line_id.order_form_id')
    product_id = fields.Many2one(related='line_id.product_id')
    warehouse_id = fields.Many2one(related='line_id.warehouse_id')
    product_uom_id = fields.Many2one(related='line_id.product_uom_id')
    on_hand_qty = fields.Float(related='line_id.on_hand_qty')
    reserved_other_qty = fields.Float(related='line_id.reserved_other_qty', string='Total Reserved (Others)')
    free_qty = fields.Float(related='line_id.free_qty')
    product_qty = fields.Float(related='line_id.product_qty')
    shortage_qty = fields.Float(related='line_id.shortage_qty')
    reserved_qty = fields.Float(related='line_id.reserved_qty', string='Reserved (This Customer)')
    reservation_ids = fields.Many2many('mariwan.reservation', compute='_compute_tables', string='Reservations')
    incoming_line_ids = fields.Many2many('purchase.order.line', compute='_compute_tables', string='Incoming')
    is_sales_manager = fields.Boolean(compute='_compute_tables')

    def _compute_tables(self):
        is_manager = self.env.user.has_group('mariwan_order_form.group_sales_manager')
        for popup in self:
            popup.is_sales_manager = is_manager
            popup.reservation_ids = self.env['mariwan.reservation'].search([
                ('product_id', '=', popup.product_id.id),
                ('warehouse_id', '=', popup.warehouse_id.id),
                ('state', '=', 'active'),
            ])
            popup.incoming_line_ids = self.env['purchase.order.line'].search([
                ('product_id', '=', popup.product_id.id),
                ('order_id.state', 'in', ('purchase', 'to approve', 'draft', 'sent')),
                ('order_id.picking_type_id.warehouse_id', '=', popup.warehouse_id.id),
                ('order_id.picking_type_id.code', '=', 'incoming'),
            ]).filtered(lambda l: l.qty_received < l.product_qty)

    def action_reserve_available(self):
        self.line_id._reserve(all_available=True)
        self.order_form_id._update_state_from_lines()
        return {'type': 'ir.actions.act_window_close'}

    def action_create_purchase_order(self):
        return self.line_id.order_form_id.with_context(
            mariwan_line_ids=self.line_id.ids).action_create_purchase_order()
