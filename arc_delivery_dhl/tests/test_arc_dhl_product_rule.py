# -*- coding: utf-8 -*-
"""Tests for DHL product rule selection."""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'arc_dhl')
class TestArcDhlProductRule(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'Test Customer',
            'zip': '58118',
            'city': 'Linkoping',
            'country_id': cls.env.ref('base.se').id,
        })
        cls.foreign_partner = cls.env['res.partner'].create({
            'name': 'Foreign Customer',
            'zip': '1000',
            'city': 'Copenhagen',
            'country_id': cls.env.ref('base.dk').id,
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

    def _create_order(self, partner, product_uom_qty=1.0):
        order = self.env['sale.order'].create({
            'partner_id': partner.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': product_uom_qty,
            })],
        })
        order.action_arc_package_proposal_create()
        order.arc_package_proposal_id.action_confirm()
        return order

    def test_domestic_small_package_selects_paket(self):
        order = self._create_order(self.partner)
        product = self.env['arc.dhl.product.selector'].select_for_order(order)
        self.assertTrue(product)
        self.assertEqual(product.code, '102')

    def test_international_selects_road_standard(self):
        order = self._create_order(self.foreign_partner)
        product = self.env['arc.dhl.product.selector'].select_for_order(order)
        self.assertTrue(product)
        self.assertEqual(product.code, '202')

    def test_domestic_small_selects_paket(self):
        order = self._create_order(self.partner)
        # 100 cm is well within the PAKET limits; no load-meter applies.
        line = order.arc_package_proposal_id.line_ids
        line.write({'goods_L_mm': 1000})
        product = self.env['arc.dhl.product.selector'].select_for_order(order)
        self.assertTrue(product)
        self.assertEqual(product.code, '102')

    def test_domestic_heavy_selects_parti(self):
        # 250 units of the test sheet push actual weight above the PALL/STYCKE
        # ceiling so the PARTI rule is selected.
        order = self._create_order(self.partner, product_uom_qty=250.0)
        product = self.env['arc.dhl.product.selector'].select_for_order(order)
        self.assertTrue(product)
        self.assertEqual(product.code, '212')
