from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError

ORDER_FORM_STATES = [
    ('draft', 'Draft'),
    ('checked', 'Checked'),
    ('reserved', 'Reserved'),
    ('awaiting_stock', 'Awaiting Stock'),
    ('awaiting_vendor', 'Awaiting Vendor'),
    ('quoted', 'Quoted'),
    ('confirmed', 'Confirmed'),
    ('in_delivery', 'In Delivery'),
    ('delivered', 'Delivered'),
    ('closed', 'Closed'),
    ('cancel', 'Cancelled'),
]
OPEN_STATES = ('draft', 'checked', 'reserved', 'awaiting_stock', 'awaiting_vendor', 'quoted')


class MariwanOrderForm(models.Model):
    _name = 'mariwan.order.form'
    _description = 'Order Form'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'
    _check_company_auto = True

    # A. Header
    name = fields.Char('Order Form No.', required=True, copy=False, readonly=True, index='trigram', default='New')
    date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    partner_id = fields.Many2one(
        'res.partner', 'Customer', required=True, tracking=True, check_company=True, index=True,
        domain="[('type', '!=', 'private'), ('is_company', '=', True)]")
    contact_name = fields.Char('Contact Person', compute='_compute_contact', store=True, readonly=False)
    contact_phone = fields.Char('Contact Phone', compute='_compute_contact', store=True, readonly=False)
    request_channel = fields.Selection([
        ('phone', 'Phone'), ('whatsapp', 'WhatsApp'), ('email', 'Email'), ('walk_in', 'Walk-in'),
    ], required=True, default='phone')
    client_order_ref = fields.Char('Customer Reference', help="Customer's own RFQ / PO number")
    user_id = fields.Many2one('res.users', 'Salesperson', required=True, default=lambda self: self.env.user,
                              tracking=True, domain="[('share', '=', False)]")
    order_type = fields.Selection([
        ('stock', 'Stock Sale'), ('import', 'Import Order'), ('dropship', 'Drop Ship'), ('mixed', 'Mixed'),
    ], compute='_compute_order_type', store=True)
    warehouse_id = fields.Many2one(
        'stock.warehouse', required=True, check_company=True,
        default=lambda self: self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1))
    payment_type = fields.Selection([('cash', 'Cash'), ('credit', 'Credit')], required=True, precompute=True,
                                    compute='_compute_payment_type', store=True, readonly=False, tracking=True)
    payment_term_id = fields.Many2one('account.payment.term', compute='_compute_payment_type', store=True,
                                      readonly=False, check_company=True, precompute=True)
    delivery_date = fields.Date('Tentative Delivery Date', tracking=True)
    partner_shipping_id = fields.Many2one(
        'res.partner', 'Delivery Address', compute='_compute_partner_shipping_id', store=True, readonly=False,
        check_company=True, domain="['|', ('id', '=', partner_id), ('parent_id', '=', partner_id)]")
    note = fields.Text('Customer Notes')
    internal_note = fields.Text('Internal Notes')
    state = fields.Selection(ORDER_FORM_STATES, default='draft', required=True, tracking=True, copy=False, index=True)
    line_ids = fields.One2many('mariwan.order.form.line', 'order_form_id', 'Lines', copy=True)
    can_edit_date = fields.Boolean(compute='_compute_can_edit_date')
    reservation_flagged = fields.Boolean(
        'Reservation re-assigned', copy=False, tracking=True,
        help="Set when a Sales Manager re-assigned stock reserved for this customer to another order.")

    # Customer credit block (A3)
    customer_type = fields.Selection(related='partner_id.commercial_partner_id.mariwan_customer_type')
    credit_limit = fields.Float(related='partner_id.commercial_partner_id.credit_limit')
    partner_balance = fields.Monetary('Outstanding Balance', compute='_compute_partner_balance')
    partner_overdue = fields.Monetary('Overdue Amount', compute='_compute_partner_balance')

    # A18 / A19
    availability = fields.Selection([
        ('green', 'All Available'), ('amber', 'Partially Available'), ('red', 'Not Available'),
    ], 'Overall Availability', compute='_compute_availability', search='_search_availability')
    amount_total = fields.Monetary('Total Selling', compute='_compute_amounts', store=True)
    amount_cost = fields.Monetary('Total Cost', compute='_compute_amounts', store=True,
                                  groups='mariwan_order_form.group_cost_access')
    amount_margin = fields.Monetary('Gross Margin', compute='_compute_amounts', store=True,
                                    groups='mariwan_order_form.group_cost_access')

    # A20 links
    sale_order_ids = fields.One2many('sale.order', 'mariwan_order_form_id', 'Quotations / Sales Orders')
    purchase_order_ids = fields.One2many('purchase.order', 'mariwan_order_form_id', 'Purchase Orders')
    reservation_ids = fields.One2many('mariwan.reservation', 'order_form_id', 'Reservations')
    quotation_count = fields.Integer(compute='_compute_counts')
    sale_count = fields.Integer(compute='_compute_counts')
    purchase_count = fields.Integer(compute='_compute_counts')
    receipt_count = fields.Integer(compute='_compute_counts')
    delivery_count = fields.Integer(compute='_compute_counts')
    vendor_shipment_count = fields.Integer(compute='_compute_counts')
    invoice_count = fields.Integer(compute='_compute_counts')
    payment_count = fields.Integer(compute='_compute_counts')
    is_overdue = fields.Boolean('Delivery Date Overdue', compute='_compute_is_overdue', search='_search_is_overdue')

    @api.depends('partner_id')
    def _compute_contact(self):
        for form in self:
            form.contact_name = form.partner_id.name if form.partner_id else False
            form.contact_phone = form.partner_id.phone if form.partner_id else False

    @api.depends('partner_id')
    def _compute_payment_type(self):
        for form in self:
            commercial = form.partner_id.commercial_partner_id
            form.payment_type = commercial.mariwan_customer_type or 'cash'
            form.payment_term_id = commercial.property_payment_term_id \
                or self.env.ref('account.account_payment_term_immediate', raise_if_not_found=False)

    @api.depends('partner_id')
    def _compute_partner_shipping_id(self):
        for form in self:
            form.partner_shipping_id = form.partner_id.address_get(['delivery'])['delivery'] if form.partner_id else False

    def _compute_can_edit_date(self):
        is_manager = self.env.user.has_group('mariwan_order_form.group_sales_manager')
        self.can_edit_date = is_manager

    @api.depends('partner_id')
    def _compute_partner_balance(self):
        today = fields.Date.context_today(self)
        for form in self:
            commercial = form.partner_id.commercial_partner_id
            if not commercial:
                form.partner_balance = form.partner_overdue = 0.0
                continue
            lines = self.env['account.move.line'].sudo().search([
                ('partner_id', 'child_of', commercial.id),
                ('account_type', '=', 'asset_receivable'),
                ('parent_state', '=', 'posted'),
                ('reconciled', '=', False),
                ('company_id', '=', form.company_id.id),
            ])
            form.partner_balance = sum(lines.mapped('amount_residual'))
            form.partner_overdue = sum(lines.filtered(
                lambda l: l.date_maturity and l.date_maturity < today).mapped('amount_residual'))

    @api.depends('line_ids.fulfilment_type')
    def _compute_order_type(self):
        for form in self:
            types = set(form.line_ids.mapped('fulfilment_type'))
            if len(types) > 1:
                form.order_type = 'mixed'
            else:
                form.order_type = types.pop() if types else 'stock'

    @api.depends('line_ids.availability_status')
    def _compute_availability(self):
        for form in self:
            statuses = set(form.line_ids.filtered(lambda l: l.fulfilment_type == 'stock').mapped('availability_status'))
            if 'not_available' in statuses:
                form.availability = 'red'
            elif 'partial' in statuses:
                form.availability = 'amber'
            else:
                form.availability = 'green'

    def _search_availability(self, operator, value):
        if operator not in ('in', 'not in'):
            return NotImplemented
        forms = self.search([('state', 'in', OPEN_STATES)])
        matching = forms.filtered(lambda f: f.availability in value)
        return [('id', operator, matching.ids)]

    @api.depends('line_ids.price_subtotal', 'line_ids.cost_subtotal')
    def _compute_amounts(self):
        for form in self:
            lines = form.line_ids
            form.amount_total = sum(lines.mapped('price_subtotal'))
            form.amount_cost = sum(lines.mapped('cost_subtotal'))
            form.amount_margin = form.amount_total - form.amount_cost

    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for form in self:
            form.is_overdue = bool(form.delivery_date and form.delivery_date < today
                                   and form.state not in ('delivered', 'closed', 'cancel'))

    def _search_is_overdue(self, operator, value):
        if operator != 'in':
            return NotImplemented
        domain = [('delivery_date', '<', fields.Date.context_today(self)),
                  ('state', 'not in', ('delivered', 'closed', 'cancel'))]
        return domain if True in value else ['!', *domain]

    def _get_pickings(self):
        return self.sale_order_ids.picking_ids | self.purchase_order_ids.picking_ids

    def _get_invoices(self):
        return self.sale_order_ids.invoice_ids.filtered(lambda m: m.state != 'cancel')

    def _get_payments(self):
        return self._get_invoices()._get_reconciled_payments()

    def _compute_counts(self):
        # Counts only (e.g. the Warehouse user has no access to invoices); the buttons keep normal rights.
        for form in self:
            sudo_form = form.sudo()
            sales = sudo_form.sale_order_ids
            pickings = sudo_form._get_pickings()
            form.quotation_count = len(sales.filtered(lambda s: s.state in ('draft', 'sent')))
            form.sale_count = len(sales.filtered(lambda s: s.state == 'sale'))
            form.purchase_count = len(sudo_form.purchase_order_ids)
            form.receipt_count = len(pickings.filtered(lambda p: p.picking_type_code == 'incoming'))
            form.delivery_count = len(pickings.filtered(lambda p: p.picking_type_code == 'outgoing'))
            form.vendor_shipment_count = len(pickings.filtered(lambda p: p.picking_type_code == 'dropship'))
            form.invoice_count = len(sudo_form._get_invoices())
            form.payment_count = len(sudo_form._get_payments())

    # ------------------------------------------------------------------
    # CRUD & validation (task 6.7)
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('mariwan.order.form') or 'New'
        forms = super().create(vals_list)
        forms._check_has_lines()
        return forms

    def write(self, vals):
        if 'date' in vals and not self.env.su and not self.env.user.has_group('mariwan_order_form.group_sales_manager'):
            raise UserError(self.env._("Only the Sales Manager can change the Order Form date."))
        if self.filtered(lambda f: f.state in ('closed', 'cancel')) and set(vals) - {
                'message_main_attachment_id', 'state', 'reservation_flagged'}:
            raise UserError(self.env._("Closed or cancelled Order Forms are read-only."))
        res = super().write(vals)
        if 'line_ids' in vals:
            self._check_has_lines()
        return res

    def _check_has_lines(self):
        for form in self:
            if not form.line_ids:
                raise ValidationError(self.env._("Order Form %s needs at least one product line.", form.name))

    def unlink(self):
        if self.filtered(lambda f: f.state != 'draft'):
            raise UserError(self.env._("Only draft Order Forms can be deleted; cancel it instead."))
        return super().unlink()

    # ------------------------------------------------------------------
    # Workflow buttons (task 5.9)
    # ------------------------------------------------------------------
    def _ensure_state(self, allowed, action):
        for form in self:
            if form.state not in allowed:
                raise UserError(self.env._(
                    "%(action)s is not allowed on %(form)s in status %(state)s.",
                    action=action, form=form.name,
                    state=dict(ORDER_FORM_STATES)[form.state]))

    def _warn_credit_stop(self):
        for form in self:
            if form.payment_type == 'credit' and form.partner_overdue > 0:
                form.message_post(body=self.env._(
                    "Credit warning: the customer has an overdue amount of %(amount)s.",
                    amount=form.currency_id.format(form.partner_overdue)))

    def action_check_availability(self):
        self._ensure_state(OPEN_STATES, self.env._("Check Availability"))
        for form in self:
            for line in form.line_ids:
                line._check_line_for_check()
            if form.state == 'draft':
                form.state = 'checked'
            form._warn_credit_stop()
            shortages = form.line_ids.filtered(lambda l: l.availability_status in ('partial', 'not_available'))
            if shortages:
                form.message_post(body=self.env._(
                    "Availability checked: %(count)s line(s) short: %(products)s",
                    count=len(shortages), products=', '.join(shortages.product_id.mapped('display_name'))))
        return True

    def action_reserve_all(self):
        self._ensure_state(OPEN_STATES, self.env._("Reserve"))
        for form in self:
            if form.state == 'draft':
                form.action_check_availability()
            form.line_ids.filtered(lambda l: l.fulfilment_type in ('stock', 'import'))._reserve(all_available=True)
            form._update_state_from_lines()
        return True

    def action_release_all(self):
        self.mapped('reservation_ids').filtered(lambda r: r.state == 'active').action_release()
        for form in self:
            form._update_state_from_lines()
        return True

    def _update_state_from_lines(self):
        """Pre-quotation status: Reserved / Awaiting Stock / Awaiting Vendor / Checked."""
        for form in self.sudo().filtered(lambda f: f.state in ('checked', 'reserved', 'awaiting_stock', 'awaiting_vendor')):
            lines = form.line_ids
            if lines.filtered(lambda l: l.fulfilment_type == 'import' and l.purchase_line_ids
                              and l.reserved_qty < l.product_qty):
                state = 'awaiting_stock'
            elif lines.filtered(lambda l: l.fulfilment_type == 'dropship' and l.purchase_line_ids):
                state = 'awaiting_vendor'
            elif lines.filtered(lambda l: l.reserved_qty):
                state = 'reserved'
            else:
                state = 'checked'
            if form.state != state:
                form.state = state

    def action_create_purchase_order(self):
        """Task 5.10: manual RFQ for import shortage lines; nothing is ordered automatically."""
        self._ensure_state(OPEN_STATES + ('confirmed',), self.env._("Create Purchase Order"))
        lines = self.line_ids
        if self.env.context.get('mariwan_line_ids'):
            lines = lines.filtered(lambda l: l.id in self.env.context['mariwan_line_ids'])
        lines = lines.filtered(lambda l: l.fulfilment_type == 'import' and l.po_qty_needed > 0)
        if not lines:
            raise UserError(self.env._(
                "No Order for Stock (Import) line needs a purchase order. Drop Ship lines get their "
                "draft RFQ from the confirmed sales order (standard drop shipping)."))
        purchases = lines._create_purchase_orders()
        self._update_state_from_lines()
        return self._action_open(purchases, 'purchase.purchase_rfq', self.env._("Purchase Orders"))

    def _prepare_sale_order_vals(self):
        self.ensure_one()
        dropship_route = self.env.ref('stock_dropshipping.route_drop_shipping', raise_if_not_found=False)
        order_lines = []
        for line in self.line_ids:
            order_lines.append(Command.create({
                'product_id': line.product_id.id,
                'name': line.name,
                'product_uom_qty': line.product_qty,
                'product_uom_id': line.product_uom_id.id,
                'price_unit': line.price_unit,
                'tax_ids': [Command.clear()],
                'route_ids': [Command.set(dropship_route.ids)] if line.fulfilment_type == 'dropship' and dropship_route else [],
                'mariwan_line_id': line.id,
            }))
        return {
            'partner_id': self.partner_id.id,
            'partner_shipping_id': self.partner_shipping_id.id or self.partner_id.id,
            'client_order_ref': self.client_order_ref,
            'user_id': self.user_id.id,
            'warehouse_id': self.warehouse_id.id,
            'payment_term_id': self.payment_term_id.id,
            'commitment_date': self.delivery_date or max(self.line_ids.mapped('delivery_date') or [False]) or False,
            'note': self.note,
            'origin': self.name,
            'mariwan_order_form_id': self.id,
            'mariwan_payment_type': self.payment_type,
            'order_line': order_lines,
        }

    def action_create_quotation(self):
        """Task 5.11: quotation with selling prices, delivery date, payment type / term; no tax."""
        self._ensure_state(('checked', 'reserved', 'awaiting_stock', 'awaiting_vendor', 'quoted'),
                           self.env._("Create Quotation"))
        sale_orders = self.env['sale.order']
        for form in self:
            for line in form.line_ids:
                line._check_line_for_quote()
            draft_quotes = form.sale_order_ids.filtered(lambda s: s.state in ('draft', 'sent'))
            draft_quotes.action_cancel()
            order = self.env['sale.order'].create(form._prepare_sale_order_vals())
            sale_orders |= order
            form.state = 'quoted'
            form.message_post(body=self.env._("Quotation %s created.", order._get_html_link()))
        return self._action_open(sale_orders, 'sale.action_quotations_with_onboarding', self.env._("Quotations"))

    def action_confirm_order(self):
        """Customer accepted: confirm the quotation (credit check runs on the sales order)."""
        self._ensure_state(('quoted',), self.env._("Confirm Order"))
        for form in self:
            quotes = form.sale_order_ids.filtered(lambda s: s.state in ('draft', 'sent'))
            if not quotes:
                raise UserError(self.env._("Create the quotation first."))
            for line in form.line_ids.filtered(lambda l: l.fulfilment_type == 'dropship'):
                if not line.vendor_id or not form.partner_shipping_id:
                    raise UserError(self.env._(
                        "Drop Ship line %s needs a vendor and a delivery address.", line.product_id.display_name))
            quotes[:1].action_confirm()
        return True

    def action_cancel(self):
        """Task 6.9: release reservations, cancel quotation, notify PO owners."""
        self._ensure_state(OPEN_STATES + ('confirmed',), self.env._("Cancel"))
        for form in self:
            form.reservation_ids.filtered(lambda r: r.state == 'active').with_context(
                mariwan_release_reason=self.env._("Order Form cancelled")).action_release()
            form.sale_order_ids.filtered(lambda s: s.state in ('draft', 'sent', 'sale')).with_context(
                disable_cancel_warning=True).action_cancel()
            for po in form.purchase_order_ids.filtered(lambda p: p.state != 'cancel'):
                po.activity_schedule(
                    'mail.mail_activity_data_todo', user_id=po.user_id.id or self.env.uid,
                    summary=self.env._("Order Form %s cancelled", form.name),
                    note=self.env._("The linked Order Form was cancelled. Cancel or re-use this purchase order manually."))
            form.state = 'cancel'
        return True

    def action_draft(self):
        self._ensure_state(('cancel',), self.env._("Reset to Draft"))
        self.state = 'draft'
        return True

    def action_close(self):
        self._ensure_state(('delivered',), self.env._("Close"))
        self.state = 'closed'
        return True

    def _log(self, body):
        """Chatter log usable by roles that only read Order Forms (accountant, pricing, warehouse)."""
        for form in self:
            form.sudo().message_post(body=body, author_id=self.env.user.partner_id.id)

    # ------------------------------------------------------------------
    # Progress from documents (In Delivery / Delivered / Closed)
    # ------------------------------------------------------------------
    def _update_progress(self):
        for form in self.sudo().filtered(lambda f: f.state in ('confirmed', 'in_delivery', 'delivered')):
            orders = form.sale_order_ids.filtered(lambda s: s.state == 'sale')
            if not orders:
                continue
            lines = orders.order_line.filtered(lambda l: not l.display_type and l.product_id.type != 'service')
            delivered = lines and all(l.qty_delivered >= l.product_uom_qty for l in lines)
            started = any(l.qty_delivered for l in lines) or form._get_pickings().filtered(
                lambda p: p.picking_type_code == 'dropship' and (p.carrier_tracking_ref or p.mariwan_dispatch_date))
            invoices = form._get_invoices().filtered(lambda m: m.move_type == 'out_invoice' and m.state == 'posted')
            paid = invoices and all(m.payment_state in ('paid', 'in_payment') for m in invoices) \
                and all(o.invoice_status == 'invoiced' for o in orders)
            if delivered and paid:
                state = 'closed'
            elif delivered:
                state = 'delivered'
            elif started:
                state = 'in_delivery'
            else:
                state = 'confirmed'
            if state != form.state:
                form.state = state

    @api.model
    def _cron_update_progress(self):
        self.search([('state', 'in', ('confirmed', 'in_delivery', 'delivered'))])._update_progress()

    # ------------------------------------------------------------------
    # Smart buttons
    # ------------------------------------------------------------------
    def _action_open(self, records, xmlid, name):
        action = self.env['ir.actions.act_window']._for_xml_id(xmlid)
        action['name'] = name
        action['context'] = {'create': False}
        if len(records) == 1:
            action['views'] = [(False, 'form')]
            action['res_id'] = records.id
        else:
            action['domain'] = [('id', 'in', records.ids)]
        return action

    def action_view_quotations(self):
        return self._action_open(self.sale_order_ids.filtered(lambda s: s.state in ('draft', 'sent', 'cancel')),
                                 'sale.action_quotations_with_onboarding', self.env._("Quotations"))

    def action_view_sale_orders(self):
        return self._action_open(self.sale_order_ids.filtered(lambda s: s.state == 'sale'),
                                 'sale.action_orders', self.env._("Sales Orders"))

    def action_view_purchase_orders(self):
        return self._action_open(self.purchase_order_ids, 'purchase.purchase_rfq', self.env._("Purchase Orders"))

    def _action_view_pickings(self, code, name):
        pickings = self._get_pickings().filtered(lambda p: p.picking_type_code == code)
        return self._action_open(pickings, 'stock.action_picking_tree_all', name)

    def action_view_receipts(self):
        return self._action_view_pickings('incoming', self.env._("Receipts"))

    def action_view_deliveries(self):
        return self._action_view_pickings('outgoing', self.env._("Deliveries"))

    def action_view_vendor_shipments(self):
        return self._action_view_pickings('dropship', self.env._("Vendor Shipments"))

    def action_view_invoices(self):
        return self._action_open(self._get_invoices(), 'account.action_move_out_invoice_type', self.env._("Invoices"))

    def action_view_payments(self):
        return self._action_open(self._get_payments(), 'account.action_account_payments', self.env._("Payments"))

    def action_view_reservations(self):
        return self._action_open(self.reservation_ids, 'mariwan_order_form.action_mariwan_reservation',
                                 self.env._("Reservations"))
