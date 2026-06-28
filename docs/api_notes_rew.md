# REW API & Data Notes

## REW EQ Text File Format

This is the primary import/export format for this application. REW exports PEQ filters as plain text files.

### Exact format spec

```text
Filter Settings file

Room EQ V5.40 Beta 125
Dated: 2026 Jun 28 21:42:22

Notes:some test notes here

Equaliser: Generic
Test measurement L ch EQ
Filter  1: ON  PK       Fc   20.00 Hz  Gain   -7.0 dB  Q 27.585
Filter  2: ON  Modal    Fc   25.00 Hz  Gain  27.00 dB  Q 16.139  T60 target   300 ms
Filter  3: ON  LP       Fc   31.50 Hz 
Filter  4: ON  HP       Fc   40.00 Hz 
Filter  5: ON  LP1      Fc   50.00 Hz 
Filter  6: ON  HP1      Fc   63.00 Hz 
Filter  7: ON  LP Q     Fc   80.00 Hz  Q   0.71
Filter  8: ON  HP Q     Fc  100.00 Hz  Q   0.71
Filter  9: ON  LS       Fc  125.00 Hz  Gain  -14.0 dB
Filter 10: ON  HS       Fc  160.00 Hz  Gain    0.0 dB
Filter 11: ON  LS 6dB   Fc  200.00 Hz  Gain    0.0 dB
Filter 12: ON  HS 6dB   Fc  250.00 Hz  Gain    0.0 dB
Filter 13: ON  LS 12dB  Fc  315.00 Hz  Gain    0.0 dB
Filter 14: ON  HS 12dB  Fc  400.00 Hz  Gain    0.0 dB
Filter 15: ON  LS Q     Fc  500.00 Hz  Gain    0.0 dB Q   0.71
Filter 16: ON  HS Q     Fc  630.00 Hz  Gain    0.0 dB Q   0.71
Filter 17: ON  None   
Filter 18: ON  Notch    Fc 1000.00 Hz 
Filter 19: ON  Notch Q  Fc 1250.00 Hz  Q   0.71
Filter 20: ON  All pass  Fc 1600.00 Hz  Q   0.71
Filter  1: OFF None      
Filter  2: ON  None              
```

The trailing `Filter  1: OFF None` / `Filter  2: ON  None` lines above are REW's real duplicate-numbered trailer — the parser stops at the first repeated filter number (here, the second `Filter  1:`), so these two lines are never actually parsed. They're shown here only because genuine REW exports include them; they have no effect on the result.

### Field breakdown per filter line

| Field | Values | Notes |
|---|---|---|
| Enabled state | `ON` / `OFF` | Maps to Canonical `type = "OFF"` when OFF |
| Filter type | `PK` / `LP Q` / `HP Q` / `LS Q` / `HS Q` / `LP` / `HP` / `LS` / `HS` / `LP1` / `HP1` / `Notch` / `Notch Q` / `Modal` / `All pass` / `L-T` / `None` | See "Filter type mapping table" |
| `Fc <value> Hz` | Frequency in Hz | Float; validated 10–22000 Hz |
| `Gain <value> dB` | Gain in dB | Float; WiiM limits: -12 to +12 dB |
| `Q <value>` | Q factor | Float; WiiM limits: 0.01–24 |

### Filter type mapping table

WiiM's LV2 `EqNp` plugin exposes only a single Q parameter per band (no separate slope parameter — see
[docs/wiim_api_notes.md](wiim_api_notes.md)), so only REW tokens that carry an actual Q translate
directly:

