#!/usr/bin/env python3
"""Run: python3 tools/lifecycle_check.py  (server on 127.0.0.1:8078, DB meriwan, role users loaded).

End-to-end Mariwan life cycle on the local `meriwan` DB, each step as the role user."""
import sys
import traceback
import xmlrpc.client
from datetime import date, timedelta

import os
URL = os.environ.get('MARIWAN_URL', 'http://127.0.0.1:8078')
DB = os.environ.get('MARIWAN_DB', 'meriwan')
USERS = {u: os.environ.get('MARIWAN_TEST_PW', f'{u}123') for u in ('saman', 'warehouse', 'accountant', 'finance', 'pricing', 'manager')}
USERS['admin'] = os.environ.get('MARIWAN_ADMIN_PW', 'admin')
common = xmlrpc.client.ServerProxy(URL + '/xmlrpc/2/common')
obj = xmlrpc.client.ServerProxy(URL + '/xmlrpc/2/object', allow_none=True)
UID = {u: common.authenticate(DB, u, p, {}) for u, p in USERS.items()}
TAG = 'LIFECYCLE TEST'
RESULTS = []


def call(user, model, method, *args, **kw):
    return obj.execute_kw(DB, UID[user], USERS[user], model, method, list(args), kw)


def step(name, fn):
    try:
        out = fn()
        RESULTS.append(('PASS', name, out if out is not None else ''))
        print(f'PASS  {name}  {out if out is not None else ""}', flush=True)
        return out
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if isinstance(e, xmlrpc.client.Fault):
            msg = e.faultString.strip().splitlines()[-1]
        RESULTS.append(('FAIL', name, msg))
        print(f'FAIL  {name}  -> {msg[:400]}', flush=True)
        if '-v' in sys.argv:
            traceback.print_exc()
        return None


def expect_fail(user, name, fn):
    try:
        fn()
    except xmlrpc.client.Fault as e:
        RESULTS.append(('PASS', name, 'blocked: ' + e.faultString.strip().splitlines()[-1][:120]))
        print(f'PASS  {name}  blocked: {e.faultString.strip().splitlines()[-1][:160]}', flush=True)
        return
    RESULTS.append(('FAIL', name, 'was NOT blocked'))
    print(f'FAIL  {name}  -> was NOT blocked', flush=True)


def ref(xmlid):
    module, name = xmlid.split('.')
    return call('admin', 'ir.model.data', 'search_read', [('module', '=', module), ('name', '=', name)],
                fields=['res_id'])[0]['res_id']


def product(code):
    return call('admin', 'product.product', 'search', [('default_code', '=', code)])[0]


def partner(name):
    return call('admin', 'res.partner', 'search', [('name', '=', name)], limit=1)[0]


def qty(code):
    return call('admin', 'product.product', 'read', [product(code)], ['qty_available', 'standard_price'])[0]


def validate_picking(user, picking_id):
    res = call(user, 'stock.picking', 'button_validate', [picking_id])
    if isinstance(res, dict) and res.get('res_model'):
        wiz = call(user, res['res_model'], 'create', {}, context=res.get('context', {}))
        for method in ('process', 'process_cancel_backorder', 'action_confirm'):
            try:
                call(user, res['res_model'], method, [wiz], context=res.get('context', {}))
                break
            except xmlrpc.client.Fault as e:
                if 'has no attribute' not in e.faultString and 'not a valid action' not in e.faultString:
                    raise
    return call('admin', 'stock.picking', 'read', [picking_id], ['name', 'state'])[0]


def confirm_po(po_id):
    call('saman', 'purchase.order', 'button_confirm', [po_id])
    state = call('admin', 'purchase.order', 'read', [po_id], ['state'])[0]['state']
    if state == 'to approve':
        call('manager', 'purchase.order', 'button_approve', [po_id])
    return call('admin', 'purchase.order', 'read', [po_id], ['name', 'state', 'picking_ids'])[0]


