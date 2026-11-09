# -*- coding: utf-8 -*-
"""SEC-B tests (findings 121-138). DHL is never called: requests is mocked."""
import importlib.util
import json
import os
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.arc_delivery_dhl.models.arc_dhl_price_quote import WEB_TIMEOUT


def _quote_response(total='150,00', unit='SEK', with_total=True):
    lines = []
    if with_total:
        lines.append({
            'id': 'TotalPrice', 'unit': unit, 'value': total,
            'description': 'Total', 'sortOrder': 100,
        })
    lines.append({
        'id': 'TotalPriceIncVAT', 'unit': unit, 'value': '187,50',
        'description': 'Total incl VAT', 'sortOrder': 120,
    })
    lines.append({
        'id': 'VAT', 'unit': unit, 'value': '37,50',
        'description': 'VAT', 'sortOrder': 110,
    })
    return lines


def _fake_response(payload):
    return type('Response', (), {
        'status_code': 200, 'ok': True, 'text': '',
        'json': lambda *args, **kwargs: payload,
    })()


@tagged('post_install', '-at_install', 'arc_dhl')
class TestArcDhlSecB(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        param = cls.env['ir.config_parameter'].sudo()
        param.set_param('arc_delivery_dhl.api_key', 'test-api-key')
        param.set_param('arc_delivery_dhl.force_environment', 'sandbox')
        param.set_param('arc_delivery_dhl.customer_number', '123456789')
        cls.carrier = cls.env['delivery.carrier'].create({
            'name': 'DHL SEC-B',
            'delivery_type': 'dhl_freight_se',
            'product_id': cls.env.ref('delivery.product_product_delivery').id,
        })
        cls.dhl_product = cls.env.ref('arc_delivery_dhl.dhl_product_paket')
        cls.partner = cls.env['res.partner'].create({
            'name': 'SEC-B Customer',
            'zip': '11122',
            'city': 'Stockholm',
            'street': 'Testgatan 1',
            'country_id': cls.env.ref('base.se').id,
        })
        uom = cls.env.ref('uom.product_uom_unit')
        cls.product = cls.env['product.template'].create({
            'name': 'SEC-B Sheet',
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
        cls.freight_product = cls.env['product.product'].sudo().search([
            ('default_code', '=', 'FRAKT'),
        ], limit=1) or cls.env['product.product'].create({
            'name': 'Frakt',
            'default_code': 'FRAKT',
            'type': 'service',
            'list_price': 0.0,
            'uom_id': uom.id,
            'uom_po_id': uom.id,
        })

    # Helpers -------------------------------------------------------------

    def _mock(self, mock_request, payload=None):
        mock_request.return_value.status_code = 200
        mock_request.return_value.ok = True
        mock_request.return_value.json.return_value = (
            payload if payload is not None else _quote_response())
        mock_request.return_value.text = ''

    def _order(self, **extra):
        vals = {
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1,
            })],
        }
        vals.update(extra)
        order = self.env['sale.order'].create(vals)
        action = order.action_arc_package_proposal_create()
        self.env['arc.package.proposal'].browse(action['res_id']).action_confirm()
        return order

    def _packages(self, length=50.0, weight=5.0):
        return [{
            'length_cm': length, 'width_cm': 30.0,
            'height_cm': 10.0, 'weight_kg': weight,
        }]

    def _quote_for(self, packages, zip_code='11122'):
        return self.env['arc.dhl.price.quote'].get_quote_for_packages(
            packages, {'country_code': 'SE', 'zip': zip_code},
            product=self.dhl_product,
        )

    def _picking(self):
        order = self._order()
        order.action_confirm()
        return order.picking_ids.filtered(
            lambda p: p.picking_type_id.code == 'outgoing')[:1]

    def _booking(self, **vals):
        base = {
            'carrier_id': self.carrier.id,
            'picking_id': self._picking().id,
            'product_id': self.dhl_product.id,
        }
        base.update(vals)
        return self.env['arc.dhl.booking'].create(base)

    # 122: price <= 0 is an error and is never cached ---------------------

    @patch('requests.request')
    def test_122_missing_total_price_is_error_and_not_cached(self, mock_request):
        self._mock(mock_request, _quote_response(with_total=False))
        last_id = self.env['arc.dhl.price.quote'].search([], limit=1, order='id desc').id
        res = self._quote_for(self._packages())
        self.assertFalse(res['success'])
        self.assertTrue(res['error_message'])
        res = self._quote_for(self._packages())
        self.assertFalse(res['success'])
        self.assertEqual(mock_request.call_count, 2, 'a zero quote is not cached')
        quotes = self.env['arc.dhl.price.quote'].search([
            ('id', '>', last_id), ('state', '=', 'quoted')])
        self.assertFalse(quotes)

    @patch('requests.request')
    def test_122_zero_total_price_is_error(self, mock_request):
        self._mock(mock_request, _quote_response(total='0,00'))
        res = self._quote_for(self._packages())
        self.assertFalse(res['success'])
        self.assertEqual(res['price'], 0.0)

    # 123: no product rule means failure, not a silent zero ---------------

    def test_123_no_rule_match_is_failure(self):
        order = self._order()
        with patch.object(
            self.env.registry['arc.dhl.product.selector'],
            'select_for_order', return_value=False,
        ):
            res = self.carrier.dhl_freight_se_rate_shipment(order)
        self.assertFalse(res['success'])
        self.assertTrue(res['error_message'])
        self.assertEqual(res['price'], 0.0)

    # 124 and 133: cache key ----------------------------------------------

    def _key(self, packages, zip_code='11122'):
        quote = self.env['arc.dhl.price.quote'].create({
            'product_id': self.dhl_product.id,
            'partner_zip': zip_code,
            'package_json': json.dumps([
                {'length': p['length_cm'], 'width': p['width_cm'],
                 'height': p['height_cm'], 'weight': p['weight_kg']}
                for p in packages]),
        })
        return quote._arc_dhl_quote_cache_key()

    def test_124_cache_key_is_sha1_and_includes_dimensions(self):
        key = self._key(self._packages(length=50.0))
        self.assertRegex(key, r'^[0-9a-f]{40}$')
        self.assertEqual(key, self._key(self._packages(length=50.0)))
        self.assertNotEqual(key, self._key(self._packages(length=80.0)))
        self.assertNotEqual(key, self._key(self._packages(weight=7.0)))

    @patch('requests.request')
    def test_124_different_dimensions_do_not_share_a_cached_price(self, mock_request):
        self._mock(mock_request)
        self._quote_for(self._packages(length=50.0))
        self._quote_for(self._packages(length=80.0))
        self.assertEqual(mock_request.call_count, 2)

    def test_133_cache_key_normalises_zip_and_weight(self):
        base = self._key(self._packages(weight=5.0), zip_code='11122')
        self.assertEqual(base, self._key(self._packages(weight=5.04), zip_code='111 22'))
        self.assertEqual(base, self._key(self._packages(weight=5.0), zip_code=' 11122 '))

    @patch('requests.request')
    def test_133_public_path_uses_short_timeout(self, mock_request):
        self._mock(mock_request)
        self._quote_for(self._packages())
        self.assertEqual(mock_request.call_args.kwargs['timeout'], WEB_TIMEOUT)
        self.assertLess(WEB_TIMEOUT, 30)

    @patch('requests.request')
    def test_133_backend_path_keeps_default_timeout(self, mock_request):
        self._mock(mock_request)
        order = self._order()
        self.carrier.arc_dhl_product_id = self.dhl_product
        self.carrier.dhl_freight_se_rate_shipment(order)
        self.assertEqual(mock_request.call_args.kwargs['timeout'], 30)

    # 138: quotes are read-only for ordinary users ------------------------

    def _salesman(self):
        groups = [
            'base.group_user',
            'sales_team.group_sale_salesman_all_leads',
            'stock.group_stock_user',
            'arc_industrial_ops.group_arc_ops_user',
        ]
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'SEC-B Salesman',
            'login': 'secb.salesman',
            'email': 'secb.salesman@example.com',
            'groups_id': [(6, 0, [self.env.ref(g).id for g in groups])],
        })

    def test_138_internal_user_cannot_create_or_write_quotes(self):
        user = self._salesman()
        Quote = self.env['arc.dhl.price.quote'].with_user(user)
        with self.assertRaises(AccessError):
            Quote.create({'product_id': self.dhl_product.id})
        quote = self.env['arc.dhl.price.quote'].create({
            'product_id': self.dhl_product.id, 'state': 'quoted', 'price': 100.0,
        })
        self.assertEqual(quote.with_user(user).price, 100.0)  # read works
        with self.assertRaises(AccessError):
            quote.with_user(user).write({'price': 1.0})

    @patch('requests.request')
    def test_138_module_paths_still_work_as_internal_user(self, mock_request):
        self._mock(mock_request)
        user = self._salesman()
        order = self._order()
        # Backend button: quote and freight line.
        order.with_user(user).action_arc_dhl_quote()
        self.assertEqual(order.arc_dhl_price_quote_id.price, 150.0)
        line = order.order_line.filtered(
            lambda l: l.product_id == self.freight_product)
        self.assertEqual(line.price_unit, 150.0)
        # Carrier rating.
        self.carrier.arc_dhl_product_id = self.dhl_product
        order2 = self._order()
        res = self.carrier.with_user(user).dhl_freight_se_rate_shipment(order2)
        self.assertTrue(res['success'])
        self.assertEqual(res['price'], 150.0)
        # Standalone calculator path.
        res = self.env['arc.dhl.price.quote'].with_user(user).get_quote_for_packages(
            self._packages(length=71.0), {'country_code': 'SE', 'zip': '11122'},
            product=self.dhl_product,
        )
        self.assertTrue(res['success'])

    # 125: booking idempotency --------------------------------------------

    def test_125_reset_blocked_when_booked_at_dhl(self):
        booking = self._booking()
        booking.write({'state': 'booked', 'dhl_booking_id': 'DHL-1'})
        with self.assertRaises(UserError):
            booking.action_reset_to_draft()
        self.assertEqual(booking.state, 'booked')

    def test_125_reset_allowed_without_booking_id_or_when_cancelled(self):
        booking = self._booking()
        booking.write({'state': 'error'})
        booking.action_reset_to_draft()
        self.assertEqual(booking.state, 'draft')
        booking.write({'state': 'cancelled', 'dhl_booking_id': 'DHL-2'})
        booking.action_reset_to_draft()
        self.assertEqual(booking.state, 'draft')

    @patch('requests.request')
    def test_125_booking_id_present_never_books_again(self, mock_request):
        booking = self._booking()
        booking.write({'state': 'error', 'dhl_booking_id': 'DHL-3'})
        res = booking.action_book_shipment()
        self.assertTrue(res['success'])
        mock_request.assert_not_called()

    @patch('requests.request')
    def test_125_second_booking_on_same_picking_is_refused(self, mock_request):
        first = self._booking()
        first.write({'state': 'booked', 'dhl_booking_id': 'DHL-4'})
        second = self.env['arc.dhl.booking'].create({
            'carrier_id': self.carrier.id,
            'picking_id': first.picking_id.id,
            'product_id': self.dhl_product.id,
        })
        with self.assertRaises(UserError):
            second.action_book_shipment()
        mock_request.assert_not_called()

    @patch('requests.request')
    def test_125_label_failure_keeps_the_booking(self, mock_request):
        booking_resp = _fake_response({
            'transportInstruction': {
                'shipmentId': 'DHL-5', 'trackingNumbers': ['JD1'],
            },
        })
        mock_request.side_effect = [booking_resp, RuntimeError('boom')]
        booking = self._booking()
        res = booking.action_book_shipment()
        self.assertTrue(res['success'])
        self.assertEqual(booking.state, 'booked')
        self.assertEqual(booking.dhl_booking_id, 'DHL-5')

    # 128: freight line in the order currency -----------------------------

    def test_128_freight_line_converted_to_order_currency(self):
        company = self.env.company
        other = self.env['res.currency'].with_context(active_test=False).search([
            ('name', 'in', ('EUR', 'USD')),
            ('id', '!=', company.currency_id.id),
        ], limit=1)
        other.active = True
        today = fields.Date.today()
        rate = self.env['res.currency.rate'].search([
            ('currency_id', '=', other.id), ('name', '=', today),
            ('company_id', '=', company.id),
        ])
        if rate:
            rate.rate = 0.5
        else:
            self.env['res.currency.rate'].create({
                'currency_id': other.id, 'name': today,
                'company_id': company.id, 'rate': 0.5,
            })
        pricelist = self.env['product.pricelist'].create({
            'name': 'SEC-B other currency', 'currency_id': other.id,
        })
        order = self._order(pricelist_id=pricelist.id)
        self.assertEqual(order.currency_id, other)
        quote = self.env['arc.dhl.price.quote'].create({
            'product_id': self.dhl_product.id,
            'state': 'quoted',
            'price': 200.0,
            'price_incl_vat': 250.0,
            'currency_id': company.currency_id.id,
        })
        order.arc_dhl_price_quote_id = quote
        order.action_arc_dhl_apply_shipping()
        line = order.order_line.filtered(
            lambda l: l.product_id == self.freight_product)
        # 1 company currency = 0.5 of the order currency.
        self.assertAlmostEqual(line.price_unit, 100.0, places=2)

    # 130: auto quote on confirm ------------------------------------------

    @patch('requests.request')
    def test_130_auto_quote_applies_once(self, mock_request):
        self._mock(mock_request)
        self.env['ir.config_parameter'].sudo().set_param(
            'arc_delivery_dhl.auto_quote_enabled', 'True')
        order = self._order()
        SaleOrder = self.env.registry['sale.order']
        original = SaleOrder.action_arc_dhl_apply_shipping
        with patch.object(
            SaleOrder, 'action_arc_dhl_apply_shipping',
            autospec=True, side_effect=original,
        ) as apply_mock:
            order.action_confirm()
        self.assertEqual(order.state, 'sale')
        self.assertEqual(apply_mock.call_count, 1)

    @patch('requests.request')
    def test_130_auto_quote_failure_is_rolled_back(self, mock_request):
        self._mock(mock_request)
        self.env['ir.config_parameter'].sudo().set_param(
            'arc_delivery_dhl.auto_quote_enabled', 'True')
        order = self._order()
        SaleOrder = self.env.registry['sale.order']
        with patch.object(
            SaleOrder, 'action_arc_dhl_apply_shipping',
            autospec=True, side_effect=UserError('boom'),
        ):
            order.action_confirm()
        self.assertEqual(order.state, 'sale')
        self.assertFalse(order.arc_dhl_price_quote_id)
        self.assertFalse(self.env['arc.dhl.price.quote'].search([
            ('sale_order_id', '=', order.id)]))
        self.assertFalse(order.order_line.filtered(
            lambda l: l.product_id == self.freight_product))

    # 131: rule data is noupdate ------------------------------------------

    def test_131_rule_xmlids_are_noupdate(self):
        data = self.env['ir.model.data'].sudo().search([
            ('module', '=', 'arc_delivery_dhl'),
            ('model', '=', 'arc.dhl.product.rule'),
        ])
        self.assertTrue(data)
        self.assertFalse(data.filtered(lambda d: not d.noupdate))

    def test_131_migration_flips_noupdate(self):
        data = self.env['ir.model.data'].sudo().search([
            ('module', '=', 'arc_delivery_dhl'),
            ('model', '=', 'arc.dhl.product.rule'),
        ], limit=1)
        self.assertTrue(data)
        data.noupdate = False
        self.env.flush_all()
        base = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'migrations', '18.0.1.5.0')
        for stage in ('pre-migration.py', 'post-migration.py'):
            data.noupdate = False
            self.env.flush_all()
            spec = importlib.util.spec_from_file_location(
                'secb_mig_' + stage[:3], os.path.join(base, stage))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.migrate(self.env.cr, '18.0.1.4.0')
            data.invalidate_recordset(['noupdate'])
            self.assertTrue(data.noupdate, stage)

    def test_128_web_adapter_returns_the_orders_currency(self):
        # Chrille 2026-11-09: EUR orders get EUR freight, also on the web path.
        Adapter = self.env['arc.dhl.visualcutter.adapter']
        sek = self.env.company.currency_id
        eur = self.env.ref('base.EUR')
        eur.active = True
        if sek == eur:
            self.skipTest('company currency is EUR')
        today = fields.Date.context_today(Adapter)
        Rate = self.env['res.currency.rate']
        rate = Rate.search([('currency_id', '=', eur.id), ('name', '=', today),
                            ('company_id', '=', self.env.company.id)], limit=1)
        if rate:
            rate.rate = 0.087
        else:
            Rate.create({'currency_id': eur.id, 'rate': 0.087, 'name': today,
                         'company_id': self.env.company.id})
        batch = {'format': 'plate', 'cut_weight_kg': 5.0, 'source_length': 1000,
                 'source_width': 500, 'source_thickness': 10}
        result = {'success': True, 'price': 800.0, 'currency_id': sek.id}
        Quote = type(self.env['arc.dhl.price.quote'])
        with patch.object(Quote, 'get_quote_for_packages', return_value=result):
            in_company = Adapter.quote_for_batch(batch, {'country_code': 'SE', 'zip': '58273'})
            in_eur = Adapter.quote_for_batch(
                batch, {'country_code': 'SE', 'zip': '58273', 'currency_id': eur.id})
        self.assertEqual(in_company['currency'], sek.name)
        self.assertEqual(in_company['shipping_fee'], 1000.0)
        self.assertEqual(in_eur['currency'], 'EUR')
        expected = round(sek._convert(800.0, eur, self.env.company,
                                      fields.Date.context_today(Adapter)) / 0.8, 2)
        self.assertAlmostEqual(in_eur['shipping_fee'], expected, places=2)
        self.assertNotEqual(in_eur['shipping_fee'], 1000.0)
