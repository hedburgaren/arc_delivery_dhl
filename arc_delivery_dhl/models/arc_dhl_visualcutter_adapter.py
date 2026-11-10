# -*- coding: utf-8 -*-
"""Adapter that lets VisualCutter request DHL shipping prices.

VisualCutter batch results (weight, dimensions, piece count) are converted to
a DHL package profile, a DHL product is selected, and a PriceQuote API call is
made. The return shape mirrors ``apply_shipping_and_packaging`` so existing
frontend code keeps working.
"""
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class ArcDhlVisualCutterAdapter(models.AbstractModel):
    _name = 'arc.dhl.visualcutter.adapter'
    _description = 'DHL price adapter for VisualCutter batches'

    @api.model
    def quote_for_batch(self, batch_result, partner_vals):
        """Return shipping fee and info for a single VC batch.

        :param batch_result: dict from ``_vc_calculate_batch`` containing
            cut_weight_kg, format, source_length/width/thickness etc.
        :param partner_vals: dict with ``country_code`` and ``zip``, and
            optionally ``currency_id``: the order's currency (res.currency
            id). The fee is returned in that currency, else in the company
            currency (Chrille 2026-11-09, SEC-B 128: EUR orders get EUR
            freight).
        :return: dict with ``success``, ``shipping_fee``, ``shipping_info``,
                 ``packaging_fee``, ``packaging_info`` and ``currency`` keys.
                 SEC-C 134: ``success`` is False and ``shipping_fee`` 0.0 when
                 no fee could be determined, so a caller can never read the
                 zero as a free shipment.
        """
        packages = self._batch_to_packages(batch_result)
        if not packages:
            return self._fallback_result(_('No packages could be derived.'))

        quote_result = self.env['arc.dhl.price.quote'].get_quote_for_packages(
            packages, partner_vals,
        )
        if not quote_result.get('success'):
            return self._fallback_result(
                quote_result.get('error_message') or _('DHL quote failed.')
            )

        # Add the agreed ~20% margin: sell price = DHL cost / 0.8.
        target = self._arc_target_currency(partner_vals)
        cost = self._arc_to_currency(
            quote_result.get('price', 0.0), quote_result.get('currency_id'), target)
        shipping_fee = round(cost / 0.8, 2)
        return {
            'success': True,
            'shipping_fee': shipping_fee,
            'currency': target.name,
            'shipping_info': {
                'rule_name': 'DHL Freight Sweden',
                'breakdown': quote_result,
            },
            # The adapter only prices freight. The caller
            # (apply_shipping_and_packaging) fills in the packaging fee from
            # arc.frakt.engine; these defaults apply if that engine is missing.
            'packaging_fee': 0.0,
            'packaging_info': {'reason': 'packaging_engine_unavailable'},
        }

    @api.model
    def _arc_target_currency(self, partner_vals):
        """The order's currency when the caller names it, else the company's."""
        currency_id = (partner_vals or {}).get('currency_id')
        currency = self.env['res.currency'].sudo().browse(currency_id).exists() \
            if currency_id else self.env['res.currency']
        return currency or self.env.company.currency_id

    @api.model
    def _arc_to_currency(self, amount, from_currency_id, target):
        """Convert a DHL amount from the quote's currency to ``target``."""
        source = self.env['res.currency'].sudo().browse(from_currency_id).exists() \
            if from_currency_id else self.env['res.currency']
        source = source or self.env.company.currency_id
        if not amount or source == target:
            return amount or 0.0
        return source._convert(
            amount, target, self.env.company, fields.Date.context_today(self))

    @api.model
    def _batch_to_packages(self, batch_result):
        """Convert a VC batch result into DHL package dicts (cm/kg)."""
        fmt = (batch_result.get('format') or '').lower()
        total_weight = batch_result.get('cut_weight_kg', 0.0)
        if total_weight <= 0:
            return []

        # The caller passes the stacked CUT-piece dimensions in the source_*
        # fields (see _apply_dhl_shipping); the raw sheet is never shipped.
        if fmt == 'plate':
            length_cm = batch_result.get('source_length', 1) / 10.0
            width_cm = batch_result.get('source_width', 1) / 10.0
            height_cm = batch_result.get('source_thickness', 1) / 10.0
        else:
            length_cm = batch_result.get('source_length', 1) / 10.0
            width_cm = batch_result.get('source_thickness', 1) / 10.0
            height_cm = batch_result.get('source_thickness', 1) / 10.0

        if length_cm <= 0 or width_cm <= 0 or height_cm <= 0:
            return []

        return [{
            'length_cm': length_cm,
            'width_cm': width_cm,
            'height_cm': height_cm,
            'weight_kg': total_weight,
        }]

    @api.model
    def _fallback_result(self, reason):
        """Return an explicit failure result when DHL quoting is not possible.

        SEC-C 134: the shape is unchanged, but ``success`` now says plainly
        that no fee was determined. The zero fee is a placeholder for callers
        that only read the amount, never a statement that shipping is free.
        """
        return {
            'success': False,
            'shipping_fee': 0.0,
            'shipping_info': {'reason': reason},
            'packaging_fee': 0.0,
            'packaging_info': {'reason': reason},
        }
