# -*- coding: utf-8 -*-
"""Post-migration for WP3 stage 2: update DHL product rule scopes."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    rules = env['arc.dhl.product.rule'].search([
        ('id', 'in', [
            env.ref('arc_delivery_dhl.dhl_product_rule_paket', raise_if_not_found=False).id,
            env.ref('arc_delivery_dhl.dhl_product_rule_stycke', raise_if_not_found=False).id,
            env.ref('arc_delivery_dhl.dhl_product_rule_parti', raise_if_not_found=False).id,
        ])
    ])
    rules.write({'is_international': False})
