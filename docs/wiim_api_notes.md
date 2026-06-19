# WiiM API Notes

## LinkPlay HTTP API

- Base command structure: `https://<device_ip>/httpapi.asp?command=<COMMAND>`
- API is open on LAN. Use `verify=False` for HTTPS due to self-signed certs.
- Port 443 (HTTPS) is standard. Some older devices may respond on port 80 (HTTP).
- All responses are JSON unless the command returns a plain string.

---

## Device Information

| Command | Response | Notes |
|---|---|---|
| `getStatusEx` | Full status object | Includes model, firmware, UUID, IP, `NewVer`, `VersionUpdate`, `InputList`, `plm_support` |
| `getDeviceName` | `{"DeviceName":"Living Room"}` | Friendly name |
| `GetMultiroomInfo` | Multiroom status including `role`, `slave_list` | Role: `0`=solo, `1`=master, `2`=slave |

### `getStatusEx` key fields

```json
{
  "DeviceName": "Living Room",
  "uuid": "FF31F09E...",
  "Release": "6.0.1.20",
  "project": "WiiM_Ultra",
  "VersionUpdate": "1",
  "NewVer": "6.0.2.10",
  "InputList": "[\"wifi\",\"bluetooth\",\"line-in\",\"optical\"]",
  "plm_support": "0x4e"
}
```

`plm_support` is a bitmask for physical inputs:
- bit1: LineIn (Aux)
- bit2: Bluetooth
- bit3: USB
- bit4: Optical
- bit6: Coaxial
- bit8: LineIn 2

---

## PEQ Source Names (confirmed by hardware testing, 2026-06-14)

Source names used in `EQGetLV2SourceBandEx` / `EQSetLV2SourceBand` are model-dependent:

| Model | Sources | Notes |
|-------|---------|-------|
| WiiM Mini (`Muzo_Mini`) | `wifi`, `bluetooth`, `line-in` | |
| WiiM Amp Ultra | `wifi`, `bluetooth`, `HDMI`, `line-in`, `optical` | `wifi` covers Wi-Fi, Ethernet AND USB disk |
| WiiM Sound / Sound Lite | `wifi`, `bluetooth`, `auxIn` | `auxIn` (not `line-in`) |

**Key findings:**
- Source names are **case-sensitive**: `HDMI` (uppercase) returns Stereo slot; `hdmi` (lowercase) returns L/R slot
- The API **accepts any source name** and returns valid-looking PEQ data even for non-existent inputs (returns default L/R template)
- There is **no API command to enumerate valid source names** for a device
- `wifi` source label is shared across Wi-Fi, Ethernet, and USB disk inputs on Amp Ultra
- WiiM Mini appears to have **global PEQ** (all sources share the same EQ data)

---

## RoomFit / Room Correction API (confirmed 2026-06-14)

RoomFit uses the **same LV2 EQ commands** as user PEQ, differentiated by the `EQLevel` parameter:

- `EQLevel: 1` (or omitted) = User PEQ
- `EQLevel: 2` = RoomFit / Room Correction filters

All RoomFit operations use standard LV2 PEQ commands with `"EQLevel": 2` added to the JSON payload. There are **no separate** `getRoomFitStatus`/`getRoomFitBands`/`setRoomFitBands` commands — those were initial assumptions that proved incorrect.

### RoomFit Band Read/Write

**Read RoomFit bands:**
```
EQGetLV2SourceBandEx:<url_encoded_json>
```
JSON payload:
```json
{
  "EQLevel": 2,
  "pluginURI": "http://moddevices.com/plugins/caps/EqNp",
  "source_name": "wifi"
}
```

**Response format:** Identical to PEQ — contains `channelMode`, `EQBandL`/`EQBandR` or `EQBand`, `Name` (loaded profile name), `EQStat` (On/Off).

**Write RoomFit bands (confirmed save, write untested):**
```
EQSetLV2SourceBand:<url_encoded_json>
```
JSON payload (same as PEQ write but with `"EQLevel": 2`):
```json
{
  "EQLevel": 2,
  "pluginURI": "http://moddevices.com/plugins/caps/EqNp",
  "source_name": "wifi",
  "channelMode": "L/R",
  "EQBandL": [...],
  "EQBandR": [...]
}
```

