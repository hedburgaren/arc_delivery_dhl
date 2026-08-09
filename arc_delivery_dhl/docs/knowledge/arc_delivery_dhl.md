# arc_delivery_dhl: Knowledge Reference

## Purpose

`arc_delivery_dhl` is the DHL Freight Sweden delivery carrier integration for the ARC Industrial Suite (Odoo 18 CE). It adds a `delivery.carrier` implementation (`delivery_type='dhl_freight_se'`) and supporting models for product selection, price quotes, shipment booking and label retrieval.

Module version: `__manifest__.py:4` (`18.0.1.3.0`).
Depends on `arc_industrial_ops`, `delivery`, `stock` and `mail`.

## API: Swedish DHL Freight API Farm

All endpoints live under `freight-logistics.dhl.com` and authenticate with a
`client-key` header:

- Sandbox: `https://test-api.freight-logistics.dhl.com`
- Production: `https://api.freight-logistics.dhl.com`

APIs used:
- **Product API** (`/productapi/v1/`) for product catalog lookups.
- **PriceQuote API** (`/pricequoteapi/v1/`) for gross price quotes.
- **TransportInstruction API** (`/transportinstructionapi/v1/`) for shipment booking.
- **Print API** (`/printapi/v1/`) for label retrieval.

Credentials are read from `ir.config_parameter` first, then environment
variables, then a `.env` file next to the module. The `.env` file must never be
committed.

## Quick map

| What | Where |
|------|-------|
| API Farm request client (client-key) | `models/arc_dhl_request_mixin.py:0`, `arc.dhl.request.mixin._arc_dhl_request()` |
| Settings fields | `models/res_config_settings.py:0`, `res.config.settings` |
| Price quote model and cache | `models/arc_dhl_price_quote.py:0`, `arc.dhl.price.quote` |
| Price quote payload builder | `models/arc_dhl_price_quote.py:0`, `arc.dhl.price.quote._arc_dhl_build_quote_payload()` |
| Product code mapping to PriceQuote enum | `models/arc_dhl_price_quote.py:0`, `_PRICE_QUOTE_PRODUCT_CODES` |
| VisualCutter adapter | `models/arc_dhl_visualcutter_adapter.py:0`, `arc.dhl.visualcutter.adapter` |
| Product selection rules | `models/arc_dhl_product_rule.py:0` |
| DHL product catalog records | `models/arc_dhl_product.py:0`, `arc.dhl.product` |
| Shipment booking | `models/arc_dhl_booking.py:0`, `arc.dhl.booking.action_book_shipment()` |
| Label retrieval and storage | `models/arc_dhl_label.py:0`, `arc.dhl.label` |
| Sale order freight quote | `models/sale_order.py:0`, `sale.order.action_arc_dhl_quote()` |
| Sale order freight line | `models/sale_order.py:0`, `sale.order.action_arc_dhl_apply_shipping()` |

## Models

### arc.dhl.product
DHL Freight product/service definitions used by product rules and price quote payloads. File: `models/arc_dhl_product.py:6`.

Key fields: `name`, `code` (DHL product code from the Product API, e.g. `102`, `210`, `202`), `is_domestic`, `is_international`, `max_length_cm`, `max_weight_kg`, `is_pallet_product`, `active`, `note`.

Seed data loads domestic products (PAKET `102`, PALL `210`, STYCKE `211`, PARTI `212`, SPECIAL `209`) and international road products (Road Freight Standard `202`, Priority `233`, Direct `205`) from `data/arc_dhl_product_data.xml`.

The PriceQuote API uses its own string enum values (e.g. `DHLPaket`, `DHLPall`, `DHLEuroConnect`). The mapping from Product API codes to PriceQuote enum values is maintained in `_PRICE_QUOTE_PRODUCT_CODES` in `models/arc_dhl_price_quote.py:0`.

### arc.dhl.product.rule
Declarative rule that maps package/country/weight/dimension profiles to an `arc.dhl.product`. File: `models/arc_dhl_product_rule.py:0`.

Key methods:
- `matches(country_code, max_length_cm, total_weight_kg, package_count)` : first-match predicate. `models/arc_dhl_product_rule.py:0`.

### arc.dhl.price.quote
Persisted price quote with caching. File: `models/arc_dhl_price_quote.py:12`.

Key fields: `name`, `carrier_id`, `sale_order_id`, `product_id`, `partner_country_code`, `partner_zip`, `package_json`, `state` (draft/quoted/error), `price`, `currency_id`, `cache_key`, `api_response`, `error_message`.

Key methods:
- `action_request_quote()` : cache lookup, then DHL Price Quote API call. `models/arc_dhl_price_quote.py:72`.
- `get_quote_for_packages(packages, partner_vals, product=None)` : model helper used by VisualCutter. `models/arc_dhl_price_quote.py:128`.
- `_arc_dhl_build_quote_payload()` : builds the DHL Freight Price Quote request including `eid`, `shipment`, `piece[]`, `parties[]` and `ownSurCharge`. `models/arc_dhl_price_quote.py:210`.
- `_arc_dhl_extract_price(response)` : returns the `TotalPrice` line from the list response. `models/arc_dhl_price_quote.py:345`.

### arc.dhl.booking
Shipment booking record linked to a picking. File: `models/arc_dhl_booking.py:10`.

Key fields: `name`, `carrier_id`, `picking_id`, `sale_order_id`, `product_id`, `state`, `dhl_booking_id`, `dhl_tracking_numbers`, `label_ids`, `price`, `api_request`, `api_response`, `error_message`.

Key methods:
- `action_book_shipment()` : validates, builds payload, calls `/transportinstructionapi/v1/transportinstruction/sendtransportinstruction`, fetches labels. `models/arc_dhl_booking.py:87`.

