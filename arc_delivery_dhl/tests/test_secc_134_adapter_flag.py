# -*- coding: utf-8 -*-
"""SEC-C 134: the VisualCutter adapter result carries an explicit success flag.

The fallback used to return shipping_fee 0.0 with only a reason, so a caller
could read the zero as a free shipment. The result now says success False on
every failure path and success True on a priced one.
"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'arc_dhl')
class TestSecC134AdapterFlag(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param(
            'arc_delivery_dhl.api_key', 'test-api-key')

    def _batch(self, weight=5.0):
        return {
            'format': 'plate',
            'source_length': 1000.0,
            'source_width': 500.0,
            'source_thickness': 10.0,
            'cut_weight_kg': weight,
        }

    def test_missing_weight_is_explicit_failure(self):
        result = self.env['arc.dhl.visualcutter.adapter'].quote_for_batch(
            self._batch(weight=0.0), {'country_code': 'SE', 'zip': '11122'},
        )
        self.assertFalse(result['success'])
        self.assertEqual(result['shipping_fee'], 0.0)
        self.assertIn('reason', result['shipping_info'])

    @patch('requests.request')
    def test_failed_quote_is_explicit_failure(self, mock_request):
        mock_request.return_value.status_code = 500
        mock_request.return_value.ok = False
        mock_request.return_value.text = 'error'
        mock_request.return_value.json.return_value = {}

        result = self.env['arc.dhl.visualcutter.adapter'].quote_for_batch(
            self._batch(), {'country_code': 'SE', 'zip': '11122'},
        )
        self.assertFalse(result['success'])
        self.assertEqual(result['shipping_fee'], 0.0)

    @patch('requests.request')
    def test_priced_quote_is_success(self, mock_request):
        mock_request.return_value.status_code = 200
        mock_request.return_value.ok = True
        mock_request.return_value.json.return_value = [
            {
                'id': 'TotalPrice', 'unit': 'SEK', 'value': '175,00',
                'description': 'Total', 'sortOrder': 100,
            },
        ]
        mock_request.return_value.text = ''

        result = self.env['arc.dhl.visualcutter.adapter'].quote_for_batch(
            self._batch(), {'country_code': 'SE', 'zip': '11122'},
        )
        self.assertTrue(result['success'])
        self.assertEqual(result['shipping_fee'], 218.75)
