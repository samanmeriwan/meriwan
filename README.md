# meriwan

Custom Odoo 20 addons for the samanmeriwan/meriwan Odoo.sh project (Mariwan Trading Ltd, UAE, AED, No VAT).

Each module goes in its own folder at the root of this repository.

| Module | Purpose |
| --- | --- |
| `mariwan_config` | Company and standard-Odoo configuration: UAE / AED / No VAT, client chart of accounts, journals, payment terms, currencies, warehouse, product categories, landed cost types, UAE / GCC pricelists, approval categories. Re-run from Settings > Technical > Mariwan > Re-apply configuration. |
| `mariwan_order_form` | Order Form: real-time availability, shortage popup, customer reservations, fulfilment type per line (stock / import / drop ship), landed-cost based cost, pricelist price, manual POs, cash / credit rules, roles. |
| `mariwan_reports` | Order Form, reservation confirmation, drop-ship instruction and landed cost prints; additions to the standard quotation, invoice, delivery slip and PO. |

Install `mariwan_reports` (it pulls in the other two).

## Data load

`tools/build_import_files.py` builds the import templates (`docs/data_load/templates`) and, from the
client item list, the product / vendor / pricelist import files (`docs/data_load`). Import them in this
order with the standard Odoo import: vendors, products, UAE pricelist, GCC pricelist.

## Task status

`docs/task_status.csv` holds the Status / Remarks for the project task sheet.