### arc.dhl.label
Binary PDF label attached to a booking. File: `models/arc_dhl_label.py:0`.

### arc.dhl.visualcutter.adapter
Abstract adapter that converts VisualCutter batch results into DHL package profiles and requests a quote. File: `models/arc_dhl_visualcutter_adapter.py:16`.

Key methods:
- `quote_for_batch(batch_result, partner_vals)` : returns a dict compatible with `apply_shipping_and_packaging`. `models/arc_dhl_visualcutter_adapter.py:21`.

## Settings

Settings are exposed under `Settings > Sales > DHL Freight Sweden` via `views/res_config_settings_views.xml`.

Config parameters:
- `arc_delivery_dhl.api_key` - Swedish API Farm client-key.
- `arc_delivery_dhl.price_quote_api_key` - Global Price Quote API consumer key.
- `arc_delivery_dhl.price_quote_api_secret` - Global Price Quote API consumer secret.
- `arc_delivery_dhl.eid_username` - DHL eID username for Price Quote payloads.
- `arc_delivery_dhl.eid_password` - DHL eID password.
- `arc_delivery_dhl.is_production` - toggles production endpoints.
- `arc_delivery_dhl.force_environment` - overrides `is_production` for testing.
- `arc_delivery_dhl.visualcutter_enabled` - show DHL prices in VisualCutter.
- `arc_delivery_dhl.booking_enabled` - allow shipment booking from pickings.
- `arc_delivery_dhl.tracking_enabled` - show tracking links.
- `arc_delivery_dhl.auto_quote_enabled` - automatically request a DHL freight quote and add a freight line when a quotation/order is confirmed.
- `arc_delivery_dhl.customer_number` - DHL Freight customer number (avtalsnummer). Required for booking; sent as the consignor party identifier.

Environment fallbacks:
- `DHL_SANDBOX_API_KEY` / `DHL_API_KEY` for the API Farm.
- `DHL_PRICE_QUOTE_API_KEY`, `DHL_PRICE_QUOTE_API_SECRET`, `DHL_EID_USERNAME`, `DHL_EID_PASSWORD` for Price Quote.

## Data and migrations

- `data/arc_dhl_sequence_data.xml` - sequences for quotes and bookings.
- `data/arc_dhl_product_data.xml` - seed DHL products.
- `data/arc_dhl_product_rule_data.xml` - seed product selection rules.
- `data/arc_dhl_parameter_data.xml` - default config parameters.
- `migrations/18.0.1.1.0/` and `migrations/18.0.1.2.0/` - historical migrations.

## Backend sale.order flow

`sale.order` is extended in `models/sale_order.py` so a salesperson can request a DHL freight quote directly from a quotation/order and add the result as a separate freight line.

Fields added to `sale.order`:
- `arc_dhl_price_quote_id` - latest `arc.dhl.price.quote` linked to the order.
- `arc_dhl_shipping_cost` - freight cost excluding VAT from the quote.
- `arc_dhl_shipping_cost_incl_vat` - freight cost including VAT from the quote.
- `arc_dhl_product_id` - optional product lock; if empty the product selector chooses the first matching DHL product.

Actions:
- `action_arc_dhl_quote()` - requires a confirmed `arc.package.proposal`, selects a DHL product, creates an `arc.dhl.price.quote`, calls the DHL PriceQuote API and stores the result. Also sets `carrier_id` to the configured DHL carrier.
- `action_arc_dhl_apply_shipping()` - adds or updates a sale order line using the service product named "Frakt", priced at `arc_dhl_shipping_cost`. Existing freight lines are updated instead of duplicated.
- `action_confirm()` (override) - when `arc_delivery_dhl.auto_quote_enabled` is set, the order is in draft/sent state and a confirmed packing proposal exists, automatically calls `action_arc_dhl_quote()` and `action_arc_dhl_apply_shipping()` before the order is confirmed. Failures are logged as warnings and do not block confirmation.

UI additions are in `views/sale_order_views.xml`: buttons next to "Calculate packaging", a stat button showing the DHL freight cost and a "DHL Freight" notebook page.

## Sandbox verification

The booking flow has been verified against the DHL Freight Sweden sandbox:
- `action_book_shipment()` calls `/transportinstructionapi/v1/transportinstruction/sendtransportinstruction`.
- The payload follows the DHL `Shipment` schema: `productCode`, `payerCode`, `parties[]`, `pieces[]`, totals and references.
- The consignor party id is set from `arc_delivery_dhl.customer_number`.
- Piece dimensions are lifted to product-specific minimums observed from the sandbox (e.g. DHL PAKET `102` needs width >= 11 cm and height >= 2 cm).
- Labels are fetched via `/printapi/v1/print/printdocumentsbyid` using the returned DHL shipment id.

The sale.order flow has also been verified against the sandbox: a test order with a confirmed packing proposal received a DHL PAKET quote of SEK 213.82 excl. VAT and a freight line was created automatically.

## Tests

Tag: `arc_dhl`. Run with `--test-tags arc_dhl`.

Key test files:
- `tests/test_arc_dhl_request_mixin.py` - environment and key selection, client-key header, OAuth token flow.
- `tests/test_arc_dhl_price_quote.py` - cache behaviour and DHL payload format.
- `tests/test_arc_dhl_visualcutter_adapter.py` - adapter fallback and pricing.
- `tests/test_arc_dhl_booking.py` - booking validation and label creation.
- `tests/test_arc_dhl_product_rule.py` - product selection rules.
- `tests/test_arc_dhl_sale_order.py` - backend order freight quote and freight line creation.
