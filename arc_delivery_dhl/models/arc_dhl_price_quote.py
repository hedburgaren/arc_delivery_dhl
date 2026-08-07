# -*- coding: utf-8 -*-
"""DHL Freight Price Quote API integration with caching."""
import json
import logging
from datetime import timedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


# Mapping from Product API / rule codes to the string enum values used by the
# Swedish API Farm PriceQuote API. The enum is defined in the PriceQuote swagger
# under ShipmentModel.dhlProductCode.
_PRICE_QUOTE_PRODUCT_CODES = {
    '102': 'DHLPaket',
    '103': 'DHLServicePointB2C',
    '109': 'DHLParcelConnect',
    '112': 'DHLParcelConnect',  # Plus is not a separate enum value.
    '118': 'DHLPaket',  # DHL Hemleverans Paket maps to the Paket enum.
    '210': 'DHLPall',
    '211': 'DHLStycke',
    '212': 'DHLParti',
    '202': 'DHLEuroConnect',
    '232': 'DHLEuroConnectPlus',
    '233': 'DHLEurapid',
    '205': 'DHLEuroline',
    '401': 'DHLHomeDelivery',
    '402': 'DHLHomeDeliveryReturn',
    '502': 'DHLHomeDeliveryReturn',
    '601': 'DHLHomeDelivery',
    'HDI': 'DHLHomeDelivery',
}


