# -*- coding: utf-8 -*-
"""stock.picking extensions for DHL booking status."""
from odoo import fields, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    arc_dhl_booking_ids = fields.One2many(
        'arc.dhl.booking',
        'picking_id',
        string='DHL bookings',
    )
    arc_dhl_label_count = fields.Integer(
        string='DHL labels',
        compute='_compute_arc_dhl_label_count',
    )
    arc_dhl_freight_stale = fields.Boolean(
        string='Freight stale',
        default=False,
        help='Set when order lines change after the delivery line was added.',
    )

    def _compute_arc_dhl_label_count(self):
        for picking in self:
            picking.arc_dhl_label_count = self.env['arc.dhl.label'].search_count([
                ('picking_id', '=', picking.id),
            ])

    def action_arc_dhl_view_bookings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'DHL Bookings',
            'res_model': 'arc.dhl.booking',
            'domain': [('picking_id', '=', self.id)],
            'view_mode': 'list,form',
            'target': 'current',
        }

    def action_arc_dhl_view_labels(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'DHL Labels',
            'res_model': 'arc.dhl.label',
            'domain': [('picking_id', '=', self.id)],
            'view_mode': 'list,form',
            'target': 'current',
        }
