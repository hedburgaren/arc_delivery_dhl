# -*- coding: utf-8 -*-
"""DHL PriceQuote API integration with caching."""
import json
import logging
from datetime import timedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class ArcDhlPriceQuote(models.Model):
    _name = 'arc.dhl.price.quote'
    _description = 'DHL price quote'
    _order = 'create_date desc'

    name = fields.Char(string='Reference', readonly=True, copy=False)
    carrier_id = fields.Many2one(
        'delivery.carrier',
        string='Carrier',
        required=True,
        ondelete='restrict',
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sales Order',
        required=True,
        ondelete='cascade',
        index=True,
    )
    product_id = fields.Many2one(
        'arc.dhl.product',
        string='DHL product',
        required=True,
        ondelete='restrict',
    )
    state = fields.Selection(
        [('draft', 'Draft'),
         ('quoted', 'Quoted'),
         ('error', 'Error')],
        string='Status',
        default='draft',
    )
    price = fields.Float(string='Price', readonly=True)
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    cache_key = fields.Char(string='Cache key', readonly=True, index=True)
    api_response = fields.Text(string='API response', readonly=True)
    error_message = fields.Text(string='Error message', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'arc.dhl.price.quote'
                ) or '/'
        return super().create(vals_list)

    def action_request_quote(self):
        """Request a price quote, using cache when available."""
        self.ensure_one()
        cache_key = self._arc_dhl_quote_cache_key()
        existing = self.search([
            ('cache_key', '=', cache_key),
            ('state', '=', 'quoted'),
            ('create_date', '>=', fields.Datetime.now() - self._cache_ttl()),
        ], limit=1, order='create_date desc')
        if existing:
            _logger.info('DHL price quote cache hit for key %s', cache_key)
            self.write({
                'state': 'quoted',
                'price': existing.price,
                'cache_key': cache_key,
            })
            return {
                'success': True,
                'price': existing.price,
                'warning_message': False,
            }

        payload = self._arc_dhl_build_quote_payload()
        try:
            response = self.env['arc.dhl.request.mixin']._arc_dhl_request(
                'post',
                '/price-quote',
                payload=payload,
            )
        except Exception as exc:  # pylint: disable=broad-except
            _logger.error('DHL price quote failed: %s', exc)
            self.write({
                'state': 'error',
                'error_message': str(exc),
                'cache_key': cache_key,
            })
            return {
                'success': False,
                'price': 0.0,
                'error_message': str(exc),
            }

        self.api_response = json.dumps(response)
        price = self._arc_dhl_extract_price(response)
        self.write({
            'state': 'quoted',
            'price': price,
            'cache_key': cache_key,
        })
        return {
            'success': True,
            'price': price,
            'warning_message': False,
        }

    def _arc_dhl_quote_cache_key(self):
        """Build a deterministic cache key from the quote inputs."""
        self.ensure_one()
        order = self.sale_order_id
        partner = order.partner_shipping_id or order.partner_id
        parts = [
            str(self.product_id.id),
            partner.country_id.code or 'SE',
            partner.zip or '',
            str(round(order.arc_chargeable_weight_kg or 0.0, 2)),
            str(int(order.arc_package_count or 0)),
        ]
        return hash(tuple(parts))

    def _cache_ttl(self):
        """Return quote cache time-to-live as a timedelta."""
        hours = int(
            self.env['ir.config_parameter'].sudo().get_param(
                'arc_delivery_dhl.quote_cache_hours', '24'
            )
        )
        return timedelta(hours=hours)

    def _arc_dhl_build_quote_payload(self):
        """Build a PriceQuote payload."""
        order = self.sale_order_id
        partner = order.partner_shipping_id or order.partner_id
        packages = []
        proposal = self.env['arc.package.proposal'].search([
            ('sale_order_id', '=', order.id),
            ('state', '=', 'confirmed'),
        ], limit=1, order='create_date desc')
        if proposal:
            for line in proposal.line_ids:
                for _i in range(line.package_qty):
                    packages.append({
                        'length': max(line.goods_L_mm or 1, 1) / 10.0,
                        'width': max(line.goods_B_mm or 1, 1) / 10.0,
                        'height': max(line.goods_H_mm or 1, 1) / 10.0,
                        'weight': line.chargeable_weight_kg
                                  / max(line.package_qty, 1),
                    })
        return {
            'productCode': self.product_id.code,
            'receiver': {
                'countryCode': partner.country_id.code or 'SE',
                'postalCode': partner.zip or '',
            },
            'packages': packages or [{'weight': 1.0}],
        }

    def _arc_dhl_extract_price(self, response):
        """Extract the price from a DHL PriceQuote response."""
        if isinstance(response, dict):
            amount = response.get('price') or response.get('totalPrice')
            if isinstance(amount, (int, float)):
                return float(amount)
        return 0.0