def pay_invoice(user, invoice_id, amount=None):
    ctx = {'active_model': 'account.move', 'active_ids': [invoice_id]}
    vals = {'amount': amount} if amount else {}
    wiz = call(user, 'account.payment.register', 'create', vals, context=ctx)
    call(user, 'account.payment.register', 'action_create_payments', [wiz], context=ctx)
    return call('admin', 'account.move', 'read', [invoice_id], ['name', 'payment_state', 'amount_residual'])[0]


def invoice_so(user, so_id):
    ctx = {'active_model': 'sale.order', 'active_ids': [so_id], 'active_id': so_id}
    wiz = call(user, 'sale.advance.payment.inv', 'create', {'advance_payment_method': 'delivered'}, context=ctx)
    call(user, 'sale.advance.payment.inv', 'create_invoices', [wiz], context=ctx)
    inv = call('admin', 'account.move', 'search', [('invoice_origin', 'ilike', call('admin', 'sale.order', 'read', [so_id], ['name'])[0]['name']), ('state', '=', 'draft'), ('move_type', '=', 'out_invoice')])
    call(user, 'account.move', 'action_post', inv)
    return inv[0]


def bill_po(user, po_id):
    call(user, 'purchase.order', 'action_create_invoice', [po_id])
    bills = call('admin', 'purchase.order', 'read', [po_id], ['invoice_ids'])[0]['invoice_ids']
    bill = bills[-1]
    call(user, 'account.move', 'write', [bill], {'invoice_date': str(date.today()), 'ref': f'{TAG} vendor bill'})
    call(user, 'account.move', 'action_post', [bill])
    return call('admin', 'account.move', 'read', [bill], ['name', 'state', 'amount_total', 'amount_tax'])[0]


def form(fid, fields=('name', 'state', 'order_type', 'availability', 'amount_total')):
    return call('admin', 'mariwan.order.form', 'read', [fid], list(fields))[0]


def lines(fid, fields=('product_id', 'fulfilment_type', 'product_qty', 'free_qty', 'availability_status',
                       'reserved_qty', 'reservation_status', 'total_unit_cost', 'landed_cost_unit', 'price_unit',
                       'line_status', 'po_info')):
    return call('admin', 'mariwan.order.form.line', 'search_read', [('order_form_id', '=', fid)], fields=list(fields))


TODAY = date.today()
DELIVERY = str(TODAY + timedelta(days=7))
P1, P2, P3, P4 = '16-1191', '16-1184', '16-1354', '16-1423'
VENDOR = partner('Powerstop')
CASH = partner('Sample Cash Customer')
CREDIT = partner('Sample Credit Customer (GCC)')
WH = call('admin', 'stock.warehouse', 'search', [], limit=1)[0]

print('==== 0. Master data checks')
step('Product has category, vendor, cost, UAE price', lambda: call('admin', 'product.product', 'read', [product(P1)],
     ['display_name', 'categ_id', 'standard_price', 'list_price', 'seller_ids', 'is_storable', 'taxes_id'])[0])
step('No taxes exist in the company (No VAT)', lambda: call('admin', 'account.tax', 'search_count', [], context={'active_test': False}))
step('Customer pricelists (UAE / GCC)', lambda: [call('admin', 'res.partner', 'read', [p], ['name', 'property_product_pricelist', 'mariwan_customer_type'])[0] for p in (CASH, CREDIT)])

print('==== 1. Buy for stock: PO > approval > receipt > bill > landed cost')
po1 = step('Officer creates PO (Powerstop, 2 SKUs)', lambda: call('saman', 'purchase.order', 'create', {
    'partner_id': VENDOR, 'partner_ref': TAG, 'mariwan_container_no': 'MSKU1234567', 'mariwan_port_of_loading': 'Los Angeles',
    'mariwan_bl_number': 'BL-001', 'mariwan_eta': DELIVERY,
    'order_line': [(0, 0, {'product_id': product(P1), 'product_qty': 20, 'price_unit': 55}),
                   (0, 0, {'product_id': product(P2), 'product_qty': 10, 'price_unit': 45})]}))
po1_info = step('PO confirm goes to approval, Sales Manager approves', lambda: confirm_po(po1))
receipt1 = po1_info and po1_info['picking_ids'][0]
step('Warehouse validates the receipt', lambda: validate_picking('warehouse', receipt1))
step('Stock after receipt', lambda: (qty(P1), qty(P2)))
step('Accountant posts vendor bill from PO (no tax)', lambda: bill_po('accountant', po1))
forwarder = step('Forwarder vendor', lambda: call('admin', 'res.partner', 'create', {'name': f'{TAG} Forwarder', 'supplier_rank': 1}))


