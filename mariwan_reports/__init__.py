def post_init_hook(env):
    """Task 12.1: standard company layout on A4, amount in words on invoices."""
    company = env.ref('base.main_company')
    vals = {'display_invoice_amount_total_words': True}
    a4 = env.ref('base.paperformat_euro', raise_if_not_found=False)
    if a4:
        vals['paperformat_id'] = a4.id
    if not company.external_report_layout_id:
        vals['external_report_layout_id'] = env.ref('web.external_layout_standard').id
    company.write(vals)
