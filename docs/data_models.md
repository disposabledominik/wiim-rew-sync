# Data Models

## Canonical Filter Representation

All formats must convert through this model. No direct REW-to-WiiM or WiiM-to-REW conversion is permitted.

```json
{
  "type": "PEAK",
  "frequency_hz": 1000.0,
  "gain_db": -3.0,
  "q": 1.41
}
```

### Valid `type` values

| Canonical `type` | REW text | WiiM `{letter}_mode` | Meaning |
|---|---|---|---|
| `"PEAK"` | `PK` | `1` | Parametric peak/notch filter |
| `"LS"` | `LS Q` | `0` | Low shelf filter |
| `"HS"` | `HS Q` | `2` | High shelf filter |
| `"LP"` | `LP Q` | `3` | Low-pass filter |
| `"HP"` | `HP Q` | `5` | High-pass filter |
| `"OFF"` | `OFF <type>` | `-1` | Disabled band |

### WiiM has only a Q parameter — what each REW token actually means

WiiM's LV2 `EqNp` plugin exposes exactly one tunable parameter per band, `{letter}_q` ("Q factor",
range 0.01–24 — see [docs/wiim_api_notes.md](wiim_api_notes.md)). There is no separate slope/`S`
parameter. REW's filter-type tokens map onto that single Q knob as follows:

