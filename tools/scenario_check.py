#!/usr/bin/env python3
"""Run: python3 tools/scenario_check.py  (server on 127.0.0.1:8078, DB meriwan, role users loaded).

Extra scenarios: USD vendor, lots, backorder, customer down payment, vendor advance, emails."""
import xmlrpc.client
from datetime import date, timedelta

import os
URL = os.environ.get('MARIWAN_URL', 'http://127.0.0.1:8078')
DB = os.environ.get('MARIWAN_DB', 'meriwan')
PW = {u: os.environ.get('MARIWAN_TEST_PW', f'{u}123') for u in ('saman', 'warehouse', 'accountant', 'finance', 'pricing', 'manager')}
PW['admin'] = os.environ.get('MARIWAN_ADMIN_PW', 'admin')
common = xmlrpc.client.ServerProxy(URL + '/xmlrpc/2/common')
obj = xmlrpc.client.ServerProxy(URL + '/xmlrpc/2/object', allow_none=True)
UID = {u: common.authenticate(DB, u, p, {}) for u, p in PW.items()}
TAG = 'SCENARIO TEST'
DELIVERY = str(date.today() + timedelta(days=7))
RES = []


def call(user, model, method, *args, **kw):
    return obj.execute_kw(DB, UID[user], PW[user], model, method, list(args), kw)


def step(name, fn):
    try:
        out = fn()
        RES.append(True)
        print(f'PASS  {name}  {"" if out is None else out}', flush=True)
        return out
    except Exception as e:  # noqa: BLE001
        msg = e.faultString.strip().splitlines()[-1] if isinstance(e, xmlrpc.client.Fault) else repr(e)
        RES.append(False)
        print(f'FAIL  {name}  -> {msg[:400]}', flush=True)


def expect_block(name, fn):
    try:
        fn()
    except xmlrpc.client.Fault as e:
        RES.append(True)
        print(f'PASS  {name}  blocked: {e.faultString.strip().splitlines()[-1][:170]}', flush=True)
        return
    RES.append(False)
    print(f'FAIL  {name}  -> was NOT blocked', flush=True)


def ref(xmlid):
    module, name = xmlid.split('.')
    return call('admin', 'ir.model.data', 'search_read', [('module', '=', module), ('name', '=', name)], fields=['res_id'])[0]['res_id']


def product(code):
    return call('admin', 'product.product', 'search', [('default_code', '=', code)])[0]


def partner(name):
    return call('admin', 'res.partner', 'search', [('name', '=', name)], limit=1)[0]


def read(model, rid, fields, user='admin'):
    return call(user, model, 'read', [rid], fields)[0]


def confirm_po(po):
    call('saman', 'purchase.order', 'button_confirm', [po])
    if read('purchase.order', po, ['state'])['state'] == 'to approve':
        call('manager', 'purchase.order', 'button_approve', [po])
    return read('purchase.order', po, ['name', 'state', 'currency_id', 'amount_total', 'picking_ids'])


def validate(user, picking):
    res = call(user, 'stock.picking', 'button_validate', [picking])
    if isinstance(res, dict) and res.get('res_model'):
        ctx = res.get('context', {})
        wiz = call(user, res['res_model'], 'create', {}, context=ctx)
        call(user, res['res_model'], 'process', [wiz], context=ctx)
    return read('stock.picking', picking, ['name', 'state', 'backorder_ids'])


def new_form(customer, code, qty, **line):
    return call('saman', 'mariwan.order.form', 'create', {
        'partner_id': customer, 'client_order_ref': TAG, 'delivery_date': DELIVERY,
        'line_ids': [(0, 0, {'product_id': product(code), 'product_qty': qty, **line})]})


def line_of(fid, fields, user='admin'):
    return call(user, 'mariwan.order.form.line', 'search_read', [('order_form_id', '=', fid)], fields=fields)[0]


def so_of(fid):
    return call('admin', 'sale.order', 'search', [('mariwan_order_form_id', '=', fid), ('state', '=', 'sale')])[0]


def form_state(fid):
    return read('mariwan.order.form', fid, ['state'])['state']


def quote_confirm(fid):
    call('saman', 'mariwan.order.form', 'action_check_availability', [fid])
    call('saman', 'mariwan.order.form', 'action_create_quotation', [fid])
    call('saman', 'mariwan.order.form', 'action_confirm_order', [fid])
    return form_state(fid)


