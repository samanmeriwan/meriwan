from odoo import models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def _get_cogs_value(self):
        """Credit note posted after everything was returned: the delivery and return moves net to zero, so the
        standard price is 0 and the cost of the invoice would never be reversed. Use the cost booked on the invoice."""
        value = super()._get_cogs_value()
        if value or self.move_id.move_type != 'out_refund' or not self.cogs_move_ids:
            return value
        invoice_lines = self.sudo().sale_line_ids.invoice_lines.filtered(
            lambda l: l.move_id.move_type == 'out_invoice' and l.parent_state == 'posted'
            and l.product_id == self.product_id)
        qty = sum(l.product_uom_id._compute_quantity(l.quantity, l.product_id.uom_id) for l in invoice_lines)
        stock_account = self.product_id.product_tmpl_id.get_product_accounts(
            fiscal_pos=self.move_id.fiscal_position_id)['stock_valuation']
        booked = sum(invoice_lines.move_id.line_ids.filtered(
            lambda l: l.display_type == 'cogs' and l.cogs_origin_id in invoice_lines
            and l.account_id == stock_account).mapped('balance'))
        return -booked / qty if qty else value
