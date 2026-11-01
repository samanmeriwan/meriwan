{
    'name': 'Mariwan - Order Form',
    'version': '20.0.1.0.1',
    'category': 'Sales/Sales',
    'summary': 'Customer request Order Form: real-time availability, shortage flag, reservations, '
               'manual import / drop-ship POs, landed cost based pricing',
    'description': """
Order Form used by the Sales/Purchase Officer when a customer requests items.

* Real-time On Hand / Reserved for others / Free / Incoming per line and warehouse
* Shortage flag with a popup of the customers holding reservations and incoming POs
* Reservations with tentative delivery date, locked to the customer (also respected by deliveries)
* Fulfilment type per line: From Stock, Order for Stock (Import), Drop Ship
* Cost = vendor cost in AED + landed cost (estimate, then actual); price from the standard pricelist margin
* Manual purchase orders, quotation / sales order / invoice / delivery links
* Cash customers: delivery released after payment; credit customers: credit limit and overdue block

Everything else uses standard Odoo (pricelists, landed costs, drop shipping, PO approval,
credit limit, lock dates, approvals, reports).
""",
    'author': 'Rabbul Mia',
    'license': 'LGPL-3',
    'depends': [
        'mariwan_config',
        'stock_delivery',
    ],
    'data': [
        'security/mariwan_security.xml',
        'security/ir.access.csv',
        'data/ir_sequence_data.xml',
        'data/ir_cron_data.xml',
        'wizard/mariwan_availability_popup_views.xml',
        'wizard/mariwan_reservation_reassign_views.xml',
        'views/mariwan_order_form_views.xml',
        'views/mariwan_order_form_line_views.xml',
        'views/mariwan_reservation_views.xml',
        'views/product_views.xml',
        'views/res_partner_views.xml',
        'views/purchase_order_views.xml',
        'views/sale_order_views.xml',
        'views/stock_picking_views.xml',
        'views/account_move_views.xml',
        'views/res_config_settings_views.xml',
        'views/mariwan_menus.xml',
    ],
    'installable': True,
    'application': True,
}
