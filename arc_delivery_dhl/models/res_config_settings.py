# -*- coding: utf-8 -*-
"""DHL settings exposed under Settings."""
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    arc_dhl_api_key = fields.Char(
        string='DHL API key',
        config_parameter='arc_delivery_dhl.api_key',
        help='API key for DHL Freight Sweden API Farm. Stored in Odoo settings.',
    )
    arc_dhl_is_production = fields.Boolean(
        string='DHL production environment',
        config_parameter='arc_delivery_dhl.is_production',
        help='When checked, requests go to the production DHL endpoint. '
             'Leave unchecked to use the sandbox.',
    )
    arc_dhl_force_environment = fields.Selection(
        [('sandbox', 'Sandbox'), ('production', 'Production')],
        string='Force DHL environment',
        config_parameter='arc_delivery_dhl.force_environment',
        help='Overrides the production flag for testing. Clear to use the '
             'production flag normally.',
    )
