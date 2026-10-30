#!/usr/bin/env python3
"""Import the Mariwan master data files into an Odoo database over the external API.

Uses the same `load` method as Settings > Import, so it can be re-run: records
with the same external ID are updated, not duplicated.

    python3 tools/import_client_data.py --url https://<db>.dev.odoo.com --db <db> \\
        --login admin --password <password or API key>

Order: vendors, products, UAE price list, GCC price list (docs/data_load).
"""
import argparse
import os
import xmlrpc.client

import openpyxl

FILES = [
    ('res.partner', 'client_vendors_import.xlsx'),
    ('product.product', 'client_products_import.xlsx'),
    ('product.pricelist.item', 'client_pricelist_uae_import.xlsx'),
    ('product.pricelist.item', 'client_pricelist_gcc_import.xlsx'),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', required=True)
    parser.add_argument('--db', required=True)
    parser.add_argument('--login', required=True)
    parser.add_argument('--password', required=True, help='Password or API key')
    parser.add_argument('--dir', default=os.path.join(os.path.dirname(__file__), '..', 'docs', 'data_load'))
    parser.add_argument('--chunk', type=int, default=200)
    args = parser.parse_args()

    url = args.url.rstrip('/')
    uid = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common').authenticate(args.db, args.login, args.password, {})
    if not uid:
        raise SystemExit('Login failed: check database, login and password / API key.')
    models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object', allow_none=True)
    installed = models.execute_kw(args.db, uid, args.password, 'ir.module.module', 'search_count',
                                  [[('name', '=', 'mariwan_order_form'), ('state', '=', 'installed')]])
    if not installed:
        raise SystemExit('Install "Mariwan - Document Templates" first (it adds the categories and price lists).')

    for model, filename in FILES:
        ws = openpyxl.load_workbook(os.path.join(args.dir, filename), data_only=True)['Import']
        rows = [[('' if v is None else str(v)) for v in r] for r in ws.iter_rows(values_only=True)]
        header, data = rows[0], [r for r in rows[1:] if any(r)]
        done, errors = 0, []
        for i in range(0, len(data), args.chunk):
            res = models.execute_kw(args.db, uid, args.password, model, 'load', [header, data[i:i + args.chunk]])
            batch_errors = [m for m in res['messages'] if m.get('type') == 'error']
            if batch_errors:
                errors += [(i + m.get('record', 0) + 2, m['message']) for m in batch_errors]
            else:
                done += len(res['ids'] or [])
        print(f'{filename}: {done} records imported, {len(errors)} errors')
        for row, message in errors[:10]:
            print(f'   row {row}: {message}')


if __name__ == '__main__':
    main()
