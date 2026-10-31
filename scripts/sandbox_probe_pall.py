# Prov i DHL-sandboxen: vad betyder PackageType 701 och 702 för DHL PALL (210)?
# Körs som sandbox_acceptance.py (odoo shell, engångscontainer), rullas tillbaka.
import json

mixin = env['arc.dhl.request.mixin']
assert mixin._arc_dhl_get_environment() == 'sandbox'
company = env.company

def party(t, name, street, zipc, city, cc):
    return {'type': t, 'id': '137399' if t == 'Consignor' else None, 'name': name,
            'contactName': name,
            'address': {'street': street, 'cityName': city, 'postalCode': zipc, 'countryCode': cc},
            'phone': '+46 13 000 00 00', 'email': 'test@example.com'}

for ptype in ('701', '702'):
    piece = {'numberOfPieces': 1, 'weight': 300, 'volume': 0.96, 'width': 80,
             'height': 100, 'length': 120, 'stackable': False, 'packageType': ptype}
    book = {'productCode': '210', 'payerCode': {'code': '1'}, 'totalNumberOfPieces': 1,
            'totalWeight': 300, 'totalVolume': 0.96, 'totalLoadingMeters': 0,
            'totalPalletPlaces': 1, 'references': [{'qualifier': 'CU', 'value': 'PROBE'}],
            'parties': [party('Consignor', company.name, company.street or '', company.zip or '',
                              company.city or '', 'SE'),
                        party('Consignee', 'Sandboxtest AB', 'Kungsgatan 1', '41101', 'Göteborg', 'SE')],
            'pieces': [piece]}
    try:
        r = mixin._arc_dhl_request('post',
            '/transportinstructionapi/v1/transportinstruction/sendtransportinstruction', payload=book)
        ti = r.get('transportInstruction') or r
        print('BOOK', ptype, 'OK', json.dumps(ti.get('pieces'), ensure_ascii=False)[:800])
    except Exception as exc:
        print('BOOK', ptype, 'ERR', exc)
    q = {'shipment': {'dhlProductCode': 'DHLPall', 'totalNumberOfPieces': 1, 'totalWeight': 300,
         'totalVolume': 0.96, 'totalLoadingMeters': 0, 'totalPalletPlaces': 1,
         'numberOfEURPallets': 0, 'numberOfFullPallets': None, 'numberOfHalfPallets': None,
         'payerCode': '1',
         'piece': [{'numberOfPieces': 1, 'weight': 300, 'volume': 0.96, 'loadingMeters': 0,
                    'palletPlaces': 1, 'width': 80, 'height': 100, 'length': 120,
                    'stackable': False, 'packageType': ptype}],
         'parties': [{'id': None, 'type': 'Consignor', 'address': {'postalCode': company.zip or '',
                      'cityName': company.city or '', 'countryCode': 'SE'}},
                     {'id': None, 'type': 'Consignee', 'address': {'postalCode': '41101',
                      'cityName': '', 'countryCode': 'SE'}}]},
         'ownSurCharge': {'percentage': 0, 'value': 0}}
    try:
        r = mixin._arc_dhl_request('post', '/pricequoteapi/v1/pricequote/quoteforgrossprice', payload=q)
        print('QUOTE', ptype, json.dumps(r, ensure_ascii=False)[:900])
    except Exception as exc:
        print('QUOTE', ptype, 'ERR', exc)
env.cr.rollback()
