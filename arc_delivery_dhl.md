# Överlämning: Frakt- och kapkedjan i PlastShop

**Till:** Kimi Code
**Från:** Claude Cowork
**Datum:** 2026-08-05
**Moduler:** `arc_industrial_ops` (ändring), `arc_delivery_dhl` (ny)
**Odoo:** 18.0 CE, container `plastshop`, port 8074, databas `utv.plastshop.se`

---

# DEL 1 — Sammanfattning (svenska)

## Vad det handlar om

PlastShop ska kunna boka frakt hos DHL Freight Sweden direkt från Odoo. Det låter som en integrationsuppgift, men utredningen visade att integrationen är den minsta delen. Två underliggande problem måste lösas först, annars går det inte att ställa en giltig fråga till DHL överhuvudtaget.

## Problem 1: Odoo skickar inga mått

`product.template` i Odoo 18 har bara `weight` och `volume`. Det finns inga fält för längd, bredd och höjd. Fraktmotorn hämtar dimensioner uteslutande från kollityp (`stock.package.type`), aldrig från produkten.

Följden: om ingen packar godset i Odoo bygger systemet ett syntetiskt kolli av totalvikten **utan mått** och skickar det till transportören. En tre meter lång skiva bokas då som ett vanligt paket. Det gäller alla ordrar, även de utan kapning.

Det som saknas är alltså inte fraktdata per artikel. Det som saknas är översättningen från "vad kunden köpte" till "vilka kollin lämnar huset". DHL har inget produktregister och behöver aldrig känna till en enda artikel. De behöver en kollilista.

## Problem 2: CTS är wizard-först

Kapberäkningen är en wizard. Den öppnas, räknar, skriver orderrader och dör. Bitlistan från VisualCutter finns inte kvar någonstans.

Två konsekvenser:

1. Man måste börja med kapningen. Wizarden kan skapa rader men aldrig knyta an till en rad som redan finns. Ringer kunden in en komplettering på en befintlig order går det inte.
2. Kollibildaren har ingen bitlista att läsa. Fraktberäkningen på kapade produkter blir omöjlig.

Ordningstvånget är alltså inte en separat bugg utan en direkt följd av att beräkningen inte är ett objekt.

## Vad som ska byggas, i ordning

**WP1** gör kapberäkningen till en persisterad post kopplad till orderraden. Wizarden blir bara redigeraren. Det löser ordningstvånget och ger bitlistan.

**WP2** bygger kollibildaren. Den läser alla orderrader oavsett typ och föreslår en kollistruktur med mått, vikt och stapelbarhet.

**WP3** bygger `arc_delivery_dhl`, en `delivery.carrier`-koppling mot DHL Freight Swedens API Farm.

Ordningen är inte kosmetisk. WP3 läser WP2:s output, WP2 läser WP1:s bitlista. Byggs de i fel ordning får vi en integration som fungerar för lagervara men går sönder på kapade produkter, alltså den del av sortimentet som är vår faktiska affär.

## Vad som INTE ingår

Prisformeln i CTS, VisualCutters SVG-rendering och guillotine-optimeringen ska inte röras. De fungerar. WP1 handlar om persistens och koppling, ingenting annat.

## Parallellt spår som inte är Kimis jobb

DHL-avtalet, långgodsfrågan över tre meter, prislistan med långgodstabellerna, registrering i sandbox och implementation request. Det är kalendertid vi inte styr över och DHL:s godkännandesteg har ingen publicerad ledtid. Startas separat, direkt.

---

# PART 2 — Specification (English)

## Context

PlastShop Sweden sells industrial plastics B2B: sheets, rods, tubes, profiles, cut to size on request. Odoo 18 CE, self-hosted, running the ARC Industrial Suite (nine custom modules). Read the `arc-industrial-suite` reference before starting.

The business needs to book freight with DHL Freight Sweden from inside Odoo. Three work packages, strictly sequential.

This specification defines **goals and acceptance criteria**. Data model design is yours. Follow existing ARC conventions rather than inventing new ones.

## Prerequisites

Read before writing any code:

| Source | Why |
|---|---|
| ARC Industrial hub, Notion `33474749d02280a6bec6e6d05711bc92` | Architecture, conventions |
| README ops, Notion `33474749d02281e6becffbe98c5ee076` | Current CTS implementation |
| INVENTORY ops, Notion `33474749d022816385fadf0bf8c6b2ac` | Existing models, avoid collisions |
| Standing instructions, Notion `33774749d02281e08689c3ce71b24735` | House rules |
| Language rules, Notion `32a74749d022819a8f5be7fa3f804219` | Terminology |
| Odoo UI glossary, Notion `33674749d02281868a80f5cbb02c3e71` | Swedish UI terms |

Existing models you will interact with: `arc.cts.wizard`, `arc.cts.material`, `arc.cts.dimension`, `arc.cts.opticutter`, `arc.cts.shipping.rule`, `arc.cts.packaging.rule`, `arc.tech.spec` and the TSB hierarchy.

Use the Notion MCP, not the REST API.

## Language and i18n rules — mandatory

This is a hard requirement and previous work has failed on it.

- **All code is English.** Model names, field names, method names, variable names, class names, comments, docstrings, commit messages, log messages, XML ids, file names. No Swedish anywhere in source.
- **All user-facing text must be translatable.** Wrap every Python string shown to a user in `_()`. Every field needs an English `string=` and `help=`. Every view label, button, menu item and selection value must be a translatable attribute, never a hardcoded literal outside the translation system.
- **No Swedish in `.xml` or `.py`.** Swedish belongs only in `i18n/sv.po`.
- **Generate a complete `.pot`** and a Swedish `.po` for every new user-facing string. Do not leave untranslated strings behind.
- Error messages must state the fix, not just the problem.

Rationale: translations have previously been overwritten wholesale because Swedish was hardcoded into source. Keeping source English and translations external makes that impossible.

## Coding conventions

- Odoo 18: `<list>` not `<tree>` in views.
- `_inherit` chains follow the existing ARC pattern. Soft dependencies via try/except imports. No new hard arc-to-arc dependencies beyond the existing `ops → core`.
- Prefix new models `arc.` and new fields on native models `arc_`.
- Security: `ir.model.access.csv` for every new model. Record rules where multi-company matters.
- Never expose supplier names in anything customer-facing. See the forbidden list in the ARC reference. This is a legal matter, not a preference.

## Deployment and verification

- Deploy by adding `-u <module>` to the docker-compose command, restart, verify the log, then **remove the flag**.
- Odoo RPC always `http://127.0.0.1:8074`. Never `https://utv.plastshop.se`, nginx blocks XML-RPC.
- Code path `/srv/odoo/plastshop/addons/`.
- Every work package must install cleanly on a database that already has the current ARC modules, with no WSOD and no traceback in the log.

---

## WP1 — Make the cutting calculation persistent

### Goal

A cutting job becomes a stored record linked to a sale order line. The wizard is demoted to being an editor for that record. Cutting can be added to, or edited on, any order line at any time, in any order relative to other lines.

### Why

Today the wizard is the only place the calculation exists. It creates order lines and discards everything else, including the piece list VisualCutter produced. That forces the user to start every order with the cutting step and makes later changes impossible. It also leaves WP2 with nothing to read.

### Acceptance criteria

1. A cutting job can be created from an existing sale order line, on an order that already contains other lines, without creating a new order.
2. An existing cutting job can be reopened, edited and recalculated. The linked order line updates to match.
3. The piece list produced by the optimiser persists after the wizard closes and is queryable from the order line.
4. VisualCutter renders from the stored record. Closing and reopening the view produces the identical layout.
5. For identical inputs, the calculated price is byte-identical to the current implementation. Write a regression test that proves this before refactoring.
6. Order line structure is unchanged: material on a discountable line, cutting fee on a line that can never be discounted.
7. State gates behave as follows. Free editing until the delivery is done. A warning on a confirmed order. A hard block once cutting has started. Follow the existing Cases stage pattern rather than inventing a new state machine.
8. An explicit field records whether the customer receives the offcut. This affects downstream weight and dimensions and must be set, not assumed.
9. The stored record renders a human-readable cutting instruction onto the order confirmation and the pick list. Generated text, not hand-typed. The warehouse and the customer must see at least what they see today.
10. Deleting an order line cleans up its cutting job. No orphans.

