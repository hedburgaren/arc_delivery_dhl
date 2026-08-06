# -*- coding: utf-8 -*-
"""Labels retrieved from DHL Print API."""
import base64
from odoo import _, api, fields, models


class ArcDhlLabel(models.Model):
    _name = 'arc.dhl.label'
    _description = 'DHL shipping label'
    _order = 'create_date desc'

    name = fields.Char(string='Filename', required=True)
    booking_id = fields.Many2one(
        'arc.dhl.booking',
        string='Booking',
        required=True,
        ondelete='cascade',
        index=True,
    )
    picking_id = fields.Many2one(
        'stock.picking',
        string='Picking',
        related='booking_id.picking_id',
        store=True,
        readonly=True,
    )
    tracking_number = fields.Char(string='Tracking number')
    label_data = fields.Binary(string='Label PDF', attachment=True)
    label_file = fields.Char(string='File reference')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            data = vals.get('label_data')
            if data and isinstance(data, str):
                # Accept Base64 strings from the API.
                vals['label_data'] = base64.b64encode(
                    base64.b64decode(data)
                ) if data else False
        records = super().create(vals_list)
        for record in records:
            if record.label_data:
                record._attach_to_picking()
        return records

    def _attach_to_picking(self):
        self.ensure_one()
        if not self.picking_id or not self.label_data:
            return
        self.env['ir.attachment'].sudo().create({
            'name': self.name,
            'res_model': 'stock.picking',
            'res_id': self.picking_id.id,
            'type': 'binary',
            'datas': self.label_data,
            'mimetype': 'application/pdf',
        })