def so_invoice(user, so, **wizard_vals):
    ctx = {'active_model': 'sale.order', 'active_ids': [so], 'active_id': so}
    before = set(read('sale.order', so, ['invoice_ids'])['invoice_ids'])
    wiz = call(user, 'sale.advance.payment.inv', 'create', wizard_vals or {'advance_payment_method': 'delivered'}, context=ctx)
    call(user, 'sale.advance.payment.inv', 'create_invoices', [wiz], context=ctx)
    inv = sorted(set(read('sale.order', so, ['invoice_ids'])['invoice_ids']) - before)[0]
    call(user, 'account.move', 'action_post', [inv])
    return inv


def pay(user, move):
    ctx = {'active_model': 'account.move', 'active_ids': [move]}
    wiz = call(user, 'account.payment.register', 'create', {}, context=ctx)
    call(user, 'account.payment.register', 'action_create_payments', [wiz], context=ctx)
    return read('account.move', move, ['name', 'amount_total', 'payment_state'])


CASH = partner('Sample Cash Customer')
CREDIT = partner('Sample Credit Customer (GCC)')
POWERSTOP = partner('Powerstop')
USD = call('admin', 'res.currency', 'search', [('name', '=', 'USD')])[0]

# ---------------------------------------------------------------- 1. USD vendor
print('==== 1. USD vendor > Order Form cost in AED > PO in USD > stock value in AED')
P_USD = '16-1519'
usd_vendor = step('Create USD vendor (overseas, purchase currency USD)', lambda: call('admin', 'res.partner', 'create', {
    'name': f'{TAG} US Supplier', 'supplier_rank': 1, 'mariwan_vendor_type': 'overseas',
    'property_purchase_currency_id': USD, 'country_id': ref('base.us')}))
step('Vendor price 10.00 USD on the product', lambda: call('admin', 'product.supplierinfo', 'create', {
    'partner_id': usd_vendor, 'product_tmpl_id': read('product.product', product(P_USD), ['product_tmpl_id'])['product_tmpl_id'][0],
    'price': 10.0, 'currency_id': USD}))
f_usd = step('Order Form import line with the USD vendor', lambda: new_form(CASH, P_USD, 6, fulfilment_type='import', vendor_id=usd_vendor))
step('Line cost: USD 10 x 3.6725 = AED 36.73', lambda: line_of(f_usd, ['vendor_currency_id', 'vendor_unit_cost', 'exchange_rate', 'vendor_cost_aed', 'total_unit_cost', 'price_unit']))
step('Check availability (no stock > shortage 6)', lambda: (call('saman', 'mariwan.order.form', 'action_check_availability', [f_usd]), line_of(f_usd, ['shortage_qty', 'availability_status']))[1])
step('Create PO for shortage', lambda: call('saman', 'mariwan.order.form', 'action_create_purchase_order', [f_usd])['res_model'])
po_usd = call('admin', 'purchase.order', 'search', [('mariwan_order_form_id', '=', f_usd)])[0]
po_usd_info = step('PO is in USD at 10.00', lambda: confirm_po(po_usd))
step('Receive > stock valued in AED (avg cost ~36.73)', lambda: (validate('warehouse', po_usd_info['picking_ids'][0]),
     read('product.product', product(P_USD), ['qty_available', 'standard_price']), line_of(f_usd, ['reserved_qty']))[1:])


def usd_bill():
    call('accountant', 'purchase.order', 'action_create_invoice', [po_usd])
    bill = read('purchase.order', po_usd, ['invoice_ids'])['invoice_ids'][-1]
    call('accountant', 'account.move', 'write', [bill], {'invoice_date': str(date.today())})
    call('accountant', 'account.move', 'action_post', [bill])
    b = read('account.move', bill, ['name', 'currency_id', 'amount_total', 'amount_total_signed'])
    return b


step('Vendor bill in USD (60 USD = AED 220.35 in the books)', usd_bill)

# ---------------------------------------------------------------- 2. Lots
print('==== 2. Lot-tracked product: receive with lot > reserve > deliver with lot')
P_LOT = '16-1435'
step('Product set to "By Lots" tracking', lambda: call('admin', 'product.template', 'write',
     [read('product.product', product(P_LOT), ['product_tmpl_id'])['product_tmpl_id'][0]], {'tracking': 'lot'}))
po_lot = step('PO 12 units', lambda: call('saman', 'purchase.order', 'create', {'partner_id': POWERSTOP, 'partner_ref': TAG,
              'order_line': [(0, 0, {'product_id': product(P_LOT), 'product_qty': 12, 'price_unit': 42})]}))
