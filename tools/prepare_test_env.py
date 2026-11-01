#!/usr/bin/env python3
"""Create (or archive) the role test users and sample customers used by the check scripts.

    MARIWAN_URL=... MARIWAN_DB=... MARIWAN_ADMIN_PW=... MARIWAN_TEST_PW=... python3 tools/prepare_test_env.py
    ... python3 tools/prepare_test_env.py --archive     # deactivate the test users afterwards

All test users share the password in MARIWAN_TEST_PW. Never run this on production.
"""
import os
import sys
import xmlrpc.client

URL = os.environ.get('MARIWAN_URL', 'http://127.0.0.1:8078')
DB = os.environ.get('MARIWAN_DB', 'meriwan')
ADMIN_PW = os.environ.get('MARIWAN_ADMIN_PW', 'admin')
TEST_PW = os.environ.get('MARIWAN_TEST_PW')
ROLES = [
    ('saman', 'Saman (Sales / Purchase Officer)', 'group_officer'),
    ('warehouse', 'Warehouse User', 'group_warehouse'),
    ('accountant', 'Accountant', 'group_accountant'),
    ('finance', 'Finance Manager', 'group_finance_manager'),
    ('pricing', 'Pricing Manager', 'group_pricing_manager'),
    ('manager', 'Sales Manager / Management', 'group_sales_manager'),
]

uid = xmlrpc.client.ServerProxy(URL + '/xmlrpc/2/common').authenticate(DB, 'admin', ADMIN_PW, {})
if not uid:
    raise SystemExit('Admin login failed.')
obj = xmlrpc.client.ServerProxy(URL + '/xmlrpc/2/object', allow_none=True)


def call(model, method, *args, **kw):
    return obj.execute_kw(DB, uid, ADMIN_PW, model, method, list(args), kw)


def ref(xmlid):
    module, name = xmlid.split('.')
    return call('ir.model.data', 'search_read', [('module', '=', module), ('name', '=', name)], fields=['res_id'])[0]['res_id']


logins = [r[0] for r in ROLES]
if '--archive' in sys.argv:
    ids = call('res.users', 'search', [('login', 'in', logins)])
    call('res.users', 'write', ids, {'active': False})
    print(f'Archived {len(ids)} test users.')
    raise SystemExit

if not TEST_PW:
    raise SystemExit('Set MARIWAN_TEST_PW to the password for the test users.')
for login, name, group in ROLES:
    vals = {'name': name, 'login': login, 'password': TEST_PW, 'tz': 'Asia/Dubai',
            'group_ids': [(4, ref('base.group_user')), (4, ref(f'mariwan_order_form.{group}'))]}
    existing = call('res.users', 'search', [('login', '=', login)], context={'active_test': False})
    if existing:
        call('res.users', 'write', existing, dict(vals, active=True))
    else:
        call('res.users', 'create', vals)
    print('user', login)
for name, ctype, pricelist in (('Sample Cash Customer', 'cash', 'pricelist_uae'),
                               ('Sample Credit Customer (GCC)', 'credit', 'pricelist_gcc')):
    # A previous run leaves invoices that become overdue and block new orders: start fresh.
    old = call('res.partner', 'search', [('name', '=', name)])
    if old and call('account.move', 'search_count', [('partner_id', 'in', old), ('state', '=', 'posted')]):
        call('res.partner', 'write', old, {'active': False})
        old = []
    if not old:
        call('res.partner', 'create', {
            'name': name, 'is_company': True, 'customer_rank': 1, 'mariwan_customer_type': ctype,
            'credit_limit': 50000 if ctype == 'credit' else 0, 'country_id': ref('base.ae'),
            'property_product_pricelist': ref(f'mariwan_config.{pricelist}')})
    print('customer', name)