| REW text | Canonical type | WiiM `{letter}_mode` | Notes |
|---|---|---|---|
| `PK` | `PEAK` | `1` | |
| `LP Q` / `HP Q` / `LS Q` / `HS Q` | `LP` / `HP` / `LS` / `HS` | `3` / `5` / `0` / `2` | Explicit REW Q, passed through unchanged. |
| `LP` / `HP` (bare) | `LP` / `HP` | `3` / `5` | No Q in REW's output; REW documents these as a fixed Q=0.7071 (12 dB/octave Butterworth), used as the default. Unlike `LP Q`/`HP Q` (a direct, lossless match needing no comment), this substitutes a value the source never specified, so the Review table surfaces it as a conversion note on the Q cell — see "Conversion notes" below. |
| `LS` / `HS` (bare), `LS 6dB`/`HS 6dB`, `LS 12dB`/`HS 12dB` | — | — | **Unsupported, skipped.** REW parameterizes these with a shelf-slope `S` (0.9 / 0.5 / 1.0), not Q — no validated S→Q conversion exists. See `docs/corrections.md`. |
| `LP1` / `HP1` | — | — | **Unsupported, skipped.** 1st-order (6 dB/octave), no Q at all. |
| `Notch` / `Notch Q` | — | — | **Unsupported, skipped.** Implies >60 dB attenuation; exceeds WiiM's -12 dB gain floor. |
| `Modal` / `All pass` / `L-T` | — | — | **Unsupported, skipped.** No WiiM equivalent. |
| `None` | `OFF` | `-1` | Empty slot — always becomes an explicit `OFF` band, never skipped, regardless of `ON`/`OFF` state. |

Note: the table above is about the **filter-type** token (the `PK`/`LS`/`Notch`/`None`/etc. column in the text format, or the `type` field in the API's JSON). The separate `ON`/`OFF` **state prefix** (see "Field breakdown per filter line" above) is a different field — when a line/entry is disabled (`OFF` prefix, or `"enabled": false`/`"on": false`), its Canonical `type` is overridden to `"OFF"` regardless of what its filter-type token was, *unless* that type is itself unsupported, in which case it's still skipped rather than becoming a generic `OFF` placeholder.

#### Conversion notes (values substituted, not specified by REW)

A skipped band (no WiiM equivalent at all) and a band that's fully usable but had a value
*substituted* for one REW's source didn't specify are different cases, and the Review table
distinguishes them:

- **Skipped** (`SkippedBand`, see `docs/data_models.md`): the band has no WiiM translation at all —
  rendered crossed out, unnumbered ("N/A").
- **Converted with a note**: the band is fully usable, but one of its values was filled in by the
  parser rather than read from the source — currently only the fixed Butterworth Q (0.7071) applied
  to a bare `LP`/`HP` with no explicit Q. The Q cell gets a distinct (non-warning) dot indicator with
  a tooltip explaining the substitution, e.g. "Note: REW's bare HP has no explicit Q; using REW's
  documented fixed Q=0.7071 (12 dB/octave Butterworth alignment)." `LP Q`/`HP Q`/`LS Q`/`HS Q` (an
  explicit Q in the source) never get this note — they're a direct, lossless match.
