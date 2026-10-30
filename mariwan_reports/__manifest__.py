{
    'name': 'Mariwan - Document Templates',
    'version': '20.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Mariwan print and email templates: Order Form, reservation confirmation, '
               'drop-ship vendor instruction, landed cost sheet, No VAT additions to standard documents',
    'description': """
Phase 12 document templates. Standard Odoo layouts are kept (company layout, A4,
quotation, invoice, delivery slip, purchase order, payment receipt, follow-up
statement); this module only adds what Mariwan needs on them:

* Order Form print and reservation confirmation (new)
* Drop-ship delivery instruction to the vendor (new)
* Landed cost sheet with approval box (new)
* Quotation / sales order: Order Form reference, payment type, tentative delivery and reservation per line
* Invoice: Order Form reference, cash / credit, amount in words (standard option enabled)
* Delivery note: receiver name, signature, stamp and condition remarks
* Purchase order: shipment details, delivery type, AED equivalent, authorised signature
* Email templates: reservation confirmation, drop-ship instruction to vendor
""",
    'author': 'Rabbul Mia',
    'license': 'LGPL-3',
    'depends': ['mariwan_order_form'],
    'data': [
        'report/mariwan_order_form_report.xml',
        'report/mariwan_purchase_report.xml',
        'report/mariwan_landed_cost_report.xml',
        'report/standard_report_inherit.xml',
        'data/mail_template_data.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
}
