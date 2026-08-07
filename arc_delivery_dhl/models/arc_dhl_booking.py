# -*- coding: utf-8 -*-
"""Shipment booking against DHL TransportInstruction API."""
import json
import logging
from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ArcDhlBooking(models.Model):
    _name = 'arc.dhl.booking'
    _description = 'DHL shipment booking'
    _order = 'create_date desc'
    _inherit = ['mail.thread']

    name = fields.Char(string='Reference', readonly=True, copy=False)
    carrier_id = fields.Many2one(
        'delivery.carrier',
        string='Carrier',
        required=True,
        ondelete='restrict',
    )
    picking_id = fields.Many2one(
        'stock.picking',
        string='Picking',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sales Order',
        related='picking_id.sale_id',
        store=True,
        readonly=True,
    )
    product_id = fields.Many2one(
        'arc.dhl.product',
        string='DHL product',
        required=True,
        ondelete='restrict',
    )
    state = fields.Selection(
        [('draft', 'Draft'),
         ('booked', 'Booked'),
         ('error', 'Error'),
         ('cancelled', 'Cancelled')],
        string='Status',
        default='draft',
        tracking=True,
    )
    dhl_booking_id = fields.Char(
        string='DHL booking ID',
        readonly=True,
        copy=False,
    )
    dhl_tracking_numbers = fields.Char(
        string='Tracking numbers',
        readonly=True,
        copy=False,
    )
    label_ids = fields.One2many(
        'arc.dhl.label',
        'booking_id',
        string='Labels',
        readonly=True,
    )
    price = fields.Float(string='Price', readonly=True)
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    api_request = fields.Text(string='Last API request', readonly=True)
    api_response = fields.Text(string='Last API response', readonly=True)
    error_message = fields.Text(string='Error message', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'arc.dhl.booking'
                ) or '/'
        return super().create(vals_list)

    def action_book_shipment(self):
        """Book the shipment with DHL and retrieve labels.

        Returns a dict consumed by delivery.carrier.send_shipping().
        """
        self.ensure_one()
        if self.state == 'booked':
            return {
                'success': True,
                'price': self.price,
                'tracking_numbers': self._tracking_numbers_list(),
            }

        picking = self.picking_id
        carrier = self.carrier_id
        product = self.product_id

        if carrier.delivery_type != 'dhl_freight_se':
            raise UserError(_(
                'The carrier is not configured for DHL Freight Sweden.'
            ))

        if not picking.partner_id:
            raise UserError(_(
                'The delivery address is missing on the picking.'
            ))

        customer_number = self.env['ir.config_parameter'].sudo().get_param(
            'arc_delivery_dhl.customer_number'
        )
        if not customer_number:
            raise UserError(_(
                'DHL customer number is not configured. Set it in Settings > '
                'DHL Freight Sweden.'
            ))

        if not product:
            product = self.env['arc.dhl.product.selector'].select_for_picking(picking)
            self.product_id = product

        packages = self._arc_dhl_collect_packages(picking)
        if not packages:
            raise UserError(_(
                'No packages found for this picking. Create packages first or '
                'use the packing planner.'
            ))

        self._arc_dhl_validate_packages(packages, product)

        payload = self._arc_dhl_build_payload(packages)
        payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
        self.api_request = payload_json
        _logger.info(
            'DHL TransportInstruction request for booking %s:\n%s',
            self.name,
            payload_json,
        )

        try:
            response = self.env['arc.dhl.request.mixin']._arc_dhl_request(
                'post',
                '/transportinstructionapi/v1/transportinstruction/sendtransportinstruction',
                payload=payload,
            )
        except UserError as exc:
            _logger.error(
                'DHL TransportInstruction failed for booking %s: %s',
                self.name,
                exc,
            )
            self.write({
                'state': 'error',
                'error_message': str(exc),
            })
            return {
                'success': False,
                'error_message': str(exc),
            }

        response_json = json.dumps(response, ensure_ascii=False, indent=2)
        self.api_response = response_json
        _logger.info(
            'DHL TransportInstruction response for booking %s:\n%s',
            self.name,
            response_json,
        )

        # The successful response wraps the accepted shipment under
        # transportInstruction.
        shipment_data = response.get('transportInstruction') or response
        booking_id = (
            shipment_data.get('shipmentId')
            or shipment_data.get('id')
            or shipment_data.get('bookingId')
        )
        tracking_numbers = self._arc_dhl_extract_tracking_numbers(shipment_data)
        if not booking_id:
            msg = _('DHL response did not contain a booking identifier.')
            self.write({
                'state': 'error',
                'error_message': msg,
            })
            return {
                'success': False,
                'error_message': msg,
            }

        self.write({
            'state': 'booked',
            'dhl_booking_id': booking_id,
            'dhl_tracking_numbers': ', '.join(tracking_numbers),
        })

        # Fetch labels in a separate call.
        label_result = self._arc_dhl_fetch_labels(payload, tracking_numbers)
        if not label_result.get('success'):
            self.message_post(body=label_result.get('error_message', ''))

        picking.write({
            'carrier_tracking_ref': self.dhl_tracking_numbers,
        })

        return {
            'success': True,
            'price': self.price,
            'tracking_numbers': tracking_numbers,
        }

    def _arc_dhl_collect_packages(self, picking):
        """Collect package data from the picking.

        Prefers WP2 package structure (arc.package.proposal), falls back to
        native stock.quant.package records.
        """
        packages = []
        proposal = self.env['arc.package.proposal'].search([
            ('sale_order_id', '=', picking.sale_id.id),
            ('state', '=', 'confirmed'),
        ], limit=1, order='create_date desc')

        if proposal:
            for line in proposal.line_ids:
                for _i in range(line.package_qty):
                    packages.append({
                        'length_cm': max(line.goods_L_mm or 1, 1) / 10.0,
                        'width_cm': max(line.goods_B_mm or 1, 1) / 10.0,
                        'height_cm': max(line.goods_H_mm or 1, 1) / 10.0,
                        'weight_kg': line.chargeable_weight_kg
                                     / max(line.package_qty, 1),
                        'stackable': line.stackable,
                    })
            return packages

        # Native package fallback.
        for package in picking.move_line_ids.mapped('result_package_id'):
            package.ensure_one()
            pt = package.package_type_id
            packages.append({
                'length_cm': (pt.length or 1) / 10.0,
                'width_cm': (pt.width or 1) / 10.0,
                'height_cm': (pt.height or 1) / 10.0,
                'weight_kg': package.weight or 1.0,
                'stackable': True,
            })
        return packages

    def _arc_dhl_validate_packages(self, packages, product):
        """Raise if packages violate published DHL limits."""
        for idx, pkg in enumerate(packages, start=1):
            max_l = product.max_length_cm
            if max_l and pkg['length_cm'] > max_l:
                raise UserError(_(
                    'Package %(index)s exceeds the %(product)s length limit of '
                    '%(limit)s cm.',
                    index=idx,
                    product=product.name,
                    limit=max_l,
                ))
            max_w = product.max_weight_kg
            if max_w and pkg['weight_kg'] > max_w:
                raise UserError(_(
                    'Package %(index)s exceeds the %(product)s weight limit of '
                    '%(limit)s kg.',
                    index=idx,
                    product=product.name,
                    limit=max_w,
                ))

    def _arc_dhl_build_payload(self, packages):
        """Build the DHL TransportInstruction `Shipment` payload.

        The schema is defined in the Swedish DHL API Farm
        TransportInstruction swagger.
        """
        picking = self.picking_id
        partner = picking.partner_id
        company = picking.company_id
        product = self.product_id

        def _dhl_address(partner):
            street = partner.street or ''
            if partner.street2:
                street = '{} {}'.format(street, partner.street2).strip()
            return {
                'street': street[:35],
                'cityName': (partner.city or '')[:35],
                'postalCode': (partner.zip or '')[:9],
                'countryCode': (partner.country_id.code or 'SE')[:3],
            }

        is_domestic = (partner.country_id.code or 'SE').upper() == 'SE'
        payer_code = '1' if is_domestic else 'DAP'

        customer_number = self.env['ir.config_parameter'].sudo().get_param(
            'arc_delivery_dhl.customer_number', ''
        )

        # Product-specific minimum dimensions observed from the DHL sandbox.
        # Kept in code so no module upgrade is required when tuning them.
        product_mins = {
            '102': {'length': 1.0, 'width': 11.0, 'height': 2.0},
        }
        mins = product_mins.get(product.code, {
            'length': 0.1, 'width': 0.1, 'height': 0.1,
        })

        piece_lines = []
        total_weight = 0.0
        total_volume = 0.0
        total_pieces = 0
        for idx, pkg in enumerate(packages, start=1):
            length = max(round(pkg['length_cm'], 1), mins['length'])
            width = max(round(pkg['width_cm'], 1), mins['width'])
            height = max(round(pkg['height_cm'], 1), mins['height'])
            weight = round(pkg['weight_kg'], 2)
            volume = round(length * width * height / 1_000_000.0, 4)
            piece_lines.append({
                'numberOfPieces': 1,
                'weight': weight,
                'volume': volume,
                'width': width,
                'height': height,
                'length': length,
                'stackable': bool(pkg.get('stackable', True)),
            })
            total_weight += weight
            total_volume += volume
            total_pieces += 1

        sender_reference = (
            self.carrier_id.arc_dhl_default_sender_reference or picking.name
        )[:35]

        payload = {
            'productCode': product.code,
            'payerCode': {'code': payer_code},
            'totalNumberOfPieces': total_pieces,
            'totalWeight': round(total_weight, 2),
            'totalVolume': round(total_volume, 4),
            'totalLoadingMeters': 0,
            'totalPalletPlaces': 0,
            'references': [
                {
                    'qualifier': 'CU',
                    'value': sender_reference,
                },
            ],
            'parties': [
                {
                    'type': 'Consignor',
                    'id': customer_number[:15],
                    'name': (company.name or '')[:35],
                    'address': {
                        'street': (company.street or '')[:35],
                        'cityName': (company.city or '')[:35],
                        'postalCode': (company.zip or '')[:9],
                        'countryCode': (company.country_id.code or 'SE')[:3],
                    },
                    'phone': (company.phone or '')[:64],
                    'email': (company.email or '')[:64],
                },
                {
                    'type': 'Consignee',
                    'name': (partner.name or '')[:35],
                    'address': _dhl_address(partner),
                    'phone': (partner.phone or partner.mobile or '')[:64],
                    'email': (partner.email or '')[:64],
                },
            ],
            'pieces': piece_lines,
        }
        return payload

    def _arc_dhl_extract_tracking_numbers(self, shipment_data):
        """Return a list of tracking numbers from a DHL shipment response."""
        numbers = shipment_data.get('trackingNumbers') or []
        if numbers:
            return [str(n) for n in numbers]
        # Fallback: collect piece ids when no explicit tracking numbers exist.
        tracking = []
        for piece in shipment_data.get('pieces') or []:
            piece_ids = piece.get('id') or []
            if isinstance(piece_ids, list):
                tracking.extend(str(pid) for pid in piece_ids)
            elif piece_ids:
                tracking.append(str(piece_ids))
        return tracking

    def _arc_dhl_fetch_labels(self, shipment_payload, tracking_numbers):
        """Fetch PDF labels from the DHL Print API.

        First tries to fetch by shipment id (PrintOptionsById); if that
        returns no reports, falls back to sending the full Shipment with
        tracking numbers as piece ids.
        """
        self.ensure_one()
        _logger.info(
            'DHL label fetch called for booking %s with tracking_numbers=%s',
            self.name, tracking_numbers,
        )

        # Try by id first: sandbox sometimes returns labels here.
        print_payload_by_id = {
            'shipmentIds': [self.dhl_booking_id],
            'options': {
                'label': True,
            },
        }
        _logger.info(
            'DHL label fetch by-id payload for booking %s:\n%s',
            self.name, json.dumps(print_payload_by_id, ensure_ascii=False, indent=2),
        )
        try:
            response = self.env['arc.dhl.request.mixin']._arc_dhl_request(
                'post',
                '/printapi/v1/print/printdocumentsbyid',
                payload=print_payload_by_id,
            )
            _logger.info(
                'DHL label fetch by-id response for booking %s:\n%s',
                self.name, json.dumps(response, ensure_ascii=False, indent=2),
            )
            reports = response.get('reports') or []
            if reports:
                return self._arc_dhl_store_labels(reports)
        except UserError as exc:
            _logger.info(
                'DHL label fetch by-id failed for booking %s: %s',
                self.name, exc,
            )

        # Fallback: full shipment with tracking numbers as piece ids.
        print_shipment = dict(shipment_payload)
        print_pieces = []
        for idx, piece in enumerate(print_shipment.get('pieces', [])):
            tracking = tracking_numbers[idx] if idx < len(tracking_numbers) else str(idx + 1)
            print_pieces.append({
                **piece,
                'id': [str(tracking)],
            })
        print_shipment['pieces'] = print_pieces
        print_payload = {
            'shipment': print_shipment,
            'options': {
                'label': True,
            },
        }
        _logger.info(
            'DHL label fetch payload for booking %s:\n%s',
            self.name, json.dumps(print_payload, ensure_ascii=False, indent=2),
        )
        try:
            response = self.env['arc.dhl.request.mixin']._arc_dhl_request(
                'post',
                '/printapi/v1/print/printdocuments',
                payload=print_payload,
            )
            _logger.info(
                'DHL label fetch response for booking %s:\n%s',
                self.name, json.dumps(response, ensure_ascii=False, indent=2),
            )
        except UserError as exc:
            return {
                'success': False,
                'error_message': str(exc),
            }

        return self._arc_dhl_store_labels(response.get('reports') or [])

    def _arc_dhl_store_labels(self, reports):
        """Create arc.dhl.label records from DHL Print API report list."""
        if not reports:
            return {
                'success': False,
                'error_message': _('DHL print response contained no documents.'),
            }
        Label = self.env['arc.dhl.label']
        for doc in reports:
            label_data = doc.get('content')
            if not label_data:
                continue
            Label.create({
                'booking_id': self.id,
                'picking_id': self.picking_id.id,
                'name': doc.get('name') or 'DHL_label.pdf',
                'label_data': label_data,
                'tracking_number': doc.get('trackingNumber'),
            })
        return {'success': True}

    def _tracking_numbers_list(self):
        self.ensure_one()
        return [
            t.strip()
            for t in (self.dhl_tracking_numbers or '').split(',')
            if t.strip()
        ]

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})