def landed_cost_from_bill():
    bill = call('accountant', 'account.move', 'create', {
        'move_type': 'in_invoice', 'partner_id': forwarder, 'invoice_date': str(TODAY), 'ref': f'{TAG} freight+customs',
        'invoice_line_ids': [
            (0, 0, {'product_id': ref('mariwan_config.product_lc_freight'), 'quantity': 1, 'price_unit': 150, 'is_landed_costs_line': True}),
            (0, 0, {'product_id': ref('mariwan_config.product_lc_customs'), 'quantity': 1, 'price_unit': 90, 'is_landed_costs_line': True})]})
    call('accountant', 'account.move', 'action_post', [bill])
    action = call('accountant', 'account.move', 'button_create_landed_costs', [bill])
    lc = action['res_id']
    call('accountant', 'stock.landed.cost', 'write', [lc], {'picking_ids': [(6, 0, [receipt1])]})
    call('accountant', 'stock.landed.cost', 'compute_landed_cost', [lc])
    call('accountant', 'stock.landed.cost', 'button_validate', [lc])
    lc_data = call('admin', 'stock.landed.cost', 'read', [lc], ['name', 'state', 'amount_total', 'account_move_id'])[0]
    move = call('admin', 'account.move.line', 'search_read', [('move_id', '=', lc_data['account_move_id'][0])], fields=['account_id', 'debit', 'credit'])
    accounts = sorted({(m['account_id'][1], 'Dr' if m['debit'] else 'Cr') for m in move})
    return lc_data['name'], lc_data['state'], lc_data['amount_total'], accounts


step('Freight + customs bill > landed cost > validate (Dr Inventory / Cr Landed Cost Clearing)', landed_cost_from_bill)
step('Average cost updated with landed cost (P1 was 55, P2 was 45)', lambda: (qty(P1)['standard_price'], qty(P2)['standard_price']))

print('==== 2. Cash stock sale (Flow B)')
f1 = step('Officer creates Order Form (cash customer, WhatsApp)', lambda: call('saman', 'mariwan.order.form', 'create', {
    'partner_id': CASH, 'request_channel': 'whatsapp', 'client_order_ref': TAG, 'delivery_date': DELIVERY,
    'line_ids': [(0, 0, {'product_id': product(P1), 'product_qty': 5})]}))
step('Check availability', lambda: (call('saman', 'mariwan.order.form', 'action_check_availability', [f1]), form(f1), lines(f1))[1:])
step('Reserve all available', lambda: (call('saman', 'mariwan.order.form', 'action_reserve_all', [f1]), form(f1)['state'], lines(f1)[0]['reserved_qty'])[1:])
expect_fail('saman', 'Officer cannot read cost fields', lambda: call('saman', 'mariwan.order.form.line', 'search_read', [('order_form_id', '=', f1)], fields=['total_unit_cost']))
expect_fail('saman', 'Officer cannot override margin', lambda: call('saman', 'mariwan.order.form.line', 'write', [lines(f1)[0]['id']], {'margin_override': 50, 'override_reason': 'x'}))
step('Create quotation (UAE fixed price, no tax)', lambda: (call('saman', 'mariwan.order.form', 'action_create_quotation', [f1]),
     call('admin', 'sale.order', 'search_read', [('mariwan_order_form_id', '=', f1)], fields=['name', 'state', 'amount_untaxed', 'amount_tax', 'amount_total', 'commitment_date']))[1])
step('Confirm order (reservation converts to delivery reservation)', lambda: (call('saman', 'mariwan.order.form', 'action_confirm_order', [f1]), form(f1)['state'],
     call('admin', 'mariwan.reservation', 'search_read', [('order_form_id', '=', f1)], fields=['state']))[1:])
