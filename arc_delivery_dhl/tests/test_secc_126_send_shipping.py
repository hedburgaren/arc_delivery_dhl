# -*- coding: utf-8 -*-
"""SEC-C 126: booking without a carrier product uses the selector.

A carrier without ``arc_dhl_product_id`` used to create the booking with
``product_id`` False (dead selector fallback); now the selector runs and a
shipment without any matching rule fails with a clear error.
"""
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'arc_dhl')
class TestSecC126SendShipping(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        param = cls.env['ir.config_parameter'].sudo()
        param.set_param('arc_delivery_dhl.api_key', 'test-api-key')
        param.set_param('arc_delivery_dhl.booking_enabled', 'True')
        param.set_param('arc_delivery_dhl.force_environment', 'sandbox')
        param.set_param('arc_delivery_dhl.customer_number', '123456789')
        cls.carrier = cls.env['delivery.carrier'].create({
            'name': 'DHL SEC-C 126',
            'delivery_type': 'dhl_freight_se',
            'product_id': cls.env.ref('delivery.product_product_delivery').id,
            # No arc_dhl_product_id: the selector must step in.
        })
        cls.dhl_product = cls.env.ref('arc_delivery_dhl.dhl_product_paket')
        cls.partner = cls.env['res.partner'].create({
            'name': 'SEC-C 126 Customer',
            'zip': '11122',
            'city': 'Stockholm',
            'street': 'Testgatan 1',
            'country_id': cls.env.ref('base.se').id,
        })
        uom = cls.env.ref('uom.product_uom_unit')
        cls.product = cls.env['product.template'].create({
            'name': 'SEC-C 126 Sheet',
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

    def _picking(self):
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
        order.action_confirm()
        return order.picking_ids.filtered(
            lambda p: p.picking_type_id.code == 'outgoing')[:1]

    @patch('requests.request')
    def test_send_shipping_without_carrier_product_uses_selector(
            self, mock_request):
        booking_response = type('Response', (), {
            'status_code': 200, 'ok': True, 'text': '',
            'json': lambda *a, **k: {
                'transportInstruction': {
                    'shipmentId': 'DHL-SECC126',
                    'trackingNumbers': ['JD0126'],
                },
            },
        })()
        label_response = type('Response', (), {
            'status_code': 200, 'ok': True, 'text': '',
            'json': lambda *a, **k: {'reports': []},
        })()
        mock_request.side_effect = [booking_response, label_response]

        picking = self._picking()
        res = self.carrier.dhl_freight_se_send_shipping(picking)
        self.assertTrue(res)
        booking = self.env['arc.dhl.booking'].search(
            [('picking_id', '=', picking.id)])
        self.assertTrue(booking)
        self.assertEqual(booking.product_id, self.dhl_product)

    def test_send_shipping_without_any_rule_raises(self):
        # A draft proposal only: the domestic PAKET rule still matches, so
        # deactivate every rule to make the selection fail.
        self.env['arc.dhl.product.rule'].search([]).write({'active': False})
        picking = self._picking()
        with self.assertRaises(UserError):
            self.carrier.dhl_freight_se_send_shipping(picking)