| REW token | REW's own parameter | WiiM translation |
|---|---|---|
| `LP Q` / `HP Q` / `LS Q` / `HS Q` | Explicit Q | Passed through unchanged — this is WiiM's native filter, exactly. |
| `LP` / `HP` (bare) | Fixed Q = 0.7071 (REW's documented 12 dB/octave Butterworth alignment) | Translated using that same fixed Q (`_BUTTERWORTH_Q` in `src/translator/rew_parser.py`). |
| `LS` / `HS` (bare, S=0.9), `LS 6dB`/`HS 6dB` (S=0.5), `LS 12dB`/`HS 12dB` (S=1.0) | Shelf-slope parameter `S` — a different quantity from Q | **Unsupported, skipped.** There is no validated S→Q conversion (or confirmation WiiM's shelf math accepts S directly) — see "Unsupported REW filter types" below and `docs/corrections.md`. |
| `LP1` / `HP1` | 1st-order (6 dB/octave) — no Q at all | **Unsupported, skipped.** |

### Field constraints

| Field | Type | Valid range | Notes |
|---|---|---|---|
| `type` | string | See table above | Required |
| `frequency_hz` | float | 10.0 – 22000.0 Hz | WiiM hardware range |
| `gain_db` | float | -12.0 – +12.0 dB | WiiM hardware limit; REW range is wider |
| `q` | float | 0.01 – 24.0 | WiiM hardware range |

When importing from REW, gain/Q values outside WiiM's hardware limits must be flagged with a validation warning. The Translation Engine will clip values to WiiM limits before writing.

### Unsupported REW filter types

REW filter types with no WiiM translation (`Modal`, `All pass`, `L-T`, `Notch`/`Notch Q`, `LP1`/`HP1`,
`LS`/`HS`, `LS 6dB`/`HS 6dB`, `LS 12dB`/`HS 12dB`) are skipped during import, in both the text-file and
live REW-API parsing paths (`REWParser.parse_file_with_rows` / `parse_filter_settings_with_rows` in
`src/translator/rew_parser.py`).

`Notch`/`Notch Q` are skipped rather than approximated as `PEAK` because REW notches imply >60 dB of
attenuation, which exceeds WiiM's -12 dB gain floor and can't be faithfully reproduced (see
`docs/corrections.md`, 2026-06-28).

`LS`/`HS`/`LS 6dB`/`HS 6dB`/`LS 12dB`/`HS 12dB` are skipped because REW parameterizes them with a shelf
*slope* value `S` (0.9 / 0.5 / 1.0 respectively), not a Q, and WiiM has no slope parameter to receive it
— see the table above and `docs/corrections.md`, 2026-06-28. `LP1`/`HP1` are 1st-order filters with no Q
at all. Note this is an asymmetry with the otherwise-supported bare `LS`/`HS` *token* used by this app's
own REW-text round-trip format (`src/translator/rew_generator.py`) — that format always writes an
explicit Q after the bare token, which is what makes it distinguishable and supported (see `_TYPE_MAP`'s
comment in `src/translator/rew_parser.py`); a genuine REW export's bare `LS`/`HS` line never carries a Q
and is always skipped.

Skipped bands are not silently dropped from the Review table — the `*_with_rows` parser methods return
a `FilterRow` list (`CanonicalFilter | SkippedBand`, defined in `src/translator/_warnings.py`) that
preserves each skipped band's original position, alongside the plain `list[CanonicalFilter]` used for
writes. `SkippedBand` carries the original REW type token and the skip reason; the Review table renders
it as an unnumbered ("N/A"), crossed-out, dimmed row with the reason on hover. Bands cut for exceeding
the device's band cap (`validate_filters_for_device` in `src/gui/shared_helpers.py`) are represented the
same way, but keep their original frequency/gain/Q for display since — unlike a type-level skip — the
band itself was valid, just over the limit.

A bare `LP`/`HP` (no explicit Q in the source) is a third, distinct case: fully usable, but with a
*substituted* value — REW's documented fixed Q (0.7071, 12 dB/octave Butterworth) fills the gap that the
source never specified, unlike `LP Q`/`HP Q`/`LS Q`/`HS Q` which carry an explicit Q and need no comment.
The `*_with_rows` methods return this as `conversion_notes: dict[int, list[str]]` (keyed by the band's
0-based index in `filters`), surfaced as a distinct info-colored dot + tooltip on the Q cell — separate
from both the `SkippedBand` treatment above and the orange clamping-warning dot, since the value isn't
out of range, just not the one REW's source specified.

---

## Device Capabilities Model

```python
class DeviceCapabilities:
    supports_peq: bool                  # True if WiiM LV2 PEQ (EqNp) is available; True on all WiiM devices
    supports_roomfit: bool              # True if a dedicated RoomFit band set exists; False on WiiM Mini
    supports_roomfit_read: bool         # True if RoomFit bands are readable (Level 2+)
    supports_roomfit_write: bool        # True if RoomFit bands are writable (Level 4)
    supports_lr_filters: bool          # True if independent L/R channel PEQ is available; True on all WiiM devices
    supports_profile_enumeration: bool  # True if device can list saved PEQ presets
    supports_batch_write: bool | None   # True/False once confirmed by a real write attempt; None until then (no connect-time write probe -- see docs/corrections.md, 2026-07-10)
    rc_version: str                     # RC subsystem version from GetAcousticCapability (e.g. "1.0"); empty when absent/unsupported -- discriminates RoomCorr* command behavior, see wiim_api_notes.md
    max_filters: int                    # Number of PEQ bands; 10 on most WiiM devices, 12 on WiiM Amp Ultra firmware 20260409+ (see docs/wiim_api_notes.md)
    model: str                          # e.g. "WiiM Ultra", "WiiM Mini", "WiiM Amp Pro"
    firmware: str                       # e.g. "6.0.1.20"
    uuid: str                           # Device UUID
    mac_address: str                    # Device MAC address
    source_names: list[str]             # Available source names, e.g. ["wifi", "bluetooth"]
    supported_filter_types: list[str]   # WiiM-supported filter types, e.g. ["PEAK","LS","HS","LP","HP"]
    source_aliases: dict[str, str]      # Optional source name aliases from the device capability file
    capability_file_override: bool      # True if a per-model override from the device capability file was merged in
    used_generic_capabilities: bool     # True if no model-specific entry was found and generic defaults were used
```

RoomFit support is three independent booleans (subsystem present / band-buffer readable / save-write
confirmed), not a graduated level -- an earlier `roomfit_level` 0-4 field encoded probe *progress* rather
than device reality and was removed (`docs/corrections.md`, 2026-07-10).

All fields above are populated by `CapabilityProber.probe()`. After probing, `probe()` applies any matching
per-model override from the device capability file (`src/models/device_capability_file.py`) before returning —
see "Device Capability File" below. This is the single merge point: every caller of `probe()` (CLI commands,
GUI connect flow, secondary workflows) gets file overrides applied automatically with no per-caller changes.

### Device Capability File

A per-model capability override file lets the developer (or, via the user-editable copy in the app data
directory, an end user) correct or extend behaviour for specific WiiM models without code changes:

- Bundled default: `src/models/assets/device_capabilities.json`.
- User-editable copy: `<app data dir>/device_capabilities.json` (seeded from the bundled default on first run;
  edits require an app restart to take effect, matching `AppSettings`' load-once-at-startup convention).
- Schema: a `"models"` object keyed by canonical model name (matching the probed `project` field, case/space/
  underscore-insensitive), each with optional fields mirroring `DeviceCapabilities` (`aliases`,
  `supports_roomfit`, `supports_roomfit_read`, `supports_roomfit_write`, `roomfit_level`,
  `supports_lr_filters`, `supports_profile_enumeration`, `supports_batch_write`, `max_bands`,
  `supported_filter_types`, `sources`, `source_aliases`).
- Models absent from the file keep the fully runtime-probed generic behaviour unchanged.
- `max_bands` acts as a **ceiling** on the probed band count (Requirement 7's 10-band default), never raising it
  past what the device actually reported — e.g. an entry can lower a model's cap below 10. The bundled default
  does **not** raise any model's cap above 10, even WiiM Amp Ultra (whose API reports 12 bands on firmware
  20260409+): the WiiM Home App itself only exposes 10 of those 12 bands to the user, so the default cap matches
  WiiM's own app behaviour rather than under-using the cap-raising mechanism (confirmed by device owner,
  2026-06-27 — see `docs/wiim_api_notes.md` Capability Nuances).
- The bundled default only lists `sources` for the four models that are device-owner-confirmed (WiiM Mini, WiiM
  Amp Ultra, WiiM Sound, WiiM Sound Lite — see `docs/wiim_api_notes.md` "PEQ Source Names"). Models without a
  confirmed source list are deliberately absent from the file and keep live `InputList` probing as the
  authoritative source list (see "Never hard-code capabilities by model name alone" in `docs/wiim_api_notes.md`)
  rather than risk a guessed override masking the real probe result.

### Capability matrix by device

| Device | `supports_peq` | `supports_lr_filters` | `max_filters` | `supports_roomfit` |
|---|---|---|---|---|
| WiiM Ultra | ✅ | ✅ | 10 | ✅ |
| WiiM Amp Ultra | ✅ | ✅ | 10 | ✅ |
| WiiM Amp Pro | ✅ | ✅ | 10 | ✅ |
| WiiM Pro | ✅ | ✅ | 10 | ✅ |
| WiiM Pro Plus | ✅ | ✅ | 10 | ✅ |
| WiiM Amp | ✅ | ✅ | 10 | ✅ |
| WiiM Sound | ✅ | ✅ | 10 | ✅ |
| WiiM Sound Lite | ✅ | ✅ | 10 | ✅ |
| WiiM Mini | ✅ | ✅ | 10 | ❌ |
| Generic LinkPlay | ❌ | ❌ | 0 | ❌ |

> Capability detection must still probe at runtime. These values are defaults/expectations only — firmware updates can change behaviour.

---

## PEQ Settings Model

Represents the full PEQ state for one source on a device (`src/models/peq.py`):

```python
class PEQSettings(BaseModel):
    source_name: str        # e.g. "wifi", "bluetooth", "line-in"
    enabled: bool = True     # Whether PEQ is active for this source
    channel_mode: ChannelMode = ChannelMode.STEREO  # STEREO or LR
    name: str = ""           # Loaded preset name, empty if none
    bands: list[CanonicalFilter] = []     # Stereo mode: shared filter list
    bands_l: list[CanonicalFilter] = []   # L/R mode: left-channel filters
    bands_r: list[CanonicalFilter] = []   # L/R mode: right-channel filters
```

A single `PEQSettings` object holds both channels' data when in L/R mode
(`bands_l`/`bands_r` populated, `bands` left empty) — there are no longer
two separate per-channel objects.

### Channel mode mapping (internal ↔ wire)

`ChannelMode` (`src/models/channel_mode.py`) is the canonical two-value enum
(`STEREO`/`LR`). It centralizes all string conversions:

| `ChannelMode` | WiiM API `channelMode` (`.wire_value`) | Bands key(s) used |
|---|---|---|
| `ChannelMode.STEREO` | `"Stereo"` | `EQBand` |
| `ChannelMode.LR` | `"L/R"` | `EQBandL` + `EQBandR` |

Profile JSON (local storage) uses a separate `.profile_value` mapping:
`ChannelMode.STEREO` → `"stereo"`, `ChannelMode.LR` → `"left"` (a legacy
sentinel meaning "L/R data present" — `"right"` is also accepted on read
for backward compatibility, see `ChannelMode.from_profile`).

---

## PEQ Band Model

Represents a single EQ band at the WiiM API level (not Canonical):

```python
class PEQBand:
    band_number: int   # Band index: 1–10 (or 1–12, see below)
    letter: str    # Band identifier: "a"–"j" (10 bands) or "a"–"l" (12 bands)
    mode: int      # -1=Off, 0=Low Shelf, 1=Peak, 2=High Shelf, 3=Low-Pass, 5=High-Pass
    frequency: float   # 10–22000 Hz
    q: float           # 0.01–24
    gain: float        # -12–+12 dB
```

12-band support (`letter` up to `"l"`) appeared on WiiM Amp Ultra firmware
20260409+; always probe device capabilities at runtime rather than
hard-coding the band count by model.

---

## Profile JSON Schema (Local Storage)

Used for both saved user profiles and automatic backups. The `channel_mode` field determines which filter array(s) are present.

**Stereo mode (`channel_mode: "stereo"`):**
```json
{
  "schema_version": 1,
  "profile_type": "peq",
  "name": "BassBoost",
  "timestamp": "2026-06-04T13:45:00Z",
  "device": {
    "model": "WiiM Ultra",
    "firmware": "6.0.1",
    "uuid": "FF31F09E12345678",
    "mac_address": "AA:BB:CC:DD:EE:FF",
    "source": "wifi",
    "channel_mode": "stereo"
  },
  "filters": [
    {"type": "PEAK", "frequency_hz": 40.0, "gain_db": 4.5, "q": 1.5},
    {"type": "LS",   "frequency_hz": 80.0, "gain_db": 3.0, "q": 0.707},
    {"type": "OFF",  "frequency_hz": 1000.0, "gain_db": 0.0, "q": 1.0}
  ],
  "tags": ["bass", "subwoofer"]
}
```

**L/R mode (`channel_mode: "left"` or `"right"`):** `filters_l` / `filters_r` replace `filters`. The `filters` key must not be present.
```json
{
  "schema_version": 1,
  "profile_type": "peq",
  "name": "LeftRightTrim",
  "timestamp": "2026-06-04T13:45:00Z",
  "device": {
    "model": "WiiM Ultra",
    "firmware": "6.0.1",
    "uuid": "FF31F09E12345678",
    "mac_address": "AA:BB:CC:DD:EE:FF",
    "source": "wifi",
    "channel_mode": "left"
  },
  "filters_l": [
    {"type": "PEAK", "frequency_hz": 1000.0, "gain_db": -1.5, "q": 1.41}
  ],
  "filters_r": [
    {"type": "PEAK", "frequency_hz": 1000.0, "gain_db": 1.5, "q": 1.41}
  ],
  "tags": []
}
```

### Schema rules

- When `channel_mode == "stereo"`: `filters` is present; `filters_l` and `filters_r` must be absent.
- When `channel_mode == "left"` or `"right"`: `filters_l` and `filters_r` are present; `filters` must be absent.
- A profile missing the expected filter key(s) for its `channel_mode` is invalid and must not be loaded silently.

### `profile_type` values

| Value | Meaning |
|---|---|
| `"peq"` | Standard stereo or L/R PEQ profile |
| `"roomfit"` | RoomFit configuration (experimental) |
| `"backup"` | Automatic pre-write backup (not shown in user-facing library) |

### Schema migration

When loading a profile, check `schema_version`. If the version is less than the current version:
- Attempt automatic migration in the Translation Engine.
- Log the migration action.
- If migration is not possible, show a clear error and refuse to load.
- Do not silently ignore unknown fields; log them as warnings.

---

## Backup Record

Backups are stored separately from user profiles (in a `backups/` subdirectory, not visible in the profile library UI) and follow the same schema with `profile_type: "backup"`. They include an additional `trigger` field:

```json
{
  "schema_version": 1,
  "profile_type": "backup",
  "name": "auto_backup_2026-06-04T13-45-00",
  "timestamp": "2026-06-04T13:45:00Z",
  "trigger": "pre_write",
  "device": { "...": "same as profile device block" },
  "filters": [ "..." ],
  "filters_l": [ "..." ],
  "filters_r": [ "..." ]
}
```

- `filters` vs `filters_l`/`filters_r` follow the same `channel_mode` rules as profiles.
- `trigger` values: `"pre_write"` (standard), `"pre_rollback"` (written if a rollback attempt is also about to write).

### Backup retention

Backups are **never automatically deleted** after a successful write — they are the user's recovery reference. Retention policy: keep the **20 most recent backups per device UUID**. When the 21st backup for a device is created, the oldest is deleted. This prevents unbounded growth while preserving a meaningful history.

---

## Floating Point Verification Rules

Never compare floats directly. Use these exact tolerances during read-back verification:

| Parameter | Tolerance | Notes |
|---|---|---|
| Frequency | ±0.1 Hz | WiiM may round to nearest integer or 0.1 Hz |
| Gain | ±0.05 dB | Accounts for firmware rounding |
| Q | ±0.01 | Accounts for firmware rounding |

If any band fails verification beyond these tolerances, the entire write is considered failed and rollback is triggered.