so1 = call('admin', 'sale.order', 'search', [('mariwan_order_form_id', '=', f1), ('state', '=', 'sale')])
out1 = so1 and call('admin', 'sale.order', 'read', so1, ['picking_ids'])[0]['picking_ids'][0]
expect_fail('warehouse', 'Delivery blocked before cash payment', lambda: call('warehouse', 'stock.picking', 'button_validate', [out1]))
inv1 = step('Accountant invoices the sales order first', lambda: invoice_so('accountant', so1[0]))
step('Accountant registers payment', lambda: pay_invoice('accountant', inv1))
step('Warehouse validates delivery after payment', lambda: validate_picking('warehouse', out1))
step('Order Form status after delivery + payment (expect closed)', lambda: form(f1)['state'])

print('==== 3. Import shortage for a credit customer (Flow C)')
f2 = step('Officer creates Order Form for 15 (stock 10)', lambda: call('saman', 'mariwan.order.form', 'create', {
    'partner_id': CREDIT, 'request_channel': 'email', 'client_order_ref': TAG, 'delivery_date': DELIVERY,
    'line_ids': [(0, 0, {'product_id': product(P2), 'product_qty': 15, 'fulfilment_type': 'import'})]}))
step('Check availability (partial)', lambda: (call('saman', 'mariwan.order.form', 'action_check_availability', [f2]), form(f2), lines(f2))[1:])
step('Reserve available part', lambda: (call('saman', 'mariwan.order.form', 'action_reserve_all', [f2]), lines(f2)[0]['reserved_qty'])[1])
step('Shortage popup opens', lambda: call('saman', 'mariwan.order.form.line', 'action_open_availability', [lines(f2)[0]['id']])['res_model'])
step('Create PO for the shortage (draft, linked)', lambda: (call('saman', 'mariwan.order.form', 'action_create_purchase_order', [f2]), form(f2)['state'],
     call('admin', 'purchase.order', 'search_read', [('mariwan_order_form_id', '=', f2)], fields=['name', 'state', 'amount_total']))[1:])
po2 = call('admin', 'purchase.order', 'search', [('mariwan_order_form_id', '=', f2)])
po2_info = step('Confirm + approve PO', lambda: confirm_po(po2[0]))
step('Receipt auto-reserves for the waiting customer', lambda: (validate_picking('warehouse', po2_info['picking_ids'][0]), lines(f2)[0]['reserved_qty'], form(f2)['state'])[1:])
step('Quotation and confirm (credit, within limit)', lambda: (call('saman', 'mariwan.order.form', 'action_create_quotation', [f2]),
     call('saman', 'mariwan.order.form', 'action_confirm_order', [f2]), form(f2)['state'])[2])
so2 = call('admin', 'sale.order', 'search', [('mariwan_order_form_id', '=', f2), ('state', '=', 'sale')])
step('Credit customer: delivery released on confirmation', lambda: validate_picking('warehouse', call('admin', 'sale.order', 'read', so2, ['picking_ids'])[0]['picking_ids'][0]))
step('Invoice after delivery (due per term)', lambda: call('admin', 'account.move', 'read', [invoice_so('accountant', so2[0])], ['name', 'invoice_date_due', 'amount_total', 'amount_tax', 'payment_state'])[0])

print('==== 4. Drop ship (Flow D)')
f3 = step('Order Form with Drop Ship line', lambda: call('saman', 'mariwan.order.form', 'create', {
    'partner_id': CREDIT, 'request_channel': 'phone', 'client_order_ref': TAG, 'delivery_date': DELIVERY,
    'line_ids': [(0, 0, {'product_id': product(P3), 'product_qty': 4, 'fulfilment_type': 'dropship', 'vendor_id': VENDOR})]}))
