from odoo import Command, fields, models


class MariwanReservedDetail(models.TransientModel):
    """Who holds the stock behind the Reserved / Reserved (Others) quantities of an Order Form line."""
    _name = 'mariwan.reserved.detail'
    _description = 'Order Form Reserved Stock Details'

    line_id = fields.Many2one('mariwan.order.form.line', required=True, ondelete='cascade')
    mode = fields.Selection([('others', 'Other Customers'), ('own', 'This Order Form')], required=True)
    product_id = fields.Many2one(related='line_id.product_id')
    warehouse_id = fields.Many2one(related='line_id.warehouse_id')
    product_uom_id = fields.Many2one(related='line_id.product_id.uom_id', string='Unit')
    total_qty = fields.Float('Total Reserved', digits='Product Unit')
    detail_ids = fields.One2many('mariwan.reserved.detail.line', 'wizard_id', 'Reserved For')


class MariwanReservedDetailLine(models.TransientModel):
    _name = 'mariwan.reserved.detail.line'
    _description = 'Order Form Reserved Stock Detail'
    _order = 'delivery_date, id'

    wizard_id = fields.Many2one('mariwan.reserved.detail', required=True, ondelete='cascade')
    source = fields.Selection([
        ('hold', 'Order Form Hold'),
        ('delivery', 'Delivery Order'),
        ('internal', 'Internal Transfer'),
        ('other', 'Other Transfer'),
    ], 'Reserved By', required=True)
    partner_id = fields.Many2one('res.partner', 'Customer')
    quantity = fields.Float('Reserved Qty', digits='Product Unit')
    product_uom_id = fields.Many2one('uom.uom', 'Unit')
    reference = fields.Char('Reference')
    order_form_id = fields.Many2one('mariwan.order.form', 'Order Form')
    # Plain text: an officer may not have read access to other users' sales orders.
    sale_order = fields.Char('Sales Order')
    user_id = fields.Many2one('res.users', 'Responsible')
    reserved_on = fields.Datetime('Reserved On')
    delivery_date = fields.Date('Expected Delivery Date')


class MariwanOrderFormLine(models.Model):
    _inherit = 'mariwan.order.form.line'

    def action_view_reserved_others(self):
        return self._open_reserved_detail('others')

    def action_view_reserved_own(self):
        return self._open_reserved_detail('own')

    def _open_reserved_detail(self, mode):
        self.ensure_one()
        rows = self.sudo()._reserved_detail_rows(mode)
        wizard = self.env['mariwan.reserved.detail'].create({
            'line_id': self.id,
            'mode': mode,
            'total_qty': sum(row['quantity'] for row in rows),
            'detail_ids': [Command.create(row) for row in rows],
        })
        title = self.env._("Reserved for other customers - %s") if mode == 'others' \
            else self.env._("Reserved for this Order Form - %s")
        return {
            'type': 'ir.actions.act_window',
            'name': title % self.product_id.display_name,
            'res_model': 'mariwan.reserved.detail',
            'res_id': wizard.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'context': {'dialog_size': 'extra-large'},
            'target': 'new',
        }

    def _reserved_detail_rows(self, mode):
        """Order Form holds plus stock Odoo reserved on transfers, split into this line / everyone else
        (same split as Reserved and Reserved (Others))."""
        warehouse = self.order_form_id.warehouse_id
        if not self.product_id.is_storable or not warehouse:
            return []
        rows = []
        holds = self.env['mariwan.reservation'].search([
            ('product_id', '=', self.product_id.id), ('warehouse_id', '=', warehouse.id), ('state', '=', 'active')])
        holds = holds.filtered(lambda r: (r.line_id == self) == (mode == 'own'))
        for hold in holds:
            rows.append({
                'source': 'hold',
                'partner_id': hold.partner_id.id,
                'quantity': hold.quantity,
                'product_uom_id': hold.product_uom_id.id,
                'reference': hold.name,
                'order_form_id': hold.order_form_id.id,
                'sale_order': hold.sale_order_id.name or False,
                'user_id': hold.reserved_by.id,
                'reserved_on': hold.reserved_on,
                'delivery_date': hold.delivery_date,
            })
        own_moves = self.sale_line_ids.move_ids
        moves = self.env['stock.move'].search([
            ('product_id', '=', self.product_id.id),
            ('state', 'in', ('assigned', 'partially_available')),
            ('location_id', 'child_of', warehouse.view_location_id.id),
            ('location_id.usage', '=', 'internal'),
        ])
        for move in moves.filtered(lambda m: (m in own_moves) == (mode == 'own') and m.quantity > 0):
            sale = move.sale_line_id.order_id
            code = move.picking_type_id.code
            rows.append({
                'source': 'delivery' if code == 'outgoing' else 'internal' if code == 'internal' else 'other',
                'partner_id': (move.picking_id.partner_id or sale.partner_id).id,
                'quantity': move.quantity_product_uom,
                'product_uom_id': move.product_id.uom_id.id,
                'reference': move.picking_id.name or move.reference,
                'order_form_id': sale.mariwan_order_form_id.id,
                'sale_order': sale.name or False,
                'user_id': (sale.user_id or move.picking_id.user_id).id,
                'reserved_on': min(move.move_line_ids.mapped('create_date'), default=move.create_date),
                'delivery_date': sale.commitment_date or move.date_deadline or move.date,
            })
        return rows
