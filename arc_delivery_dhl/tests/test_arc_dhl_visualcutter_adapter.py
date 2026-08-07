# -*- coding: utf-8 -*-
"""Tests for DHL VisualCutter adapter."""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'arc_dhl')
class TestArcDhlVisualCutterAdapter(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param(
            'arc_delivery_dhl.api_key', 'test-api-key'
        )

    @patch('requests.request')
    def test_adapter_returns_dhl_price(self, mock_request):
        mock_request.return_value.status_code = 200
        mock_request.return_value.ok = True
        mock_request.return_value.json.return_value = [
            {
                'description': 'Total',
                'descriptionEng': 'Total price',
                'id': 'TotalPrice',
                'sortOrder': 100,
                'unit': 'SEK',
                'value': '175,00',
            },
            {
                'description': 'Total incl VAT',
                'descriptionEng': 'Total price inc VAT',
                'id': 'TotalPriceIncVAT',
                'sortOrder': 120,
                'unit': 'SEK',
                'value': '218,75',
            },
        ]
        mock_request.return_value.text = ''

        batch = {
            'format': 'plate',
            'source_length': 1000.0,
            'source_width': 500.0,
            'source_thickness': 10.0,
            'cut_weight_kg': 5.0,
        }
        result = self.env['arc.dhl.visualcutter.adapter'].quote_for_batch(
            batch, {'country_code': 'SE', 'zip': '11122'},
        )
        self.assertEqual(result['shipping_fee'], 175.0)
        self.assertEqual(result['shipping_info']['rule_name'], 'DHL Freight Sweden')
        self.assertEqual(mock_request.call_count, 1)

    def test_adapter_fail_open_on_missing_weight(self):
        batch = {
            'format': 'plate',
            'source_length': 1000.0,
            'source_width': 500.0,
            'source_thickness': 10.0,
            'cut_weight_kg': 0.0,
        }
        result = self.env['arc.dhl.visualcutter.adapter'].quote_for_batch(
            batch, {'country_code': 'SE', 'zip': '11122'},
        )
        self.assertEqual(result['shipping_fee'], 0.0)
        self.assertIn('reason', result['shipping_info'])
