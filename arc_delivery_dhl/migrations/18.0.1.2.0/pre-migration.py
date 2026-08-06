# -*- coding: utf-8 -*-
"""Migration for 18.0.1.2.0: make carrier_id nullable on price quotes.

Frontend VisualCutter quotes do not require a delivery.carrier record.
"""


def migrate(cr, version):
    cr.execute("""
        ALTER TABLE arc_dhl_price_quote
        ALTER COLUMN carrier_id DROP NOT NULL;
    """)
