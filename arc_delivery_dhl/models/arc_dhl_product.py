# -*- coding: utf-8 -*-
"""DHL products and services that can be booked manually or by rule."""
from odoo import fields, models


class ArcDhlProduct(models.Model):
    _name = 'arc.dhl.product'
    _description = 'DHL Freight Sweden product'
    _order = 'code'

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(
        string='Product code',
        required=True,
        help='DHL product code used in API payloads, e.g. 210, 211.',
    )
    is_domestic = fields.Boolean(
        string='Domestic Sweden',
        default=True,
        help='True for products available within Sweden.',
    )
    is_international = fields.Boolean(
        string='International road',
        default=False,
        help='True for international road freight products.',
    )
    max_length_cm = fields.Integer(
        string='Max length (cm)',
        help='Published length limit. Zero means no hard limit configured.',
    )
    max_weight_kg = fields.Float(
        string='Max weight (kg)',
        help='Published weight limit per piece. Zero means no hard limit.',
    )
    is_pallet_product = fields.Boolean(
        string='Pallet product',
        default=False,
        help='Pallet products are priced by pallet count, not by weight.',
    )
    active = fields.Boolean(string='Active', default=True)
    note = fields.Text(string='Note', translate=True)

    _sql_constraints = [
        ('unique_code', 'UNIQUE(code)', 'Product code must be unique.'),
    ]

    # DHL package types for pallet products, verified in the sandbox
    # 2026-10-31 (task 88): the price quote names 701 "Frakt Helpall" and
    # 702 "Frakt Halvpall". The booking API refuses DHL PALL without one.
    PACKAGE_TYPE_FULL_PALLET = '701'
    PACKAGE_TYPE_HALF_PALLET = '702'
    HALF_PALLET_FOOTPRINT_CM = (80.0, 60.0)

    def _arc_dhl_package_type(self, length_cm, width_cm):
        """Return the DHL package type for one piece, or None.

        Pallet products get a half pallet when the footprint fits 80 x 60 cm
        in either orientation, otherwise a full pallet. Other products return
        None and keep their current default.
        """
        self.ensure_one()
        if not self.is_pallet_product:
            return None
        long_side = max(length_cm or 0.0, width_cm or 0.0)
        short_side = min(length_cm or 0.0, width_cm or 0.0)
        max_long, max_short = self.HALF_PALLET_FOOTPRINT_CM
        if long_side <= max_long and short_side <= max_short:
            return self.PACKAGE_TYPE_HALF_PALLET
        return self.PACKAGE_TYPE_FULL_PALLET
