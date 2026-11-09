from odoo import fields, models, tools


class MariwanStockCategoryReport(models.Model):
    """Stock by product category: on hand, reserved (deliveries + Order Form holds), free,
    sales value and stock value, one row per product, totals per category in the views."""
    _name = 'mariwan.stock.category.report'
    _description = 'Stock by Category'
    _auto = False
    _order = 'categ_id, product_id'

    product_id = fields.Many2one('product.product', 'Product', readonly=True)
    categ_id = fields.Many2one('product.category', 'Product Category', readonly=True)
    uom_id = fields.Many2one('uom.uom', 'Unit', readonly=True)
    on_hand_qty = fields.Float('On Hand', digits='Product Unit', readonly=True)
    delivery_reserved_qty = fields.Float('Reserved (Deliveries)', digits='Product Unit', readonly=True,
                                         help="Reserved by Odoo on delivery orders and transfers.")
    hold_qty = fields.Float('Reserved (Order Form Holds)', digits='Product Unit', readonly=True)
    reserved_qty = fields.Float('Reserved', digits='Product Unit', readonly=True,
                                help="Deliveries + Order Form holds.")
    free_qty = fields.Float('Free', digits='Product Unit', readonly=True)
    sale_price = fields.Float('Sales Price', digits='Product Price', readonly=True, aggregator=None)
    sale_value = fields.Float('Sales Value', digits='Product Price', readonly=True,
                              help="On hand x Sales Price (UAE price).")
    stock_value = fields.Float('Stock Value', digits='Product Price', readonly=True,
                               groups='mariwan_order_form.group_cost_access',
                               help="On hand x current average cost (incl. landed costs).")

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                WITH quants AS (
                    SELECT q.product_id,
                           SUM(q.quantity) AS on_hand,
                           SUM(q.reserved_quantity) AS reserved,
                           SUM(q.quantity * COALESCE((pp.standard_price ->> q.company_id::text)::numeric, 0)) AS value
                      FROM stock_quant q
                      JOIN stock_location l ON l.id = q.location_id AND l.usage = 'internal'
                      JOIN product_product pp ON pp.id = q.product_id
                     GROUP BY q.product_id
                ), holds AS (
                    SELECT product_id, SUM(quantity) AS held
                      FROM mariwan_reservation
                     WHERE state = 'active'
                     GROUP BY product_id
                )
                SELECT pp.id AS id,
                       pp.id AS product_id,
                       pt.categ_id,
                       pt.uom_id,
                       COALESCE(q.on_hand, 0) AS on_hand_qty,
                       COALESCE(q.reserved, 0) AS delivery_reserved_qty,
                       COALESCE(h.held, 0) AS hold_qty,
                       COALESCE(q.reserved, 0) + COALESCE(h.held, 0) AS reserved_qty,
                       GREATEST(COALESCE(q.on_hand, 0) - COALESCE(q.reserved, 0) - COALESCE(h.held, 0), 0) AS free_qty,
                       pt.list_price AS sale_price,
                       COALESCE(q.on_hand, 0) * pt.list_price AS sale_value,
                       COALESCE(q.value, 0) AS stock_value
                  FROM product_product pp
                  JOIN product_template pt ON pt.id = pp.product_tmpl_id
                  LEFT JOIN quants q ON q.product_id = pp.id
                  LEFT JOIN holds h ON h.product_id = pp.id
                 WHERE pt.is_storable AND pp.active
            )""")
