"""Import the Mariwan master data inside an Odoo shell (Odoo.sh SHELL tab or local):

    odoo-bin shell < ~/src/user/tools/import_client_data_shell.py

Same files and `load` method as tools/import_client_data.py; safe to re-run.
"""
import os

import openpyxl

FILES = [
    ('res.partner', 'client_vendors_import.xlsx'),
    ('product.product', 'client_products_import.xlsx'),
    ('product.pricelist.item', 'client_pricelist_uae_import.xlsx'),
    ('product.pricelist.item', 'client_pricelist_gcc_import.xlsx'),
]
for base in ('/home/odoo/src/user/docs/data_load', '/home/rabbul-mia/odoo20/meriwan/docs/data_load'):
    if os.path.isdir(base):
        break

if not env['ir.module.module'].search_count([('name', '=', 'mariwan_order_form'), ('state', '=', 'installed')]):
    print('STOP: install "Mariwan - Document Templates" first (Apps).')
else:
    for model, filename in FILES:
        ws = openpyxl.load_workbook(os.path.join(base, filename), data_only=True)['Import']
        rows = [[('' if v is None else str(v)) for v in r] for r in ws.iter_rows(values_only=True)]
        header, data = rows[0], [r for r in rows[1:] if any(r)]
        done, errors = 0, []
        for i in range(0, len(data), 200):
            res = env[model].load(header, data[i:i + 200])
            batch_errors = [m for m in res['messages'] if m.get('type') == 'error']
            if batch_errors:
                errors += [(i + m.get('record', 0) + 2, m['message']) for m in batch_errors]
            else:
                done += len(res['ids'] or [])
        env.cr.commit()
        print(f'{filename}: {done} records imported, {len(errors)} errors')
        for row, message in errors[:10]:
            print(f'   row {row}: {message}')
