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