lot_receipt = (step('Confirm + approve', lambda: confirm_po(po_lot)) or {}).get('picking_ids', [None])[0]
expect_block('Receipt without lot number is refused', lambda: call('warehouse', 'stock.picking', 'button_validate', [lot_receipt]))


def receive_lot():
    mls = call('warehouse', 'stock.move.line', 'search', [('picking_id', '=', lot_receipt)])
    call('warehouse', 'stock.move.line', 'write', mls[:1], {'lot_name': 'PS-LOT-2026-001', 'quantity': 12})
    return validate('warehouse', lot_receipt)['state']


step('Receive with lot PS-LOT-2026-001', receive_lot)
f_lot = step('Order Form 4 units (cash customer)', lambda: new_form(CREDIT, P_LOT, 4))
step('Reserve > quote > confirm', lambda: (call('saman', 'mariwan.order.form', 'action_reserve_all', [f_lot]), quote_confirm(f_lot))[1])
lot_out = read('sale.order', so_of(f_lot), ['picking_ids'])['picking_ids'][0]
step('Delivery reserved the lot automatically', lambda: call('admin', 'stock.move.line', 'search_read', [('picking_id', '=', lot_out)], fields=['lot_id', 'quantity']))
step('Deliver with the lot', lambda: validate('warehouse', lot_out)['state'])

# ---------------------------------------------------------------- 3. Backorder
print('==== 3. Partial delivery > backorder > rest delivered')
P_BO = '16-1454'
po_bo = call('saman', 'purchase.order', 'create', {'partner_id': POWERSTOP, 'partner_ref': TAG,
             'order_line': [(0, 0, {'product_id': product(P_BO), 'product_qty': 5, 'price_unit': 46})]})
step('Stock 5 units in', lambda: (validate('warehouse', confirm_po(po_bo)['picking_ids'][0]), read('product.product', product(P_BO), ['qty_available']))[1])
f_bo = step('Credit customer orders 8 (5 in stock)', lambda: new_form(CREDIT, P_BO, 8))
step('Reserve 5 > quote > confirm', lambda: (call('saman', 'mariwan.order.form', 'action_reserve_all', [f_bo]), quote_confirm(f_bo))[1])
bo_out = read('sale.order', so_of(f_bo), ['picking_ids'])['picking_ids'][0]
bo1 = step('Deliver the 5 available > backorder created', lambda: validate('warehouse', bo_out))
step('Order Form status (expect In Delivery)', lambda: form_state(f_bo))
po_bo2 = call('saman', 'purchase.order', 'create', {'partner_id': POWERSTOP, 'partner_ref': TAG,
              'order_line': [(0, 0, {'product_id': product(P_BO), 'product_qty': 3, 'price_unit': 46})]})
step('3 more received', lambda: validate('warehouse', confirm_po(po_bo2)['picking_ids'][0])['state'])
back = bo1 and bo1['backorder_ids'][0]
step('Backorder reserved and delivered', lambda: (call('warehouse', 'stock.picking', 'action_assign', [back]), validate('warehouse', back)['state'])[1])
step('Order Form status (expect Delivered)', lambda: form_state(f_bo))

# ---------------------------------------------------------------- 4. Customer down payment
print('==== 4. Cash customer 50% advance > delivery released > final invoice deducts advance')
company = ref('base.main_company')
step('Settings: cash delivery released after 50% advance', lambda: call('admin', 'res.company', 'write', [company],
     {'mariwan_cash_release_rule': 'advance', 'mariwan_cash_advance_percent': 50}))
P_DP = '16-1191'
f_dp = step('Cash Order Form 4 units', lambda: new_form(CASH, P_DP, 4))
step('Reserve > quote > confirm', lambda: (call('saman', 'mariwan.order.form', 'action_reserve_all', [f_dp]), quote_confirm(f_dp))[1])
so_dp = so_of(f_dp)
dp_out = read('sale.order', so_dp, ['picking_ids'])['picking_ids'][0]
expect_block('Delivery blocked before the advance', lambda: call('warehouse', 'stock.picking', 'button_validate', [dp_out]))
dp_inv = step('Accountant raises 50% down payment invoice', lambda: so_invoice('accountant', so_dp, advance_payment_method='percentage', amount=50))
step('Down payment posts to Customer Advances (214000)', lambda: sorted({l['account_id'][1] for l in call('admin', 'account.move.line', 'search_read',
     [('move_id', '=', dp_inv), ('display_type', '=', 'product')], fields=['account_id'])}))
