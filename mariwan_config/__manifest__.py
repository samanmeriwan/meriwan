{
    'name': 'Mariwan - UAE Company Configuration',
    'version': '20.0.1.0.0',
    'category': 'Accounting/Localizations',
    'summary': 'Mariwan Trading Ltd: UAE company, AED, No VAT, chart of accounts, journals, warehouse and inventory setup',
    'description': """
Configuration-as-code for Mariwan Trading Ltd (UAE, AED, No VAT).

Applied by the post-init hook (idempotent, can be re-run from
Settings > Technical > Mariwan > Re-apply configuration):

* Company: UAE, AED, Asia/Dubai, fiscal year Jan-Dec
* No VAT: no taxes, no tax defaults, no TRN
* Chart of accounts additions (stock, landed cost clearing, drop ship COGS, advances, ...)
* Journals (Customer Invoices, Vendor Bills, Bank AED/USD, Cash, Petty Cash, Inventory Valuation, Landed Cost, Misc)
* Payment terms, payment methods, multi-currency, reconciliation models
* Main warehouse, locations, product categories (AVCO + perpetual), UoM, landed cost types
* Manual purchasing only: no Buy route by default, MTO archived, PO approval two-step
""",
    'author': 'Rabbul Mia',
    'license': 'LGPL-3',
    'depends': [
        'contacts',
        'sale_management',
        'sale_stock',
        'sale_purchase_stock',
        'purchase_stock',
        'stock_account',
        'stock_landed_costs',
        'stock_dropshipping',
        'product_expiry',
        'account_accountant',
        'account_reports',
        'currency_rate_live',
        'approvals',
    ],
    'data': [
        'data/uom_data.xml',
        'data/account_payment_term_data.xml',
        'data/approval_category_data.xml',
        'data/ir_actions_server.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
