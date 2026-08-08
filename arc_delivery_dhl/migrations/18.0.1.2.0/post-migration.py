# -*- coding: utf-8 -*-
"""Migration for 18.0.1.2.0: make sale_order_id nullable on price quotes.

Standalone VisualCutter price quotes do not link to a sales order.
"""


def migrate(cr, version):
    cr.execute("""
        ALTER TABLE arc_dhl_price_quote
        ALTER COLUMN sale_order_id DROP NOT NULL;
    """)