### Out of scope

Do not modify the price formula, the guillotine optimiser, the SVG rendering logic or the existing report templates. If a change to any of these appears necessary, stop and report rather than proceeding.

---

## WP2 — Packing planner

### Goal

A function that takes a set of order lines or a delivery and returns a proposed package structure: how many packages, of what type, with what outer dimensions, weight and stackability.

### Why

Freight is priced on packages, never on products. There is no one-to-one relation between an order line and a package and there never was. Five sheets on one order may ship as one stacked unit or as three. This translation layer is the only thing that makes a valid question to DHL possible, and it is equally required for orders that contain no cutting at all.

### Required inputs, and where they come from

Per product, three properties, all sourced from TSB as the authoritative source. Do not create a parallel data path:

- Geometry class (sheet, rod, tube, profile, loose goods)
- Nominal dimensions
- Density

Weight must be **calculated** from density and volume. Do not use `product.weight`, which holds the full-sheet weight and is wrong for any cut piece.

### Acceptance criteria

1. Produces a valid package structure for an order containing only stock items and no cutting. This case must work first, it is currently broken and is the most common order type.
2. Produces a valid package structure for the mixed reference order: two sheets of material A, three sheets of material B, one sheet cut into six pieces, and one length of loose goods, all on one order.
3. Chargeable weight is calculated as the greatest of actual weight, volumetric weight at 1 m³ = 280 kg, and loading-metre weight at 1 loading metre = 1950 kg. These figures are from DHL's domestic terms, cited below.
4. Every package carries a stackability flag. It materially changes the price and must be explicit, never inferred silently.
5. Length limits are validated and violations are surfaced **before** order confirmation, not at the loading dock. See the limits table below.
6. The offcut flag from WP1 changes the resulting weight and dimensions.
7. The proposal is editable by a human at the order stage and again at the packing stage. Rules get most of the way, the eye at the packing bench does the rest.
8. At packing, the confirmed structure produces real `stock.quant.package` records with correct `stock.package.type`. This is what the carrier connector reads.
9. Packages can be recalculated when order lines change. Recalculation must not silently overwrite a structure a human has already confirmed.
10. Rules live in data, not in code, so they can be tuned without a deploy. Extend the existing `arc.cts.packaging.rule` concept rather than creating a second parallel rule engine.

### Out of scope

Route optimisation, carrier selection logic, anything that talks to an external API. WP2 produces a package structure and stops.

---

## WP3 — `arc_delivery_dhl`

### Goal

A new module implementing a `delivery.carrier` provider for DHL Freight Sweden, using the Swedish API Farm.

### Critical prerequisite reading

DHL Freight Sweden does **not** use the DHL Freight APIs published on developer.dhl.com. DHL's own product manual states that Sweden has different documentation and services, and the global manual is titled "DHL Freight Global (excl. Sweden)". Building against the wrong platform is the single most likely way to waste weeks on this task.

Use the Swedish API Farm for everything except tracking. Use developer.dhl.com only for Shipment Tracking Unified.

### Odoo framework contract

This part is fixed by Odoo and is not a design choice. Inherit `delivery.carrier`, extend the `delivery_type` selection with an `ondelete` mapping, and implement the provider methods Odoo dispatches by name: rate shipment, send shipping, get tracking link, cancel shipment, plus the default custom package code helper. Depend on `stock_delivery`.

Study OCA `delivery_schenker` on branch 18.0 as the structural reference. It is the only OCA 18.0 module that models palletised land freight rather than parcels, which is the right shape for this problem. Do not copy code from any OPL-1 licensed module.

Consider OCA `delivery_carrier_shipping_label` for per-package label identity. Odoo's native mechanism identifies labels by attachment name prefix only, which is insufficient when one shipment has several packages with different labels.

### Acceptance criteria

