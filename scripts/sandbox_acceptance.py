# DHL Freight Sweden, sandboxtest före Implementation Request (kort 88).
#
# Körs i odoo shell mot staging.plastshop.se (sandboxläge). Provar modulens
# egna vägar för alla tre API:er som används i produktion: prisförfrågan
# (get_quote_for_packages), bokning (action_book_shipment) och fraktsedel
# (anropas av bokningen). Allt sker i en transaktion som rullas tillbaka:
# staging lämnas orörd, bara utskrifter och etikett-PDF:er sparas.
#
#   docker exec -i plastshop-staging-web odoo shell -c /etc/odoo/odoo.conf \
#       -d staging.plastshop.se --no-http < scripts/sandbox_acceptance.py
import base64
import json
import os

OUT = '/var/log/odoo/dhl-sandbox-test'
os.makedirs(OUT, exist_ok=True)

ICP = env['ir.config_parameter'].sudo()
mixin = env['arc.dhl.request.mixin']
assert mixin._arc_dhl_get_environment() == 'sandbox', 'staging är inte i sandboxläge'
ICP.set_param('arc_delivery_dhl.customer_number', '137399')
ICP.set_param('arc_delivery_dhl.quote_cache_hours', '0')

Product = env['arc.dhl.product']
Booking = env['arc.dhl.booking']
carrier = env['delivery.carrier'].search([('delivery_type', '=', 'dhl_freight_se')], limit=1)
out_type = env['stock.picking.type'].search([('code', '=', 'outgoing')], limit=1)
countries = {c: env['res.country'].search([('code', '=', c)], limit=1) for c in ('SE', 'NO', 'FI')}

# Typiska PlastShop-sändningar, en per produkt som reglerna kan välja.
CASES = [
    ('102', 'SE', '11122', 'Stockholm', 'Drottninggatan 1',
     [dict(length_cm=120, width_cm=30, height_cm=10, weight_kg=8)]),
    ('211', 'SE', '21115', 'Malmö', 'Stortorget 1',
     [dict(length_cm=300, width_cm=125, height_cm=10, weight_kg=90)]),
    ('210', 'SE', '41101', 'Göteborg', 'Kungsgatan 1',
     [dict(length_cm=120, width_cm=80, height_cm=100, weight_kg=300)]),
    ('212', 'SE', '90326', 'Umeå', 'Storgatan 1',
     [dict(length_cm=300, width_cm=125, height_cm=20, weight_kg=400)] * 3),
    ('202', 'NO', '0150', 'Oslo', 'Karl Johans gate 1',
     [dict(length_cm=120, width_cm=80, height_cm=100, weight_kg=300)]),
    ('233', 'FI', '00100', 'Helsinki', 'Mannerheimintie 1',
     [dict(length_cm=120, width_cm=80, height_cm=100, weight_kg=300)]),
]

orig_collect = type(Booking)._arc_dhl_collect_packages
results = []
for code, cc, zipc, city, street, pkgs in CASES:
    product = Product.search([('code', '=', code)], limit=1)
    row = {'product': code, 'dest': f'{cc} {zipc} {city}', 'pieces': len(pkgs)}
    # 1. Prisförfrågan
    q = env['arc.dhl.price.quote'].get_quote_for_packages(
        pkgs, {'country_code': cc, 'zip': zipc}, product=product)
    row['quote_ok'] = bool(q.get('success'))
    row['quote_price'] = q.get('price')
    row['quote_error'] = q.get('error_message')
    # 2. Bokning och 3. fraktsedel
    partner = env['res.partner'].create({
        'name': f'Sandboxtest {code} AB', 'street': street, 'zip': zipc,
        'city': city, 'country_id': countries[cc].id,
        'phone': '+46 13 000 00 00', 'email': 'test@example.com',
    })
    picking = env['stock.picking'].create({
        'picking_type_id': out_type.id, 'partner_id': partner.id,
    })
    booking = Booking.create({
        'carrier_id': carrier.id, 'picking_id': picking.id, 'product_id': product.id,
    })
    type(Booking)._arc_dhl_collect_packages = lambda self, p, _pk=pkgs: list(_pk)
    try:
        res = booking.action_book_shipment()
    except Exception as exc:  # valideringsfel före anropet
        res = {'success': False, 'error_message': str(exc)}
    finally:
        type(Booking)._arc_dhl_collect_packages = orig_collect
    row['book_ok'] = bool(res.get('success'))
    row['book_error'] = res.get('error_message') or booking.error_message
    row['dhl_shipment_id'] = booking.dhl_booking_id
    row['tracking'] = booking.dhl_tracking_numbers
    row['labels'] = len(booking.label_ids)
    for i, lab in enumerate(booking.label_ids, 1):
        data = lab.label_data
        raw = base64.b64decode(data) if isinstance(data, (bytes, str)) else b''
        fn = f'{OUT}/{code}-{cc}-label-{i}.pdf'
        with open(fn, 'wb') as fh:
            fh.write(raw)
        row.setdefault('label_files', []).append(fn)
        row.setdefault('label_is_pdf', []).append(raw[:4] == b'%PDF')
    with open(f'{OUT}/{code}-{cc}-booking-request.json', 'w') as fh:
        fh.write(booking.api_request or '')
    with open(f'{OUT}/{code}-{cc}-booking-response.json', 'w') as fh:
        fh.write(booking.api_response or '')
    results.append(row)

env.cr.rollback()
with open(f'{OUT}/summary.json', 'w') as fh:
    json.dump(results, fh, ensure_ascii=False, indent=2)
print('SUMMARY')
for r in results:
    print(json.dumps(r, ensure_ascii=False))
