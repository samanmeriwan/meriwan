from odoo import models


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _mariwan_set_default_invoice_report(self):
        """Client invoice format as default on the sales journals (standard per-journal
        "Invoice report" setting); a template already chosen there is kept."""
        report = self.env.ref('mariwan_reports.action_report_mariwan_invoice')
        journals = self.env['account.journal'].search([('type', '=', 'sale'), ('invoice_template_pdf_report_id', '=', False)])
        journals.invoice_template_pdf_report_id = report
        return True
