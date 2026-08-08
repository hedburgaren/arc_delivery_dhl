# -*- coding: utf-8 -*-
"""delivery.carrier extension for DHL Freight Sweden."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    delivery_type = fields.Selection(
        selection_add=[('dhl_freight_se', 'DHL Freight Sweden')],
        ondelete={'dhl_freight_se': 'set default'},
    )
    arc_dhl_product_id = fields.Many2one(
        'arc.dhl.product',
        string='DHL product',
        help='Product code sent to DHL. Leave empty to select manually at booking.',
    )
    arc_dhl_service_text = fields.Char(
        string='DHL service text',
        help='Optional service text included in the booking payload.',
    )
    arc_dhl_default_sender_reference = fields.Char(
        string='Default sender reference',
        help='Default reference shown on the DHL label.',
    )

    def _arc_dhl_carrier_name(self):
        self.ensure_one()
        if self.delivery_type != 'dhl_freight_se':
            return False
        return 'DHL Freight Sweden'

    def dhl_freight_se_rate_shipment(self, order):
        """Return a cached price quote for the sales order."""
        self.ensure_one()
        product = self.arc_dhl_product_id
        if not product:
            product = self.env['arc.dhl.product.selector'].select_for_order(order)
        if not product:
            return {
                'success': True,
                'price': 0.0,
                'error_message': False,
                'warning_message': _(
                    'No DHL product rule matches this order; manual product '
                    'selection required.'
                ),
            }
        quote = self.env['arc.dhl.price.quote'].create({
            'carrier_id': self.id,
            'sale_order_id': order.id,
            'product_id': product.id,
        })
        result = quote.action_request_quote()
        return {
            'success': result.get('success', False),
            'price': result.get('price', 0.0),
            'error_message': result.get('error_message', False),
            'warning_message': result.get('warning_message', False),
        }

    def dhl_freight_se_send_shipping(self, pickings):
        """Book shipments and create labels for the given pickings."""
        self.ensure_one()
        if not self.env['ir.config_parameter'].sudo().get_param(
            'arc_delivery_dhl.booking_enabled'
        ):
            raise UserError(_(
                'DHL shipment booking is disabled in Settings. Enable it to '
                'book directly from Odoo, or book manually in myDHLFreight and '
                'paste the tracking reference into the picking.'
            ))
        res = []
        for picking in pickings:
            booking = self.env['arc.dhl.booking'].create({
                'carrier_id': self.id,
                'picking_id': picking.id,
                'product_id': self.arc_dhl_product_id.id,
            })
            result = booking.action_book_shipment()
            if not result.get('success'):
                raise UserError(result.get('error_message') or _('Booking failed.'))
            res.append({
                'exact_price': result.get('price', 0.0),
                'tracking_number': ', '.join(result.get('tracking_numbers', [])),
            })
        return res

    def dhl_freight_se_get_tracking_link(self, picking):
        """Return the DHL tracking URL for a picking."""
        self.ensure_one()
        if not self.env['ir.config_parameter'].sudo().get_param(
            'arc_delivery_dhl.tracking_enabled'
        ):
            return False
        tokens = [
            t.strip()
            for t in (picking.carrier_tracking_ref or '').split(',')
            if t.strip()
        ]
        if not tokens:
            return False
        # developer.dhl.com Shipment Tracking Unified is used for tracking.
        return 'https://www.dhl.com/se-en/home/tracking/tracking-ecommerce.html?tracking-id={}'.format(
            tokens[0]
        )

    def dhl_freight_se_cancel_shipment(self, pickings):
        """Cancel shipments. DHL API Farm cancellation is not always supported."""
        self.ensure_one()
        for picking in pickings:
            if picking.delivery_type != 'dhl_freight_se':
                continue
            if not picking.carrier_tracking_ref:
                raise UserError(_(
                    'Cannot cancel a shipment that has no tracking reference.'
                ))
            # Cancellation endpoint is implementation-specific; log and raise
            # so the user uses the manual fallback when the API does not support it.
            raise UserError(_(
                'Automatic DHL cancellation is not implemented. Cancel the '
                'shipment in myDHLFreight and clear the tracking reference here.'
            ))

    def dhl_freight_se_get_default_custom_package_code(self):
        """Return the default package type code for this carrier."""
        self.ensure_one()
        return 'DHL'
