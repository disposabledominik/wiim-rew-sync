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
| `"LS"` | `LS` | `0` | Low shelf filter |
| `"HS"` | `HS` | `2` | High shelf filter |
| `"OFF"` | `OFF <type>` | `-1` | Disabled band |

### Field constraints

| Field | Type | Valid range | Notes |
|---|---|---|---|
| `type` | string | See table above | Required |
| `frequency_hz` | float | 10.0 – 22000.0 Hz | WiiM hardware range |
| `gain_db` | float | -12.0 – +12.0 dB | WiiM hardware limit; REW range is wider |
| `q` | float | 0.01 – 24.0 | WiiM hardware range |

When importing from REW, gain/Q values outside WiiM's hardware limits must be flagged with a validation warning. The Translation Engine will clip values to WiiM limits before writing.

---

## Device Capabilities Model

```python
class DeviceCapabilities:
    supports_peq: bool                  # True if WiiM LV2 PEQ (EqNp) is available; True on all WiiM devices
    supports_roomfit: bool              # True if a dedicated RoomFit band set exists; False on WiiM Mini
    supports_roomfit_read: bool         # True if RoomFit bands are readable (Level 2+)
    supports_roomfit_write: bool        # True if RoomFit bands are writable (Level 4)
    roomfit_level: int                  # 0–4 (see PRD for level definitions); always 0 for WiiM Mini
    supports_channel_peq: bool          # True if independent L/R channel PEQ is available; True on all WiiM devices
    supports_profile_enumeration: bool  # True if device can list saved PEQ presets
    supports_batch_write: bool          # True if all 10 bands can be set in one payload
    max_filters: int                    # Number of PEQ bands; 10 on all WiiM devices
    model: str                          # e.g. "WiiM Ultra", "WiiM Mini", "WiiM Amp Pro"
    firmware: str                       # e.g. "6.0.1.20"
    uuid: str                           # Device UUID
    mac_address: str                    # Device MAC address
    role: str                           # "solo", "master", or "slave"
    source_names: list[str]             # Available source names, e.g. ["wifi", "bluetooth"]
```

### Capability matrix by device

| Device | `supports_peq` | `supports_channel_peq` | `max_filters` | `supports_roomfit` |
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

Represents the complete PEQ state for one source on a device:

```python
class PEQSettings:
    source_name: str        # e.g. "wifi", "bluetooth", "line-in"
    enabled: bool           # Whether PEQ is active for this source
    channel_mode: str       # "Stereo" or "L/R"
    name: str               # Loaded preset name, empty if none
    bands: list[PEQBand]    # 10 bands (Stereo mode or when channel_mode == "Stereo")
    bands_l: list[PEQBand]  # Left channel bands (L/R mode only)
    bands_r: list[PEQBand]  # Right channel bands (L/R mode only)
```

---

## PEQ Band Model

Represents a single EQ band at the WiiM API level (not Canonical):

```python
class PEQBand:
    letter: str    # Band identifier: "a"–"j" (bands 1–10)
    mode: int      # -1=Off, 0=Low Shelf, 1=Peak, 2=High Shelf
    frequency: float   # 10–22000 Hz
    q: float           # 0.01–24
    gain: float        # -12–+12 dB
```

---

## Profile JSON Schema (Local Storage)

Used for both saved user profiles and automatic backups. The `channel_mode` field in `device` determines which filter array(s) are present.

**Stereo mode:**
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
    "channel_mode": "Stereo"
  },
  "filters": [
    {"type": "PEAK", "frequency_hz": 40.0, "gain_db": 4.5, "q": 1.5},
    {"type": "LS",   "frequency_hz": 80.0, "gain_db": 3.0, "q": 0.707},
    {"type": "OFF",  "frequency_hz": 1000.0, "gain_db": 0.0, "q": 1.0}
  ],
  "tags": ["bass", "subwoofer"]
}
```

**L/R mode:** `channel_mode` is `"L/R"` and `filters_l` / `filters_r` replace `filters`. The `filters` key must not be present.
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
    "channel_mode": "L/R"
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

- When `channel_mode == "Stereo"`: `filters` is present; `filters_l` and `filters_r` must be absent.
- When `channel_mode == "L/R"`: `filters_l` and `filters_r` are present; `filters` must be absent.
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
