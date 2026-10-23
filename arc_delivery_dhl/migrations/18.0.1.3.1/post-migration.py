# -*- coding: utf-8 -*-
"""18.0.1.3.1: task 191, inställningssteg 1: 1 död nyckel bort.

Verifikationen (brand-repot, audits/2026-10-18-settings/task191-verifikation.md)
bevisade att ingen kod läser arc_delivery_dhl.request_timeout: fröet i
data/arc_dhl_parameter_data.xml (30) låg där utan konsument, och requestens
timeout är DEFAULT_TIMEOUT i models/arc_dhl_request_mixin.py. Fröet är borttaget
i samma version. Den här post-migrationen exporterar först nyckel och värde
till fil (old-value-guard) och tar sedan bort raden ur ir_config_parameter
(frö-raderna är noupdate=1, så de försvinner inte av sig själva vid -u).
Exporten hamnar i /var/log/odoo/task191-dead-settings/ (inne i containern; på
värden under loggkatalogen). Misslyckas exporten avbryts migrationen innan
något raderas.
"""
import json
import logging
import os
import time

_logger = logging.getLogger(__name__)

DEAD_KEYS = [
    'arc_delivery_dhl.request_timeout',
]

EXPORT_DIR_CANDIDATES = ('/var/log/odoo', os.environ.get('HOME') or '/tmp')


def _export_dir():
    for candidate in EXPORT_DIR_CANDIDATES:
        path = os.path.join(candidate, 'task191-dead-settings')
        try:
            os.makedirs(path, exist_ok=True)
            probe = os.path.join(path, '.probe')
            with open(probe, 'w') as fh:
                fh.write('')
            os.remove(probe)
            return path
        except OSError:
            continue
    raise RuntimeError(
        'task 191 old-value-guard: ingen skrivbar katalog för exporten '
        '(provade %s); nycklarna lämnas kvar' % (EXPORT_DIR_CANDIDATES,))


def migrate(cr, version):
    if not version:
        return
    export_dir = _export_dir()
    cr.execute(
        "SELECT key, value FROM ir_config_parameter WHERE key = ANY(%s)",
        (list(DEAD_KEYS),))
    rows = cr.fetchall()
    stamp = time.strftime('%Y%m%d-%H%M%S')
    export_path = os.path.join(
        export_dir, 'arc_delivery_dhl-%s.json' % stamp)
    payload = {
        'module': 'arc_delivery_dhl',
        'version': '18.0.1.3.1',
        'exported_at': stamp,
        'keys': {key: value for key, value in rows},
        'missing': sorted(set(DEAD_KEYS) - {key for key, _ in rows}),
    }
    with open(export_path, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, indent=1, sort_keys=True, ensure_ascii=False)
    if not os.path.exists(export_path) or not os.path.getsize(export_path):
        raise RuntimeError(
            'task 191 old-value-guard: exporten till %s misslyckades' %
            export_path)
    if rows:
        cr.execute(
            "DELETE FROM ir_config_parameter WHERE key = ANY(%s)",
            (list(DEAD_KEYS),))
    _logger.info(
        'arc_delivery_dhl 18.0.1.3.1: %d döda inställningsnycklar '
        'exporterade till %s och borttagna ur ir_config_parameter '
        '(%d saknades sedan tidigare)',
        len(rows), export_path, len(payload['missing']))
