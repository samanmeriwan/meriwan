from odoo import fields, models
from odoo.exceptions import UserError

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
    # Task 9.1: the client's per-item market prices, kept in the UAE / GCC Market price lists
    # (the price the Order Form and quotation use), shown and edited on the product.
    mariwan_uae_price = fields.Float(
        'UAE Price', digits='Product Price', compute='_compute_mariwan_market_prices',
        inverse='_inverse_mariwan_uae_price', help="Fixed price in the UAE Market price list (UAE customers).")
    mariwan_gcc_price = fields.Float(
        'GCC Price', digits='Product Price', compute='_compute_mariwan_market_prices',
        inverse='_inverse_mariwan_gcc_price', help="Fixed price in the GCC Market price list (GCC customers).")

    def _mariwan_market_item(self, xmlid):
        pricelist = self.env.ref(f'mariwan_config.{xmlid}', raise_if_not_found=False)
        if not pricelist or not self.id:
            return pricelist, self.env['product.pricelist.item']
        return pricelist, self.env['product.pricelist.item'].sudo().search([
            ('pricelist_id', '=', pricelist.id), ('applied_on', '=', '1_product'),
            ('product_tmpl_id', '=', self.id), ('compute_price', '=', 'fixed')], limit=1)

    def _compute_mariwan_market_prices(self):
        for product in self:
            product.mariwan_uae_price = product._mariwan_market_item('pricelist_uae')[1].fixed_price
            product.mariwan_gcc_price = product._mariwan_market_item('pricelist_gcc')[1].fixed_price

    def _inverse_mariwan_uae_price(self):
        self._mariwan_set_market_price('pricelist_uae', 'mariwan_uae_price')

    def _inverse_mariwan_gcc_price(self):
        self._mariwan_set_market_price('pricelist_gcc', 'mariwan_gcc_price')

    def _mariwan_set_market_price(self, xmlid, fname):
        if not self.env.su and not self.env.user.has_group('mariwan_order_form.group_pricing_manager'):
            raise UserError(self.env._("Only the Pricing Manager can change the UAE / GCC prices."))
        for product in self:
            pricelist, item = product._mariwan_market_item(xmlid)
            price = product[fname]
            if not pricelist:
                continue
            if item and price:
                item.fixed_price = price
            elif item:
                item.unlink()  # no price: the price list falls back to its default rule
            elif price:
                item.create({'pricelist_id': pricelist.id, 'applied_on': '1_product', 'product_tmpl_id': product.id,
                             'compute_price': 'fixed', 'fixed_price': price})

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
    mariwan_dispatch_contact_id = fields.Many2one(
        'res.partner', 'Dispatch Contact', domain="[('parent_id', '=', id)]",
        help="Drop-ship vendors: the contact who receives the delivery instructions.")


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
