#!/usr/bin/env python3
"""Run: python3 tools/ui_check.py  (server on 127.0.0.1:8078, DB meriwan, role users loaded).

Replay the web client calls (get_views / onchange / web_save / web_read / buttons) per role."""
import json, urllib.request, http.cookiejar
import os
URL = os.environ.get('MARIWAN_URL', 'http://127.0.0.1:8078')
DB = os.environ.get('MARIWAN_DB', 'meriwan')
RESULTS = []

class Session:
    def __init__(self, login, pw):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        r = self.rpc('/web/session/authenticate', {'db': DB, 'login': login, 'password': pw})
        self.uid = r['uid']; self.ctx = r['user_context']; self.login = login
    def rpc(self, path, params):
        req = urllib.request.Request(URL + path, json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': params}).encode(),
                                     {'Content-Type': 'application/json'})
        res = json.loads(self.op.open(req).read())
        if 'error' in res:
            d = res['error'].get('data', {})
            raise Exception(d.get('message') or res['error'].get('message'))
        return res['result']
    def call(self, model, method, args=(), **kw):
        kw.setdefault('context', self.ctx)
        return self.rpc(f'/web/dataset/call_kw/{model}/{method}', {'model': model, 'method': method, 'args': list(args), 'kwargs': kw})
    def button(self, model, method, ids):
        return self.rpc('/web/dataset/call_button/' + model + '/' + method, {'model': model, 'method': method, 'args': [ids], 'kwargs': {'context': self.ctx}})

def check(name, fn):
    try:
        out = fn(); RESULTS.append(True); print('PASS', name, '' if out is None else str(out)[:160])
        return out
    except Exception as e:
        RESULTS.append(False); print('FAIL', name, '->', str(e)[:300])

def spec(fields_desc):
    return {f: {} for f in fields_desc}

def open_form(s, model, view_types=(('list', False), ('form', False), ('search', False))):
    v = s.call(model, 'get_views', [list(view_types)], options={'toolbar': True, 'load_filters': True})
    return v

admin = Session('admin', os.environ.get('MARIWAN_ADMIN_PW', 'admin'))
roles = {u: Session(u, os.environ.get('MARIWAN_TEST_PW', u + '123')) for u in ('saman', 'warehouse', 'accountant', 'finance', 'pricing', 'manager')}
roles['admin'] = admin

# 1. Every Mariwan view loads for every role, and the list/kanban/pivot data loads
for login, s in roles.items():
    def views(s=s):
        v = s.call('mariwan.order.form', 'get_views', [[[False, 'list'], [False, 'kanban'], [False, 'form'], [False, 'search'], [False, 'pivot'], [False, 'graph']]], options={'toolbar': True, 'load_filters': True})
        fields = v['models']['mariwan.order.form']['fields']
        data = s.call('mariwan.order.form', 'web_search_read', [[]], specification={'name': {}, 'state': {}, 'availability': {}, 'amount_total': {}}, limit=80)
        lines = v['models'].get('mariwan.order.form.line', {}).get('fields', {})
        return f"{data['length']} forms, cost column visible: {'total_unit_cost' in lines}"
    check(f'[{login}] Order Form list/kanban/form/search/pivot views + data', views)
    check(f'[{login}] Reservations view', lambda s=s: s.call('mariwan.reservation', 'web_search_read', [[]], specification={'name': {}, 'state': {}}, limit=10)['length'])
    check(f'[{login}] Margin analysis / drop-ship reports', lambda s=s: s.call('mariwan.order.form.line', 'get_views', [[[False, 'list'], [False, 'pivot'], [False, 'search']]]) and 'ok')

# 2. Open an existing form exactly like the browser (web_read with the form's field spec)
s = roles['saman']
v = s.call('mariwan.order.form', 'get_views', [[[False, 'form']]])
form_fields = v['models']['mariwan.order.form']['fields']
line_fields = v['models']['mariwan.order.form.line']['fields']
fspec = {f: {} for f in form_fields if f not in ('line_ids', 'reservation_ids', 'message_ids', 'activity_ids', 'message_follower_ids')}
fspec['line_ids'] = {'fields': {f: {} for f in line_fields}}
for login in ('saman', 'warehouse', 'accountant', 'pricing', 'manager', 'admin'):
    rs = roles[login]
    vv = rs.call('mariwan.order.form', 'get_views', [[[False, 'form']]])
    sp = {f: {} for f in vv['models']['mariwan.order.form']['fields'] if f not in ('line_ids', 'reservation_ids', 'message_ids', 'activity_ids', 'message_follower_ids')}
    sp['line_ids'] = {'fields': {f: {} for f in vv['models']['mariwan.order.form.line']['fields']}}
    ids = rs.call('mariwan.order.form', 'search', [[]], limit=3)
    check(f'[{login}] open 3 Order Forms in form view (web_read)', lambda rs=rs, ids=ids, sp=sp: len(rs.call('mariwan.order.form', 'web_read', [ids], specification=sp)))

