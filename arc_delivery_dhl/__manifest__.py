# -*- coding: utf-8 -*-
{
    'name': 'ARC Delivery DHL',
    'version': '18.0.1.2.0',
    'author': 'ARC Gruppen AB',
    'maintainer': 'Chrille Hedberg',
    'maintainer_email': 'chrille.hedberg@arcgruppen.se',
    'website': 'https://arcgruppen.se',
    'license': 'LGPL-3',
    'category': 'Inventory/Delivery',
    'summary': 'DHL Freight Sweden delivery carrier integration',
    'description': """
ARC Delivery DHL
================
Integrates DHL Freight Sweden (Swedish API Farm) as an Odoo delivery carrier.

Features:
- Book shipments via DHL TransportInstruction API
- Retrieve labels via DHL Print API
- Request price quotes via DHL PriceQuote API
- Support sandbox and production environments
- Read credentials from Odoo settings or environment variables
- Tie into the ARC packing planner package structure

This module is built for the Swedish API Farm. It does not use the global
DHL Freight APIs on developer.dhl.com.
    """,
    'depends': [
        'arc_industrial_ops',
        'delivery',
        'stock',
        'mail',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/arc_dhl_sequence_data.xml',
        'data/arc_dhl_product_data.xml',
        'data/arc_dhl_product_rule_data.xml',
        'data/arc_dhl_parameter_data.xml',
        'views/delivery_carrier_views.xml',
        'views/res_config_settings_views.xml',
        'views/stock_picking_views.xml',
        'views/arc_dhl_product_rule_views.xml',
        'views/arc_dhl_booking_views.xml',
        'views/arc_dhl_label_views.xml',
        'views/arc_dhl_price_quote_views.xml',
        'views/arc_dhl_menus.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
}
