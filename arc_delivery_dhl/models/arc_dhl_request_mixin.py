# -*- coding: utf-8 -*-
"""Shared DHL API client utilities."""
import json
import logging
import os
from urllib.parse import urljoin

import requests


def _read_dotenv(key, module_path):
    """Read a key from a .env file next to the module root.

    This is used only as a fallback; ir.config_parameter is preferred.
    The .env file must never be committed.
    """
    env_path = os.path.join(module_path, '..', '.env')
    if not os.path.isfile(env_path):
        env_path = os.path.join(module_path, '.env')
    if not os.path.isfile(env_path):
        return ''
    try:
        with open(env_path, 'r', encoding='utf-8') as env_file:
            for line in env_file:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, _, v = line.partition('=')
                if k.strip() == key:
                    return v.strip().strip('"\'')
    except OSError:
        return ''
    return ''

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


DEFAULT_TIMEOUT = 30
SANDBOX_BASE_URL = 'https://test-api.freight-logistics.dhl.com'
PRODUCTION_BASE_URL = 'https://api.freight-logistics.dhl.com'


class ArcDhlRequestMixin(models.AbstractModel):
    _name = 'arc.dhl.request.mixin'
    _description = 'DHL API request mixin'

    @api.model
    def _arc_dhl_get_api_key(self):
        """Return the DHL API key from settings or environment.

        The key is never stored in versioned code. It is read from the
        ir.config_parameter record or, as a fallback, from the DHL_API_KEY
        environment variable.
        """
        key = self.env['ir.config_parameter'].sudo().get_param(
            'arc_delivery_dhl.api_key'
        )
        if key:
            return key
        key = os.environ.get('DHL_API_KEY', '').strip()
        if key:
            return key
        module_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        key = _read_dotenv('DHL_API_KEY', module_path)
        if key:
            return key
        raise UserError(_(
            'DHL API key is not configured. Set it in Settings > DHL Delivery '
            'or define the DHL_API_KEY environment variable.'
        ))

    @api.model
    def _arc_dhl_get_base_url(self):
        """Return the active API base URL."""
        param = self.env['ir.config_parameter'].sudo()
        force_env = param.get_param('arc_delivery_dhl.force_environment')
        if force_env == 'sandbox':
            return SANDBOX_BASE_URL
        if force_env == 'production':
            return PRODUCTION_BASE_URL
        # Default to sandbox unless the database is explicitly marked prod.
        is_prod = param.get_param('arc_delivery_dhl.is_production')
        return PRODUCTION_BASE_URL if is_prod else SANDBOX_BASE_URL

    @api.model
    def _arc_dhl_request(
        self,
        method,
        endpoint,
        payload=None,
        params=None,
        headers=None,
        timeout=DEFAULT_TIMEOUT,
    ):
        """Execute a DHL API request and return the parsed JSON response."""
        base_url = self._arc_dhl_get_base_url()
        url = urljoin(base_url + '/', endpoint.lstrip('/'))
        api_key = self._arc_dhl_get_api_key()

        request_headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': api_key,
        }
        if headers:
            request_headers.update(headers)

        data = json.dumps(payload) if payload is not None else None
        _logger.info(
            'DHL API %s %s (payload keys: %s)',
            method.upper(),
            url,
            sorted(payload.keys()) if isinstance(payload, dict) else 'n/a',
        )
        try:
            response = requests.request(
                method=method.upper(),
                url=url,
                data=data,
                params=params,
                headers=request_headers,
                timeout=timeout,
            )
        except requests.exceptions.Timeout as exc:
            _logger.error('DHL API timeout: %s', exc)
            raise UserError(_(
                'DHL API request timed out. Try again or use the manual '
                'fallback and paste the tracking reference into the picking.'
            )) from exc
        except requests.exceptions.RequestException as exc:
            _logger.error('DHL API request failed: %s', exc)
            raise UserError(_(
                'DHL API request failed. Check the network and try again, or '
                'use the manual fallback and paste the tracking reference.'
            )) from exc

        try:
            body = response.json()
        except ValueError:
            body = {'raw': response.text}

        if not response.ok:
            _logger.error(
                'DHL API error %s: %s',
                response.status_code,
                body,
            )
            raise UserError(_(
                'DHL API returned error %(status)s: %(message)s',
                status=response.status_code,
                message=body.get('message') or body.get('raw') or response.reason,
            ))

        return body