> ✅ Direct band write via `EQSetLV2SourceBand` + `EQLevel: 2` **confirmed working** (2026-06-14). Writes to the API working buffer (not directly to DSP). Must be followed by `EQSourceSave` to persist.
>
> ⚠️ **Side effect of saving to the ACTIVE profile:** `EQSourceSave` with `EQLevel: 2` and the currently-active profile name **deactivates RoomFit** and deselects the profile. Saving to a NEW/different profile name does NOT deactivate RoomFit — the active profile remains selected.

### RoomFit Write Workflow (confirmed 2026-06-14)

The complete write sequence is:
1. `EQv2SourceLoad` — load target profile into API working buffer
2. `EQSetLV2SourceBand` + `EQLevel: 2` — modify bands in the buffer
3. `EQSourceSave` + `EQLevel: 2` + `Name: "<profile>"` — persist buffer to named profile
4. **If saving to the active profile name:** RoomFit deactivates — user must re-select in app
5. **If saving to a new/different name:** RoomFit stays active — user can switch at leisure

**Buffer behaviour after save:** The buffer retains the saved data and adopts the saved profile name. It is NOT cleared. The buffer is device-global, persistent across connections, and survives reboots (stored in flash). It is only overwritten when a profile is actively edited or calibrated via the WiiM app. The app never reads the buffer for display — it uses its own internal state for profile selection and curve rendering. Leaving data in the buffer after our operations is safe and has no observable effect on the WiiM app.

**Recommended UX strategies:**
- Non-destructive: Save as a new profile name → tell user to switch in WiiM app when ready
- Overwrite: Save to the active profile → warn "RoomFit will deactivate; re-select to apply"

### RoomFit Three-Layer Architecture

| Layer | Command | Behaviour |
|-------|---------|-----------|
| Profile storage | `EQv2GetNewList` / `EQSourceSave` / `EQv2Delete` | CRUD for saved profiles |
| API working buffer | `EQv2SourceLoad` → `EQGetLV2SourceBandEx` / `EQSetLV2SourceBand` | Read/write bands of loaded profile |
| DSP-active state | WiiM app only (**no API command exists** — confirmed 2026-06-15) | What's actually applied to audio |

**Key difference from PEQ:** For PEQ (EQLevel 1), `EQGetLV2SourceBandEx` returns the live DSP state without needing a prior load. For RoomFit (EQLevel 2), reads return the working buffer — which is device-global and persistent across connections (not session-scoped). Always `EQv2SourceLoad` before reading to ensure you're reading the intended profile.

### RoomFit DSP Toggle — NOT POSSIBLE (confirmed 2026-06-15)

There is **no HTTP API command** to enable or disable RoomFit processing on the DSP. The following were tested against a WiiM device with RoomFit active:

| Command | Response | Effect on DSP |
|---------|----------|---------------|
| `EQSourceOff` + `EQLevel: 2` + pluginURI | `{'status': 'OK'}` | None |
| `EQChangeSourceFX` + `EQLevel: 2` + pluginURI | `{'status': 'OK'}` | None |
| `EQSourceOff` + `EQLevel: 2` (no pluginURI) | `{'status': 'Failed'}` | None |
| `setRoomCorrection:0` | `OK` (readable via `getRoomCorrection` → `0`) | None — unrelated to LV2 RoomFit |
| `MCURoomCorrection:0` | `unknown command` | N/A |
| `EQSetRoomFit:Off` | `{'status': 'Failed'}` | N/A |
| `EQSetLV2Stat` + `EQLevel: 2` + `EQStat: Off` | `{'status': 'Failed'}` | N/A |

**Conclusion:** The DSP-active state (which RoomFit profile is applied to audio) is controlled exclusively by the WiiM app's internal logic. The HTTP API can read/write/save profiles but cannot activate or deactivate them on the DSP.

### RoomFit Profile CRUD (all confirmed 2026-06-14)