- Implementation: `_parse_filter_body`/`parse_filter_settings_with_rows`
  (`src/translator/rew_parser.py`) return a `conversion_notes: dict[int, list[str]]` (keyed by the
  band's 0-based index in the returned filter list) alongside `filters`/`rows`, threaded through
  `WizardState.pending_conversion_notes`/`_l`/`_r` to `FilterTable` for display.

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

Returns an array of `FilterSetting` objects. Confirmed against real REW API output: **REW omits the
`q` key entirely** for any type whose own format has no Q field — `PK` and the `*Q`-suffixed types
always carry `q`; `LP`/`HP`/`LS`/`HS`/`LS 6dB`/`HS 6dB`/`LS 12dB`/`HS 12dB`/`LP1`/`HP1` do not:

```json
[
  { "index": 1, "type": "PK", "enabled": true, "isAuto": true, "frequency": 20.0, "gaindB": -7.0, "q": 27.585 },
  { "index": 2, "type": "Modal", "enabled": true, "isAuto": true, "frequency": 25.0, "gaindB": 27.0, "t60Target": 0.3 },
  { "index": 3, "type": "LP", "enabled": true, "isAuto": true, "frequency": 31.5 },
  { "index": 4, "type": "HP", "enabled": true, "isAuto": true, "frequency": 40.0 },
  { "index": 5, "type": "LP1", "enabled": true, "isAuto": true, "frequency": 50.0 },
  { "index": 6, "type": "HP1", "enabled": true, "isAuto": true, "frequency": 63.0 },
  { "index": 7, "type": "LP Q", "enabled": true, "isAuto": true, "frequency": 80.0, "q": 0.71 },
  { "index": 8, "type": "HP Q", "enabled": true, "isAuto": true, "frequency": 100.0, "q": 0.71 },
  { "index": 9, "type": "LS", "enabled": true, "isAuto": true, "frequency": 125.0, "gaindB": -14.0 },
  { "index": 10, "type": "HS", "enabled": true, "isAuto": true, "frequency": 160.0, "gaindB": 0.0 },
  { "index": 11, "type": "LS 6dB", "enabled": true, "isAuto": true, "frequency": 200.0, "gaindB": 0.0 },
  { "index": 12, "type": "HS 6dB", "enabled": true, "isAuto": true, "frequency": 250.0, "gaindB": 0.0 },
  { "index": 13, "type": "LS 12dB", "enabled": true, "isAuto": true, "frequency": 315.0, "gaindB": 0.0 },
  { "index": 14, "type": "HS 12dB", "enabled": true, "isAuto": true, "frequency": 400.0, "gaindB": 0.0 },
  { "index": 15, "type": "LS Q", "enabled": true, "isAuto": true, "frequency": 500.0, "gaindB": 0.0, "q": 0.7100000000000001 },
  { "index": 16, "type": "HS Q", "enabled": true, "isAuto": true, "frequency": 630.0, "gaindB": 0.0, "q": 0.7100000000000001 },
  { "index": 17, "type": "None", "enabled": true, "isAuto": true },
  { "index": 18, "type": "Notch", "enabled": true, "isAuto": true, "frequency": 1000.0 },
  { "index": 19, "type": "Notch Q", "enabled": true, "isAuto": true, "frequency": 1250.0, "q": 0.71 },
  { "index": 20, "type": "All pass", "enabled": true, "isAuto": true, "frequency": 1600.0, "q": 0.71 },
  { "index": 21, "type": "None", "enabled": false, "isAuto": true },
  { "index": 22, "type": "None", "enabled": true, "isAuto": true}
]
```

Field meanings match the text format: `type` uses the same abbreviations (`PK`, `LP`/`HP`, `LS`/`HS`,
`LP Q`/`HP Q`/`LS Q`/`HS Q`, `LP1`/`HP1`, `LS 6dB`/`HS 6dB`, `LS 12dB`/`HS 12dB`, `Notch`/`Notch Q`,
`Modal`, `All pass`, `None`). See "Filter type mapping table" above for which ones translate and which
are skipped. Filter 2 above (`LP`, no `q`) gets REW's documented fixed Q (0.7071); filter 3 (bare `LS`,
no `q`) is skipped — REW's shelf-slope `S` parameter has no validated WiiM Q equivalent (this was a real
bug: the parser used to default a missing `q` to an arbitrary `1.0` for every type instead of REW's
documented value, and `LS`/`HS`/`LP1`/`HP1`/etc. used to silently pass through instead of being skipped
— see `docs/corrections.md`). 
Note that REW API may return numbers with up to 16 decimal places, whereas WiiM API returns numbers with 
up to 3 decimal places. Long decimal numbers should be rounded to 3 decimals before being pushing to WiiM 
API.

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
| Filter type | `PK`, `LP`/`HP`, `LP Q`/`HP Q`/`LS Q`/`HS Q`, bare `LP`/`HP` | Anything else (`Modal`, `All pass`, `L-T`, `Notch`/`Notch Q`, `LP1`/`HP1`, bare `LS`/`HS`, `LS 6dB`/`HS 6dB`, `LS 12dB`/`HS 12dB`, or any unrecognized token) is **skipped with a warning** (`SkippedBand` placeholder), not rejected as an error — see "Filter type mapping table" above |

When the gain or Q values are within REW's valid range but outside WiiM's hardware limits, show a validation warning and allow the user to proceed (clipping will be applied by the Translation Engine) or cancel.

When a REW file contains **more filter bands than the device's `max_filters`** (e.g. a 20-band REW export imported for a 10-band WiiM device):
- Show a validation warning stating how many bands will be used and how many will be discarded.
- Use the first `max_filters` **enabled** bands in file order.
- Do not silently discard bands; require the user to acknowledge before proceeding.

---

## References

1. [REW API documentation](https://www.roomeqwizard.com/help/help_en-GB/html/api.html)
2. [REW Equaliser documentation](https://www.roomeqwizard.com/help/help_en-GB/html/equaliser.html)