1. Sandbox and production are separate and enforced. The `prod_environment` flag is honoured. The development database must be structurally incapable of reaching the production endpoint.
2. Booking and label retrieval are two separate calls. The booking call returns an identifier, the print call returns documents. Do not assume the label arrives with the booking response.
3. Labels are returned as Base64-encoded PDF. There is no documented ZPL support. Build for PDF and confirm with DHL before anyone buys printers.
4. Labels are attached to the picking using Odoo's naming conventions so that return labels, portal download and the tracking widgets all work.
5. Multiple packages produce multiple labels, correctly associated with their package.
6. Multiple tracking numbers per delivery are supported.
7. Price quotes are cached. Assume a quota of 250 calls per day until DHL confirms otherwise. Live quoting on every cart update will exhaust the quota before lunch.
8. A manual fallback exists from day one. When the API is unavailable, a user must be able to book in myDHLFreight and paste the tracking reference into Odoo without anything breaking.
9. A freight-stale flag is set when order lines change after the delivery line was added. Odoo does not do this and without it we will invoice the wrong freight without noticing.
10. Errors are logged with enough context to reproduce them, and surfaced to the user in language that states the fix.

### Suggested internal sequencing

Ship value early rather than building everything before anything works.

| Stage | Content |
|---|---|
| 1 | Booking and label. Manual product selection. No price quoting. |
| 2 | Package structure from WP2 feeding the booking payload. |
| 3 | Price quote, first in the back office for comparison against the CTS estimate, then exposed. |
| 4 | Pickup requests, return labels, CMR. |
| 5 | Invoice reconciliation. |

### Out of scope

DHL Express. Any other carrier. Do design `delivery_type` so additional carriers can be added later without restructuring.

---

## DHL reference data

These figures are verified against DHL's published documents and must be encoded, not guessed.

### Products, domestic Sweden

| Product | Code | Limits | Long goods |
|---|---|---|---|
| DHL PAKET | 102 | 35 kg per piece, 150 kg per shipment, 150×50×50 cm | No |
| DHL PALL | 210 | 800 kg per pallet, 120×80×220 cm | Explicitly no |
| DHL STYCKE | 211 | 1000 kg per piece, 2500 kg per shipment | Yes |
| DHL PARTI | 212 | minimum 1000 kg chargeable | Yes |
| DHL SPECIAL | 209 | separate agreement, 150 m³ | Yes |

### Products, international road

| Product | Code | Length limit |
|---|---|---|
| DHL Road Freight Standard (ex EuroConnect) | 202 | 299 cm |
| DHL Road Freight Priority (ex EURAPID) | 233 | 299 cm |
| DHL Road Freight Direct (ex Euroline) | 205 | direct and full loads |

### Length rules

Domestic DHL STYCKE: maximum length 599 cm for a piece under 50 kg, 299 cm for a piece of 50 kg or more.

International: 299 cm regardless of weight. A three metre sheet has no standard international groupage path. Flag it, do not silently book it.

### Chargeable weight

Chargeable weight is the greater of actual weight and volumetric weight.

- 1 cubic metre = 280 kg
- 1 loading metre = 1950 kg
- DHL PALL is priced on the count of full and half EUR pallets, not on weight at all
- Pieces 3.00 to 5.99 m under 50 kg use a separate table in DHL STYCKE
- Pieces 3.00 to 5.99 m from 50 kg, and anything 6.00 to 12.00 m regardless of weight, use a separate table in DHL PARTI

The long-goods tables are in the price list, not in the terms. Chrille supplies them.

### Label requirements

- Code 128 as symbology, GS1-128 where SSCC data is carried
- Licence plate is an SSCC, 18 to 20 characters, prefix `JD00` or `JD01`
- Label width 95 to 110 mm, preferred length 148 mm (A6) to 162.4 mm
- x-dimension 0.33 to 0.51 mm, barcode height at least 25 mm
- Print quality at least Grade B per EN 1635
- If a correct routing barcode cannot be guaranteed, it must be omitted. A wrong routing barcode is worse than none, because the terminal will misroute the goods.

### Cost

All DHL Group APIs are free of charge except the Duty and Tax Calculator. There are no per-call fees. Quotas apply and are the real constraint.

---

## Links

### Swedish API Farm, the platform to build against