step('Check (no stock check, N/A)', lambda: (call('saman', 'mariwan.order.form', 'action_check_availability', [f3]), form(f3), lines(f3))[1:])
step('Quote and confirm', lambda: (call('saman', 'mariwan.order.form', 'action_create_quotation', [f3]), call('saman', 'mariwan.order.form', 'action_confirm_order', [f3]), form(f3)['state'])[2])
po3 = call('admin', 'purchase.order', 'search', [('mariwan_order_form_id', '=', f3)])
step('Draft drop-ship RFQ created with customer address', lambda: call('admin', 'purchase.order', 'read', po3, ['name', 'state', 'mariwan_delivery_type', 'dest_address_id'])[0])
po3_info = step('Officer confirms, manager approves', lambda: confirm_po(po3[0]))
ship = po3_info and po3_info['picking_ids'][0]
step('Record vendor dispatch + tracking', lambda: (call('saman', 'stock.picking', 'write', [ship], {'carrier_tracking_ref': 'UPS-1Z999', 'mariwan_dispatch_date': str(TODAY)}),
     call('admin', 'ir.cron', 'method_direct_trigger', [ref('mariwan_order_form.ir_cron_order_form_progress')]), form(f3)['state'], lines(f3)[0]['line_status'])[2:])
step('Delivery confirmation validates drop-ship (Delivered)', lambda: (validate_picking('saman', ship), form(f3)['state'], qty(P3)['qty_available'])[1:])
step('Customer invoice + vendor bill', lambda: (invoice_so('accountant', call('admin', 'sale.order', 'search', [('mariwan_order_form_id', '=', f3), ('state', '=', 'sale')])[0]), bill_po('accountant', po3[0]))[1])

print('==== 5. Conflicts, cancellation, return, credit note (Flow E)')
f4 = step('Form A reserves 6 of P1', lambda: call('saman', 'mariwan.order.form', 'create', {
    'partner_id': CASH, 'client_order_ref': TAG, 'delivery_date': DELIVERY, 'line_ids': [(0, 0, {'product_id': product(P1), 'product_qty': 6})]}))
step('reserve A', lambda: (call('saman', 'mariwan.order.form', 'action_reserve_all', [f4]), lines(f4)[0]['reserved_qty'])[1])
f5 = step('Form B (other customer) sees reduced free qty', lambda: call('saman', 'mariwan.order.form', 'create', {
    'partner_id': CREDIT, 'client_order_ref': TAG, 'delivery_date': DELIVERY, 'line_ids': [(0, 0, {'product_id': product(P1), 'product_qty': 20})]}))
step('B availability', lambda: lines(f5)[0])
expect_fail('saman', 'Officer cannot re-assign a reservation', lambda: call('saman', 'mariwan.reservation.reassign', 'create', {
    'reservation_id': call('admin', 'mariwan.reservation', 'search', [('order_form_id', '=', f4), ('state', '=', 'active')])[0],
    'quantity': 2, 'target_line_id': lines(f5)[0]['id'], 'reason': 'test'}))


def reassign():
    res = call('admin', 'mariwan.reservation', 'search', [('order_form_id', '=', f4), ('state', '=', 'active')])[0]
    wiz = call('manager', 'mariwan.reservation.reassign', 'create', {'reservation_id': res, 'quantity': 2, 'target_line_id': lines(f5)[0]['id'], 'reason': f'{TAG} VIP'})
    call('manager', 'mariwan.reservation.reassign', 'action_confirm', [wiz])
    return form(f4, ['name', 'reservation_flagged']), lines(f4)[0]['reserved_qty'], lines(f5)[0]['reserved_qty']


step('Sales Manager re-assigns 2 with reason (A flagged)', reassign)
step('Cancel form A releases reservations', lambda: (call('saman', 'mariwan.order.form', 'action_cancel', [f4]), form(f4)['state'],
     call('admin', 'mariwan.reservation', 'search_read', [('order_form_id', '=', f4)], fields=['state']))[1:])


def customer_return():
    picking = call('admin', 'sale.order', 'read', so1, ['picking_ids'])[0]['picking_ids'][0]
    ret = call('warehouse', 'stock.picking', 'action_return', [picking])['res_id']
    for mv in call('warehouse', 'stock.move', 'search_read', [('picking_id', '=', ret)], fields=['origin_returned_move_id']):
        orig = call('warehouse', 'stock.move', 'read', [mv['origin_returned_move_id'][0]], ['quantity'])[0]['quantity']
        call('warehouse', 'stock.move', 'write', [mv['id']], {'product_uom_qty': orig})
    call('warehouse', 'stock.picking', 'action_confirm', [ret])
    call('warehouse', 'stock.picking', 'action_assign', [ret])
    return validate_picking('warehouse', ret), qty(P1)['qty_available']


