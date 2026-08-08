# -*- coding: utf-8 -*-
"""Tests for DHL request mixin environment and key selection."""
import os
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install', 'arc_dhl')
class TestArcDhlRequestMixin(TransactionCase):

    def test_sandbox_environment_uses_sandbox_key(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'arc_delivery_dhl.api_key', ''
        )
        self.env['ir.config_parameter'].sudo().set_param(
            'arc_delivery_dhl.force_environment', 'sandbox'
        )
        with patch.dict(os.environ, {'DHL_SANDBOX_API_KEY': 'sandbox-key'}, clear=False):
            with patch.dict(os.environ, {'DHL_API_KEY': 'prod-key'}, clear=False):
                key = self.env['arc.dhl.request.mixin']._arc_dhl_get_api_key()
        self.assertEqual(key, 'sandbox-key')

    def test_production_environment_uses_production_key(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'arc_delivery_dhl.api_key', ''
        )
        self.env['ir.config_parameter'].sudo().set_param(
            'arc_delivery_dhl.force_environment', 'production'
        )
        with patch.dict(os.environ, {'DHL_SANDBOX_API_KEY': 'sandbox-key'}, clear=False):
            with patch.dict(os.environ, {'DHL_API_KEY': 'prod-key'}, clear=False):
                key = self.env['arc.dhl.request.mixin']._arc_dhl_get_api_key()
        self.assertEqual(key, 'prod-key')

    def test_settings_key_overrides_environment(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'arc_delivery_dhl.api_key', 'settings-key'
        )
        with patch.dict(os.environ, {'DHL_SANDBOX_API_KEY': 'sandbox-key'}, clear=False):
            key = self.env['arc.dhl.request.mixin']._arc_dhl_get_api_key()
        self.assertEqual(key, 'settings-key')

    def test_missing_key_raises_user_error(self):
        from odoo.addons.arc_delivery_dhl.models import arc_dhl_request_mixin

        self.env['ir.config_parameter'].sudo().set_param(
            'arc_delivery_dhl.api_key', ''
        )
        self.env['ir.config_parameter'].sudo().set_param(
            'arc_delivery_dhl.force_environment', 'sandbox'
        )
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(
                arc_dhl_request_mixin, '_read_dotenv', return_value=''
            ):
                with self.assertRaises(UserError):
                    self.env['arc.dhl.request.mixin']._arc_dhl_get_api_key()

    @patch('requests.request')
    def test_api_farm_request_uses_client_key_header(self, mock_request):
        self.env['ir.config_parameter'].sudo().set_param(
            'arc_delivery_dhl.api_key', 'client-key-value'
        )
        mock_request.return_value.status_code = 200
        mock_request.return_value.ok = True
        mock_request.return_value.json.return_value = {'products': []}
        mock_request.return_value.text = ''

        self.env['arc.dhl.request.mixin']._arc_dhl_request(
            'get', '/products', params={'countryCode': 'SE'},
        )

        call_kwargs = mock_request.call_args.kwargs
        self.assertEqual(call_kwargs['headers']['client-key'], 'client-key-value')
        self.assertNotIn('Authorization', call_kwargs['headers'])
