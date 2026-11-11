from odoo import models
from odoo.tools import format_date


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    def _mariwan_invoices(self):
        self.ensure_one()
        return self.invoice_ids | self.reconciled_invoice_ids | self.reconciled_bill_ids

    def _mariwan_log_on_invoices(self, event, invoices=None):
        """Payments stay on the Payments button of the invoice and are also written in its log.
        :param invoices: {payment: invoices} or the invoices to use when a payment has no link (yet / any more)."""
        for payment in self:
            moves = invoices.get(payment, self.env['account.move']) if isinstance(invoices, dict) \
                else payment._mariwan_invoices()
            if not moves and invoices and not isinstance(invoices, dict):
                moves = invoices.filtered(
                    lambda m: m.commercial_partner_id == payment.partner_id.commercial_partner_id)
            values = {
                'payment': payment._get_html_link(),
                'amount': payment.currency_id.format(payment.amount),
                'date': format_date(self.env, payment.date),
                'journal': payment.journal_id.name,
                'method': payment.payment_method_line_id.name or '',
            }
            if event == 'registered':
                body = self.env._(
                    "Payment %(payment)s registered: %(amount)s on %(date)s - %(journal)s (%(method)s).", **values)
            elif event == 'draft':
                body = self.env._("Payment %(payment)s of %(amount)s reset to draft.", **values)
            else:
                body = self.env._("Payment %(payment)s of %(amount)s cancelled.", **values)
            for move in moves:
                move.message_post(body=body)

    def action_cancel(self):
        # Before super: it drops the link to the invoices. Payments already in that state are not logged again.
        invoices = {payment: payment._mariwan_invoices() for payment in self if payment.state not in ('canceled', 'rejected')}
        res = super().action_cancel()
        self._mariwan_log_on_invoices('cancelled', invoices)
        return res

    def action_reject(self):
        # Before super: it drops the link to the invoices. Payments already in that state are not logged again.
        invoices = {payment: payment._mariwan_invoices() for payment in self if payment.state not in ('canceled', 'rejected')}
        res = super().action_reject()
        self._mariwan_log_on_invoices('cancelled', invoices)
        return res

    def action_draft(self):
        # Before super: it drops the link to the invoices. Payments already in that state are not logged again.
        invoices = {payment: payment._mariwan_invoices() for payment in self if payment.state not in ('draft',)}
        res = super().action_draft()
        self._mariwan_log_on_invoices('draft', invoices)
        return res


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def _create_payments(self):
        payments = super()._create_payments()
        payments._mariwan_log_on_invoices('registered', self.line_ids.move_id)
        return payments