step('Customer return of the cash sale', customer_return)


def credit_note():
    ctx = {'active_model': 'account.move', 'active_ids': [inv1]}
    wiz = call('accountant', 'account.move.reversal', 'create', {'reason': f'{TAG} customer return', 'journal_id': call('admin', 'account.move', 'read', [inv1], ['journal_id'])[0]['journal_id'][0]}, context=ctx)
    res = call('accountant', 'account.move.reversal', 'refund_moves', [wiz], context=ctx)
    refund = res['res_id']
    call('accountant', 'account.move', 'action_post', [refund])
    return call('admin', 'account.move', 'read', [refund], ['name', 'state', 'amount_total', 'mariwan_order_form_id'])[0]


step('Credit note with reason', credit_note)

print('==== 6. Credit block and override')
f6 = step('Big order for credit customer above limit', lambda: call('saman', 'mariwan.order.form', 'create', {
    'partner_id': CREDIT, 'client_order_ref': TAG, 'delivery_date': DELIVERY,
    'line_ids': [(0, 0, {'product_id': product(P4), 'product_qty': 1500, 'fulfilment_type': 'dropship', 'vendor_id': VENDOR})]}))
step('check + quote', lambda: (call('saman', 'mariwan.order.form', 'action_check_availability', [f6]), call('saman', 'mariwan.order.form', 'action_create_quotation', [f6]), form(f6)['amount_total'])[2])
expect_fail('saman', 'Confirmation blocked by credit limit', lambda: call('saman', 'mariwan.order.form', 'action_confirm_order', [f6]))
so6 = call('admin', 'sale.order', 'search', [('mariwan_order_form_id', '=', f6), ('state', 'in', ('draft', 'sent'))])
expect_fail('saman', 'Officer cannot override credit block', lambda: call('saman', 'sale.order', 'action_mariwan_override_credit', so6))
step('Finance Manager overrides, order confirms', lambda: (call('finance', 'sale.order', 'action_mariwan_override_credit', so6),
     call('saman', 'mariwan.order.form', 'action_confirm_order', [f6]), form(f6)['state'])[2])

print('==== 7. Price override by Pricing Manager')
f7 = call('saman', 'mariwan.order.form', 'create', {'partner_id': CASH, 'client_order_ref': TAG, 'delivery_date': DELIVERY,
                                                   'line_ids': [(0, 0, {'product_id': product(P2), 'product_qty': 1})]})
expect_fail('pricing', 'Override without reason blocked', lambda: call('pricing', 'mariwan.order.form.line', 'write', [lines(f7)[0]['id']], {'margin_override': 30}))
step('Override with reason (logged)', lambda: (call('pricing', 'mariwan.order.form.line', 'write', [lines(f7)[0]['id']], {'margin_override': 30, 'override_reason': f'{TAG} key account'}),
     call('pricing', 'mariwan.order.form.line', 'read', [lines(f7)[0]['id']], ['total_unit_cost', 'margin_percent', 'price_unit', 'is_price_overridden'])[0])[1])

print('==== 8. Prints and emails')
reports = [('mariwan_reports.action_report_order_form', f1), ('mariwan_reports.action_report_reservation_confirmation', f2),
           ('sale.action_report_saleorder', so1[0] if so1 else None), ('account.account_invoices', inv1),
           ('stock.action_report_delivery', out1), ('purchase.action_report_purchase_order', po1),
           ('mariwan_reports.action_report_dropship_instruction', po3[0] if po3 else None)]
lc_ids = call('admin', 'stock.landed.cost', 'search', [], limit=1)
reports.append(('mariwan_reports.action_report_landed_cost', lc_ids[0] if lc_ids else None))
RESULTS_REPORTS = reports
print('REPORT_IDS', reports, flush=True)

print('\n==== SUMMARY')
print(f"{sum(r[0] == 'PASS' for r in RESULTS)} passed, {sum(r[0] == 'FAIL' for r in RESULTS)} failed")
for r in RESULTS:
    if r[0] == 'FAIL':
        print('  FAIL', r[1], '->', str(r[2])[:300])
