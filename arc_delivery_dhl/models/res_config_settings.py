# -*- coding: utf-8 -*-
"""DHL settings exposed under Settings."""
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    arc_dhl_api_key = fields.Char(
        string='DHL API Farm key',
        config_parameter='arc_delivery_dhl.api_key',
        help='Client-Key for the Swedish DHL Freight API Farm '
             '(products, price quotes, booking, labels).',
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
    arc_dhl_visualcutter_enabled = fields.Boolean(
        string='DHL price quote in VisualCutter',
        config_parameter='arc_delivery_dhl.visualcutter_enabled',
        help='Show DHL freight prices in the public VisualCutter calculator. '
             'Requires a valid DHL API Farm key.',
    )
    arc_dhl_booking_enabled = fields.Boolean(
        string='DHL shipment booking',
        config_parameter='arc_delivery_dhl.booking_enabled',
        help='Allow bookings to be created directly from Odoo pickings. '
             'Disable to keep the integration quote-only.',
    )
    arc_dhl_tracking_enabled = fields.Boolean(
        string='DHL tracking links',
        config_parameter='arc_delivery_dhl.tracking_enabled',
        help='Show DHL tracking links on deliveries.',
    )
    arc_dhl_auto_quote_enabled = fields.Boolean(
        string='DHL automatic freight quote',
        config_parameter='arc_delivery_dhl.auto_quote_enabled',
        help='Automatically request a DHL freight quote and add a freight line '
             'when confirming a quotation/order.',
    )
    arc_dhl_customer_number = fields.Char(
        string='DHL customer number',
        config_parameter='arc_delivery_dhl.customer_number',
        help='DHL Freight customer number (avtalsnummer). Required for booking '
             'shipments; it is sent as the consignor party identifier.',
    )