| Operation | Command | Payload |
|-----------|---------|---------|
| List PEQ profiles | `EQv2GetNewList:<json>` | `{"pluginURI": "...EqNp", "EQLevel": 1}` |
| List RoomFit profiles | `EQv2GetNewList:<json>` | `{"pluginURI": "...EqNp", "EQLevel": 2}` |
| Save current as PEQ profile | `EQSourceSave:<json>` | `{"pluginURI": "...", "source_name": "...", "Name": "..."}` |
| Save current as RC profile | `EQSourceSave:<json>` | `{"pluginURI": "...", "source_name": "...", "Name": "...", "EQLevel": 2}` |
| Delete PEQ profile | `EQv2Delete:<json>` | `{"pluginURI": "...", "Name": "..."}` |
| Delete RC profile | `EQv2Delete:<json>` | `{"pluginURI": "...", "Name": "...", "EQLevel": 2}` |
| Load PEQ profile | `EQv2SourceLoad:<json>` | `{"pluginURI": "...", "source_name": "...", "Name": "..."}` (untested) |
| Load RC profile | `EQv2SourceLoad:<json>` | `{"pluginURI": "...", "source_name": "...", "Name": "...", "EQLevel": 2}` (untested) |
| Read active PEQ bands | `EQGetLV2SourceBandEx:<json>` | `{"pluginURI": "...", "source_name": "..."}` |
| Read active RC bands | `EQGetLV2SourceBandEx:<json>` | `{"pluginURI": "...", "source_name": "...", "EQLevel": 2}` |
| Write PEQ bands | `EQSetLV2SourceBand:<json>` | `{"pluginURI": "...", "source_name": "...", "EQBand": [...]}` |
| Write RC bands | `EQSetLV2SourceBand:<json>` | `{"pluginURI": "...", "source_name": "...", "EQBand": [...], "EQLevel": 2}` (untested) |

### Profile List Response

**Example response (EQLevel: 2):**
```json
{
  "custom": [
    {
      "Name": "My RoomFit Profile",
      "channelMode": "L/R",
      "Type": "RC",
      "rc_output": "AUDIO_OUTPUT_SPEAKER_MODE",
      "UpdateAt": "1778180921516"
    }
  ],
  "preset": []
}
```

**Profile metadata fields:**
- `Name` — profile name
- `channelMode` — "Stereo" or "L/R"
- `Type` — "RC" for calibration-created profiles; "Custom" for user-saved profiles (both stored at EQLevel 2)
- `rc_output` — output mode (e.g. `"AUDIO_OUTPUT_SPEAKER_MODE"`)
- `UpdateAt` — timestamp (Unix millis, set by calibration process; absent if not provided during save)

