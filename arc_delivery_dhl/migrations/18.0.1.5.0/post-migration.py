# -*- coding: utf-8 -*-
"""18.0.1.5.0 (SEC-B 131): safety net, see pre-migration.py.

Sets noupdate=true on the product rule xmlids of this module, in case the
data load flipped any of them back.
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
        'arc_delivery_dhl 18.0.1.5.0 post: %d product rule xmlids set noupdate',
        cr.rowcount)