# 3. New Order Form as Saman through onchange + web_save, like typing in the browser
cust = admin.call('res.partner', 'search', [[('name', '=', 'Sample Cash Customer')]])[0]
prod = admin.call('product.product', 'search', [[('default_code', '=', '16-1423')]])[0]
def new_form():
    sp_form = {k: v for k, v in fspec.items() if k != 'line_ids'}
    defaults = s.call('mariwan.order.form', 'onchange', [[], {}, [], sp_form])['value']
    after_partner = s.call('mariwan.order.form', 'onchange', [[], {'partner_id': cust}, ['partner_id'], sp_form])['value']
    lspec = {f: {} for f in line_fields}
    line_vals = s.call('mariwan.order.form.line', 'onchange', [[], {'product_id': prod, 'product_qty': 3}, ['product_id'], lspec],
                       context=dict(s.ctx, default_delivery_date=None))['value']
    rec = s.call('mariwan.order.form', 'web_save', [[], {'partner_id': cust, 'request_channel': 'walk_in', 'client_order_ref': 'UI TEST',
                 'delivery_date': '2026-11-15', 'line_ids': [[0, 'virtual_1', {'product_id': prod, 'product_qty': 3}]]}],
                 specification={'name': {}, 'state': {}, 'payment_type': {}, 'availability': {}})[0]
    return rec, {'default_salesperson': defaults.get('user_id'), 'partner_onchange': {k: after_partner.get(k) for k in ('payment_type', 'contact_name', 'partner_shipping_id')},
                 'line_onchange': {k: line_vals.get(k) for k in ('fulfilment_type', 'product_uom_id', 'price_unit', 'availability_status')}}
res = check('[saman] new Order Form via onchange + web_save', new_form)
fid = res and res[0]['id']

# 4. Buttons as the browser calls them
if fid:
    check('[saman] button Check Availability', lambda: s.button('mariwan.order.form', 'action_check_availability', [fid]))
    lid = s.call('mariwan.order.form', 'web_read', [[fid]], specification={'line_ids': {'fields': {'id': {}}}})[0]['line_ids'][0]['id']
    popup = check('[saman] shortage flag opens popup', lambda: s.button('mariwan.order.form.line', 'action_open_availability', [lid]))
    if popup:
        pv = s.call('mariwan.availability.popup', 'get_views', [[[False, 'form']]])
        pspec = {f: {} for f in pv['models']['mariwan.availability.popup']['fields']}
        for rel in ('reservation_ids', 'incoming_line_ids'):
            pspec[rel] = {'fields': {f: {} for f in pv['models'][pv['models']['mariwan.availability.popup']['fields'][rel]['relation']]['fields']}}
        check('[saman] popup content loads', lambda: s.call('mariwan.availability.popup', 'web_read', [[popup['res_id']]], specification=pspec)[0]['free_qty'])
    check('[saman] button Create Purchase Order (import line) / message', lambda: s.button('mariwan.order.form', 'action_create_quotation', [fid]) and 'quotation action returned')
    for name, model, method in (('Quotation', 'mariwan.order.form', 'action_view_quotations'),):
        check(f'[saman] smart button {name}', lambda: s.button(model, method, [fid])['res_model'])
    check('[saman] print Order Form PDF', lambda: s.op.open(URL + f'/report/pdf/mariwan_reports.report_order_form/{fid}').status)
    check('[saman] Cancel button', lambda: s.button('mariwan.order.form', 'action_cancel', [fid]))

# 5. Standard forms extended by the module open for the roles that use them
for login, model in (('saman', 'sale.order'), ('saman', 'purchase.order'), ('warehouse', 'stock.picking'), ('accountant', 'account.move'),
                     ('saman', 'product.template'), ('saman', 'res.partner'), ('pricing', 'product.category'), ('admin', 'res.config.settings')):
    rs = roles[login]
    def std(rs=rs, model=model):
        vv = rs.call(model, 'get_views', [[[False, 'form']]])
        ids = rs.call(model, 'search', [[]], limit=2) if model != 'res.config.settings' else []
        if ids:
            # like the browser: only fields left in the arch after group filtering
            arch = vv['views']['form']['arch']
            sp = {f: {} for f, d in vv['models'][model]['fields'].items()
                  if d['type'] not in ('one2many', 'many2many') and f'name="{f}"' in arch}
            rs.call(model, 'web_read', [ids], specification=sp)
        return 'ok'
    check(f'[{login}] {model} form with Mariwan fields', std)

print(f'\n{sum(RESULTS)} passed, {len(RESULTS) - sum(RESULTS)} failed')
