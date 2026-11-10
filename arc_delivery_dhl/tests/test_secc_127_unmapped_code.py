# -*- coding: utf-8 -*-
"""SEC-C 127: an unmapped DHL product code fails closed, not with ValueError.

The payload builder raised a raw ValueError outside the API call's try block
when the selected product had no PriceQuote enum mapping (the old catch-all
SPECIAL rule, code 209, could trigger it). The quote request now reports it
as a failed quote like any other error, and the catch-all rule is gone.
"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'arc_dhl')
class TestSecC127UnmappedCode(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        param = cls.env['ir.config_parameter'].sudo()
        param.set_param('arc_delivery_dhl.api_key', 'test-api-key')
        param.set_param('arc_delivery_dhl.force_environment', 'sandbox')
        cls.dhl_product = cls.env.ref('arc_delivery_dhl.dhl_product_paket')
        cls.special_product = cls.env.ref('arc_delivery_dhl.dhl_product_special')

    def test_special_catchall_rule_is_not_active(self):
        # Fresh installs no longer get the rule at all; upgraded databases
        # keep the (noupdate) row but migration 18.0.1.5.1 deactivates it.
        rule = self.env.ref(
            'arc_delivery_dhl.dhl_product_rule_special',
            raise_if_not_found=False,
        )
        self.assertFalse(
            rule and rule.active,
            'The SPECIAL catch-all rule must not be active.',
        )

    @patch('requests.request')
    def test_unmapped_code_returns_error_dict(self, mock_request):
        quote = self.env['arc.dhl.price.quote'].create({
            'product_id': self.special_product.id,
            'partner_country_code': 'SE',
            'partner_zip': '11122',
            'package_json': (
                '[{"length": 50, "width": 30, "height": 10, "weight": 5}]'
            ),
        })
        result = quote.action_request_quote()
        self.assertFalse(result['success'])
        self.assertEqual(result['price'], 0.0)
        self.assertTrue(result['error_message'])
        self.assertEqual(quote.state, 'error')
        mock_request.assert_not_called()
