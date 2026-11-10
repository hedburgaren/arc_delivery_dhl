# -*- coding: utf-8 -*-
"""SEC-C 127: deactivate the SPECIAL catch-all selection rule.

The rule is removed from data/arc_dhl_product_rule_data.xml because product
code 209 (SPECIAL) has no PriceQuote API enum value, so every shipment it
matched could never be priced. The data file is noupdate, so existing
databases keep the row; it is deactivated here instead of deleted, so any
manual calibration note stays recoverable.
"""


def migrate(cr, version):
    cr.execute(
        "UPDATE arc_dhl_product_rule SET active = FALSE WHERE id IN ("
        "  SELECT res_id FROM ir_model_data"
        "  WHERE module = 'arc_delivery_dhl'"
        "    AND model = 'arc.dhl.product.rule'"
        "    AND name = 'dhl_product_rule_special'"
        ")"
    )
