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

> ⚠️ **The `InputList` field shown above is illustrative, not observed.** `getStatusEx`'s `InputList` field is unpopulated/absent on every device tested by this project (see `docs/corrections.md`, 2026-06-12 and 2026-07-03 rows) — don't rely on it. Use the "Source Enumeration" commands under "PEQ Source Names" below instead.

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
| WiiM Sound | `wifi`, `bluetooth`, `auxIn` | `auxIn` (not `line-in`) |
| WiiM Sound Lite (incl. `WiiM_Sound_Lite_V2`) | `wifi`, `bluetooth`, `auxIn` | Same source set as WiiM Sound |

These four models (Mini, Amp Ultra, Sound, Sound Lite) are device-owner-confirmed and are the only entries in the bundled `device_capabilities.json` capability file (`src/models/assets/device_capabilities.json`) as of 2026-06-27 — see "Device Capability File" in `docs/data_models.md`. Other models are not yet owned/confirmed and intentionally keep generic runtime-probed behaviour rather than a guessed override.

**Key findings:**
- Source names are **case-sensitive**: `HDMI` (uppercase) returns Stereo slot; `hdmi` (lowercase) returns L/R slot
- The API **accepts any source name** and returns valid-looking PEQ data even for non-existent inputs (returns default L/R template)
- Source names **can** be enumerated at runtime on most devices — see "Source Enumeration" below (WiiM Mini is the confirmed exception; keep using the per-model table above and the capability-file override for it)
- `wifi` source label is shared across Wi-Fi, Ethernet, and USB disk inputs on Amp Ultra
- WiiM Mini appears to have **global PEQ** (all sources share the same EQ data)

### Source Enumeration (confirmed 2026-07-03)

Two plain commands (no JSON payload, same style as `getStatusEx`) return a device's input list directly. (Note: `getAudioInputCapbility` is spelled that way on the wire — missing the second "a" in "Capability" — this is the device's own command name, not a typo in this doc; do not "fix" the spelling when implementing.)

**`getAudioInputCapbility`** — the device's supported/physical inputs:
```
GET https://<ip>/httpapi.asp?command=getAudioInputCapbility
```
```json
{"ver": "1.0", "audioInput": [{"mode": "wifi"}, {"mode": "line-in"}, {"mode": "bluetooth"}, {"mode": "optical"}, {"mode": "HDMI"}, {"mode": "udisk"}]}
```

**`getAudioInputEnable`** — the same set, plus whether each is currently enabled/shown in the WiiM app (`enable: 0` = present in hardware but hidden in the app UI):
```
GET https://<ip>/httpapi.asp?command=getAudioInputEnable
```
```json
{"ver": "1.0", "audioInput": [{"mode": "wifi", "enable": 1}, {"mode": "bluetooth", "enable": 0}, {"mode": "line-in", "enable": 1}, {"mode": "optical", "enable": 0}, {"mode": "HDMI", "enable": 1}]}
```

The `mode` value in both responses is exactly the `source_name` used by every PEQ/RoomFit command.

**Confirmed against real hardware (2026-07-03):**

| Device | `getAudioInputCapbility` | `getAudioInputEnable` |
|---|---|---|
| WiiM Amp Ultra | `wifi`, `line-in`, `bluetooth`, `optical`, `HDMI`, `udisk` | `wifi`(1), `bluetooth`(0), `line-in`(1), `optical`(0), `HDMI`(1) |
| WiiM Sound / Sound Lite | `wifi`, `auxIn`, `bluetooth` | `wifi`(1), `bluetooth`(1), `auxIn`(1) — same on both models |
| WiiM Mini | `"unknown command"` | `"unknown command"` |

**WiiM Mini supports neither command** — it needs the hardcoded fallback table above and the `device_capabilities.json` override; don't rely on runtime enumeration for it. Other untested/older devices should probe both commands and fall back to the hardcoded table on `"unknown command"`.

