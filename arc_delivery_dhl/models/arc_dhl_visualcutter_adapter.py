# -*- coding: utf-8 -*-
"""Adapter that lets VisualCutter request DHL shipping prices.

VisualCutter batch results (weight, dimensions, piece count) are converted to
a DHL package profile, a DHL product is selected, and a PriceQuote API call is
made. The return shape mirrors ``apply_shipping_and_packaging`` so existing
frontend code keeps working.
"""
import logging

from odoo import _, api, models

_logger = logging.getLogger(__name__)


class ArcDhlVisualCutterAdapter(models.AbstractModel):
    _name = 'arc.dhl.visualcutter.adapter'
    _description = 'DHL price adapter for VisualCutter batches'

    @api.model
    def quote_for_batch(self, batch_result, partner_vals):
        """Return shipping fee and info for a single VC batch.

        :param batch_result: dict from ``_vc_calculate_batch`` containing
            cut_weight_kg, format, source_length/width/thickness etc.
        :param partner_vals: dict with ``country_code`` and ``zip``.
        :return: dict with ``shipping_fee``, ``shipping_info``,
                 ``packaging_fee`` and ``packaging_info`` keys.
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

        shipping_fee = quote_result.get('price', 0.0)
        return {
            'shipping_fee': shipping_fee,
            'shipping_info': {
                'rule_name': 'DHL Freight Sweden',
                'breakdown': quote_result,
            },
            # Packaging is intentionally kept at 0 here; it is handled by the
            # WP2 packaging engine / arc.frakt.engine separately until that
            # engine is replaced as well.
            'packaging_fee': 0.0,
            'packaging_info': {'rule_name': _('Handled by packaging engine')},
        }

    @api.model
    def _batch_to_packages(self, batch_result):
        """Convert a VC batch result into DHL package dicts (cm/kg)."""
        fmt = (batch_result.get('format') or '').lower()
        total_weight = batch_result.get('cut_weight_kg', 0.0)
        if total_weight <= 0:
            return []

        # Use the source sheet/rod dimensions as the shipment package dims.
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
        """Return a fail-open result when DHL quoting is not possible."""
        return {
            'shipping_fee': 0.0,
            'shipping_info': {'reason': reason},
            'packaging_fee': 0.0,
            'packaging_info': {'reason': reason},
        }
