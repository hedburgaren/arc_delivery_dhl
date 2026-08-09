# -*- coding: utf-8 -*-
# Part of ARC Industrial Suite. See LICENSE file for full copyright and licensing details.
"""sale.order extensions for DHL Freight Sweden price quotes.

Adds a one-click path from a confirmed packing proposal to a DHL gross price
quote, and lets the salesperson add the freight as its own order line.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    arc_dhl_price_quote_id = fields.Many2one(
        'arc.dhl.price.quote',
        string='DHL Price Quote',
        readonly=True,
        copy=False,
        help='Latest DHL freight price quote for this order.',
    )
    arc_dhl_shipping_cost = fields.Float(
        string='DHL freight excl. VAT',
        related='arc_dhl_price_quote_id.price',
        readonly=True,
        help='Freight cost excluding VAT from the latest DHL quote.',
    )
    arc_dhl_shipping_cost_incl_vat = fields.Float(
        string='DHL freight incl. VAT',
        related='arc_dhl_price_quote_id.price_incl_vat',
        readonly=True,
        help='Freight cost including VAT from the latest DHL quote.',
    )
    arc_dhl_product_id = fields.Many2one(
        'arc.dhl.product',
        string='DHL product',
        help='Optional product lock. If empty the product selector picks the '
             'first matching DHL product from the confirmed packing proposal.',
    )

    def _arc_dhl_carrier(self):
        """Return the first DHL Freight Sweden carrier record."""
        return self.env['delivery.carrier'].sudo().search([
            ('delivery_type', '=', 'dhl_freight_se'),
        ], limit=1)

    def action_arc_dhl_quote(self):
        """Create or refresh a DHL price quote for this order.

        Requires a confirmed packing proposal. The selected DHL product comes
        from ``arc_dhl_product_id`` or from the automatic selector.
        """
        self.ensure_one()
        if self.state not in ('draft', 'sent'):
            raise UserError(_(
                'DHL freight quotes can only be requested for draft or sent '
                'quotations.'
            ))

        proposal = self.env['arc.package.proposal'].search([
            ('sale_order_id', '=', self.id),
            ('state', '=', 'confirmed'),
        ], limit=1, order='create_date desc')
        if not proposal:
            raise UserError(_(
                'No confirmed packing proposal found. Create and confirm a '
                'packaging proposal first.'
            ))
        if proposal.error_message:
            raise UserError(_(
                'The packing proposal has errors: %(errors)s',
                errors=proposal.error_message,
            ))

        carrier = self._arc_dhl_carrier()
        if not carrier:
            raise UserError(_(
                'No DHL Freight Sweden carrier is configured. Create one in '
                'Sales > Configuration > Shipping Methods.'
            ))

        product = self.arc_dhl_product_id
        if not product:
            product = self.env['arc.dhl.product.selector'].select_for_order(self)
        if not product:
            raise UserError(_(
                'No DHL product rule matches this order. Check the product '
                'dimensions, weight and destination country.'
            ))

        quote = self.env['arc.dhl.price.quote'].create({
            'carrier_id': carrier.id,
            'sale_order_id': self.id,
            'product_id': product.id,
        })
        result = quote.action_request_quote()
        if not result.get('success'):
            raise UserError(
                result.get('error_message')
                or _('The DHL price quote request failed.')
            )

        self.write({
            'arc_dhl_price_quote_id': quote.id,
            'carrier_id': carrier.id,
        })
        self.message_post(body=_(
            'DHL freight quote %(quote)s received: %(cost)s excl. VAT (%(cost_incl)s incl. VAT).'
        ) % {
            'quote': quote.name,
            'cost': self.currency_id.format(self.arc_dhl_shipping_cost),
            'cost_incl': self.currency_id.format(self.arc_dhl_shipping_cost_incl_vat),
        })

        return {
            'type': 'ir.actions.act_window',
            'name': _('DHL Price Quote'),
            'res_model': 'arc.dhl.price.quote',
            'res_id': quote.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_arc_dhl_apply_shipping(self):
        """Add or update a freight line on the order from the latest DHL quote."""
        self.ensure_one()
        if self.state not in ('draft', 'sent'):
            raise UserError(_(
                'Freight can only be added to draft or sent quotations.'
            ))
        if not self.arc_dhl_price_quote_id or self.arc_dhl_price_quote_id.state != 'quoted':
            raise UserError(_(
                'Request a DHL freight quote before adding the freight line.'
            ))

        freight_template = self.env['product.template'].sudo().search([
            ('name', '=', 'Frakt'),
            ('type', '=', 'service'),
        ], limit=1)
        freight_product = freight_template.product_variant_id if freight_template else self.env['product.product']
        if not freight_product:
            raise UserError(_(
                'No service product named "Frakt" was found. Create one to use '
                'as the freight line.'
            ))

        price = self.arc_dhl_shipping_cost
        existing = self.order_line.filtered(
            lambda l: l.product_id == freight_product
        )[:1]
        if existing:
            existing.write({
                'price_unit': price,
                'product_uom_qty': 1,
                'name': _('Freight - DHL %(product)s') % {
                    'product': self.arc_dhl_price_quote_id.product_id.name,
                },
            })
        else:
            self.env['sale.order.line'].create({
                'order_id': self.id,
                'product_id': freight_product.id,
                'product_uom_qty': 1,
                'price_unit': price,
                'name': _('Freight - DHL %(product)s') % {
                    'product': self.arc_dhl_price_quote_id.product_id.name,
                },
            })

        self.message_post(body=_(
            'Freight line updated to %(cost)s excl. VAT from DHL quote %(quote)s.'
        ) % {
            'cost': self.currency_id.format(price),
            'quote': self.arc_dhl_price_quote_id.name,
        })
        return True

    def _arc_dhl_auto_quote_enabled(self):
        """Return True if this order should auto-request a DHL freight quote."""
        self.ensure_one()
        if self.env['ir.config_parameter'].sudo().get_param(
            'arc_delivery_dhl.auto_quote_enabled'
        ) != 'True':
            return False
        if self.state not in ('draft', 'sent'):
            return False
        if not self._arc_dhl_carrier():
            return False
        proposal = self.env['arc.package.proposal'].search([
            ('sale_order_id', '=', self.id),
            ('state', '=', 'confirmed'),
        ], limit=1, order='create_date desc')
        if not proposal or proposal.error_message:
            return False
        return True

    def _arc_dhl_auto_quote_and_apply(self):
        """Ensure a fresh DHL quote exists and add it as a freight line."""
        self.ensure_one()
        quote = self.arc_dhl_price_quote_id
        if not quote or quote.state != 'quoted':
            self.action_arc_dhl_quote()
        if self.arc_dhl_price_quote_id and self.arc_dhl_price_quote_id.state == 'quoted':
            self.action_arc_dhl_apply_shipping()

    def action_confirm(self):
        """Auto-request DHL freight quote before confirming, if enabled."""
        for order in self:
            if order._arc_dhl_auto_quote_enabled():
                try:
                    order._arc_dhl_auto_quote_and_apply()
                except Exception as e:
                    _logger.warning(
                        'DHL auto-quote failed for %s: %s', order.name, e
                    )
        return super().action_confirm()
