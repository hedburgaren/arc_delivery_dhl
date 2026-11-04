# -*- coding: utf-8 -*-
"""Task 426: the customer delivery date from DHL's tracking."""
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

GET = 'odoo.addons.arc_delivery_dhl.models.purchase_order.requests.get'


def response(status_code=200, payload=None):
    result = MagicMock(status_code=status_code)
    result.json.return_value = payload if payload is not None else {}
    return result


def delivered(stamp='2026-10-01T22:30:00Z'):
    return response(payload={'shipments': [{
        'status': {'statusCode': 'delivered', 'timestamp': stamp},
    }]})


def in_transit():
    return response(payload={'shipments': [{
        'status': {'statusCode': 'transit', 'timestamp': '2026-10-01T08:00:00Z'},
    }]})


@tagged('post_install', '-at_install', 'arc_dhl')
class TestDhlCustomerDelivery(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.param = cls.env['ir.config_parameter'].sudo()
        cls.param.set_param('arc_delivery_dhl.tracking_api_key', 'test-key')
        cls.param.set_param('arc_delivery_dhl.force_environment', 'production')
        cls.supplier = cls.env['res.partner'].create({'name': 'Leverantör T426', 'is_company': True})
        cls.customer = cls.env['res.partner'].create({'name': 'Kund T426'})
        cls.product = cls.env['product.product'].create({'name': 'Skiva T426', 'type': 'consu'})
        cls.carrier_product = cls.env['product.product'].create({'name': 'Frakt T426', 'type': 'service'})
        cls.carrier = cls.env['delivery.carrier'].create({
            'name': 'DHL T426', 'delivery_type': 'dhl_freight_se',
            'product_id': cls.carrier_product.id,
        })
        cls.dropship_type = cls.env['stock.picking.type'].search(
            [('code', '=', 'dropship')], limit=1)
        cls.incoming_type = cls.env['stock.picking.type'].search(
            [('code', '=', 'incoming')], limit=1)
        cls.Order = cls.env['purchase.order']

    def _order(self, name='PO-T426-D1', tracking='JJD0001', picking_type=None, carrier=True,
               age_days=1, state='purchase'):
        """A real order and delivery. Written directly: confirming would build routes."""
        order = self.Order.create({
            'name': name, 'partner_id': self.supplier.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id, 'product_qty': 1, 'price_unit': 10,
                'name': 'Skiva',
            })],
        })
        order.write({
            'state': state,
            'date_order': fields.Datetime.now() - timedelta(days=age_days),
        })
        self._picking(order, tracking, picking_type or self.dropship_type, carrier)
        return order

    def _picking(self, order, tracking, picking_type=None, carrier=True):
        picking_type = picking_type or self.dropship_type
        location_src = self.env.ref('stock.stock_location_suppliers')
        location_dest = self.env.ref('stock.stock_location_customers')
        picking = self.env['stock.picking'].create({
            'partner_id': self.customer.id,
            'picking_type_id': picking_type.id,
            'location_id': location_src.id,
            'location_dest_id': location_dest.id,
            'carrier_id': self.carrier.id if carrier else False,
            'carrier_tracking_ref': tracking,
            'move_ids': [(0, 0, {
                'name': 'Skiva',
                'product_id': self.product.id,
                'product_uom_qty': 1,
                'product_uom': self.product.uom_id.id,
                'location_id': location_src.id,
                'location_dest_id': location_dest.id,
                'purchase_line_id': order.order_line[0].id,
            })],
        })
        return picking

    def _run(self, *responses):
        with patch(GET, side_effect=list(responses)) as mocked:
            self.Order._cron_arc_dhl_customer_delivery()
        return mocked

    def _only(self, order):
        """Other orders in the database must not eat the mocked answers."""
        return patch.object(
            type(self.Order), '_arc_dhl_tracking_candidates',
            lambda model, limit: order.with_env(model.env))

    def test_production_fills_the_stockholm_day(self):
        order = self._order()
        with self._only(order):
            self._run(delivered('2026-10-01T22:30:00Z'))
        self.assertEqual(order.arc_customer_delivery_date, date(2026, 10, 2))
        self.assertEqual(order.arc_customer_delivery_source, 'dhl')
        self.assertTrue(order.arc_dhl_tracking_checked_at)
        self.assertIn('JJD0001', ' '.join(order.message_ids.mapped('body')))

    def test_sandbox_never_writes(self):
        self.param.set_param('arc_delivery_dhl.force_environment', 'sandbox')
        order = self._order()
        with self._only(order):
            mocked = self._run(delivered())
        self.assertEqual(mocked.call_count, 1)
        self.assertFalse(order.arc_customer_delivery_date)
        self.assertFalse(order.arc_customer_delivery_source)

    def test_seeded_false_is_not_production(self):
        self.param.set_param('arc_delivery_dhl.force_environment', '')
        self.param.set_param('arc_delivery_dhl.is_production', 'False')
        self.assertFalse(self.Order._arc_dhl_tracking_is_live())
        self.param.set_param('arc_delivery_dhl.is_production', '1')
        self.assertTrue(self.Order._arc_dhl_tracking_is_live())

    def test_no_key_makes_no_call(self):
        order = self._order()
        with patch.object(type(self.Order), '_arc_dhl_tracking_key', lambda model: ''):
            with self._only(order):
                mocked = self._run()
        mocked.assert_not_called()
        self.assertFalse(order.arc_customer_delivery_date)

    def test_manual_date_is_not_even_asked_about(self):
        order = self._order()
        order.arc_customer_delivery_date = date(2026, 9, 1)
        self.assertNotIn(order, self.Order._arc_dhl_tracking_candidates(1000))

    def test_manual_date_set_during_the_run_survives(self):
        order = self._order()
        order.arc_customer_delivery_date = date(2026, 9, 1)
        with self._only(order):
            self._run(delivered())
        self.assertEqual(order.arc_customer_delivery_date, date(2026, 9, 1))
        self.assertEqual(order.arc_customer_delivery_source, 'manual')
        self.assertNotIn('JJD0001', ' '.join(order.message_ids.mapped('body')))

    def test_not_delivered_writes_nothing_but_remembers_the_check(self):
        order = self._order()
        with self._only(order):
            self._run(in_transit())
        self.assertFalse(order.arc_customer_delivery_date)
        self.assertTrue(order.arc_dhl_tracking_checked_at)

    def test_unknown_shipment_writes_nothing(self):
        order = self._order()
        with self._only(order):
            self._run(response(404))
        self.assertFalse(order.arc_customer_delivery_date)

    def test_every_parcel_must_be_delivered(self):
        order = self._order()
        self._picking(order, 'JJD0002')
        with self._only(order):
            self._run(delivered(), in_transit())
        self.assertFalse(order.arc_customer_delivery_date)

    def test_the_last_parcel_decides_the_date(self):
        order = self._order(tracking='JJD0001,JJD0002')
        with self._only(order):
            self._run(delivered('2026-10-05T10:00:00Z'), delivered('2026-10-03T10:00:00Z'))
        self.assertEqual(order.arc_customer_delivery_date, date(2026, 10, 5))

    def test_selection_skips_what_it_should(self):
        wanted = self._order(name='PO-T426-D2')
        no_carrier = self._order(name='PO-T426-D3', carrier=False)
        too_old = self._order(name='PO-T426-D4', age_days=61)
        not_dropship = self._order(name='PO-T426-D5', picking_type=self.incoming_type)
        no_tracking = self._order(name='PO-T426-D6', tracking=False)
        draft = self._order(name='PO-T426-D7', state='draft')
        found = self.Order._arc_dhl_tracking_candidates(1000)
        self.assertIn(wanted, found)
        for order in (no_carrier, too_old, not_dropship, no_tracking, draft):
            with self.subTest(order=order.name):
                self.assertNotIn(order, found)

    def test_failing_order_does_not_stop_the_others(self):
        first = self._order(name='PO-T426-D8')
        second = self._order(name='PO-T426-D9', tracking='JJD0009')
        with self._only(first | second):
            failing = response(500)
            failing.raise_for_status.side_effect = RuntimeError('DHL 500')
            self._run(failing, delivered())
        self.assertFalse(first.arc_customer_delivery_date)
        self.assertEqual(second.arc_customer_delivery_source, 'dhl')

    def test_call_limit_stops_the_run(self):
        first = self._order(name='PO-T426-D10')
        second = self._order(name='PO-T426-D11', tracking='JJD0011')
        with self._only(first | second):
            mocked = self._run(response(429), delivered())
        self.assertEqual(mocked.call_count, 1)
        self.assertFalse(second.arc_customer_delivery_date)

    def test_the_longest_waiting_order_goes_first(self):
        seen = self._order(name='PO-T426-D12')
        waiting = self._order(name='PO-T426-D13', tracking='JJD0013')
        seen.arc_dhl_tracking_checked_at = fields.Datetime.now()
        found = self.Order._arc_dhl_tracking_candidates(1000)
        self.assertLess(list(found).index(waiting), list(found).index(seen))