> ⚠️ **`udisk` is not a real PEQ source — confirmed 2026-07-03.** `getAudioInputCapbility` lists `udisk` as a distinct hardware input mode on Amp Ultra, but at the PEQ layer it behaves exactly like a nonexistent source name: `EQGetLV2SourceBandEx` with `source_name:"udisk"` returned `Name:""` and an all-default L/R template (stock frequencies, zero gain) — the same fallback already documented for made-up source names — and writing to it (`EQv2SourceLoad` targeting `udisk`) returned `{"status":"Failed"}` outright, unlike genuine sources (`wifi`, `HDMI`, `line-in`), which accept loads normally.
>
> **Note `udisk` only appears in `getAudioInputCapbility`'s output, never in `getAudioInputEnable`'s** (confirmed across all tested devices, including with a USB drive connected and actively playing — not just `enable:0`, it's absent from the list entirely even then). Explanation (device owner, 2026-07-03): USB playback on Amp Ultra is implemented as a media server and routes through the same network-playback pipeline as `wifi` — it's not a distinct physical input line the way `line-in`/`HDMI`/`optical`/`bluetooth` are, so it never needs (or gets) its own switchable-input entry or its own PEQ source slot. `getAudioInputCapbility` reports the broader hardware-capability concept (the device supports USB media playback as a feature); `getAudioInputEnable` tracks the narrower set of inputs the app treats as switchable, which is what the PEQ engine's behavior agrees with. **Practical consequence, confirmed safe: build a PEQ source picker from `getAudioInputEnable`'s output, not `getAudioInputCapbility`'s** — it already excludes `udisk` without needing a hardcoded denylist. This confirms the original "PEQ Source Names" table's claim that `wifi` covers USB disk, with no separate PEQ source needed.

curl:
```bash
curl -sk "https://$WIIM_IP/httpapi.asp?command=getAudioInputCapbility"
curl -sk "https://$WIIM_IP/httpapi.asp?command=getAudioInputEnable"
```

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

**Write RoomFit bands (confirmed 2026-06-14):**
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

### Previewing a Saved Profile's Bands Without Disrupting the Active One

There is no stateless "peek" command — reading a specific saved profile's band data requires `EQv2SourceLoad` (stage it into the working buffer) followed by `EQGetLV2SourceBandEx` (read the buffer). This does **not** change the DSP on/off state (a separate toggle — see "RoomFit DSP Toggle" below) but it does replace whichever profile the working buffer, and the WiiM app's own "currently selected" UI state, was previously pointing at.

**Recommended approach:** read the currently-active profile `Name` first (via the empty-`source_name` status read documented under "RoomFit DSP Toggle" below), then before loading a different profile purely to preview its bands, warn the user that doing so changes the selected profile — and offer to restore the original `Name` via a second `EQv2SourceLoad` afterward — rather than silently swapping it.

> This whole approach is confirmed workable for **RoomFit** (global scope, no ambiguity about what gets loaded) and, as of 2026-07-03, also for **PEQ** as long as `source_name` is included explicitly in the `EQv2SourceLoad` payload (see "RoomFit Profile CRUD" below) — read the target source's current `Name` first, load-and-read to preview, then load the original `Name` back to restore.
>
> **Ruled out (2026-07-03):** omitting `source_name` from a PEQ `EQv2SourceLoad` call is *not* a safe stateless preview. It's a real write that silently lands on whichever input is currently live/active on the device — confirmed by observing it follow a live input switch from `HDMI` to `wifi` between two tests. This means it will overwrite whatever the user is actually listening to, with no warning. Always use the explicit-`source_name` load-then-restore pattern above for PEQ; never call `EQv2SourceLoad` without `source_name` for PEQ under any circumstances. See `docs/corrections.md` for the full test trail.

### RoomFit Three-Layer Architecture

| Layer | Command | Behaviour |
|-------|---------|-----------|
| Profile storage | `EQv2GetNewList` / `EQSourceSave` / `EQv2Delete` | CRUD for saved profiles |
| API working buffer | `EQv2SourceLoad` → `EQGetLV2SourceBandEx` / `EQSetLV2SourceBand` | Read/write bands of loaded profile |
| DSP-active state | `EQChangeSourceFX` / `EQSourceOff` (+ `EQLevel:2`, empty `source_name`) to toggle; `EQGetLV2SourceBandEx` (+ `EQLevel:2`, empty `source_name`) → `EQStat` to read — **confirmed 2026-07-02**, see below | What's actually applied to audio |

**Key difference from PEQ:** For PEQ (EQLevel 1), `EQGetLV2SourceBandEx` returns the live DSP state without needing a prior load. For RoomFit (EQLevel 2), reads return the working buffer — which is device-global and persistent across connections (not session-scoped). Always `EQv2SourceLoad` before reading to ensure you're reading the intended profile.

### RoomFit DSP Toggle — CONFIRMED (2026-07-02)

**The DSP toggle exists and is reachable over the local HTTP API.** The 2026-06-15 conclusion below ("not possible") was wrong — see corrected findings first, historical (failed) test table kept afterward for context. Full investigation trail in `docs/corrections.md` (2026-07-02 entry).

**Read current on/off status + active profile name:**
```
EQGetLV2SourceBandEx:<url-encoded json>
```
```json
{"EQLevel": 2, "source_name": "", "pluginURI": "http://moddevices.com/plugins/caps/EqNp"}
```
`EQStat` (`"On"`/`"Off"`) in the response is the toggle state; `Name` is the active profile.

> This is a **different read from the buffer-band read** documented above under "RoomFit Band Read/Write" (which uses a real `source_name`, e.g. `"wifi"`, and returns the loaded profile's band data). The empty-`source_name` variant here is scoped to the global on/off state, not any particular profile's bands — use whichever matches what you need.

**Enable:**
```
EQChangeSourceFX:{"EQLevel":2,"source_name":"","pluginURI":"http://moddevices.com/plugins/caps/EqNp"}
```

**Disable:**
```
EQSourceOff:{"EQLevel":2,"source_name":"","pluginURI":"http://moddevices.com/plugins/caps/EqNp"}
```

> ⚠️ **`source_name` must be an empty string `""`, not a populated source name.** This is the single detail that made the 2026-06-15 test (table below) conclude no toggle existed: the same two commands (`EQChangeSourceFX`/`EQSourceOff`) were tried with a real source name (following the convention every other PEQ/RoomFit command uses), which the device silently accepts — returning `{"status":"OK"}` — but applies to the wrong (per-source) scope instead of the global master switch. RoomFit on/off is global, not per-source, unlike the buffer read/write commands documented above (which do use a real `source_name`, e.g. `"wifi"`).

**curl reproduction (verified against real hardware, 2026-07-02):**
```bash
WIIM_IP=192.168.1.50   # replace with your device's IP

# Read status
curl -sk -G --data-urlencode 'command=EQGetLV2SourceBandEx:{"EQLevel":2,"source_name":"","pluginURI":"http://moddevices.com/plugins/caps/EqNp"}' "https://$WIIM_IP/httpapi.asp"

# Enable
curl -sk -G --data-urlencode 'command=EQChangeSourceFX:{"EQLevel":2,"source_name":"","pluginURI":"http://moddevices.com/plugins/caps/EqNp"}' "https://$WIIM_IP/httpapi.asp"

# Disable
curl -sk -G --data-urlencode 'command=EQSourceOff:{"EQLevel":2,"source_name":"","pluginURI":"http://moddevices.com/plugins/caps/EqNp"}' "https://$WIIM_IP/httpapi.asp"
```

| Command | Payload | Result |
|---|---|---|
| `EQChangeSourceFX` + `EQLevel:2` + `source_name:""` + pluginURI | Enable | ✅ Confirmed — `EQStat` flips to `"On"` |
| `EQSourceOff` + `EQLevel:2` + `source_name:""` + pluginURI | Disable | ✅ Confirmed — `EQStat` flips to `"Off"` |
| `EQGetLV2SourceBandEx` + `EQLevel:2` + `source_name:""` + pluginURI | Read status | ✅ Confirmed — returns `EQStat` and `Name` |

**Note on adapter code:** this documents the API only — `src/adapters/wiim_adapter.py` does not implement `enable_roomfit()`/`disable_roomfit()`/status-read using these commands, and a GUI toggle is intentionally out of scope (product decision, 2026-07-02). The existing `# TODO: RoomFit toggle` marker and disabled-toggle tooltip in the GUI are now stale references to the old "not possible" conclusion and can be removed if touched.

#### Historical failed attempts (2026-06-15) — root cause now understood

The following were tested against a WiiM device with RoomFit active, all before the empty-`source_name` requirement was discovered:

| Command | Response | Effect on DSP | Now understood as |
|---------|----------|---------------|---|
| `EQSourceOff` + `EQLevel: 2` + pluginURI | `{'status': 'OK'}` | None | Non-empty `source_name` — wrong scope (see above) |
| `EQChangeSourceFX` + `EQLevel: 2` + pluginURI | `{'status': 'OK'}` | None | Non-empty `source_name` — wrong scope (see above) |
| `EQSourceOff` + `EQLevel: 2` (no pluginURI) | `{'status': 'Failed'}` | None | pluginURI is required |
| `setRoomCorrection:0` | `OK` (readable via `getRoomCorrection` → `0`) | None — unrelated to LV2 RoomFit | Writes calibration metadata (`{"RC_Version": "...", "Time": "yyyy:MM:dd HH:mm"}`) recorded after a calibration run — not a DSP toggle at all |
| `MCURoomCorrection:0` | `unknown command` | N/A | Not a real command |
| `EQSetRoomFit:Off` | `{'status': 'Failed'}` | N/A | Not a real command |
| `EQSetLV2Stat` + `EQLevel: 2` + `EQStat: Off` | `{'status': 'Failed'}` | N/A | Not a real command |

### RoomFit Profile CRUD (all confirmed 2026-06-14)

| Operation | Command | Payload |
|-----------|---------|---------|
| List PEQ profiles | `EQv2GetNewList:<json>` | `{"pluginURI": "...EqNp", "EQLevel": 1}` |
| List RoomFit profiles | `EQv2GetNewList:<json>` | `{"pluginURI": "...EqNp", "EQLevel": 2}` |
| Save current as PEQ profile | `EQSourceSave:<json>` | `{"pluginURI": "...", "source_name": "...", "Name": "..."}` |
| Save current as RC profile | `EQSourceSave:<json>` | `{"pluginURI": "...", "source_name": "...", "Name": "...", "EQLevel": 2}` |
| Delete PEQ profile | `EQv2Delete:<json>` | `{"pluginURI": "...", "Name": "..."}` |
| Delete RC profile | `EQv2Delete:<json>` | `{"pluginURI": "...", "Name": "...", "EQLevel": 2}` |
| Load PEQ profile | `EQv2SourceLoad:<json>` | `{"EQLevel": 1, "source_name": "wifi", "pluginURI": "http://moddevices.com/plugins/caps/EqNp", "Name": "..."}` — **confirmed 2026-07-03** (curl-tested against real hardware: round-tripped `wifi` from `M16` to `flat` and back, response and follow-up read both correctly reflected `wifi`). **`source_name` is required** — omitting it does not fail, but silently targets a different, unintended source instead (see caveat below). |
| Load RC profile | `EQv2SourceLoad:<json>` | `{"EQLevel": 2, "pluginURI": "http://moddevices.com/plugins/caps/EqNp", "Name": "..."}` — **confirmed 2026-07-02** (curl-tested against real hardware). No `source_name` field. |
| Read active PEQ bands | `EQGetLV2SourceBandEx:<json>` | `{"pluginURI": "...", "source_name": "..."}` |
| Read active RC bands | `EQGetLV2SourceBandEx:<json>` | `{"pluginURI": "...", "source_name": "...", "EQLevel": 2}` |
| Write PEQ bands | `EQSetLV2SourceBand:<json>` | `{"pluginURI": "...", "source_name": "...", "EQBand": [...]}` |
| Write RC bands | `EQSetLV2SourceBand:<json>` | `{"pluginURI": "...", "source_name": "...", "EQBand": [...], "EQLevel": 2}` — confirmed 2026-06-14 |

> ⚠️ **`EQv2SourceLoad` at `EQLevel: 1` (PEQ) requires an explicit `source_name` — confirmed 2026-07-03.** Omitting it (as the RoomFit row's payload does, since RoomFit omits `source_name` on purpose for its global scope) does **not** fail and does **not** target the source you're working with elsewhere in the same session. Adding `"source_name":"wifi"` (or whichever source you mean) to the payload fixes it completely and is confirmed safe — round-tripped repeatedly with correct results.
>
> **Resolved (2026-07-03): omitting `source_name` is a real write, not a preview.** It applies to **whichever input is currently live/active on the device** — confirmed by switching the device's active input from `HDMI` to `wifi` between two otherwise-identical tests and observing the no-`source_name` load's target follow the switch exactly. This is *not* a safe way to inspect a saved preset's bands: it silently overwrites whatever the user happens to be listening to at that moment, with no error and no indication anything unexpected happened. **Never omit `source_name` on a PEQ `EQv2SourceLoad` call.** There is no confirmed stateless way to preview a saved PEQ preset's bands without changing a real source — use the explicit-`source_name` load-then-restore pattern in "Previewing a Saved Profile's Bands" above, which is slower but safe.
>
> **Good news for error handling:** a write targeting an invalid/non-PEQ source (e.g. `udisk` — see "Source Enumeration" above) returns `{"status":"Failed"}` outright rather than silently misbehaving, so a caller can safely check the response status after every `EQv2SourceLoad` call.

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

**curl reproduction (verified against real hardware, 2026-07-02):**
```bash
WIIM_IP=192.168.1.50   # replace with your device's IP

# List saved RoomFit profiles
curl -sk -G --data-urlencode 'command=EQv2GetNewList:{"pluginURI":"http://moddevices.com/plugins/caps/EqNp","EQLevel":2}' "https://$WIIM_IP/httpapi.asp"

# Load/activate a profile by name (use a Name from the list above)
curl -sk -G --data-urlencode 'command=EQv2SourceLoad:{"EQLevel":2,"pluginURI":"http://moddevices.com/plugins/caps/EqNp","Name":"YOUR_PROFILE_NAME"}' "https://$WIIM_IP/httpapi.asp"
```
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

Before issuing any PEQ command, probe for `supports_peq` by attempting `EQGetLV2BandEx`. If it returns a valid response, PEQ is supported. All current WiiM devices (including WiiM Mini) support the LV2 PEQ API. Generic (non-WiiM) LinkPlay devices are assumed not to — this has never actually been tested against real generic LinkPlay hardware by this project; all testing to date has been against WiiM-branded devices only. Treat as a reasonable inference, not a confirmed fact — runtime probing (attempt `EQGetLV2BandEx`, fall back gracefully on `"unknown command"`) is required regardless, so this assumption being wrong wouldn't break anything, just mis-set an expectation.

### PEQ Band Model

Each band is identified by a **letter** (`a` through `j` = bands 1–10 standard; `a` through `l` = bands 1–12 on devices/firmware that support 12 bands — see Key distinctions below). Each band has four parameters:

| Parameter | API key | Type | Valid Range |
|---|---|---|---|
| Filter mode | `{letter}_mode` | int | `-1`=Off, `0`=Low Shelf, `1`=Peak, `2`=High Shelf, `3`=Low-Pass, `5`=High-Pass |
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
JSON: `{"EQLevel": 1, "source_name": "wifi", "pluginURI": "http://moddevices.com/plugins/caps/EqNp"}`

Or (current source, legacy):
```
EQChangeFX:<url-encoded pluginURI>
```

**Disable PEQ:**
```
EQSourceOff:<url-encoded JSON>
```
JSON: `{"EQLevel": 1, "source_name": "wifi", "pluginURI": "..."}`

Or legacy (current source):
```
EQOff
```

> This is the **same command pair as the RoomFit DSP Toggle** documented above — the difference is entirely in the payload: `EQLevel: 1` + a real `source_name` (e.g. `"wifi"`) toggles PEQ for that one source; `EQLevel: 2` + an empty `source_name` toggles RoomFit globally.
>
> **Confirmed working against real hardware (2026-07-03)** — round-tripped on a `line-in` source with an unaffected read in between:
> ```bash
> WIIM_IP=192.168.0.222
>
> # 1. Baseline: EQStat "On"
> curl -sk -G --data-urlencode 'command=EQGetLV2SourceBandEx:{"EQLevel":1,"source_name":"line-in","pluginURI":"http://moddevices.com/plugins/caps/EqNp"}' "https://$WIIM_IP/httpapi.asp"
> # 2. Disable
> curl -sk -G --data-urlencode 'command=EQSourceOff:{"EQLevel":1,"source_name":"line-in","pluginURI":"http://moddevices.com/plugins/caps/EqNp"}' "https://$WIIM_IP/httpapi.asp"
> # 3. Read back: EQStat flipped to "Off", bands unchanged
> curl -sk -G --data-urlencode 'command=EQGetLV2SourceBandEx:{"EQLevel":1,"source_name":"line-in","pluginURI":"http://moddevices.com/plugins/caps/EqNp"}' "https://$WIIM_IP/httpapi.asp"
> # 4. Enable
> curl -sk -G --data-urlencode 'command=EQChangeSourceFX:{"EQLevel":1,"source_name":"line-in","pluginURI":"http://moddevices.com/plugins/caps/EqNp"}' "https://$WIIM_IP/httpapi.asp"
> # 5. Read back: EQStat flipped back to "On"
> curl -sk -G --data-urlencode 'command=EQGetLV2SourceBandEx:{"EQLevel":1,"source_name":"line-in","pluginURI":"http://moddevices.com/plugins/caps/EqNp"}' "https://$WIIM_IP/httpapi.asp"
> ```

### PEQ Preset Commands

> ⚠️ **Confirmed non-functional on current firmware (2026-07-03).** These commands don't appear in use anywhere in the current WiiM Home app (the app uses the `EQv2GetNewList`/`EQv2SourceLoad`/`EQSourceSave`/`EQv2Delete` family instead — see "RoomFit Profile CRUD" above — for both PEQ and RoomFit, distinguished by `EQLevel`), and direct testing backs that up: `EQGetLV2List` (bare `EqNp` pluginURI), `EQGetLV2NewList` (`EqNp` with and without `EQLevel`), and both variants against the older `Eq4p` plugin URI all returned `{"status":"Failed"}` — five different call shapes, zero successes. **Do not use this table; use the `EQv2*` family above instead.**
>
> ⚠️ **Capability gap: there is no known working command to rename a saved PEQ/RoomFit profile.** `EQRenameLV2Preset` was tested directly (`{"pluginURI":"...","Name":"<existing>","newName":"<new>"}`) and returned `{"status":"Failed"}`, confirmed by a follow-up list read showing the name unchanged. Since nothing in the confirmed `EQv2*` family performs a rename either, renaming a saved profile currently has no known API path — the only confirmed workaround is save-as-new-name-then-delete-old (`EQSourceSave` + `EQv2Delete`), which loses the original `UpdateAt`/creation metadata.

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

| Device | `supports_peq` | `supports_lr_filters` | `supports_roomfit` | Notes |
|---|---|---|---|---|
| WiiM Ultra | ✅ True | ✅ True | ✅ True | Per-input PEQ (stereo or L/R), dedicated RoomFit band set (stereo or L/R, per-source) |
| WiiM Amp Ultra | ✅ True | ✅ True | ✅ True | Same as Ultra; API reports 12 bands on firmware 20260409+, but WiiM Home App exposes only 10 of them to the user — this app's default 10-band cap (Requirement 7) matches that, not just a safety margin |
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
- **Confirmed (device owner, 2026-06-27):** on hardware that returns 12 bands via the API (WiiM Amp Ultra), the WiiM Home App itself only exposes/uses 10 of them — the 11th/12th bands are reachable over the API but not surfaced in the official app's PEQ UI. The bundled `device_capabilities.json` intentionally does **not** raise `WiiM_Amp_Ultra`'s `max_bands` ceiling above the generic default for this reason: this app's 10-band cap matches WiiM's own app behaviour rather than under-using available hardware.
- **Confirmed (2026-07-03):** the 12-band count is genuinely per-channel in L/R mode, not a total split across both channels. `EQBandL`/`EQBandR` each independently report 12 bands (letters a-l) in L/R mode — 24 addressable bands total — while `EQBand` reports 12 bands total in Stereo mode. See `docs/corrections.md`.
- Capability detection must still probe at runtime — firmware updates can change behaviour. Never hard-code capabilities by model name alone.

**Batch Write:** Some firmware supports writing all 10 bands in a single `EQSetLV2Band` payload (standard). Sequential fallback via `WiiMCommandQueue` is still needed if a single-band variant is required by capability detection.

---

## RoomFit API — Implementation Reference

> The RoomFit API has been **confirmed via hardware testing** (2026-06-14). See "RoomFit / Room Correction API" section above for the complete, verified command reference. The DSP on/off toggle — previously believed impossible — was also confirmed 2026-07-02; see "RoomFit DSP Toggle — CONFIRMED" above.

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
| Command name not recognized at all | Returns `"unknown command"` or HTTP 400 |
| Command recognized but rejected (bad/missing parameter, wrong target) | Returns `{"status":"Failed"}` — distinct from `"unknown command"`; confirmed for e.g. a `pluginURI`-less `EQSourceOff`, an `EQv2SourceLoad` targeting a non-PEQ source (`udisk`), and every tested variant of the dead "PEQ Preset Commands" family. Check for this explicitly; don't treat any non-`"OK"` response the same as a network failure. |
| Device offline | Connection timeout; catch `httpx.TimeoutException` |
| Self-signed cert | Use `verify=False`; do not reject — expected behaviour |
| Malformed JSON response | Log error, raise `WiiMResponseError`, return safe default |
| Slave node targeted | PEQ writes work directly on slave nodes (PEQ is per-device); no redirect needed |

> ⚠️ **`{"status":"OK"}` confirms the command was accepted — never that it did what you intended.** This project has hit that gap twice on hardware: the RoomFit toggle accepted a populated `source_name` and returned `OK` while silently applying to the wrong scope (`docs/corrections.md`, 2026-07-02), and PEQ's `EQv2SourceLoad` accepted a missing `source_name` and returned success while silently writing to whichever source was currently live rather than the one requested (`docs/corrections.md`, 2026-07-03). **Always verify the specific field you care about changed as expected** (`EQStat`, `Name`, the actual band values) via a follow-up read — don't treat `"OK"` alone as proof of the intended effect. This is exactly what `SafeWrite`/`RoomFitSafeWrite`'s read-back verification already does; the lesson here is to apply the same skepticism to one-off diagnostic/administrative calls, not just the main write path.

---

## References

1. [HTTP API for WiiM PRODUCTS (official PDF)](https://www.wiimhome.com/pdf/HTTP%20API%20for%20WiiM%20Products.pdf)
2. [wiim-httpapi — community OpenAPI docs](https://github.com/cvdlinden/wiim-httpapi)
3. [pywiim API Reference](https://github.com/mjcumming/pywiim/blob/main/docs/integration/API_REFERENCE.md)
4. [pywiim peq.py source](https://github.com/mjcumming/pywiim/blob/main/pywiim/api/peq.py)
