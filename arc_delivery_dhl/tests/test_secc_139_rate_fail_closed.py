# -*- coding: utf-8 -*-
"""SEC-C 139: rate_shipment never reports success with a zero price.

SEC-B 122 already makes the quote request fail closed on a missing or zero
price; this is the belt at the carrier boundary: even a success result with
price 0 is downgraded to a failed rate.
"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'arc_dhl')
class TestSecC139RateFailClosed(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        param = cls.env['ir.config_parameter'].sudo()
        param.set_param('arc_delivery_dhl.api_key', 'test-api-key')
        param.set_param('arc_delivery_dhl.force_environment', 'sandbox')
        cls.carrier = cls.env['delivery.carrier'].create({
            'name': 'DHL SEC-C 139',
            'delivery_type': 'dhl_freight_se',
            'product_id': cls.env.ref('delivery.product_product_delivery').id,
            'arc_dhl_product_id': cls.env.ref(
                'arc_delivery_dhl.dhl_product_paket').id,
        })
        cls.partner = cls.env['res.partner'].create({
            'name': 'SEC-C 139 Customer',
            'zip': '11122',
            'city': 'Stockholm',
            'country_id': cls.env.ref('base.se').id,
        })
        uom = cls.env.ref('uom.product_uom_unit')
        cls.product = cls.env['product.template'].create({
            'name': 'SEC-C 139 Sheet',
            'type': 'consu',
            'is_storable': True,
            'list_price': 1000.0,
            'uom_id': uom.id,
            'uom_po_id': uom.id,
            'cts_tsb_density': 950.0,
            'vc_basplatta_L_mm': 1000.0,
            'vc_basplatta_B_mm': 500.0,
            'vc_tjocklek_mm': 10.0,
        }).product_variant_id

    def _order_with_proposal(self):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1,
            })],
        })
        action = order.action_arc_package_proposal_create()
        self.env['arc.package.proposal'].browse(
            action['res_id']).action_confirm()
        return order

    @patch(
        'odoo.addons.arc_delivery_dhl.models.'
        'arc_dhl_price_quote.ArcDhlPriceQuote.action_request_quote'
    )
    def test_zero_price_success_is_downgraded(self, mock_quote):
        mock_quote.return_value = {'success': True, 'price': 0.0}
        order = self._order_with_proposal()
        result = self.carrier.dhl_freight_se_rate_shipment(order)
        self.assertFalse(result['success'])
        self.assertEqual(result['price'], 0.0)

    @patch(
        'odoo.addons.arc_delivery_dhl.models.'
        'arc_dhl_price_quote.ArcDhlPriceQuote.action_request_quote'
    )
    def test_positive_price_stays_success(self, mock_quote):
        mock_quote.return_value = {'success': True, 'price': 197.82}
        order = self._order_with_proposal()
        result = self.carrier.dhl_freight_se_rate_shipment(order)
        self.assertTrue(result['success'])
        self.assertEqual(result['price'], 197.82)