step('Advance paid', lambda: pay('accountant', dp_inv))
step('Delivery now released', lambda: validate('warehouse', dp_out)['state'])
final = step('Final invoice deducts the advance', lambda: so_invoice('accountant', so_dp))
step('Final invoice amounts', lambda: read('account.move', final, ['name', 'amount_total', 'amount_residual']))
step('Restore setting: full payment before delivery', lambda: call('admin', 'res.company', 'write', [company], {'mariwan_cash_release_rule': 'full'}))

# ---------------------------------------------------------------- 5. Vendor advance
print('==== 5. Vendor advance against a PO > final bill deducts it')
po_adv = call('saman', 'purchase.order', 'create', {'partner_id': POWERSTOP, 'partner_ref': f'{TAG} advance',
              'order_line': [(0, 0, {'product_id': product('16-1550'), 'product_qty': 10, 'price_unit': 65})]})
step('PO 650 AED confirmed', lambda: confirm_po(po_adv)['amount_total'])


def vendor_advance():
    bill = call('accountant', 'account.move', 'create', {
        'move_type': 'in_invoice', 'partner_id': POWERSTOP, 'invoice_date': str(date.today()), 'ref': f'{TAG} 50% advance',
        'invoice_line_ids': [(0, 0, {'name': 'Advance 50%', 'quantity': 1, 'price_unit': 325})]})
    aml = call('admin', 'account.move.line', 'search', [('move_id', '=', bill), ('display_type', '=', 'product')])
    ctx = {'active_model': 'account.move.line', 'active_ids': [-i for i in aml]}
    wiz = call('accountant', 'bill.to.po.wizard', 'create', {'purchase_order_id': po_adv, 'partner_id': POWERSTOP}, context=ctx)
    call('accountant', 'bill.to.po.wizard', 'action_add_downpayment', [wiz], context=ctx)
    call('accountant', 'account.move', 'action_post', [bill])
    pay('accountant', bill)
    lines = call('admin', 'purchase.order.line', 'search_read', [('order_id', '=', po_adv)], fields=['name', 'is_downpayment', 'price_unit', 'qty_invoiced'])
    return [l for l in lines if l['is_downpayment']]


step('Advance bill 325 AED linked to the PO as down payment, paid', vendor_advance)
step('Goods received', lambda: validate('warehouse', read('purchase.order', po_adv, ['picking_ids'])['picking_ids'][0])['state'])


def final_bill():
    before = set(read('purchase.order', po_adv, ['invoice_ids'])['invoice_ids'])
    call('accountant', 'purchase.order', 'action_create_invoice', [po_adv])
    bill = sorted(set(read('purchase.order', po_adv, ['invoice_ids'])['invoice_ids']) - before)[0]
    call('accountant', 'account.move', 'write', [bill], {'invoice_date': str(date.today())})
    call('accountant', 'account.move', 'action_post', [bill])
    return read('account.move', bill, ['name', 'amount_total'])


step('Final bill = 650 - 325 advance', final_bill)

# ---------------------------------------------------------------- 6. Emails
print('==== 6. Emails queued with PDF attached')


def send(template_xmlid, res_id, user):
    tmpl = ref(template_xmlid)
    mail_id = call(user, 'mail.template', 'send_mail', [tmpl], res_id)
    m = call('admin', 'mail.mail', 'read', [mail_id], ['subject', 'email_to', 'recipient_ids', 'attachment_ids', 'state'])[0]
    names = [a['name'] for a in call('admin', 'ir.attachment', 'read', m['attachment_ids'], ['name'])]
    return m['subject'], [r[1] for r in m['recipient_ids']] if isinstance(m['recipient_ids'][0], list) else m['recipient_ids'], names, m['state']


step('Reservation confirmation email to customer', lambda: send('mariwan_reports.mail_template_reservation_confirmation', f_lot, 'saman'))
dropship_po = call('admin', 'purchase.order', 'search', [('mariwan_delivery_type', '=', 'dropship')], limit=1)
step('Drop-ship instruction email to vendor', lambda: send('mariwan_reports.mail_template_dropship_instruction', dropship_po[0], 'saman'))
step('Standard quotation email', lambda: send('sale.email_template_edi_sale', so_dp, 'saman'))
step('Standard invoice email', lambda: send('account.email_template_edi_invoice', final, 'accountant'))

print(f'\n{sum(RES)} passed, {len(RES) - sum(RES)} failed')
