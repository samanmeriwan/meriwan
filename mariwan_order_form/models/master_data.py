from odoo import fields, models

from .mariwan_order_form_line import FULFILMENT_TYPES

# Tasks 4.1 - 4.3. HS code, country of origin, weight, volume, vendors (seller_ids),
# vendor currency, credit limit, payment terms, addresses and bank accounts are
# standard Odoo fields; only what Odoo does not have is added here.


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    mariwan_brand = fields.Char('Brand')
    mariwan_model = fields.Char('Model')
    mariwan_fulfilment_type = fields.Selection(
        FULFILMENT_TYPES, 'Default Fulfilment Type', default='stock', required=True,
        help="Default fulfilment type on Order Form lines.")
    mariwan_min_stock = fields.Float(
        'Minimum Stock (alert)', digits='Product Unit',
        help="Alert / dashboard only - never creates a purchase order.")
    mariwan_below_min = fields.Boolean('Below Minimum Stock', compute='_compute_mariwan_below_min',
                                       search='_search_mariwan_below_min')

    def _compute_mariwan_below_min(self):
        for product in self:
            product.mariwan_below_min = bool(product.mariwan_min_stock) and product.qty_available < product.mariwan_min_stock

    def _search_mariwan_below_min(self, operator, value):
        if operator != 'in':
            return NotImplemented
        products = self.search([('mariwan_min_stock', '>', 0)]).filtered(lambda p: p.mariwan_below_min)
        return [('id', 'in' if True in value else 'not in', products.ids)]


class ProductCategory(models.Model):
    _inherit = 'product.category'

    mariwan_landed_cost_estimate = fields.Float(
        'Estimated Landed Cost %', digits=(16, 2),
        help="Task 8.5: estimated landed cost (% of vendor cost) used on Order Form import lines "
             "until the actual landed cost is validated. Maintained by the Pricing Manager.")


class ResPartner(models.Model):
    _inherit = 'res.partner'

    mariwan_customer_type = fields.Selection([('cash', 'Cash'), ('credit', 'Credit')], 'Customer Type',
                                             default='cash')
    mariwan_region = fields.Selection([
        ('abu_dhabi', 'Abu Dhabi'), ('dubai', 'Dubai'), ('sharjah', 'Sharjah'), ('ajman', 'Ajman'),
        ('umm_al_quwain', 'Umm Al Quwain'), ('ras_al_khaimah', 'Ras Al Khaimah'), ('fujairah', 'Fujairah'),
        ('gcc', 'GCC'), ('other', 'Other'),
    ], 'Sales Region')
    mariwan_vendor_type = fields.Selection([
        ('overseas', 'Overseas Supplier'), ('local', 'Local Supplier'), ('dropship', 'Drop-Ship Vendor'),
    ], 'Vendor Type')
    mariwan_trade_licence = fields.Char('Trade Licence No.')


class ResCompany(models.Model):
    _inherit = 'res.company'

    mariwan_reservation_grace_days = fields.Integer('Reservation Grace Period (days)', default=3)
    mariwan_cash_release_rule = fields.Selection([
        ('full', 'Full payment'), ('advance', 'Advance received'),
    ], 'Cash Sale Delivery Release', default='full', required=True)
    mariwan_cash_advance_percent = fields.Float('Required Advance %', default=50.0)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    mariwan_reservation_grace_days = fields.Integer(related='company_id.mariwan_reservation_grace_days',
                                                    readonly=False)
    mariwan_cash_release_rule = fields.Selection(related='company_id.mariwan_cash_release_rule', readonly=False)
    mariwan_cash_advance_percent = fields.Float(related='company_id.mariwan_cash_advance_percent', readonly=False)
