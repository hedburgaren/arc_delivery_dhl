# -*- coding: utf-8 -*-
"""Rules that map a package structure to a DHL product."""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ArcDhlProductRule(models.Model):
    _name = 'arc.dhl.product.rule'
    _description = 'DHL product selection rule'
    _order = 'sequence, id'

    name = fields.Char(string='Name', required=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(string='Active', default=True)

    is_domestic = fields.Boolean(
        string='Domestic',
        default=True,
        help='Matches shipments where the receiver country is SE.',
    )
    is_international = fields.Boolean(
        string='International',
        default=False,
        help='Matches shipments where the receiver country is not SE.',
    )

    min_length_cm = fields.Integer(string='Min length (cm)', default=0)
    max_length_cm = fields.Integer(string='Max length (cm)', default=0)
    min_weight_kg = fields.Float(string='Min weight (kg)', default=0.0)
    max_weight_kg = fields.Float(string='Max weight (kg)', default=0.0)
    min_package_count = fields.Integer(string='Min packages', default=1)
    max_package_count = fields.Integer(string='Max packages', default=0)

    product_id = fields.Many2one(
        'arc.dhl.product',
        string='DHL product',
        required=True,
        ondelete='restrict',
    )
    note = fields.Text(string='Note', translate=True)

    _sql_constraints = [
        ('check_length', 'CHECK(min_length_cm <= max_length_cm OR max_length_cm = 0)',
         'Max length must be greater than or equal to min length.'),
        ('check_weight', 'CHECK(min_weight_kg <= max_weight_kg OR max_weight_kg = 0)',
         'Max weight must be greater than or equal to min weight.'),
        ('check_count', 'CHECK(min_package_count <= max_package_count OR max_package_count = 0)',
         'Max package count must be greater than or equal to min package count.'),
    ]

    @api.constrains('is_domestic', 'is_international')
    def _check_scope(self):
        for rule in self:
            if not rule.is_domestic and not rule.is_international:
                raise ValidationError(_(
                    'A rule must match domestic, international, or both.'
                ))

    def matches(self, country_code, max_length_cm, total_weight_kg, package_count):
        """Return True if this rule matches the shipment profile."""
        self.ensure_one()
        is_domestic = country_code == 'SE'
        if is_domestic and not self.is_domestic:
            return False
        if not is_domestic and not self.is_international:
            return False
        if self.min_length_cm and max_length_cm < self.min_length_cm:
            return False
        if self.max_length_cm and max_length_cm > self.max_length_cm:
            return False
        if self.min_weight_kg and total_weight_kg < self.min_weight_kg:
            return False
        if self.max_weight_kg and total_weight_kg > self.max_weight_kg:
            return False
        if self.min_package_count and package_count < self.min_package_count:
            return False
        if self.max_package_count and package_count > self.max_package_count:
            return False
        return True
