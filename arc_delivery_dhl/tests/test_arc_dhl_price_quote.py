# -*- coding: utf-8 -*-
"""Tests for DHL price quote caching."""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'arc_dhl')
class TestArcDhlPriceQuote(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param(
            'arc_delivery_dhl.api_key', 'test-api-key'
        )
        cls.partner = cls.env['res.partner'].create({
            'name': 'Test Customer',
            'zip': '58118',
            'city': 'Linkoping',
            'country_id': cls.env.ref('base.se').id,
        })
        cls.product_tmpl = cls.env['product.template'].create({
            'name': 'PE-HD Test Sheet',
            'type': 'consu',
            'is_storable': True,
            'list_price': 1000.0,
            'uom_id': cls.env.ref('uom.product_uom_unit').id,
            'uom_po_id': cls.env.ref('uom.product_uom_unit').id,
            'cts_tsb_density': 950.0,
            'vc_basplatta_L_mm': 1000.0,
            'vc_basplatta_B_mm': 500.0,
            'vc_tjocklek_mm': 10.0,
        })
        cls.product = cls.product_tmpl.product_variant_id
        cls.dhl_product = cls.env.ref('arc_delivery_dhl.dhl_product_paket')

    def _create_order(self):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1.0,
            })],
        })
        order.action_arc_package_proposal_create()
        order.arc_package_proposal_id.action_confirm()
        return order

    @patch('requests.request')
    def test_quote_cache_hit_avoids_second_api_call(self, mock_request):
        mock_request.return_value.status_code = 200
        mock_request.return_value.ok = True
        mock_request.return_value.json.return_value = {'price': 150.0}
        mock_request.return_value.text = ''

        order = self._create_order()
        carrier = self.env['delivery.carrier'].create({
            'name': 'DHL Test',
            'delivery_type': 'dhl_freight_se',
            'product_id': self.env.ref('delivery.product_product_delivery').id,
            'arc_dhl_product_id': self.dhl_product.id,
        })
        quote1 = self.env['arc.dhl.price.quote'].create({
            'carrier_id': carrier.id,
            'sale_order_id': order.id,
            'product_id': self.dhl_product.id,
        })
        res1 = quote1.action_request_quote()
        self.assertTrue(res1['success'])
        self.assertEqual(res1['price'], 150.0)

        quote2 = self.env['arc.dhl.price.quote'].create({
            'carrier_id': carrier.id,
            'sale_order_id': order.id,
            'product_id': self.dhl_product.id,
        })
        res2 = quote2.action_request_quote()
        self.assertTrue(res2['success'])
        self.assertEqual(res2['price'], 150.0)
        self.assertEqual(mock_request.call_count, 1)