class ArcDhlPriceQuote(models.Model):
    _name = 'arc.dhl.price.quote'
    _description = 'DHL price quote'
    _order = 'create_date desc'

    name = fields.Char(string='Reference', readonly=True, copy=False)
    carrier_id = fields.Many2one(
        'delivery.carrier',
        string='Carrier',
        required=False,
        ondelete='restrict',
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sales Order',
        ondelete='cascade',
        index=True,
    )
    product_id = fields.Many2one(
        'arc.dhl.product',
        string='DHL product',
        required=True,
        ondelete='restrict',
    )
    partner_country_code = fields.Char(
        string='Receiver country',
        size=2,
        default='SE',
    )
    partner_zip = fields.Char(string='Receiver ZIP')
    package_json = fields.Text(
        string='Packages (JSON)',
        help='JSON list of packages used when no sales order is linked.',
    )
    state = fields.Selection(
        [('draft', 'Draft'),
         ('quoted', 'Quoted'),
         ('error', 'Error')],
        string='Status',
        default='draft',
    )
    price = fields.Float(string='Price', readonly=True)
    price_incl_vat = fields.Float(string='Price incl. VAT', readonly=True)
    vat_amount = fields.Float(string='VAT amount', readonly=True)
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
                'price_incl_vat': existing.price_incl_vat,
                'vat_amount': existing.vat_amount,
                'currency_id': existing.currency_id.id,
                'cache_key': cache_key,
            })
            return {
                'success': True,
                'price': existing.price,
                'price_incl_vat': existing.price_incl_vat,
                'vat_amount': existing.vat_amount,
                'warning_message': False,
            }

        payload = self._arc_dhl_build_quote_payload()
        try:
            response = self.env['arc.dhl.request.mixin']._arc_dhl_request(
                'post',
                '/pricequoteapi/v1/pricequote/quoteforgrossprice',
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
        price_incl_vat = self._arc_dhl_extract_price(response, 'TotalPriceIncVAT')
        vat_amount = self._arc_dhl_extract_price(response, 'VAT')
        currency = self._arc_dhl_extract_currency(response)
        vals = {
            'state': 'quoted',
            'price': price,
            'price_incl_vat': price_incl_vat,
            'vat_amount': vat_amount,
            'cache_key': cache_key,
        }
        if currency:
            vals['currency_id'] = currency.id
        self.write(vals)
        return {
            'success': True,
            'price': price,
            'price_incl_vat': price_incl_vat,
            'vat_amount': vat_amount,
            'warning_message': False,
        }

    @api.model
    def get_quote_for_packages(self, packages, partner_vals, product=None):
        """Request a DHL price quote for a raw package list.

        :param packages: list of dicts with length_cm, width_cm, height_cm,
                         weight_kg.
        :param partner_vals: dict with country_code and zip.
        :param product: optional arc.dhl.product record; if not provided the
                        first matching rule is used.
        :return: dict with success, price, error_message as returned by
                 action_request_quote.
        """
        country_code = (partner_vals.get('country_code') or 'SE').upper()
        zip_code = partner_vals.get('zip') or ''

        if not product:
            product = self.env['arc.dhl.product.selector'].select_from_packages(
                packages, country_code, silent=True,
            )
        if not product:
            return {
                'success': False,
                'price': 0.0,
                'error_message': _(
                    'No DHL product rule matches the shipment.'
                ),
            }

        carrier = self.env['delivery.carrier'].sudo().search([
            ('delivery_type', '=', 'dhl_freight_se'),
        ], limit=1)
        package_list = [
            {
                'length': max(p.get('length_cm', 1), 1),
                'width': max(p.get('width_cm', 1), 1),
                'height': max(p.get('height_cm', 1), 1),
                'weight': max(p.get('weight_kg', 0.001), 0.001),
            }
            for p in packages
        ]
        quote = self.create({
            'carrier_id': carrier.id if carrier else False,
            'product_id': product.id,
            'partner_country_code': country_code,
            'partner_zip': zip_code,
            'package_json': json.dumps(package_list),
        })
        return quote.action_request_quote()

    def _arc_dhl_quote_cache_key(self):
        """Build a deterministic cache key from the quote inputs."""
        self.ensure_one()
        if self.sale_order_id:
            order = self.sale_order_id
            partner = order.partner_shipping_id or order.partner_id
            packages = self._arc_dhl_collect_packages_from_order()
            parts = [
                str(self.product_id.id),
                partner.country_id.code or 'SE',
                partner.zip or '',
                str(round(order.arc_chargeable_weight_kg or 0.0, 2)),
                str(int(order.arc_package_count or 0)),
            ]
        else:
            packages = self._arc_dhl_collect_packages_from_json()
            parts = [
                str(self.product_id.id),
                self.partner_country_code or 'SE',
                self.partner_zip or '',
                str(round(sum(p['weight'] for p in packages), 2)),
                str(len(packages)),
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

    def _arc_dhl_price_quote_product_code(self):
        """Return the PriceQuote API enum value for the selected product."""
        self.ensure_one()
        code = self.product_id.code or ''
        price_quote_code = _PRICE_QUOTE_PRODUCT_CODES.get(code)
        if not price_quote_code:
            raise ValueError(_(
                'DHL product code %(code)s has no PriceQuote API mapping.',
                code=code,
            ))
        return price_quote_code

    def _arc_dhl_build_quote_payload(self):
        """Build a Swedish API Farm PriceQuote gross-price payload.

        The schema follows the PriceQuote API swagger for
        ``/pricequote/quoteforgrossprice``.
        """
        if self.sale_order_id:
            order = self.sale_order_id
            partner = order.partner_shipping_id or order.partner_id
            country_code = partner.country_id.code or 'SE'
            zip_code = partner.zip or ''
            packages = self._arc_dhl_collect_packages_from_order()
            company = order.company_id
        else:
            country_code = self.partner_country_code or 'SE'
            zip_code = self.partner_zip or ''
            packages = self._arc_dhl_collect_packages_from_json()
            company = self.env.company

        piece_lines = []
        total_weight = 0.0
        total_volume = 0.0
        total_pieces = 0
        total_pallet_places = 0
        for pkg in packages or [{'length': 1.0, 'width': 1.0, 'height': 1.0, 'weight': 1.0}]:
            length_cm = pkg.get('length', 1)
            width_cm = pkg.get('width', 1)
            height_cm = pkg.get('height', 1)
            # Volume in cubic metres for the DHL API.
            volume = (length_cm * width_cm * height_cm) / 1_000_000.0
            weight = pkg.get('weight', 0.001)
            number_of_pieces = int(pkg.get('number_of_pieces', 1)) or 1
            pallet_places = pkg.get('pallet_places', 0)
            is_stackable = pkg.get('stackable', True)

            piece_lines.append({
                'numberOfPieces': number_of_pieces,
                'weight': round(weight, 2),
                'volume': round(volume, 4),
                'loadingMeters': 0,
                'palletPlaces': pallet_places,
                'width': round(width_cm, 1),
                'height': round(height_cm, 1),
                'length': round(length_cm, 1),
                'stackable': is_stackable,
                'packageType': pkg.get('package_type') or 'CLL',
            })
            total_weight += weight * number_of_pieces
            total_volume += volume * number_of_pieces
            total_pieces += number_of_pieces
            total_pallet_places += pallet_places * number_of_pieces

        is_domestic = country_code == 'SE'
        payer_code = '1' if is_domestic else 'DAP'

        payload = {
            'shipment': {
                'dhlProductCode': self._arc_dhl_price_quote_product_code(),
                'totalNumberOfPieces': total_pieces,
                'totalWeight': round(total_weight, 2),
                'totalVolume': round(total_volume, 4),
                'totalLoadingMeters': 0,
                'totalPalletPlaces': total_pallet_places,
                'numberOfEURPallets': 0,
                'numberOfFullPallets': None,
                'numberOfHalfPallets': None,
                'payerCode': payer_code,
                'piece': piece_lines,
                'parties': [
                    {
                        'id': None,
                        'type': 'Consignor',
                        'address': {
                            'postalCode': company.zip or '',
                            'cityName': company.city or '',
                            'countryCode': company.country_id.code or 'SE',
                        },
                    },
                    {
                        'id': None,
                        'type': 'Consignee',
                        'address': {
                            'postalCode': zip_code,
                            'cityName': partner.city or '' if self.sale_order_id else '',
                            'countryCode': country_code,
                        },
                    },
                ],
            },
            'ownSurCharge': {
                'percentage': 0,
                'value': 0,
            },
        }

        # Optional additional services can be injected by submodules by overriding
        # this method and updating payload['shipment']['additionalServices'].
        return payload

    def _arc_dhl_collect_packages_from_order(self):
        """Collect packages from the linked sale order's proposal."""
        self.ensure_one()
        order = self.sale_order_id
        packages = []
        proposal = self.env['arc.package.proposal'].search([
            ('sale_order_id', '=', order.id),
            ('state', 'in', ('draft', 'confirmed')),
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
                        'stackable': line.stackable,
                    })
        return packages

    def _arc_dhl_collect_packages_from_json(self):
        """Collect packages from the stored package_json field."""
        self.ensure_one()
        if not self.package_json:
            return []
        try:
            return json.loads(self.package_json)
        except ValueError:
            return []

    def _arc_dhl_extract_price(self, response, line_id='TotalPrice'):
        """Extract a price line from a DHL Price Quote response.

        The response is a list of charge lines. Values are returned with a
        comma as decimal separator in the Swedish locale, e.g. "207,00".
        """
        if isinstance(response, list):
            for line in response:
                if isinstance(line, dict) and line.get('id') == line_id:
                    value = line.get('value', '0')
                    try:
                        return float(str(value).replace(',', '.'))
                    except (TypeError, ValueError):
                        return 0.0
        return 0.0

    def _arc_dhl_extract_currency(self, response):
        """Return a res.currency record matching the quote response."""
        if isinstance(response, list):
            for line in response:
                if isinstance(line, dict) and line.get('id') == 'TotalPrice':
                    code = line.get('unit') or ''
                    if code:
                        return self.env['res.currency'].with_context(
                            active_test=False
                        ).search([('name', '=', code.upper())], limit=1)
        return False
