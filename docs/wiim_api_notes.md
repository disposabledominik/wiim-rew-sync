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

## RoomFit / Room Correction API (discovered 2026-06-14)

RoomFit uses the **same LV2 EQ commands** as user PEQ, differentiated by the `EQLevel` parameter:

- `EQLevel: 1` = User PEQ (default, what `EQGetLV2SourceBandEx` returns without specifying)
- `EQLevel: 2` = RoomFit / Room Correction filters

**Read RoomFit bands:**
```
EQGetLV2SourceBandEx:<url_encoded_json>
```
where JSON = `{"EQLevel": 2, "pluginURI": "http://moddevices.com/plugins/caps/EqNp", "source_name": "wifi"}`

**Response format:** Identical to PEQ — contains `channelMode`, `EQBandL`/`EQBandR` or `EQBand`, `Name` (profile name), `EQStat` (On/Off).

**Write RoomFit bands (probable, not yet tested):**
```
EQSetLV2SourceBand:<url_encoded_json>
```
where JSON includes `"EQLevel": 2` alongside the band data.

**Key observations:**
- RoomFit can be per-source (tested with `source_name: "wifi"`)
- RoomFit supports L/R mode independently from user PEQ
- The `Name` field shows the loaded RoomFit profile name
- Band data uses the same param_name format (a_mode, a_freq, a_q, a_gain, etc.)

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

- Check `player.role` from `GetMultiroomInfo`: `0`=solo, `1`=master, `2`=slave.
- EQ changes must always target the **master node's IP**. Slave nodes may be on internal 10.10.10.x addresses (legacy WiFi Direct firmware < 4.2.8020) and unreachable from the LAN.
- For modern firmware (≥ 4.2.8020), all nodes remain on the LAN with normal IPs.
- Before issuing any PEQ write, confirm the target is not a slave.

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
| WiiM Ultra | ✅ True | ✅ True | ✅ True | 10-band per-input PEQ (stereo or L/R), dedicated 10-band RoomFit (stereo or L/R) |
| WiiM Amp Ultra | ✅ True | ✅ True | ✅ True | Same capabilities as WiiM Ultra |
| WiiM Amp Pro | ✅ True | ✅ True | ✅ True | Same capabilities as WiiM Ultra |
| WiiM Pro | ✅ True | ✅ True | ✅ True | Same capabilities as WiiM Ultra |
| WiiM Pro Plus | ✅ True | ✅ True | ✅ True | Same capabilities as WiiM Ultra |
| WiiM Amp | ✅ True | ✅ True | ✅ True | Same capabilities as WiiM Ultra |
| WiiM Sound | ✅ True | ✅ True | ✅ True | Same capabilities as WiiM Ultra |
| WiiM Sound Lite | ✅ True | ✅ True | ✅ True | Same capabilities as WiiM Ultra |
| WiiM Mini | ✅ True | ✅ True | ❌ False | 10-band per-input PEQ (stereo or L/R); **no separate RoomFit band set** |
| Generic LinkPlay | ❌ False | ❌ False | ❌ False | LV2 PEQ API unavailable |

**Key distinctions:**
- All WiiM devices except WiiM Mini support a **dedicated RoomFit band set** (separate from PEQ bands).
- WiiM Mini supports the full 10-band per-input PEQ (including L/R channel mode) but has **no RoomFit capability**.
- Capability detection must still probe at runtime — firmware updates can change behaviour. Never hard-code capabilities by model name alone.

**Batch Write:** Some firmware supports writing all 10 bands in a single `EQSetLV2Band` payload (standard). Sequential fallback via `WiiMCommandQueue` is still needed if a single-band variant is required by capability detection.

---

## RoomFit API (Experimental)

RoomFit is partially undocumented. The following is based on community research and may be incomplete or firmware-specific.

### Capability Probe Sequence

Attempt each command in order. The highest level that succeeds determines the capability level:

| Level | Probe command | Success condition |
|---|---|---|
| 0 | (no probe) | Device does not have RoomFit at all (WiiM Mini, generic LinkPlay) |
| 1 | `getRoomFitStatus` or `getStatusEx` field | Returns a non-error response indicating RoomFit is present and active/inactive |
| 2 | `getRoomFitBands` (or equivalent read command) | Returns readable filter data |
| 3 | Attempt REW text export of the read data | Filter data is parseable and exportable |
| 4 | `setRoomFitBands` or equivalent write command | Returns success without error |

> ⚠️ **Assumption C applies here**: RoomFit API endpoints are not fully documented. During implementation, if any endpoint returns an unexpected response, stop, log the behaviour in `corrections.md`, set the capability to the last confirmed level, and continue.

### RoomFit Data Format (Best-Known)

When readable (Level 2+), RoomFit data is expected to return a filter array in the same band-parameter format as PEQ (`param_name`/`value` pairs). Treat it as a read-only Canonical filter set unless Level 4 is confirmed.

---

## Source Names

The `source_name` parameter used in PEQ commands corresponds to the device input source:

| Source | `source_name` value |
|---|---|
| WiFi / Network | `"wifi"` |
| Bluetooth | `"bluetooth"` |
| Line In (Aux) | `"line-in"` |
| Optical In | `"optical"` |
| Coaxial In | `"coax"` |
| USB | `"udisk"` |

---

## Error Handling

| Scenario | Expected behaviour |
|---|---|
| Command not supported | Returns `"unknown command"` or HTTP 400 |
| Device offline | Connection timeout; catch `httpx.TimeoutException` |
| Self-signed cert | Use `verify=False`; do not reject — expected behaviour |
| Malformed JSON response | Log error, raise `WiiMResponseError`, return safe default |
| Slave node targeted | EQ write will silently do nothing or return an error; always target master |

---

## References

1. [HTTP API for WiiM PRODUCTS (official PDF)](https://www.wiimhome.com/pdf/HTTP%20API%20for%20WiiM%20Products.pdf)
2. [wiim-httpapi — community OpenAPI docs](https://github.com/cvdlinden/wiim-httpapi)
3. [pywiim API Reference](https://github.com/mjcumming/pywiim/blob/main/docs/integration/API_REFERENCE.md)
4. [pywiim peq.py source](https://github.com/mjcumming/pywiim/blob/main/pywiim/api/peq.py)
