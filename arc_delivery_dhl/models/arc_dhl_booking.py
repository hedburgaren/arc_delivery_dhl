# -*- coding: utf-8 -*-
"""Shipment booking against DHL TransportInstruction API."""
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
        self.api_request = str(payload)

        try:
            response = self.env['arc.dhl.request.mixin']._arc_dhl_request(
                'post',
                '/transport-instruction',
                payload=payload,
            )
        except UserError as exc:
            self.write({
                'state': 'error',
                'error_message': str(exc),
            })
            return {
                'success': False,
                'error_message': str(exc),
            }

        self.api_response = str(response)
        booking_id = response.get('bookingId') or response.get('shipmentId')
        tracking_numbers = response.get('trackingNumbers', []) or []
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
        label_result = self._arc_dhl_fetch_labels(booking_id, packages)
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
        """Build the TransportInstruction payload.

        The exact schema is confirmed with DHL during implementation. This
        builds a representative payload using the fields documented in the
        Swedish API Farm integration guide.
        """
        picking = self.picking_id
        partner = picking.partner_id
        company = picking.company_id
        product = self.product_id

        def _address_lines(partner):
            lines = [partner.street or '']
            if partner.street2:
                lines.append(partner.street2)
            return [l for l in lines if l]

        package_lines = []
        for idx, pkg in enumerate(packages, start=1):
            package_lines.append({
                'packageId': str(idx),
                'length': round(pkg['length_cm'], 1),
                'width': round(pkg['width_cm'], 1),
                'height': round(pkg['height_cm'], 1),
                'weight': round(pkg['weight_kg'], 2),
                'stackable': pkg['stackable'],
            })

        payload = {
            'sender': {
                'name': company.name,
                'address': {
                    'street': company.street or '',
                    'postalCode': company.zip or '',
                    'city': company.city or '',
                    'countryCode': company.country_id.code or 'SE',
                },
                'contact': {
                    'phone': company.phone or '',
                    'email': company.email or '',
                },
            },
            'receiver': {
                'name': partner.name,
                'address': {
                    'street': _address_lines(partner)[0] if _address_lines(partner) else '',
                    'postalCode': partner.zip or '',
                    'city': partner.city or '',
                    'countryCode': partner.country_id.code or 'SE',
                },
                'contact': {
                    'phone': partner.phone or partner.mobile or '',
                    'email': partner.email or '',
                },
            },
            'shipment': {
                'productCode': product.code,
                'senderReference': self.carrier_id.arc_dhl_default_sender_reference
                                   or picking.name,
                'packages': package_lines,
            },
        }
        if self.carrier_id.arc_dhl_service_text:
            payload['shipment']['serviceText'] = self.carrier_id.arc_dhl_service_text
        return payload

    def _arc_dhl_fetch_labels(self, booking_id, packages):
        """Fetch PDF labels from the DHL Print API."""
        self.ensure_one()
        try:
            response = self.env['arc.dhl.request.mixin']._arc_dhl_request(
                'post',
                '/print',
                payload={
                    'bookingId': booking_id,
                    'labelFormat': 'PDF',
                },
            )
        except UserError as exc:
            return {
                'success': False,
                'error_message': str(exc),
            }

        documents = response.get('documents') or []
        if not documents:
            return {
                'success': False,
                'error_message': _('DHL print response contained no documents.'),
            }

        Label = self.env['arc.dhl.label']
        for doc in documents:
            label_data = doc.get('data')
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
