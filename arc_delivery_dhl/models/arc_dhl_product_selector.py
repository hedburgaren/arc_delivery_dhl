# -*- coding: utf-8 -*-
"""Helper that selects a DHL product from a confirmed packing proposal."""
from odoo import _, api, models
from odoo.exceptions import UserError


class ArcDhlProductSelector(models.AbstractModel):
    _name = 'arc.dhl.product.selector'
    _description = 'DHL product selector'

    @api.model
    def select_for_picking(self, picking):
        """Return the first matching arc.dhl.product for a picking.

        Reads the confirmed arc.package.proposal on the related sale order.
        Falls back to native stock.quant.package records if no proposal exists.
        Raises UserError if no rule matches.
        """
        sale_order = picking.sale_id
        if not sale_order:
            raise UserError(_(
                'Cannot select a DHL product for a picking with no sales order.'
            ))

        packages = self._collect_packages(sale_order)
        if not packages:
            raise UserError(_(
                'No packages found to select a DHL product. Create a packing '
                'proposal first.'
            ))

        country_code = self._receiver_country_code(sale_order)
        return self.select_from_packages(packages, country_code)

    @api.model
    def select_for_order(self, sale_order):
        """Return the first matching arc.dhl.product for a sales order."""
        packages = self._collect_packages(sale_order)
        if not packages:
            return False

        country_code = self._receiver_country_code(sale_order)
        return self.select_from_packages(packages, country_code, silent=True)

    @api.model
    def select_from_packages(self, packages, country_code, silent=False):
        """Return the first matching arc.dhl.product for a package list.

        :param packages: list of dicts with keys length_cm, width_cm,
                         height_cm, weight_kg.
        :param country_code: two-letter receiver country code.
        :param silent: if True, return False instead of raising when no rule
                       matches.
        """
        if not packages:
            if silent:
                return False
            raise UserError(_(
                'No packages found to select a DHL product.'
            ))

        country_code = (country_code or 'SE').upper()
        max_length_cm = max(p['length_cm'] for p in packages)
        total_weight_kg = sum(p['weight_kg'] for p in packages)
        package_count = len(packages)

        rules = self.env['arc.dhl.product.rule'].search([
            ('active', '=', True),
        ], order='sequence')
        for rule in rules:
            if rule.matches(country_code, max_length_cm, total_weight_kg, package_count):
                return rule.product_id

        if silent:
            return False
        raise UserError(_(
            'No DHL product rule matches the shipment: country %(country)s, '
            'max length %(length)s cm, weight %(weight)s kg, packages %(count)s.',
            country=country_code,
            length=max_length_cm,
            weight=round(total_weight_kg, 2),
            count=package_count,
        ))

    @api.model
    def _receiver_country_code(self, sale_order):
        partner = sale_order.partner_shipping_id or sale_order.partner_id
        return (partner.country_id.code or 'SE').upper()

    # SEC-C 136: one shared package collector -----------------------------
    #
    # Booking, product selection and price quoting each used to carry a copy
    # of this logic with slightly different state filters and dict schemas,
    # so the same order could weigh differently per path. All paths now use
    # these methods: the newest draft or confirmed proposal, or the native
    # packages, always in the same cm/kg schema with stackable.

    @api.model
    def collect_packages_for_order(self, sale_order):
        """Collect packages (cm/kg) for a sale order.

        Prefers the newest draft or confirmed ``arc.package.proposal``,
        falls back to the native packages on the order's delivery lines.
        """
        proposal = self.env['arc.package.proposal'].search([
            ('sale_order_id', '=', sale_order.id),
            ('state', 'in', ('draft', 'confirmed')),
        ], limit=1, order='create_date desc')
        if proposal:
            return self._packages_from_proposal(proposal)

        return [
            self._package_from_native(package)
            for package in sale_order.order_line.mapped(
                'move_ids.move_line_ids.result_package_id')
        ]

    @api.model
    def collect_packages_for_picking(self, picking):
        """Collect packages (cm/kg) for a picking.

        Same rules as :meth:`collect_packages_for_order`, with the native
        packages read from the picking's move lines.
        """
        sale_order = picking.sale_id
        if sale_order:
            proposal = self.env['arc.package.proposal'].search([
                ('sale_order_id', '=', sale_order.id),
                ('state', 'in', ('draft', 'confirmed')),
            ], limit=1, order='create_date desc')
            if proposal:
                return self._packages_from_proposal(proposal)

        return [
            self._package_from_native(package)
            for package in picking.move_line_ids.mapped('result_package_id')
        ]

    @api.model
    def _packages_from_proposal(self, proposal):
        """Expand a packing proposal into one dict per physical package."""
        packages = []
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

    @api.model
    def _package_from_native(self, package):
        """Read one native stock.quant.package record (cm/kg)."""
        pt = package.package_type_id
        return {
            'length_cm': (pt.length or 1) / 10.0,
            'width_cm': (pt.width or 1) / 10.0,
            'height_cm': (pt.height or 1) / 10.0,
            'weight_kg': package.weight or 1.0,
            'stackable': True,
        }

    @api.model
    def _collect_packages(self, sale_order):
        """Backwards-compatible alias for :meth:`collect_packages_for_order`."""
        return self.collect_packages_for_order(sale_order)