- [DHL Dashboard, Swedish developer portal](https://dhlpaket.se/dashboard/)
- [API Farm overview](https://dhlpaket.se/dashboard/services/api-farm/)
- [API list](https://dhlpaket.se/dashboard/services/api-farm/api-overview/)
- [Getting started](https://dhlpaket.se/dashboard/services/api-farm/get-started/)
- [Integration guide](https://dhlpaket.se/dashboard/services/api-farm/1910-2/)
- [Print API](https://dhlpaket.se/dashboard/services/api-farm/print/)
- [Implementation request](https://dhlpaket.se/dashboard/services/api-farm/implementation-request/)
- [EDI specifications](https://dhlpaket.se/dashboard/specifications/edi/)

Endpoints reported in the documentation, verify on registration:
sandbox admin `test-admin.freight-logistics.dhl.com`, sandbox API `test-api.freight-logistics.dhl.com`, production `api.freight-logistics.dhl.com`.

APIs available: TransportInstruction, PickupRequest, Print, PriceQuote, Product, AdditionalService, TimeTable, ServicePointLocator, HomeDeliveryLocator, PostalCodes, e-ID.

### Product and label specifications

- [DHL Freight Sweden Product Manual v5.25](https://dhlpaket.se/dashboard/wp-content/uploads/sites/2/2026/04/DHL-FREIGHT-SWEDEN-PRODUCT-MANUAL-v5.25.pdf)
- [Product-specific terms, domestic Sweden](https://www.dhl.com/content/dam/dhl/local/se/dhl-freight/documents/pdf/sv/se-freight-product-specific-terms-and-conditions-domestic-sv.pdf)
- [DHL Freight Label Definition v2.4](https://www.dhl.com/content/dam/dhl/global/dhl-freight/documents/posted-documents/glo-freight-label-definition.pdf)
- [Product manual index](https://dhlpaket.se/dashboard/specifications/products/)

### developer.dhl.com, tracking only

- [API catalog](https://developer.dhl.com/api-catalog)
- [Shipment Tracking Unified](https://developer.dhl.com/api-reference/shipment-tracking-unified)
- [Fee policy](https://support-developer.dhl.com/support/solutions/articles/47001175782-is-there-a-fee-for-using-dhl-group-apis-)
- [Rate limit increases](https://developer.dhl.com/getting-started/get-a-higher-rate-limit)

Do not build against [DHL Freight APIs](https://developer.dhl.com/dhl-freight) on this portal. Sweden is excluded from it.

### Odoo and OCA references

- [Odoo 18 third-party shipping carriers](https://www.odoo.com/documentation/18.0/applications/inventory_and_mrp/inventory/shipping_receiving/setup_configuration/third_party_shipper.html)
- [Odoo 18 multi-package shipments](https://www.odoo.com/documentation/18.0/applications/inventory_and_mrp/inventory/shipping_receiving/setup_configuration/multipack.html)
- [OCA delivery_schenker 18.0](https://github.com/OCA/delivery-carrier/tree/18.0/delivery_schenker), structural reference
- [OCA delivery_carrier_shipping_label 18.0](https://github.com/OCA/delivery-carrier/tree/18.0/delivery_carrier_shipping_label)

### Contact

DHL Freight (Sweden) AB, Gustav III:s Boulevard 18, 169 73 Solna, 0771-345 345.
API Farm registration confirmations arrive from apifarm@dhl.com.

---

## Commit rules

- One work package per branch. Do not mix WP1 and WP2 in the same branch.
- English commit messages, imperative mood.
- Commit after each acceptance criterion that can be independently verified, not in one large drop at the end.
- Never commit credentials, API keys or customer data. Sandbox keys go in configuration records or environment variables, never in source.
- Update both the GitHub README and the corresponding Notion README page. They must not diverge.

## Verification per work package

Before declaring a work package done:

1. Module installs and upgrades cleanly on a database with existing ARC modules. No WSOD, no traceback.
2. Every acceptance criterion has a demonstrable check. Automated where practical, a written reproduction step where not.
3. The regression test in WP1 criterion 5 passes.
4. `.pot` regenerated, Swedish `.po` complete, no untranslated user-facing strings.
5. No Swedish strings in `.py` or `.xml`.
6. No supplier names anywhere in customer-facing output.
7. Backwards compatibility: existing orders with existing cutting calculations still open and still show correct prices.

## Fallback if blocked

Stop and report. Do not improvise around any of these:

- A required TSB property does not exist for the products being tested. Report which property and which products.
- DHL API behaviour contradicts this document. Document the discrepancy with the actual request and response, then stop.
- A change to the CTS price formula, the optimiser or the SVG rendering appears necessary. Report why, do not proceed.
- Package structure rules require data that does not exist in TSB and cannot be derived. Report what is missing rather than hardcoding a default.
- An acceptance criterion cannot be met without breaking an existing feature. Report the conflict.

## Open questions for DHL, not for Kimi

These are unresolved in public documentation and Chrille is chasing them. Design defensively rather than assuming an answer.

1. ZPL support. Assume PDF only until DHL confirms otherwise.
2. Rate limits on the Swedish API Farm. Not published anywhere. Assume 250 per day.
3. Long goods above 299 cm for cross-border shipments. No standard path identified.
4. The long-goods chargeable weight tables for 3.00 to 5.99 m.
5. Which product codes are covered by the PlastShop agreement.
## Implementation notes

### WP3 E3, VisualCutter price quote (2026-08-06)

New models:
- `arc.dhl.visualcutter.adapter` (`models/arc_dhl_visualcutter_adapter.py`): AbstractModel that converts a VisualCutter batch result into DHL package dimensions and requests a price quote through `arc.dhl.price.quote`.
- Extended `arc.dhl.price.quote` (`models/arc_dhl_price_quote.py`) with `partner_country_code`, `partner_zip` and `package_json` so quotes can be created without a sales order. `sale_order_id` and `carrier_id` are now nullable.
- Extended `arc.dhl.product.selector` (`models/arc_dhl_product_selector.py`) with `select_from_packages(packages, country_code, silent=False)` for headless product selection.

Frontend integration:
- `arc_industrial_ui/controllers/_helpers.py::apply_shipping_and_packaging()` routes to DHL when `arc.dhl.visualcutter.adapter` exists and the ICP `arc_delivery_dhl.visualcutter_enabled` is not explicitly disabled. Falls back to `arc.frakt.engine` when DHL is unavailable.

Settings toggles (Settings > Sales > DHL Freight Sweden):
- `arc_dhl_visualcutter_enabled`: show DHL price quotes in VisualCutter.
- `arc_dhl_booking_enabled`: allow shipment booking from Odoo pickings.
- `arc_dhl_tracking_enabled`: show DHL tracking links on deliveries.
- `delivery_carrier.py` blocks `send_shipping` and hides tracking links when the corresponding toggle is off.

Migrations:
- `migrations/18.0.1.2.0/pre-migration.py` makes `carrier_id` nullable.
- `migrations/18.0.1.2.0/post-migration.py` makes `sale_order_id` nullable.

Tests:
- `tests/test_arc_dhl_visualcutter_adapter.py`
- `tests/test_arc_dhl_price_quote.py`
- `tests/test_arc_dhl_product_rule.py`

Verification:
- Module upgrade from `18.0.1.1.0` to `18.0.1.2.0` succeeded.
- `arc_delivery_dhl` regression tests: 16 tests, 0 failures.
- `/visualcutter/calculate` hits the DHL path and issues a PriceQuote request.
- DHL test environment currently returns `400 Index was outside the bounds of the array.` for every request with the supplied test key, including direct `curl` calls to `test-api.freight-logistics.dhl.com`. This appears to be a key/account issue on DHL's side, not a payload problem.

Open follow-up:
- The supplied test key returns `400 Index was outside the bounds of the array.` for every endpoint, including `/price-quote`, `/postal-codes` and `/products`, with multiple header formats. According to DHL, the key must be created inside an Organisation/Application in the API Farm test environment. Verify that the key is linked to an active test application, or create a new one in DHLAPIFarm test.
- Verify the exact PriceQuote payload shape once a working key is available; add sender/postal-code fields if required.
- The local change in `/srv/odoo/plastshop/addons/arc_industrial_ui/controllers/_helpers.py` is not under separate version control; it must be preserved when that module is next deployed.
