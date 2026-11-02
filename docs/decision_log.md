# Decision and Issue Log - Mariwan / Meriwan Trading Odoo 20

## Decisions

| # | Date | Decision | Why |
|---|------|----------|-----|
| D1 | 2026-10-30 | Odoo 20 Enterprise on Odoo.sh; 3 modules: `mariwan_config` (setup), `mariwan_order_form` (Order Form + rules), `mariwan_reports` (documents) | Keep custom code small and separate from configuration |
| D2 | 2026-10-30 | Standard Odoo wherever it exists (pricelists, landed costs, drop-ship route, PO approval, credit limit, lock dates, Approvals app) | The task sheet was AI-generated; standard features are cheaper to maintain |
| D3 | 2026-10-30 | No VAT: no taxes on products, documents or fiscal positions | Client is not VAT registered; tax can be added later as a change request |
| D4 | 2026-10-30 | Client chart of accounts on top of the generic Odoo chart | Client file "Chart of Accounts - Meriwan Dubai.xlsx" |
| D5 | 2026-10-30 | Selling prices = fixed UAE / GCC price per item from the client file; 15% markup on cost only as fallback | Client file "Categories and item details.xlsx" |
| D6 | 2026-10-30 | Average cost, real-time stock valuation, landed costs added to stock value | Import business: freight, customs and clearing are part of item cost |
| D7 | 2026-10-30 | Cash customers: full payment before delivery (setting allows 50% advance instead); credit customers: blocked above credit limit or with overdue invoices, Finance Manager can override | Client payment rules |
| D8 | 2026-10-30 | Reservations hold stock until tentative date + grace days; expiry raises an alert, never a silent release | Avoid losing customer holds without anyone knowing |
| D9 | 2026-11-02 | Client document formats (Invoice, Delivery Challan, Packing Slip) as the default prints; standard Odoo layouts kept as alternatives | Client sent its own formats |
| D10 | 2026-11-02 | Company name "Meriwan Trading FZCO", Jafza One, Building BB1307, from the client formats | Client documents |
| D11 | 2026-11-02 | Password minimum 8 characters (standard policy); 2FA available per user, enforced only after outgoing email works in production | Avoid locking users out |

## Open questions for the client

| # | Question | Status |
|---|----------|--------|
| Q1 | Should vendor bills, payments and journal entries be blocked until approved, or is an approval request with a record enough? | Waiting |
| Q2 | Are vendor costs in the item file in AED? | Waiting |
| Q3 | Prices for the 17 items without a price | Waiting |
| Q4 | User list (name, email, role) | Waiting |
| Q5 | Opening balances and opening stock at go-live date | Waiting |
| Q6 | Is Manufacturing needed? (installed on Odoo.sh production, not used by a trading company) | Waiting |

## Issues found and fixed during testing

| # | Date | Issue | Fix |
|---|------|-------|-----|
| I1 | 2026-10-30 | Cash delivery stayed blocked after payment ("In Payment" invoices not counted) | Count In Payment as paid |
| I2 | 2026-11-01 | Accountant could not validate landed costs when Manufacturing is installed | Read target moves with elevated rights |
| I3 | 2026-11-01 | Warehouse user could not open Order Forms that have invoices | Smart-button counts computed with elevated rights |
