# -*- coding: utf-8 -*-
"""SEC-C 136: one shared package collector for booking, selection and quotes.

Booking, product selection and price quoting each carried a copy of the
package collection with different state filters and dict schemas. All paths
now go through arc.dhl.product.selector and produce the same cm/kg packages
with stackable.
"""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'arc_dhl')
class TestSecC136PackageCollector(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'SEC-C 136 Customer',
            'zip': '11122',
            'city': 'Stockholm',
            'country_id': cls.env.ref('base.se').id,
        })
        uom = cls.env.ref('uom.product_uom_unit')
        cls.product = cls.env['product.template'].create({
            'name': 'SEC-C 136 Sheet',
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
        proposal = self.env['arc.package.proposal'].browse(action['res_id'])
        proposal.action_confirm()
        return order, proposal

    def test_order_and_picking_collection_agree(self):
        order, _proposal = self._order_with_proposal()
        order.action_confirm()
        picking = order.picking_ids.filtered(
            lambda p: p.picking_type_id.code == 'outgoing')[:1]

        selector = self.env['arc.dhl.product.selector']
        from_order = selector.collect_packages_for_order(order)
        from_picking = selector.collect_packages_for_picking(picking)

        self.assertTrue(from_order)
        # Same proposal, same packages: weight cannot differ per path.
        self.assertEqual(from_order, from_picking)
        for package in from_order:
            self.assertIn('stackable', package)
            self.assertGreater(package['weight_kg'], 0.0)

    def test_price_quote_order_collection_uses_shared_schema(self):
        order, _proposal = self._order_with_proposal()
        quote = self.env['arc.dhl.price.quote'].create({
            'sale_order_id': order.id,
            'product_id': self.env.ref('arc_delivery_dhl.dhl_product_paket').id,
        })
        packages = quote._arc_dhl_collect_packages_from_order()
        self.assertTrue(packages)
        for package in packages:
            self.assertIn('length', package)
            self.assertIn('stackable', package)

    def test_booking_collection_delegates_to_shared_collector(self):
        order, _proposal = self._order_with_proposal()
        order.action_confirm()
        picking = order.picking_ids.filtered(
            lambda p: p.picking_type_id.code == 'outgoing')[:1]
        carrier = self.env['delivery.carrier'].create({
            'name': 'DHL SEC-C 136',
            'delivery_type': 'dhl_freight_se',
            'product_id': self.env.ref('delivery.product_product_delivery').id,
        })
        booking = self.env['arc.dhl.booking'].create({
            'carrier_id': carrier.id,
            'picking_id': picking.id,
            'product_id': self.env.ref('arc_delivery_dhl.dhl_product_paket').id,
        })
        self.assertEqual(
            booking._arc_dhl_collect_packages(picking),
            self.env['arc.dhl.product.selector']
            .collect_packages_for_picking(picking),
        )
