# -*- coding: utf-8 -*-
"""Tests for DHL booking flow."""
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'arc_dhl')
class TestArcDhlBooking(TransactionCase):

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
            'phone': '013123456',
            'email': 'test@example.com',
            'street': 'Testgatan 1',
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

    def _create_picking(self):
        order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1.0,
            })],
        })
        order.action_arc_package_proposal_create()
        order.arc_package_proposal_id.action_confirm()
        order.action_confirm()
        return order.picking_ids.filtered(
            lambda p: p.picking_type_id.code == 'outgoing'
        )[:1]

    def test_booking_requires_packages(self):
        # Create a picking manually without confirming an order, so no packages exist.
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.env.ref('stock.picking_type_out').id,
            'location_id': self.env.ref('stock.stock_location_stock').id,
            'location_dest_id': self.env.ref('stock.stock_location_customers').id,
            'partner_id': self.partner.id,
        })
        carrier = self.env['delivery.carrier'].create({
            'name': 'DHL Test',
            'delivery_type': 'dhl_freight_se',
            'product_id': self.env.ref('delivery.product_product_delivery').id,
            'arc_dhl_product_id': self.dhl_product.id,
        })
        booking = self.env['arc.dhl.booking'].create({
            'carrier_id': carrier.id,
            'picking_id': picking.id,
            'product_id': self.dhl_product.id,
        })
        with self.assertRaises(UserError):
            booking.action_book_shipment()

    def test_booking_payload_structure(self):
        picking = self._create_picking()

        carrier = self.env['delivery.carrier'].create({
            'name': 'DHL Test',
            'delivery_type': 'dhl_freight_se',
            'product_id': self.env.ref('delivery.product_product_delivery').id,
            'arc_dhl_product_id': self.dhl_product.id,
        })
        booking = self.env['arc.dhl.booking'].create({
            'carrier_id': carrier.id,
            'picking_id': picking.id,
            'product_id': self.dhl_product.id,
        })
        payload = booking._arc_dhl_build_payload(booking._arc_dhl_collect_packages(picking))
        self.assertIn('sender', payload)
        self.assertIn('receiver', payload)
        self.assertIn('shipment', payload)
        self.assertEqual(payload['shipment']['productCode'], self.dhl_product.code)
        self.assertTrue(payload['shipment']['packages'])

    def test_length_validation_blocks_oversized_package(self):
        picking = self._create_picking()
        order = picking.sale_id
        # Force a huge dimension to trigger the length limit.
        order.arc_package_proposal_id.line_ids.goods_L_mm = 5000

        carrier = self.env['delivery.carrier'].create({
            'name': 'DHL Test',
            'delivery_type': 'dhl_freight_se',
            'product_id': self.env.ref('delivery.product_product_delivery').id,
            'arc_dhl_product_id': self.dhl_product.id,
        })
        booking = self.env['arc.dhl.booking'].create({
            'carrier_id': carrier.id,
            'picking_id': picking.id,
            'product_id': self.dhl_product.id,
        })
        with self.assertRaises(UserError):
            booking.action_book_shipment()

    @patch('requests.request')
    def test_successful_booking_creates_label(self, mock_request):
        booking_response = type('Response', (), {
            'status_code': 200,
            'ok': True,
            'text': '',
            'json': lambda *args, **kwargs: {
                'bookingId': 'DHL-BOOK-123',
                'trackingNumbers': ['JD0012345678'],
            },
        })()
        label_response = type('Response', (), {
            'status_code': 200,
            'ok': True,
            'text': '',
            'json': lambda *args, **kwargs: {
                'documents': [{
                    'name': 'label.pdf',
                    'data': 'JVBERi0xLg==',
                    'trackingNumber': 'JD0012345678',
                }],
            },
        })()
        mock_request.side_effect = [booking_response, label_response]

        picking = self._create_picking()

        carrier = self.env['delivery.carrier'].create({
            'name': 'DHL Test',
            'delivery_type': 'dhl_freight_se',
            'product_id': self.env.ref('delivery.product_product_delivery').id,
            'arc_dhl_product_id': self.dhl_product.id,
        })
        booking = self.env['arc.dhl.booking'].create({
            'carrier_id': carrier.id,
            'picking_id': picking.id,
            'product_id': self.dhl_product.id,
        })
        result = booking.action_book_shipment()
        self.assertTrue(result['success'])
        self.assertEqual(booking.state, 'booked')
