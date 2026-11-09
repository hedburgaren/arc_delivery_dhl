# -*- coding: utf-8 -*-
"""18.0.1.5.0 (SEC-B 131): product rule data becomes noupdate.

The rule records were loaded with noupdate="0", so ir_model_data marks them
noupdate=false and every -u overwrote UI calibrations. The data file is now
noupdate="1". Records that are already loaded keep the old flag until it is
flipped here. Done in pre-migration so the flag is right before this
upgrade's data load, and again in post-migration as a safety net.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        "UPDATE ir_model_data SET noupdate = true "
        "WHERE module = 'arc_delivery_dhl' "
        "AND model = 'arc.dhl.product.rule' AND noupdate = false")
    _logger.info(
        'arc_delivery_dhl 18.0.1.5.0 pre: %d product rule xmlids set noupdate',
        cr.rowcount)
