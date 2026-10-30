import logging

from odoo import Command, models

_logger = logging.getLogger(__name__)

MODULE = 'mariwan_config'

# Task 2.4: client chart of accounts ("Chart of Accounts - Meriwan Dubai.xlsx") on top of
# the default Odoo chart: (xmlid, code, name, account_type, reconcile). Landed Cost Clearing
# and Customer Advances are also needed by the landed cost and down payment flows.
MARIWAN_ACCOUNTS = [
    ('account_fixed_assets_furniture', '151100', 'Fixed Assets - Furniture', 'asset_fixed', False),
    ('account_landed_cost_clearing', '213000', 'Landed Cost Clearing', 'liability_current', True),
    ('account_customer_advances', '214000', 'Customer Advances', 'liability_current', True),
    ('account_utilities', '613000', 'Utilities Expense', 'expense', False),
    ('account_marketing', '614000', 'Marketing Expense', 'expense', False),
    ('account_travel', '615000', 'Travel Expense', 'expense', False),
    ('account_office_supplies', '616000', 'Office Supplies', 'expense', False),
    ('account_employee_expense', '617000', 'Employee Expense', 'expense', False),
    ('account_transportation', '618000', 'Transportation Expense', 'expense', False),
    ('account_shipping_clearing', '619000', 'Shipping and Clearing Expense', 'expense', False),
]

# Default chart accounts renamed to the client names: code -> (xmlid, name)
MARIWAN_RENAMED_ACCOUNTS = {
    '101401': ('account_bank', 'Bank Account'),
    '110100': ('account_stock_valuation', 'Inventory'),
    '151000': ('account_fixed_assets_equipment', 'Fixed Assets - Equipment'),
    '301000': ('account_owner_equity', "Owner's Equity"),
    '400000': ('account_sales', 'Sales Revenue'),
    '612000': ('account_rent', 'Rent Expense'),
    '630000': ('account_salary', 'Salary Expense'),
    '600000': ('account_other_expense', 'Other Expense'),
}

# Task 8.1: landed cost types (xmlid, name, default split method)
MARIWAN_LANDED_COST_TYPES = [
    ('product_lc_freight', 'Ocean / Air Freight', 'by_current_cost_price'),
    ('product_lc_customs', 'Customs Duty', 'by_current_cost_price'),
    ('product_lc_clearing', 'Clearing Charges', 'by_current_cost_price'),
    ('product_lc_port', 'Port / Terminal Charges', 'by_quantity'),
    ('product_lc_transport', 'Inland Transportation', 'by_weight'),
    ('product_lc_insurance', 'Insurance', 'by_current_cost_price'),
    ('product_lc_other', 'Other Landed Cost', 'equal'),
]

# Task 3.3
# Task 3.3: client categories ("Categories and item details.xlsx")
MARIWAN_CATEGORIES = [
    ('categ_brake_pads', 'Brake Pads'),
    ('categ_brake_rotors', 'Brake Rotors'),
    ('categ_drum_brake_shoe', 'Drum Brake Shoe'),
    ('categ_brake_lines', 'Brake Lines'),
    ('categ_brake_fluid', 'Brake Fluid'),
    ('categ_callipers', 'Callipers'),
    ('categ_brake_wire_sensor', 'Brake Wire Sensor'),
    ('categ_big_brake_kit', 'Big Brake Upgrade Kit'),
]

MARIWAN_CURRENCIES = ['USD', 'EUR', 'CNY', 'GBP', 'INR', 'SAR']


