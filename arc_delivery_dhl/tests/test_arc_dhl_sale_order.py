# -*- coding: utf-8 -*-
"""Tests for DHL Freight sale.order integration."""
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'arc_dhl')
class TestArcDhlSaleOrder(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param(
            'arc_delivery_dhl.api_key', 'test-api-key'
        )
        cls.env['ir.config_parameter'].sudo().set_param(
            'arc_delivery_dhl.force_environment', 'sandbox'
        )
        cls.partner = cls.env['res.partner'].create({
            'name': 'DHL SO Test Customer',
            'zip': '11122',
            'city': 'Stockholm',
            'country_id': cls.env.ref('base.se').id,
        })
        cls.uom_unit = cls.env.ref('uom.product_uom_unit')
        cls.product_tmpl = cls.env['product.template'].create({
            'name': 'DHL Test Sheet',
            'type': 'consu',
            'is_storable': True,
            'list_price': 1000.0,
            'uom_id': cls.uom_unit.id,
            'uom_po_id': cls.uom_unit.id,
            'cts_tsb_density': 950.0,
            'vc_basplatta_L_mm': 1000.0,
            'vc_basplatta_B_mm': 500.0,
            'vc_tjocklek_mm': 10.0,
        })
        cls.product = cls.product_tmpl.product_variant_id

        # Ensure exactly one service product named "Frakt" exists for the model
        # to find. Reuse an existing one if present.
        existing_freight = cls.env['product.template'].sudo().search([
            ('name', '=', 'Frakt'),
            ('type', '=', 'service'),
        ], limit=1)
        if existing_freight:
            cls.freight_product = existing_freight.product_variant_id
        else:
            cls.freight_product = cls.env['product.product'].create({
                'name': 'Frakt',
                'type': 'service',
                'list_price': 0.0,
                'uom_id': cls.uom_unit.id,
                'uom_po_id': cls.uom_unit.id,
            })

    def _create_order(self):
        return self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1,
            })],
        })

    def _confirm_proposal(self, order):
        action = order.action_arc_package_proposal_create()
        proposal = self.env['arc.package.proposal'].browse(action['res_id'])
        proposal.action_confirm()
        return proposal

    def _quote_response(self):
        return [
            {
                'description': 'Total',
                'descriptionEng': 'Total price',
                'id': 'TotalPrice',
                'sortOrder': 100,
                'unit': 'SEK',
                'value': '197,82',
            },
            {
                'description': 'Total incl VAT',
                'descriptionEng': 'Total price inc VAT',
                'id': 'TotalPriceIncVAT',
                'sortOrder': 120,
                'unit': 'SEK',
                'value': '247,28',
            },
            {
                'description': 'VAT',
                'id': 'VAT',
                'sortOrder': 110,
                'unit': 'SEK',
                'value': '49,46',
            },
        ]

    def test_quote_requires_confirmed_proposal(self):
        order = self._create_order()
        with self.assertRaises(UserError):
            order.action_arc_dhl_quote()

    @patch('requests.request')
    def test_quote_creates_price_quote_and_sets_costs(self, mock_request):
        mock_request.return_value.status_code = 200
        mock_request.return_value.ok = True
        mock_request.return_value.json.return_value = self._quote_response()
        mock_request.return_value.text = ''

        order = self._create_order()
        self._confirm_proposal(order)

        action = order.action_arc_dhl_quote()
        self.assertEqual(action['res_model'], 'arc.dhl.price.quote')
        self.assertTrue(order.arc_dhl_price_quote_id)
        self.assertAlmostEqual(order.arc_dhl_shipping_cost, 197.82, places=2)
        self.assertAlmostEqual(order.arc_dhl_shipping_cost_incl_vat, 247.28, places=2)
        self.assertTrue(order.carrier_id)
        self.assertEqual(order.carrier_id.delivery_type, 'dhl_freight_se')

    @patch('requests.request')
    def test_apply_shipping_adds_freight_line(self, mock_request):
        mock_request.return_value.status_code = 200
        mock_request.return_value.ok = True
        mock_request.return_value.json.return_value = self._quote_response()
        mock_request.return_value.text = ''

        order = self._create_order()
        self._confirm_proposal(order)
        order.action_arc_dhl_quote()
        order.action_arc_dhl_apply_shipping()

        freight_line = order.order_line.filtered(
            lambda l: l.product_id == self.freight_product
        )
        self.assertTrue(freight_line)
        self.assertEqual(len(freight_line), 1)
        self.assertAlmostEqual(freight_line.price_unit, 197.82, places=2)

    @patch('requests.request')
    def test_apply_shipping_updates_existing_freight_line(self, mock_request):
        mock_request.return_value.status_code = 200
        mock_request.return_value.ok = True
        mock_request.return_value.json.return_value = self._quote_response()
        mock_request.return_value.text = ''

        order = self._create_order()
        self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': self.freight_product.id,
            'product_uom_qty': 1,
            'price_unit': 50.0,
        })
        self._confirm_proposal(order)
        order.action_arc_dhl_quote()
        order.action_arc_dhl_apply_shipping()

        freight_line = order.order_line.filtered(
            lambda l: l.product_id == self.freight_product
        )
        self.assertEqual(len(freight_line), 1)
        self.assertAlmostEqual(freight_line.price_unit, 197.82, places=2)

    @patch('requests.request')
    def test_auto_quote_on_confirm_enabled(self, mock_request):
        mock_request.return_value.status_code = 200
        mock_request.return_value.ok = True
        mock_request.return_value.json.return_value = self._quote_response()
        mock_request.return_value.text = ''

        self.env['ir.config_parameter'].sudo().set_param(
            'arc_delivery_dhl.auto_quote_enabled', 'True'
        )
        order = self._create_order()
        self._confirm_proposal(order)
        order.action_confirm()

        self.assertEqual(order.state, 'sale')
        freight_line = order.order_line.filtered(
            lambda l: l.product_id == self.freight_product
        )
        self.assertEqual(len(freight_line), 1)
        self.assertAlmostEqual(freight_line.price_unit, 197.82, places=2)
        self.assertTrue(order.arc_dhl_price_quote_id)

    @patch('requests.request')
    def test_auto_quote_on_confirm_disabled(self, mock_request):
        self.env['ir.config_parameter'].sudo().set_param(
            'arc_delivery_dhl.auto_quote_enabled', 'False'
        )
        order = self._create_order()
        self._confirm_proposal(order)
        order.action_confirm()

        self.assertEqual(order.state, 'sale')
        freight_line = order.order_line.filtered(
            lambda l: l.product_id == self.freight_product
        )
        self.assertFalse(freight_line)
        self.assertFalse(order.arc_dhl_price_quote_id)
        mock_request.assert_not_called()

    @patch('requests.request')
    def test_auto_quote_failure_does_not_block_confirm(self, mock_request):
        mock_request.return_value.status_code = 400
        mock_request.return_value.ok = False
        mock_request.return_value.json.return_value = {'error': 'Bad request'}
        mock_request.return_value.text = 'Bad request'

        self.env['ir.config_parameter'].sudo().set_param(
            'arc_delivery_dhl.auto_quote_enabled', 'True'
        )
        order = self._create_order()
        self._confirm_proposal(order)
        order.action_confirm()

        self.assertEqual(order.state, 'sale')
        freight_line = order.order_line.filtered(
            lambda l: l.product_id == self.freight_product
        )
        self.assertFalse(freight_line)
        self.assertFalse(order.arc_dhl_price_quote_id)