**Quirk:** Profiles saved via `EQSourceSave` with `EQLevel: 2` get `Type: "Custom"` instead of `"RC"`. The `EQLevel: 2` determines RoomFit placement (shown in WiiM app's RoomFit section), not the `Type` field. The "RC" type is reserved for profiles created by the device's own RoomFit calibration process.

### RoomFit Key Observations

- RoomFit is **per-source** — same source_name semantics as PEQ
- RoomFit supports L/R mode independently from user PEQ
- Band data uses the same param_name format (a_mode, a_freq, a_q, a_gain, etc.)
- WiiM Mini (`Muzo_Mini`) has no RoomFit — `EQv2GetNewList` with `EQLevel: 2` returns empty `custom` list and reading bands shows `EQStat: Off`

### Capability Detection (Confirmed)

| Condition | Result |
|-----------|--------|
| `EQv2GetNewList` + `EQLevel: 2` returns non-empty `custom` list | Device has RoomFit profiles |
| `EQGetLV2SourceBandEx` + `EQLevel: 2` returns band data | RoomFit readable |
| `EQSourceSave` + `EQLevel: 2` succeeds | RoomFit profile save works |
| `EQv2Delete` + `EQLevel: 2` succeeds | RoomFit profile delete works |
| Empty list from `EQv2GetNewList` + `EQLevel: 2` AND `EQStat: Off` from band read | Device has no RoomFit (WiiM Mini) |

### Revised Capability Probe Sequence

| Level | Probe | Success Condition |
|---|---|---|
| 0 | (default) | No RoomFit |
| 1 | `EQv2GetNewList:{"pluginURI":"...","EQLevel":2}` | Returns valid response (even if empty list) without "unknown command" |
| 2 | `EQGetLV2SourceBandEx:{"pluginURI":"...","source_name":"wifi","EQLevel":2}` | Returns band data with `EQBand`/`EQBandL`/`EQBandR` |
| 3 | (implicit from level 2) | Band data is parseable into CanonicalFilter list |
| 4 | `EQSetLV2SourceBand` + `EQSourceSave` with `EQLevel: 2` | Buffer write + profile save both succeed (CONFIRMED 2026-06-14). Note: saving to the ACTIVE profile name deactivates RoomFit; saving to a new name does not. |

**Older list command:** `EQv2GetList:<pluginURI>` (plain URI, no JSON) — returns PEQ profiles only, without metadata (just names).
---

## EQ (Non-PEQ) Commands

> ⚠️ **Out of scope for this application.** The following commands control the legacy graphic EQ and preset system. They are documented here for completeness only — this application uses exclusively the LV2 PEQ API (`EQGetLV2BandEx` family). Do not use these commands in implementation.

| Command | Response | Notes |
|---|---|---|
| `EQGetStat` | `{"EQStat":"On"}` | Whether any EQ is active (graphic or PEQ) |
| `EQGetList` | `["Flat","Rock","Custom"]` | Legacy graphic EQ preset names |
| `EQLoad:<name>` | OK | Load a legacy graphic EQ preset |

---

## Parametric EQ (PEQ) — WiiM LV2 API

WiiM's PEQ system is built on the LV2 plugin architecture. The relevant plugin URI is:

```
http://moddevices.com/plugins/caps/EqNp
```

This is the **only** plugin addressed by the PEQ commands below. A separate 10-band graphic EQ plugin (`Eq10HP`) exists but is not part of this application's scope.

### Capability Check

Before issuing any PEQ command, probe for `supports_peq` by attempting `EQGetLV2BandEx`. If it returns a valid response, PEQ is supported. All current WiiM devices (including WiiM Mini) support the LV2 PEQ API. Generic LinkPlay devices do not.

### PEQ Band Model

Each band is identified by a **letter** (`a` through `j` = bands 1–10). Each band has four parameters:

| Parameter | API key | Type | Valid Range |
|---|---|---|---|
| Filter mode | `{letter}_mode` | int | `-1`=Off, `0`=Low Shelf, `1`=Peak, `2`=High Shelf |
| Frequency | `{letter}_freq` | float | 10 – 22000 Hz |
| Q factor | `{letter}_q` | float | 0.01 – 24 |
| Gain | `{letter}_gain` | float | -12 – +12 dB |

Example band parameter list (4 dicts per band, 10 bands = 40 total entries):

```json
[
  {"param_name": "a_mode",  "value": 1.0},
  {"param_name": "a_freq",  "value": 80.0},
  {"param_name": "a_q",     "value": 1.41},
  {"param_name": "a_gain",  "value": -4.0},
  {"param_name": "b_mode",  "value": -1.0},
  ...
]
```

### Channel Modes

| Mode | `channelMode` value | Bands key(s) |
|---|---|---|
| Stereo (shared L+R) | `"Stereo"` | `EQBand` |
| Independent L/R | `"L/R"` | `EQBandL` + `EQBandR` |

### PEQ Read Commands

**Get current source bands (stereo):**
```
EQGetLV2BandEx:<url-encoded pluginURI>
```
Response includes `EQStat`, `channelMode`, `EQBand` (array of 40 param dicts), and optionally `Name`.

**Get bands for a specific source:**
```
EQGetLV2SourceBandEx:<url-encoded JSON>
```
JSON payload: `{"source_name": "wifi", "pluginURI": "http://moddevices.com/plugins/caps/EqNp"}`

Full response:
```json
{
  "EQStat": "On",
  "channelMode": "Stereo",
  "source_name": "wifi",
  "Name": "My Preset",
  "EQBand": [
    {"param_name": "a_mode", "value": 1.0},
    {"param_name": "a_freq", "value": 80.0},
    {"param_name": "a_q",    "value": 1.41},
    {"param_name": "a_gain", "value": -4.0},
    ...
  ]
}
```

For `"L/R"` channel mode, response contains `EQBandL` and `EQBandR` instead of `EQBand`.

### PEQ Write Commands

**Set bands (stereo):**
```
EQSetLV2Band:<url-encoded JSON>
```
JSON payload:
```json
{
  "pluginURI": "http://moddevices.com/plugins/caps/EqNp",
  "channelMode": "Stereo",
  "EQBand": [ ... ]
}
```

**Set bands (L/R mode):**
Same endpoint, but with `"channelMode": "L/R"` and two arrays:
```json
{
  "pluginURI": "http://moddevices.com/plugins/caps/EqNp",
  "channelMode": "L/R",
  "EQBandL": [ ... ],
  "EQBandR": [ ... ]
}
```

**Set bands for a specific source:**
```
EQSetLV2SourceBand:<url-encoded JSON>
```
Add `"source_name": "<source>"` to the payload.

**Set channel mode:**
```
EQSetLV2ChannelMode:<url-encoded JSON>
```
JSON: `{"source_name": "wifi", "pluginURI": "...", "channelMode": "L/R"}`

**Enable PEQ (switch source to PEQ plugin):**
```
EQChangeSourceFX:<url-encoded JSON>
```
JSON: `{"source_name": "wifi", "pluginURI": "http://moddevices.com/plugins/caps/EqNp"}`

Or (current source, legacy):
```
EQChangeFX:<url-encoded pluginURI>
```

**Disable PEQ:**
```
EQSourceOff:<url-encoded JSON>
```
JSON: `{"source_name": "wifi", "pluginURI": "..."}`

Or legacy (current source):
```
EQOff
```

### PEQ Preset Commands

| Command | Payload / Notes |
|---|---|
| `EQGetLV2List:<url-encoded pluginURI>` | Returns `{"custom": [...], "preset": [...]}` — name strings |
| `EQGetLV2NewList:<url-encoded JSON>` | Returns detailed list with `Name`, `channelMode`, `Type` per entry |
| `EQSaveLV2Preset:<url-encoded name>` | Save current source settings as named custom preset |
| `EQSaveLV2SourcePreset:<url-encoded JSON>` | Save specific source: `{"source_name": ..., "pluginURI": ..., "Name": ...}` |
| `EQLoadLV2Preset:<url-encoded JSON>` | Load: `{"pluginURI": ..., "Name": ...}` |
| `EQLoadLV2SourcePreset:<url-encoded JSON>` | Load onto specific source: add `"source_name"` |
| `EQDeleteLV2Preset:<url-encoded JSON>` | Delete: `{"pluginURI": ..., "Name": ...}` |
| `EQRenameLV2Preset:<url-encoded JSON>` | Rename: `{"pluginURI": ..., "Name": ..., "newName": ...}` |

---

## Multiroom

- `GetMultiroomInfo` returns the device's group role: `0`=solo, `1`=master, `2`=slave.
- The multiroom role is **informational only** for this application.
- PEQ and RoomFit filters are per-device — each device in a group has independent EQ settings.
- There is no need to redirect writes to the master. Write directly to whichever device the user selected.
- On older firmware (< 4.2.8020), slave nodes may use internal 10.10.10.x WiFi Direct addresses. Modern firmware keeps all nodes on the LAN with normal IPs.

---

## Zeroconf / mDNS Discovery

WiiM devices advertise via mDNS. Known service types:
- `_wiim._tcp.local.` (primary, WiiM-specific)
- `_linkplay._tcp.local.` (older devices / LinkPlay legacy)
- `_http._tcp.local.` (fallback; generic — do not rely on this alone)

Fallback strategy if mDNS yields no results: subnet scan on ports 80 and 443 with a `getStatusEx` probe. Only consider a host a WiiM device if the response contains a recognisable `project` field.

---

## Capability Nuances

| Device | `supports_peq` | `supports_channel_peq` | `supports_roomfit` | Notes |
|---|---|---|---|---|
| WiiM Ultra | ✅ True | ✅ True | ✅ True | Per-input PEQ (stereo or L/R), dedicated RoomFit band set (stereo or L/R, per-source) |
| WiiM Amp Ultra | ✅ True | ✅ True | ✅ True | Same as Ultra; 12 bands on firmware 20260409+ |
| WiiM Amp Pro | ✅ True | ✅ True | ✅ True | Same capabilities as WiiM Ultra |
| WiiM Pro | ✅ True | ✅ True | ✅ True | Same capabilities as WiiM Ultra |
| WiiM Pro Plus | ✅ True | ✅ True | ✅ True | Same capabilities as WiiM Ultra |
| WiiM Amp | ✅ True | ✅ True | ✅ True | Same capabilities as WiiM Ultra |
| WiiM Sound | ✅ True | ✅ True | ✅ True | Same capabilities as WiiM Ultra |
| WiiM Sound Lite | ✅ True | ✅ True | ✅ True | Same capabilities as WiiM Ultra |
| WiiM Mini | ✅ True | ✅ True | ❌ False | Per-input PEQ (stereo or L/R); **no RoomFit** (empty profile list, EQStat: Off on band read) |
| Generic LinkPlay | ❌ False | ❌ False | ❌ False | LV2 PEQ API unavailable |

**Key distinctions:**
- All WiiM devices except WiiM Mini support a **dedicated RoomFit band set** (separate from PEQ bands, accessed via `EQLevel: 2`).
- RoomFit is **per-source** — same `source_name` semantics as PEQ.
- WiiM Mini supports the full per-input PEQ (including L/R channel mode) but has **no RoomFit capability** (confirmed: empty profile list, bands show `EQStat: Off`).
- Band count varies by device/firmware: 10 bands (a-j) standard, 12 bands (a-l) on WiiM Amp Ultra firmware 20260409+. Always probe dynamically.
- Capability detection must still probe at runtime — firmware updates can change behaviour. Never hard-code capabilities by model name alone.

**Batch Write:** Some firmware supports writing all 10 bands in a single `EQSetLV2Band` payload (standard). Sequential fallback via `WiiMCommandQueue` is still needed if a single-band variant is required by capability detection.

---

## RoomFit API — Implementation Reference

> The RoomFit API has been **confirmed via hardware testing** (2026-06-14). See "RoomFit / Room Correction API" section above for the complete, verified command reference.

### Capability Probe Sequence (Confirmed)

| Level | Probe command | Success condition |
|---|---|---|
| 0 | (no probe) | Device does not have RoomFit at all (WiiM Mini, generic LinkPlay) |
| 1 | `EQv2GetNewList:{"pluginURI":"...","EQLevel":2}` | Returns valid JSON response (not "unknown command") |
| 2 | `EQGetLV2SourceBandEx:{"pluginURI":"...","source_name":"wifi","EQLevel":2}` | Returns readable band data |
| 3 | (implicit from level 2) | Band data is parseable into CanonicalFilter list |
| 4 | `EQSetLV2SourceBand:{"pluginURI":"...","source_name":"wifi","EQLevel":2,...}` + `EQSourceSave` | Buffer write + profile save both succeed (CONFIRMED 2026-06-14). Saving to active profile name deactivates RoomFit; saving to new name does not. |

**Note:** The original assumptions about `getRoomFitStatus`, `getRoomFitBands`, and `setRoomFitBands` commands were incorrect. These commands do not exist. RoomFit uses the standard LV2 PEQ command family with `"EQLevel": 2` added to the payload. See `docs/corrections.md` for the full correction log.

### RoomFit Data Format

RoomFit band data uses the **identical format** to PEQ bands:
- Same `param_name`/`value` pair structure (a_mode, a_freq, a_q, a_gain, ...)
- Same band letters (a-j or a-l depending on device)
- Same `channelMode` semantics ("Stereo" / "L/R")
- Same `EQStat` ("On" / "Off")

This means `wiim_parser.py` and `wiim_generator.py` work unchanged for RoomFit data — only the adapter commands differ (adding `EQLevel: 2`).

---

## Source Names

The `source_name` parameter used in PEQ commands corresponds to the device input source:

| Source | `source_name` value | Notes |
|---|---|---|
| WiFi / Network / Ethernet / USB disk | `"wifi"` | Shared across Wi-Fi, Ethernet, USB on Amp Ultra |
| Bluetooth | `"bluetooth"` | |
| Line In (Aux) | `"line-in"` | WiiM Mini, Amp Ultra |
| Aux In | `"auxIn"` | WiiM Sound / Sound Lite (not "line-in") |
| Optical In | `"optical"` | |
| HDMI | `"HDMI"` | Case-sensitive: uppercase = Stereo slot |

> See "PEQ Source Names" section above for the confirmed per-model breakdown.

---

## Error Handling

| Scenario | Expected behaviour |
|---|---|
| Command not supported | Returns `"unknown command"` or HTTP 400 |
| Device offline | Connection timeout; catch `httpx.TimeoutException` |
| Self-signed cert | Use `verify=False`; do not reject — expected behaviour |
| Malformed JSON response | Log error, raise `WiiMResponseError`, return safe default |
| Slave node targeted | PEQ writes work directly on slave nodes (PEQ is per-device); no redirect needed |

---

## References

1. [HTTP API for WiiM PRODUCTS (official PDF)](https://www.wiimhome.com/pdf/HTTP%20API%20for%20WiiM%20Products.pdf)
2. [wiim-httpapi — community OpenAPI docs](https://github.com/cvdlinden/wiim-httpapi)
3. [pywiim API Reference](https://github.com/mjcumming/pywiim/blob/main/docs/integration/API_REFERENCE.md)
4. [pywiim peq.py source](https://github.com/mjcumming/pywiim/blob/main/pywiim/api/peq.py)