class ResCompany(models.Model):
    _inherit = 'res.company'

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _mariwan_ref(self, xmlid):
        return self.env.ref(f'{MODULE}.{xmlid}', raise_if_not_found=False)

    def _mariwan_bind_xmlid(self, xmlid, record):
        if not self._mariwan_ref(xmlid):
            self.env['ir.model.data'].create({
                'module': MODULE,
                'name': xmlid,
                'model': record._name,
                'res_id': record.id,
                'noupdate': True,
            })
        return record

    def _mariwan_ensure(self, xmlid, model, vals, search_domain=None):
        """Return the record bound to ``xmlid``; create it (or adopt the record
        matching ``search_domain``) if missing. Never overwrites user changes."""
        record = self._mariwan_ref(xmlid)
        if record:
            return record
        Model = self.env[model].with_context(active_test=False)
        record = Model.search(search_domain, limit=1) if search_domain else Model
        if record:
            record.write(vals)
        else:
            record = Model.create(vals)
        return self._mariwan_bind_xmlid(xmlid, record)

    def _mariwan_account(self, code):
        self.ensure_one()
        return self.env['account.account'].with_company(self).search([
            ('code', '=', code), ('company_ids', 'in', self.id)], limit=1)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def _mariwan_apply_configuration(self):
        company = self.env.ref('base.main_company')
        company = company.with_company(company)
        _logger.info("Applying Mariwan configuration on %s", company.name)
        company._mariwan_setup_company()
        if not company.chart_template:
            _logger.warning("No chart of accounts loaded yet; accounting configuration skipped")
            return False
        company._mariwan_setup_chart()
        company._mariwan_setup_no_vat()
        company._mariwan_setup_accounts()
        company._mariwan_setup_journals()
        company._mariwan_setup_payment_methods()
        company._mariwan_setup_currencies()
        company._mariwan_setup_reconcile_models()
        company._mariwan_setup_settings()
        company._mariwan_setup_warehouse()
        company._mariwan_setup_categories()
        company._mariwan_setup_landed_cost_types()
        company._mariwan_setup_pricelists()
        return True

    def _mariwan_setup_pricelists(self):
        """Task 9.1: standard pricelists, selling price = cost x (1 + margin %),
        rounded to 0.05 AED. Change the margin on the rule (or add category
        rules) and every Order Form / quotation follows."""
        gcc = self.env.ref('base.gulf_cooperation_council', raise_if_not_found=False)
        for xmlid, name, margin in (
            ('pricelist_uae', 'UAE Market', 15.0),
            ('pricelist_gcc', 'GCC Market', 15.0),
        ):
            if self._mariwan_ref(xmlid):
                continue
            self._mariwan_ensure(xmlid, 'product.pricelist', {
                'name': name,
                'currency_id': self.currency_id.id,
                'company_id': self.id,
                'country_group_ids': [Command.set(gcc.ids)] if gcc and xmlid == 'pricelist_gcc' else [],
                'item_ids': [Command.create({
                    'applied_on': '3_global',
                    'base': 'standard_price',
                    'compute_price': 'markup',
                    'price_markup': margin,
                    'price_round': 0.05,
                })],
            }, [('name', '=', name)])
        uae = self._mariwan_ref('pricelist_uae')
        if uae:
            uae.sequence = 1
        default = self.env.ref('product.list0', raise_if_not_found=False)
        if default and default.currency_id != self.currency_id:
            default.currency_id = self.currency_id

    # ------------------------------------------------------------------
    # Phase 2 - Company & accounting
    # ------------------------------------------------------------------
    def _mariwan_setup_company(self):
        """Task 2.1: UAE company, AED, Asia/Dubai, fiscal year Jan-Dec."""
        uae = self.env.ref('base.ae')
        aed = self.env.ref('base.AED')
        aed.active = True
        vals = {
            'country_id': uae.id,
            'fiscalyear_last_month': '12',
            'fiscalyear_last_day': 31,
        }
        if self.name in ('My Company', 'YourCompany'):
            vals.update({'name': 'Mariwan Trading Ltd', 'city': 'Dubai'})
        if self.currency_id != aed:
            vals['currency_id'] = aed.id
        self.write(vals)
        self.partner_id.tz = 'Asia/Dubai'
        self.env.ref('base.user_admin').tz = 'Asia/Dubai'
        price_precision = self.env.ref('product.decimal_price', raise_if_not_found=False)
        if price_precision:
            price_precision.digits = 2

    def _mariwan_setup_chart(self):
        # The default (generic) chart is loaded by Odoo itself; only fix the fiscal country.
        self.account_fiscal_country_id = self.env.ref('base.ae')

    def _mariwan_setup_no_vat(self):
        """Task 2.3: no tax anywhere; tax can be added later by change request."""
        self.write({
            'vat': False,
            'account_sale_tax_id': False,
            'account_purchase_tax_id': False,
        })
        taxes = self.env['account.tax'].with_context(active_test=False).search([('company_id', '=', self.id)])
        used = self.env['account.move.line'].search([('tax_ids', 'in', taxes.ids)]).tax_ids
        products = self.env['product.template'].with_context(active_test=False).search([])
        products.write({'taxes_id': [Command.clear()], 'supplier_taxes_id': [Command.clear()]})
        (taxes - used).unlink()
        used.active = False
        self.env['account.fiscal.position'].search([('company_id', '=', self.id)]).active = False

    def _mariwan_setup_accounts(self):
        Account = self.env['account.account'].with_company(self)
        for code, (xmlid, name) in MARIWAN_RENAMED_ACCOUNTS.items():
            account = self._mariwan_ref(xmlid) or self._mariwan_account(code)
            if account:
                if not self._mariwan_ref(xmlid):
                    account.name = name
                self._mariwan_bind_xmlid(xmlid, account)
        for xmlid, code, name, account_type, reconcile in MARIWAN_ACCOUNTS:
            if self._mariwan_ref(xmlid):
                continue
            account = self._mariwan_account(code) or Account.create({
                'code': code,
                'name': name,
                'account_type': account_type,
                'reconcile': reconcile,
                'company_ids': [Command.link(self.id)],
            })
            self._mariwan_bind_xmlid(xmlid, account)

        customer_adv = self._mariwan_ref('account_customer_advances')
        vals = {
            'cost_method': 'average',
            'inventory_valuation': 'real_time',
            'account_use_credit_limit': True,
        }
        if customer_adv and 'downpayment_account_id' in self._fields:
            vals['downpayment_account_id'] = customer_adv.id
        self.write(vals)

    def _mariwan_setup_journals(self):
        """Task 2.5: journals, codes and currencies."""
        Journal = self.env['account.journal'].with_company(self)
        usd = self.env.ref('base.USD')
        usd.active = True

        def adopt(xmlid, jtype, name, code, extra=None):
            journal = self._mariwan_ref(xmlid)
            if journal:
                return journal
            journal = Journal.search([('company_id', '=', self.id), ('code', '=', code)], limit=1)
            vals = {'name': name, 'code': code, **(extra or {})}
            if journal:
                journal.write(vals)
            else:
                journal = Journal.create({'type': jtype, 'company_id': self.id, **vals})
            return self._mariwan_bind_xmlid(xmlid, journal)

        adopt('journal_customer_invoices', 'sale', 'Customer Invoices', 'INV')
        adopt('journal_vendor_bills', 'purchase', 'Vendor Bills', 'BILL')
        adopt('journal_bank_aed', 'bank', 'Bank (AED)', 'BNK1')
        adopt('journal_bank_usd', 'bank', 'Bank (USD)', 'BNK2', {'currency_id': usd.id})
        adopt('journal_cash', 'cash', 'Cash', 'CSH1')
        adopt('journal_petty_cash', 'cash', 'Petty Cash', 'PCSH')
        stock_journal = adopt('journal_inventory_valuation', 'general', 'Inventory Valuation', 'STJ')
        lc_journal = adopt('journal_landed_cost', 'general', 'Landed Cost', 'LC')
        adopt('journal_misc', 'general', 'Miscellaneous', 'MISC')
        self.write({
            'account_stock_journal_id': stock_journal.id,
            'lc_journal_id': lc_journal.id,
        })

    def _mariwan_setup_payment_methods(self):
        """Task 2.6: Cash, Bank Transfer, Cheque, Card."""
        manual_in = self.env.ref('account.account_payment_method_manual_in')
        manual_out = self.env.ref('account.account_payment_method_manual_out')
        for xmlid in ('journal_bank_aed', 'journal_bank_usd'):
            journal = self._mariwan_ref(xmlid)
            if not journal:
                continue
            for method, names in ((manual_in, journal.inbound_payment_method_line_ids),
                                  (manual_out, journal.outbound_payment_method_line_ids)):
                existing = set(names.mapped('name'))
                field = 'inbound_payment_method_line_ids' if method == manual_in else 'outbound_payment_method_line_ids'
                commands = [
                    Command.create({'name': name, 'payment_method_id': method.id})
                    for name in ('Bank Transfer', 'Cheque', 'Card') if name not in existing
                ]
                if commands:
                    journal.write({field: commands})

    def _mariwan_setup_currencies(self):
        """Task 2.8: vendor currencies with daily live rates (CBUAE provider)."""
        currencies = self.env['res.currency'].with_context(active_test=False).search([('name', 'in', MARIWAN_CURRENCIES)])
        currencies.active = True
        if 'currency_interval_unit' in self._fields:
            self.currency_interval_unit = 'daily'

    def _mariwan_setup_reconcile_models(self):
        """Task 2.9: Bank Fees / Internal Transfers models are Odoo defaults; add the advance ones."""
        bank_journals = self.env['account.journal'].search([('company_id', '=', self.id), ('type', 'in', ('bank', 'cash'))])
        models_def = [
            ('reco_customer_advance', 'Customer Receipt (Advance)', 'advance', self._mariwan_ref('account_customer_advances')),
        ]
        for xmlid, name, label, account in models_def:
            if self._mariwan_ref(xmlid) or not account:
                continue
            self._mariwan_ensure(xmlid, 'account.reconcile.model', {
                'name': name,
                'company_id': self.id,
                'trigger': 'manual',
                'match_journal_ids': [Command.set(bank_journals.ids)],
                'match_label': 'contains',
                'match_label_param': label,
                'line_ids': [Command.create({
                    'account_id': account.id,
                    'amount_type': 'percentage',
                    'amount_string': '100',
                    'label': name,
                })],
            })

    def _mariwan_setup_settings(self):
        """Tasks 2.2, 2.7, 3.4, 3.5, 7.4, 10.4: features via the settings wizard."""
        Settings = self.env['res.config.settings'].with_company(self)
        wanted = {
            'group_multi_currency': True,
            'group_uom': True,
            'group_product_variant': True,
            'group_stock_multi_locations': True,
            'group_stock_production_lot': True,
            'group_lot_on_delivery_slip': True,
            'group_expiry_date_on_delivery_slip': True,
            'group_stock_sign_delivery': True,
            'group_sale_delivery_address': True,
            'group_product_pricelist': True,
            'account_use_credit_limit': True,
            'po_order_approval': True,
            'po_double_validation_amount': 0.0,
        }
        settings = Settings.create({k: v for k, v in wanted.items() if k in Settings._fields})
        settings.execute()
        self.write({'po_double_validation': 'two_step', 'po_double_validation_amount': 0.0})

    # ------------------------------------------------------------------
    # Phase 3 - Inventory
    # ------------------------------------------------------------------
    def _mariwan_setup_warehouse(self):
        """Tasks 3.1 / 3.2: main warehouse, locations, reservation at confirmation."""
        warehouse = self._mariwan_ref('warehouse_main')
        if not warehouse:
            warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.id)], limit=1)
            if warehouse:
                warehouse.write({'name': 'Mariwan UAE Warehouse', 'code': 'MRW'})
                self._mariwan_bind_xmlid('warehouse_main', warehouse)
        if not warehouse:
            return
        warehouse.partner_id = self.partner_id
        Location = self.env['stock.location']
        for xmlid, name, parent in (
            ('location_receiving', 'Receiving / Inbound', warehouse.view_location_id),
            ('location_quality_hold', 'Quality Hold', warehouse.view_location_id),
            ('location_damaged', 'Damaged', warehouse.view_location_id),
        ):
            self._mariwan_ensure(xmlid, 'stock.location', {
                'name': name, 'usage': 'internal', 'location_id': parent.id, 'company_id': self.id,
            }, [('name', '=', name), ('location_id', '=', parent.id)])
        scrap = Location.search([('company_id', '=', self.id), ('usage', '=', 'inventory'),
                                 ('name', 'ilike', 'scrap')], limit=1)
        if scrap:
            self._mariwan_bind_xmlid('location_scrap', scrap)
        warehouse.out_type_id.reservation_method = 'at_confirm'
        # Drop shipping route active, Buy route never selected by default (manual POs only).
        dropship_route = self.env.ref('stock_dropshipping.route_drop_shipping', raise_if_not_found=False)
        if dropship_route:
            dropship_route.active = True
        mto = self.env.ref('stock.route_warehouse0_mto', raise_if_not_found=False)
        if mto:
            mto.active = False

    def _mariwan_setup_categories(self):
        """Task 3.3: categories; costing (AVCO), perpetual valuation and accounts
        come from the company defaults set in _mariwan_setup_accounts."""
        for xmlid, name in MARIWAN_CATEGORIES:
            self._mariwan_ensure(xmlid, 'product.category', {'name': name}, [('name', '=', name)])
        clearing = self._mariwan_ref('account_landed_cost_clearing')
        categ = self._mariwan_ensure('categ_landed_costs', 'product.category',
                                     {'name': 'Landed Costs'}, [('name', '=', 'Landed Costs')])
        categ.with_company(self).property_account_expense_categ_id = clearing

    def _mariwan_setup_landed_cost_types(self):
        """Task 8.1: landed cost types post to Landed Cost Clearing."""
        categ = self._mariwan_ref('categ_landed_costs')
        clearing = self._mariwan_ref('account_landed_cost_clearing')
        for xmlid, name, split in MARIWAN_LANDED_COST_TYPES:
            product = self._mariwan_ensure(xmlid, 'product.product', {
                'name': name,
                'type': 'service',
                'landed_cost_ok': True,
                'split_method_landed_cost': split,
                'categ_id': categ.id,
                'purchase_ok': True,
                'sale_ok': False,
                'standard_price': 0.0,
                'list_price': 0.0,
            }, [('name', '=', name), ('landed_cost_ok', '=', True)])
            product.product_tmpl_id.with_company(self).property_account_expense_id = clearing
