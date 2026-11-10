# -*- coding: utf-8 -*-
"""SEC-C 132: quote reuse on cache hits and a purge cron.

Every rate call used to create a new quote row, even when the cache answered,
and nothing ever removed old rows. A cache hit now reuses the cached record
(no duplicate row) and a daily cron deletes quotes past the retention window.
"""
import json
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged


def _quote_response():
    return [
        {
            'id': 'TotalPrice', 'unit': 'SEK', 'value': '150,00',
            'description': 'Total', 'sortOrder': 100,
        },
        {
            'id': 'TotalPriceIncVAT', 'unit': 'SEK', 'value': '187,50',
            'description': 'Total incl VAT', 'sortOrder': 120,
        },
    ]


@tagged('post_install', '-at_install', 'arc_dhl')
class TestSecC132QuotePurge(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        param = cls.env['ir.config_parameter'].sudo()
        param.set_param('arc_delivery_dhl.api_key', 'test-api-key')
        param.set_param('arc_delivery_dhl.force_environment', 'sandbox')
        cls.dhl_product = cls.env.ref('arc_delivery_dhl.dhl_product_paket')

    def _quote_for(self, zip_code='11122'):
        packages = [{
            'length_cm': 50.0, 'width_cm': 30.0,
            'height_cm': 10.0, 'weight_kg': 5.0,
        }]
        return self.env['arc.dhl.price.quote'].get_quote_for_packages(
            packages, {'country_code': 'SE', 'zip': zip_code},
            product=self.dhl_product,
        )

    @patch('requests.request')
    def test_cache_hit_reuses_record_and_does_not_grow(self, mock_request):
        mock_request.return_value.status_code = 200
        mock_request.return_value.ok = True
        mock_request.return_value.json.return_value = _quote_response()
        mock_request.return_value.text = ''

        result1 = self._quote_for()
        self.assertTrue(result1['success'])
        count_after_first = self.env['arc.dhl.price.quote'].search_count([])

        result2 = self._quote_for()
        self.assertTrue(result2['success'])
        # SEC-C 132: the cache hit removes the duplicate row.
        self.assertEqual(
            self.env['arc.dhl.price.quote'].search_count([]),
            count_after_first,
        )
        self.assertEqual(result2['quote_id'], result1['quote_id'])
        self.assertEqual(mock_request.call_count, 1)

    def test_purge_removes_old_quotes_only(self):
        old_quote = self.env['arc.dhl.price.quote'].create({
            'product_id': self.dhl_product.id,
            'partner_country_code': 'SE',
            'partner_zip': '11122',
            'package_json': (
                '[{"length": 50, "width": 30, "height": 10, "weight": 5}]'
            ),
        })
        self.env.cr.execute(
            'UPDATE arc_dhl_price_quote SET create_date = %s WHERE id = %s',
            (fields.Datetime.now().replace(year=2025), old_quote.id),
        )
        fresh_quote = self.env['arc.dhl.price.quote'].create({
            'product_id': self.dhl_product.id,
            'partner_country_code': 'SE',
            'partner_zip': '11122',
            'package_json': (
                '[{"length": 50, "width": 30, "height": 10, "weight": 5}]'
            ),
        })

        removed = self.env['arc.dhl.price.quote']._arc_dhl_purge_old_quotes()

        self.assertGreaterEqual(removed, 1)
        self.assertFalse(old_quote.exists())
        self.assertTrue(fresh_quote.exists())
