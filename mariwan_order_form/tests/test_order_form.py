from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import Form, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMariwanOrderForm(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.ref('base.main_company')
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.stock_location = cls.warehouse.lot_stock_id
        cls.pricelist = cls.env.ref('mariwan_config.pricelist_uae')
        cls.categ = cls.env.ref('mariwan_config.categ_brake_pads')
        cls.categ.mariwan_landed_cost_estimate = 10.0
        cls.vendor = cls.env['res.partner'].create({
            'name': 'Overseas Vendor', 'is_company': True, 'mariwan_vendor_type': 'overseas'})
        cls.cash_customer = cls.env['res.partner'].create({
            'name': 'Cash Customer', 'is_company': True, 'mariwan_customer_type': 'cash',
            'property_product_pricelist': cls.pricelist.id})
        cls.credit_customer = cls.env['res.partner'].create({
            'name': 'Credit Customer', 'is_company': True, 'mariwan_customer_type': 'credit',
            'credit_limit': 1000.0, 'property_product_pricelist': cls.pricelist.id})
        cls.other_customer = cls.env['res.partner'].create({
            'name': 'Other Customer', 'is_company': True, 'mariwan_customer_type': 'credit',
            'property_product_pricelist': cls.pricelist.id})
        cls.product = cls.env['product.product'].create({
            'name': 'TV 55"', 'is_storable': True, 'categ_id': cls.categ.id,
            'standard_price': 200.0, 'list_price': 300.0,
            'seller_ids': [Command.create({'partner_id': cls.vendor.id, 'price': 200.0})],
        })
        cls.dropship_product = cls.env['product.product'].create({
            'name': 'Tractor', 'is_storable': True, 'categ_id': cls.categ.id,
            'mariwan_fulfilment_type': 'dropship',
            'seller_ids': [Command.create({'partner_id': cls.vendor.id, 'price': 180.0})],
        })
        cls.env['stock.quant']._update_available_quantity(cls.product, cls.stock_location, 10.0)
        cls.delivery_date = fields.Date.today() + timedelta(days=7)

    def _form(self, partner, qty, product=None, **kw):
        return self.env['mariwan.order.form'].create({
            'partner_id': partner.id,
            'delivery_date': self.delivery_date,
            'line_ids': [Command.create({'product_id': (product or self.product).id, 'product_qty': qty, **kw})],
        })

    # 16.2 ------------------------------------------------------------------
    def test_header_defaults_and_validation(self):
        form = self._form(self.credit_customer, 2)
        self.assertTrue(form.name.startswith('OF/'))
        self.assertEqual(form.payment_type, 'credit')
        self.assertEqual(form.order_type, 'stock')
        with self.assertRaises(Exception):
            self.env['mariwan.order.form'].create({'partner_id': self.cash_customer.id})
        with self.assertRaises(Exception), self.cr.savepoint():
            self._form(self.cash_customer, 0)

    def test_availability_statuses(self):
        line = self._form(self.cash_customer, 4).line_ids
        self.assertEqual((line.on_hand_qty, line.free_qty, line.availability_status), (10, 10, 'available'))
        line = self._form(self.cash_customer, 15).line_ids
        self.assertEqual((line.availability_status, line.shortage_qty), ('partial', 5))
        empty = self.env['product.product'].create({'name': 'Empty', 'is_storable': True})
        line = self._form(self.cash_customer, 1, empty).line_ids
        self.assertEqual(line.availability_status, 'not_available')

    # 16.3 ------------------------------------------------------------------
    def test_reservation_and_conflicts(self):
        form_a = self._form(self.cash_customer, 6)
        form_a.action_reserve_all()
        self.assertEqual(form_a.state, 'reserved')
        self.assertEqual(form_a.line_ids.reserved_qty, 6)

        form_b = self._form(self.other_customer, 6)
        line_b = form_b.line_ids
        self.assertEqual((line_b.reserved_other_qty, line_b.free_qty, line_b.availability_status), (6, 4, 'partial'))
        form_b.action_check_availability()
        line_b.reserve_qty = 5
        with self.assertRaises(UserError):
            line_b.action_reserve_line()
        form_b.action_reserve_all()
        self.assertEqual(line_b.reserved_qty, 4)

        # A delivery of another customer cannot consume the held stock (R2).
        so = self.env['sale.order'].create({
            'partner_id': self.other_customer.id,
            'order_line': [Command.create({'product_id': self.product.id, 'product_uom_qty': 5})],
        })
        so.action_confirm()
        self.assertEqual(so.picking_ids.move_ids.quantity, 0)

        # Re-assign (Sales Manager) flags the original Order Form.
        reservation = form_a.reservation_ids
        self.env['mariwan.reservation.reassign'].create({
            'reservation_id': reservation.id, 'quantity': 2, 'target_line_id': line_b.id, 'reason': 'VIP',
        }).action_confirm()
        self.assertTrue(form_a.reservation_flagged)
        self.assertEqual(form_a.line_ids.reserved_qty, 4)
        self.assertEqual(line_b.reserved_qty, 6)

        form_a.action_cancel()
        self.assertFalse(form_a.reservation_ids.filtered(lambda r: r.state == 'active'))

    def test_reservation_requires_date(self):
        form = self._form(self.cash_customer, 1)
        form.write({'delivery_date': False})
        form.line_ids.delivery_date = False
        form.action_check_availability()
        with self.assertRaises(UserError):
            form.action_reserve_all()

    def test_expiry_alert(self):
        form = self._form(self.cash_customer, 1)
        form.action_reserve_all()
        form.reservation_ids.delivery_date = fields.Date.today() - timedelta(days=30)
        self.env['mariwan.reservation']._cron_alerts()
        self.assertTrue(form.reservation_ids.expiry_alerted)
        self.assertEqual(form.reservation_ids.state, 'active', "No silent release")
        self.assertTrue(form.activity_ids)

    # 16.8 / 16.7 -------------------------------------------------------------
    def test_pricing_and_no_vat(self):
        form = self._form(self.cash_customer, 3)
        line = form.line_ids
        self.assertEqual(line.total_unit_cost, 200.0)
        self.assertEqual(line.margin_percent, 15.0)
        self.assertEqual(line.price_unit, 230.0)
        self.assertEqual(form.amount_total, 690.0)
        form.action_check_availability()
        form.action_create_quotation()
        order = form.sale_order_ids
        self.assertEqual(order.order_line.price_unit, 230.0)
        self.assertFalse(order.order_line.tax_ids)
        self.assertEqual(order.amount_total, order.amount_untaxed)
        self.assertFalse(self.env['account.tax'].search([]))

    def test_price_override(self):
        line = self._form(self.cash_customer, 1).line_ids
        officer = self.env['res.users'].create({
            'name': 'Saman', 'login': 'saman_test',
            'group_ids': [Command.set(self.env.ref('mariwan_order_form.group_officer').ids)],
        })
        with self.assertRaises(UserError):
            line.with_user(officer).write({'margin_override': 20.0, 'override_reason': 'x'})
        with self.assertRaises(UserError):
            line.write({'margin_override': 20.0})
        line.write({'margin_override': 20.0, 'override_reason': 'Key account'})
        self.assertTrue(line.is_price_overridden)
        self.assertEqual(line.price_unit, 240.0)

    # 16.6 -------------------------------------------------------------------
    def test_cash_customer_invoice_before_delivery(self):
        form = self._form(self.cash_customer, 2)
        form.action_reserve_all()
        form.action_create_quotation()
        form.action_confirm_order()
        self.assertEqual(form.state, 'confirmed')
        self.assertEqual(form.reservation_ids.state, 'converted')
        order = form.sale_order_ids
        picking = order.picking_ids
        self.assertEqual(picking.move_ids.quantity, 2, "Reservation converted to delivery reservation")
        with self.assertRaises(UserError):
            picking.button_validate()
        invoice = order._create_invoices()
        invoice.action_post()
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids).create({})._create_payments()
        self.assertTrue(order.mariwan_delivery_released)
        picking.button_validate()
        self.assertEqual(picking.state, 'done')
        form._update_progress()
        self.assertEqual(form.state, 'closed')

    def test_credit_limit_block(self):
        form = self._form(self.credit_customer, 6)  # 6 x 230 = 1380 > 1000
        form.action_check_availability()
        form.action_create_quotation()
        with self.assertRaises(UserError):
            form.action_confirm_order()
        order = form.sale_order_ids
        order.action_mariwan_override_credit()
        form.action_confirm_order()
        self.assertEqual(order.state, 'sale')
        order.picking_ids.button_validate()  # credit: released on confirmation

    # 16.4 -------------------------------------------------------------------
    def test_import_flow_with_landed_cost(self):
        form = self._form(self.cash_customer, 15, fulfilment_type='import')
        line = form.line_ids
        self.assertEqual(line.vendor_id, self.vendor)
        self.assertEqual(line.landed_cost_unit, 20.0)  # 10% estimate on 200
        form.action_reserve_all()
        self.assertEqual(line.reserved_qty, 10)
        form.action_create_purchase_order()
        po = form.purchase_order_ids
        self.assertEqual(po.state, 'draft', "Nothing is ordered automatically")
        self.assertEqual(po.order_line.product_qty, 5)
        self.assertEqual(form.state, 'awaiting_stock')
        po.button_confirm()
        if po.state == 'to approve':
            po.button_approve()
        receipt = po.picking_ids
        receipt.button_validate()
        self.assertEqual(line.reserved_qty, 15, "Received stock is assigned to the waiting customer first")

        freight = self.env.ref('mariwan_config.product_lc_freight')
        landed = self.env['stock.landed.cost'].create({
            'picking_ids': [Command.set(receipt.ids)],
            'cost_lines': [Command.create({
                'product_id': freight.id, 'name': 'Freight', 'price_unit': 150.0,
                'split_method': 'equal', 'account_id': self.env.ref('mariwan_config.account_landed_cost_clearing').id,
            })],
        })
        landed.compute_landed_cost()
        landed.button_validate()
        self.assertTrue(line.landed_cost_is_actual)
        self.assertEqual(line.actual_landed_cost_unit, 30.0)
        self.assertEqual(line.total_unit_cost, 230.0)
        self.assertAlmostEqual(line.price_unit, 264.5)
        move_accounts = landed.account_move_id.line_ids.account_id
        self.assertIn(self.env.ref('mariwan_config.account_landed_cost_clearing'), move_accounts)

    # 16.5 -------------------------------------------------------------------
    def test_dropship_flow(self):
        form = self._form(self.credit_customer, 2, self.dropship_product, dropship_extra_cost=20.0)
        line = form.line_ids
        self.assertEqual(line.fulfilment_type, 'dropship')
        self.assertEqual(line.availability_status, 'na')
        self.assertEqual(line.total_unit_cost, 190.0)
        self.assertAlmostEqual(line.price_unit, 218.5)
        form.action_check_availability()
        form.action_create_quotation()
        form.action_confirm_order()
        po = self.env['purchase.order'].search([('mariwan_order_form_id', '=', form.id)])
        self.assertEqual(po.state, 'draft', "Standard drop-ship RFQ waits for review")
        self.assertEqual(po.mariwan_delivery_type, 'dropship')
        self.assertEqual(po.dest_address_id, form.partner_shipping_id)
        po.button_confirm()
        if po.state == 'to approve':
            po.button_approve()
        shipment = po.picking_ids
        self.assertEqual(shipment.picking_type_code, 'dropship')
        shipment.write({'carrier_tracking_ref': 'TRK1', 'mariwan_dispatch_date': fields.Date.today()})
        form._update_progress()
        self.assertEqual(form.state, 'in_delivery')
        self.assertEqual(line.line_status, 'dispatched')
        shipment.button_validate()
        self.assertEqual(form.state, 'delivered')
        self.assertFalse(self.dropship_product.with_context(warehouse_id=self.warehouse.id).qty_available,
                         "Drop-ship goods never enter stock")

    def test_mixed_order_type(self):
        form = self._form(self.cash_customer, 1)
        form.write({'line_ids': [Command.create({'product_id': self.dropship_product.id, 'product_qty': 1})]})
        self.assertEqual(form.order_type, 'mixed')

    def test_fixed_pricelist_price(self):
        """Client price list: fixed UAE price per item wins over the markup rule."""
        self.env['product.pricelist.item'].create({
            'pricelist_id': self.pricelist.id,
            'applied_on': '0_product_variant',
            'product_id': self.product.id,
            'compute_price': 'fixed',
            'fixed_price': 280.0,
        })
        line = self._form(self.cash_customer, 2).line_ids
        self.assertEqual(line.price_unit, 280.0)
        self.assertAlmostEqual(line.margin_percent, 40.0)
        self.assertEqual(line.margin_amount, 160.0)
