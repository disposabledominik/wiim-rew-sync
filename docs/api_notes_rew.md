# REW API & Data Notes

## REW EQ Text File Format

This is the primary import/export format for this application. REW exports PEQ filters as plain text files.

### Exact format spec

```text
Equaliser: Parametric EQ
Filter  1: ON  PK       Fc    50.00 Hz  Gain  -4.00 dB  Q  2.500
Filter  2: ON  LS       Fc    80.00 Hz  Gain   3.00 dB  Q  0.707
Filter  3: ON  HS       Fc  8000.00 Hz  Gain  -2.00 dB  Q  0.707
Filter  4: OFF PK       Fc   200.00 Hz  Gain   0.00 dB  Q  1.000
```

### Field breakdown per filter line

| Field | Values | Notes |
|---|---|---|
| `ON` / `OFF` | Enabled state | Maps to Canonical `type = "OFF"` when OFF |
| `PK` | Peak filter | Maps to Canonical `type = "PEAK"` |
| `LS` | Low shelf | Maps to Canonical `type = "LS"` |
| `HS` | High shelf | Maps to Canonical `type = "HS"` |
| `Fc <value> Hz` | Frequency in Hz | Float; validated 10–22000 Hz |
| `Gain <value> dB` | Gain in dB | Float; WiiM limits: -12 to +12 dB |
| `Q <value>` | Q factor | Float; WiiM limits: 0.01–24 |

### Filter type mapping table

| REW text | Canonical type | WiiM `{letter}_mode` |
|---|---|---|
| `PK` | `PEAK` | `1` |
| `LS` | `LS` | `0` |
| `HS` | `HS` | `2` |
| `OFF` (any type) | `OFF` | `-1` |

### Export rules (when generating REW files from WiiM data)

- First line **must** be exactly: `Equaliser: Parametric EQ`
- Filter lines are 1-indexed and zero-padded to two digits: `Filter  1:`, `Filter  2:`, etc.
- All numeric values are formatted to 2 decimal places for gain/frequency, 3 for Q.
- Disabled bands (mode `-1`) are written as `OFF PK Fc ... Gain ... Q ...` — type defaults to `PK`, frequency/gain/Q are preserved from the last known state (or set to sensible defaults: 1000 Hz, 0 dB, 1.0 Q).
- Do not omit disabled filters; write all bands up to the device's `max_filters` count.

---

## REW HTTP API (Localhost)

REW exposes a local REST API when launched with the `-api` flag or via API preferences.

- **Base URL**: `http://localhost:4735/`
- **Default port**: 4735 (configurable with `-port`)
- **Access scope**: Localhost only. Not accessible from other machines.
- **Auth**: None.
- **When REW is not running**: All requests will fail with a connection refused error. The app must handle this gracefully and not require REW to be running.

### Relevant endpoints

#### List measurements

```
GET /measurements
```

Returns an array of measurement summary objects:

```json
[
  {
    "title": "Listening Position",
    "uuid": "ba2da346-0f31-4d9d-bbeb-2bfcd07e1cb9",
    "date": "2026-06-04 13:00:00",
    "startFreq": 20.0,
    "endFreq": 20000.0
  }
]
```

> **Strict rule**: Never auto-select the "latest" or first measurement. The user must explicitly choose a measurement UUID from this list before any filter operation proceeds.

#### Get filters for a measurement

```
GET /measurements/:id/filters
```

Where `:id` is the measurement **UUID** (not index — indexes change when measurements are added/removed).

Returns an array of `FilterSetting` objects:

```json
[
  {"filterNo": 1, "on": true,  "type": "PK", "freq": 80.0,   "gain": 5.3,  "q": 3.885},
  {"filterNo": 2, "on": true,  "type": "LS", "freq": 40.0,   "gain": 3.0,  "q": 0.707},
  {"filterNo": 3, "on": false, "type": "PK", "freq": 200.0,  "gain": 0.0,  "q": 1.0}
]
```

Field meanings match the text format: `type` uses the same `PK`/`LS`/`HS` abbreviations.

#### Update filters (future / optional)

```
PUT /measurements/:id/filters      (single filter)
POST /measurements/:id/filters     (multiple filters as FilterList)
```

These are available for future live-sync features (Backlog). Not required for MVP.

### Error responses

| Scenario | HTTP status | Handling |
|---|---|---|
| REW not running | Connection refused | Show "REW not connected" status in UI; do not crash |
| Invalid measurement UUID | 404 | Show error to user |
| REW API not started | Connection refused | Same as "not running" |
| Malformed request | 400 | Log and display generic API error |

### Blocking mode (optional)

REW supports a blocking mode for scripting use (`POST /application/blocking` with `true`). Not required for this application — we only use GET operations on the API.

---

## Filter Validation Rules (on import, both text and API)

Before any filter is passed to the Translation Engine or used in a device write, validate:

| Parameter | Valid range | On violation |
|---|---|---|
| Frequency | 10 Hz – 22000 Hz | Reject file / show error before any device interaction |
| Gain | -120 dB – +30 dB (REW range) | Warn if outside WiiM's ±12 dB hardware limit; clip or reject |
| Q | 0.001 – 50 (REW range) | Warn if outside WiiM's 0.01–24 range; clip or reject |
| Filter type | `PK`, `LS`, `HS` | Reject unknown types with a clear error message |

When the gain or Q values are within REW's valid range but outside WiiM's hardware limits, show a validation warning and allow the user to proceed (clipping will be applied by the Translation Engine) or cancel.

When a REW file contains **more filter bands than the device's `max_filters`** (e.g. a 20-band REW export imported for a 10-band WiiM device):
- Show a validation warning stating how many bands will be used and how many will be discarded.
- Use the first `max_filters` **enabled** bands in file order.
- Do not silently discard bands; require the user to acknowledge before proceeding.

---

## References

1. [REW API documentation](https://www.roomeqwizard.com/help/help_en-GB/html/api.html)
2. [REW Equaliser documentation](https://www.roomeqwizard.com/help/help_en-GB/html/equaliser.html)
