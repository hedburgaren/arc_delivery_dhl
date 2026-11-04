# -*- coding: utf-8 -*-
"""Fill the customer delivery date from DHL's tracking (task 426).

The Swedish API Farm used for quotes and bookings has no tracking API. DHL
points to Shipment Tracking - Unified, a separate service with its own key
(arc_delivery_dhl.tracking_api_key, or DHL_TRACKING_API_KEY).

The cron writes only when the DHL environment is explicitly production. In any
other case it logs what it found and writes nothing. It never touches a manual
date: arc_industrial_ops refuses that write whatever the caller says.
"""
import logging
import os
from datetime import datetime, timedelta

import pytz
import requests
from markupsafe import Markup, escape

from odoo import api, fields, models

from .arc_dhl_request_mixin import DEFAULT_TIMEOUT, _read_dotenv

_logger = logging.getLogger(__name__)

TRACKING_URL = 'https://api-eu.dhl.com/track/shipments'
MAX_AGE_DAYS = 60
DEFAULT_BATCH = 20  # The unified API allows 250 calls a day on its base plan.
TIMEZONE = 'Europe/Stockholm'
TRUE_VALUES = ('1', 'true', 'True')


class DhlTrackingLimit(Exception):
    """DHL refused because of the call limit: stop this run."""


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    arc_dhl_tracking_checked_at = fields.Datetime(
        string='DHL-spårning kontrollerad', copy=False, readonly=True,
        help='När cronen senast frågade DHL, så att alla ordrar får sin tur.')

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _arc_dhl_tracking_refs(self):
        """DHL tracking numbers on this order's live dropship deliveries."""
        self.ensure_one()
        refs = []
        pickings = self.order_line.move_ids.picking_id.filtered(
            lambda p: p.picking_type_code == 'dropship' and p.state != 'cancel')
        for picking in pickings:
            is_dhl = (picking.carrier_id.delivery_type == 'dhl_freight_se'
                      or picking.arc_dhl_booking_ids)
            if not is_dhl or not picking.carrier_tracking_ref:
                continue
            refs += [r.strip() for r in picking.carrier_tracking_ref.split(',') if r.strip()]
        return refs

    @api.model
    def _arc_dhl_tracking_candidates(self, limit):
        cutoff = fields.Datetime.now() - timedelta(days=MAX_AGE_DAYS)
        orders = self.search([
            ('state', 'in', ('purchase', 'done')),
            ('arc_customer_delivery_date', '=', False),
            ('date_order', '>=', cutoff),
            ('order_line.move_ids.picking_id.picking_type_code', '=', 'dropship'),
            ('order_line.move_ids.picking_id.carrier_tracking_ref', '!=', False),
        ], order='arc_dhl_tracking_checked_at asc nulls first, id asc')
        return orders.filtered(lambda o: o._arc_dhl_tracking_refs())[:limit]

    # ------------------------------------------------------------------
    # DHL
    # ------------------------------------------------------------------

    @api.model
    def _arc_dhl_tracking_is_live(self):
        """Strict on purpose: the seeded 'False' is a non-empty string."""
        param = self.env['ir.config_parameter'].sudo()
        force = param.get_param('arc_delivery_dhl.force_environment')
        if force:
            return force == 'production'
        return param.get_param('arc_delivery_dhl.is_production') in TRUE_VALUES

    @api.model
    def _arc_dhl_tracking_key(self):
        key = self.env['ir.config_parameter'].sudo().get_param(
            'arc_delivery_dhl.tracking_api_key')
        if key:
            return key
        key = os.environ.get('DHL_TRACKING_API_KEY', '').strip()
        if key:
            return key
        module_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return _read_dotenv('DHL_TRACKING_API_KEY', module_path)

    @api.model
    def _arc_dhl_parse_delivered_day(self, payload):
        """The local day of a delivered event in a tracking response, or None."""
        for shipment in (payload or {}).get('shipments') or []:
            statuses = [shipment.get('status') or {}] + list(shipment.get('events') or [])
            for status in statuses:
                if (status.get('statusCode') or '').lower() != 'delivered':
                    continue
                stamp = status.get('timestamp')
                if not stamp:
                    continue
                try:
                    moment = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
                except ValueError:
                    _logger.warning('DHL tracking: unreadable timestamp %r', stamp)
                    continue
                zone = pytz.timezone(TIMEZONE)
                if moment.tzinfo is None:
                    return moment.date()  # DHL gives local time at the event.
                return moment.astimezone(zone).date()
        return None

    @api.model
    def _arc_dhl_fetch_delivered_day(self, reference, key):
        response = requests.get(
            TRACKING_URL,
            params={'trackingNumber': reference, 'service': 'freight'},
            headers={'DHL-API-Key': key, 'Accept': 'application/json'},
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code == 404:
            return None
        if response.status_code == 429:
            raise DhlTrackingLimit()
        response.raise_for_status()
        return self._arc_dhl_parse_delivered_day(response.json())

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------

    @api.model
    def _cron_arc_dhl_customer_delivery(self):
        key = self._arc_dhl_tracking_key()
        if not key:
            _logger.info('DHL tracking: no tracking key configured, nothing checked.')
            return
        live = self._arc_dhl_tracking_is_live()
        batch = int(self.env['ir.config_parameter'].sudo().get_param(
            'arc_delivery_dhl.tracking_batch', DEFAULT_BATCH))
        for order in self._arc_dhl_tracking_candidates(batch):
            try:
                with self.env.cr.savepoint():
                    order._arc_dhl_check_tracking(key, live)
            except DhlTrackingLimit:
                _logger.warning('DHL tracking: call limit reached, stopping this run.')
                return
            except Exception:
                _logger.exception('DHL tracking: %s could not be checked', order.name)

    def _arc_dhl_check_tracking(self, key, live):
        self.ensure_one()
        refs = self._arc_dhl_tracking_refs()
        days = [self._arc_dhl_fetch_delivered_day(ref, key) for ref in refs]
        self.arc_dhl_tracking_checked_at = fields.Datetime.now()
        if not days or not all(days):
            return
        # Every parcel must be there: the goods arrived with the last one.
        day = max(days)
        if not live:
            _logger.info('DHL tracking (not production): %s delivered %s, nothing written.',
                         self.name, day)
            return
        self.with_context(arc_customer_delivery_source='dhl').write(
            {'arc_customer_delivery_date': day})
        if self.arc_customer_delivery_source == 'dhl':
            self.message_post(
                body=Markup('<p>%s</p>') % escape(
                    'Levererat hos kund %s enligt DHL:s spårning (%s).' % (day, ', '.join(refs))),
                subtype_xmlid='mail.mt_note', message_type='comment')
