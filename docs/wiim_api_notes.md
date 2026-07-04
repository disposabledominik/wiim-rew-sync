# WiiM API Notes

Pragmatic reference for the LinkPlay/WiiM HTTP API surface this project uses. This is a spec, not
a lab notebook — for the investigation history behind any non-obvious rule below (what was tested,
what changed, why), see `docs/corrections.md`. GUI-visible bugs are tracked in
`docs/smoke_test_issues.md`.

## Transport

- Base command structure: `https://<device_ip>/httpapi.asp?command=<COMMAND>`
- Open on LAN, no auth. Self-signed TLS cert — use `verify=False` (`curl -k`).
- Port 443 (HTTPS) is standard; some older devices also respond on port 80 (HTTP).
- Commands are either bare (`getStatusEx`) or `COMMAND:<url-encoded-JSON>`.
- All responses are JSON unless the command returns a plain string.
- Every network call needs an explicit timeout (default 5s) — see `src/adapters/`.

**Making a call:** URL-encode the JSON payload and append it after the command name and a colon.
Every payload shown below substitutes into this same pattern:
```bash
curl -sk -G --data-urlencode 'command=EQGetLV2SourceBandEx:{"EQLevel":2,"source_name":"","pluginURI":"http://moddevices.com/plugins/caps/EqNp"}' "https://$WIIM_IP/httpapi.asp"
```

---

## Discovery

WiiM devices advertise via mDNS:
- `_wiim._tcp.local.` (primary, WiiM-specific)
- `_linkplay._tcp.local.` (older devices / LinkPlay legacy)
- `_http._tcp.local.` (fallback; generic — don't rely on this alone)

Browse both `_wiim`/`_linkplay` types concurrently in one shared timeout window — probing them
sequentially lets an absent service type consume the whole timeout before the other type gets a
chance (`docs/corrections.md`, 2026-06-29).

TXT records are unreliable/empty on tested devices — after resolving an IP via mDNS, call
`getStatusEx` to enrich the device record.

Fallback if mDNS yields nothing: subnet scan on ports 80/443 with a `getStatusEx` probe. Only treat
a host as a WiiM device if the response has a recognizable `project` field (see the `Muzo_Mini`
exception below).

On Windows, the packaged app's firewall rule only allows inbound mDNS replies on the "Private"
network profile — a "Public"-classified Wi-Fi network silently forces the slow subnet-scan fallback
(`docs/corrections.md`, 2026-06-29).

---

## Device Information

| Command | Response | Notes |
|---|---|---|
| `getStatusEx` | Full status object | Model, firmware, UUID, IP, `NewVer`, `VersionUpdate`, `plm_support` |
| `getDeviceName` | `{"DeviceName":"Living Room"}` | Friendly name |
| `GetMultiroomInfo` | `role`, `slave_list` | Role: `0`=solo, `1`=master, `2`=slave |

```json
{
  "DeviceName": "Living Room",
  "uuid": "FF31F09E...",
  "Release": "6.0.1.20",
  "project": "WiiM_Ultra",
  "VersionUpdate": "1",
  "NewVer": "6.0.2.10",
  "plm_support": "0x4e"
}
```

- `project` doesn't always start with `WiiM_` — WiiM Mini reports the legacy OEM name
  `Muzo_Mini`. Match on both.
- `InputList` is documented upstream but unpopulated/absent on every device tested here
  (`docs/corrections.md`, 2026-06-12, 2026-07-03) — don't rely on it. Use Source Discovery below.
- `plm_support` is a bitmask for physical inputs: bit1 LineIn/Aux, bit2 Bluetooth, bit3 USB,
  bit4 Optical, bit6 Coaxial, bit8 LineIn 2.

---

## Source Discovery & Naming

Two bare commands enumerate a device's inputs. (Wire spelling `getAudioInputCapbility` is
correct — missing the second "a" — it's the device's own command name; don't "fix" it.)

**`getAudioInputCapbility`** — supported/physical inputs:
```
GET https://<ip>/httpapi.asp?command=getAudioInputCapbility
```
```json
{"ver": "1.0", "audioInput": [{"mode": "wifi"}, {"mode": "line-in"}, {"mode": "bluetooth"}, {"mode": "optical"}, {"mode": "HDMI"}, {"mode": "udisk"}]}
```

**`getAudioInputEnable`** — same set plus whether each is enabled/shown in the app (`enable:0` =
present in hardware but hidden in the UI):
```
GET https://<ip>/httpapi.asp?command=getAudioInputEnable
```
```json
{"ver": "1.0", "audioInput": [{"mode": "wifi", "enable": 1}, {"mode": "bluetooth", "enable": 0}, {"mode": "line-in", "enable": 1}, {"mode": "optical", "enable": 0}, {"mode": "HDMI", "enable": 1}]}
```

`mode` is exactly the `source_name` used by every PEQ/RoomFit command. **Build source pickers from
`getAudioInputEnable`, not `getAudioInputCapbility`** — the latter includes `udisk`, which isn't a
real addressable PEQ source (see below); the former already excludes it.

WiiM Mini returns `"unknown command"` for both — it has no enumeration endpoint. Fall back to the
per-model table below (and the `device_capabilities.json` override) whenever either command fails.

**Per-model source names** (device-owner-confirmed; the only models in
`src/models/assets/device_capabilities.json` as of 2026-06-27 — see "Device Capability File" in
`docs/data_models.md`):

| Model | Sources | Notes |
|-------|---------|-------|
| WiiM Mini (`Muzo_Mini`) | `wifi`, `bluetooth`, `line-in` | No enumeration endpoint; global PEQ (all sources share one EQ) |
| WiiM Amp Ultra | `wifi`, `bluetooth`, `HDMI`, `line-in`, `optical` | `wifi` covers Wi-Fi, Ethernet, and USB disk |
| WiiM Sound | `wifi`, `bluetooth`, `auxIn` | `auxIn`, not `line-in` |
| WiiM Sound Lite (incl. `WiiM_Sound_Lite_V2`) | `wifi`, `bluetooth`, `auxIn` | Same as WiiM Sound |

Other models: not yet owned/confirmed, keep generic runtime probing rather than a guessed override.

**Key rules:**
- Source names are **case-sensitive**: `HDMI` (uppercase) → Stereo slot; `hdmi` (lowercase) → L/R
  slot. Same physical input, different data.
- The API accepts *any* source name string and returns a valid-looking default L/R template for
  nonexistent ones — it never errors on an unrecognized source at the PEQ layer.
- `udisk` is not a real PEQ source, despite being listed by `getAudioInputCapbility`: reading it
  returns the same all-default template as a nonexistent source, and writing to it
  (`EQv2SourceLoad`) returns `{"status":"Failed"}`. USB playback on Amp Ultra is implemented as a
  media server routed through the `wifi` pipeline, not a distinct input line
  (`docs/corrections.md`, 2026-07-03).

---

## `source_name` & `EQLevel` Reference

Every PEQ/RoomFit command is scoped by two parameters: `EQLevel` (`1`/omitted = PEQ, `2` =
RoomFit) and `source_name`, which takes three non-interchangeable forms. `EQLevel:1` and
`EQLevel:2` are fully independent storage namespaces — a write at one level never bleeds into the
other, confirmed by investigation of an apparent PEQ/RoomFit interaction bug that turned out to be
an unrelated coincidence (`docs/corrections.md`, 2026-07-04; `docs/smoke_test_issues.md` #163).

| Form | Example | Meaning |
|---|---|---|
| Real value | `"source_name": "wifi"` | A specific per-source slot (PEQ) — or an orphaned, unused slot (RoomFit) |
| Empty string | `"source_name": ""` | The device-global/"default" scope |
| Omitted key | *(absent)* | Command-specific — see tables below |

**The API never rejects the wrong form — it silently does something else.** Get this wrong and
you'll overwrite the wrong source, or write to dead storage, with `{"status":"OK"}` and no
indication anything went wrong.

### PEQ (`EQLevel: 1`) — genuinely per-source

| Command(s) | `source_name` | If you get it wrong |
|---|---|---|
| `EQGetLV2SourceBandEx` / `EQSetLV2SourceBand` — band read/write | real value | Reads/writes a different source — usually an obvious mistake |
| `EQChangeSourceFX` / `EQSourceOff` — enable/disable | real value | — |
| `EQv2SourceLoad` — profile load | **required, explicit — never omit** | Silently loads onto whichever input is currently live/active, with no error (`docs/corrections.md`, 2026-07-03) |
| `EQSourceSave` — profile save | **required, explicit — never omit/empty** | Silently captures the wrong source's data instead of the one intended (`docs/corrections.md`, 2026-07-04) |
| `EQv2GetNewList` / `EQv2Delete` — profile list/delete | omit entirely | — |

### RoomFit (`EQLevel: 2`) — a single global buffer, NOT per-source

Despite an identical-looking API surface, RoomFit isn't addressed per-source at all.

| Command(s) | `source_name` | Behavior |
|---|---|---|
| `EQGetLV2SourceBandEx` / `EQSetLV2SourceBand` — band read/write | **`""` (must be present)** | The one real "default" buffer — same one `EQv2SourceLoad` loads into and the app treats as "the" active profile |
| `EQChangeSourceFX` / `EQSourceOff` — master on/off toggle | **`""` (must be present)** | See RoomFit DSP Toggle below |
| `EQv2SourceLoad` / `EQv2Delete` / `EQv2GetNewList` / `EQSourceSave` — profile CRUD | **omit entirely** | Named-profile operations; no source concept |

**Never use a real source name for any RoomFit command.** The API silently accepts one —
`EQGetLV2SourceBandEx` with `source_name:"wifi"` at `EQLevel:2` returns a completely different,
orphaned dataset (unrelated to the real active profile, not tracked in the profile list) — most
likely leftover from this project's own earlier testing under the wrong per-source assumption. Full
test trail: `docs/corrections.md`, 2026-07-04.

**The one trap shared by both:** `EQChangeSourceFX`/`EQSourceOff` is the *same command pair* for
PEQ's per-source toggle and RoomFit's global toggle — only `EQLevel` and `source_name`'s emptiness
distinguish them. Copying the per-source pattern into a RoomFit call is the single easiest mistake
in this API, and it fails silently.

---

## Parametric EQ (PEQ) API

Plugin URI: `http://moddevices.com/plugins/caps/EqNp` (LV2 "EqNp" — the only plugin this app
addresses; the older `Eq4p` and the 10-band graphic `Eq10HP` plugin are out of scope).

### Capability check
Probe with `EQGetLV2BandEx`; a valid response means PEQ is supported. All WiiM-branded devices
(including Mini) support it; generic LinkPlay devices are assumed not to — untested against real
hardware, low-impact either way since runtime probing with graceful fallback is required regardless.

### Band model
Bands are letters `a`-`j` (10 bands, standard) or `a`-`l` (12 bands, WiiM Amp Ultra firmware
20260409+). Four parameters per band:

| Parameter | Key | Type | Range |
|---|---|---|---|
| Filter mode | `{letter}_mode` | int | `-1`=Off, `0`=Low Shelf, `1`=Peak, `2`=High Shelf, `3`=Low-Pass, `5`=High-Pass |
| Frequency | `{letter}_freq` | float | 10–22000 Hz |
| Q factor | `{letter}_q` | float | 0.01–24 |
| Gain | `{letter}_gain` | float | -12–+12 dB |

```json
[
  {"param_name": "a_mode", "value": 1.0},
  {"param_name": "a_freq", "value": 80.0},
  {"param_name": "a_q", "value": 1.41},
  {"param_name": "a_gain", "value": -4.0},
  ...
]
```

**Response formatting:** every numeric `value` in a band read response is rendered with exactly 3
decimal places (`1.000`, `-7.770`, `18000.000`) — confirmed across every PEQ/RoomFit test run
against real hardware this project has done.

**Writes must be rounded to 3 decimal places before sending — this is a real requirement, not just
cosmetic.** REW's live API can return filter values with up to 16 decimal digits (freq/gain/Q);
passing that precision straight through to a WiiM device produced corrupted/stale filters in L/R
mode specifically (Stereo mode didn't reproduce the symptom in testing) — see
`docs/smoke_test_issues.md` #93. Round every value to 3 decimal places before writing, regardless of
channel mode, matching the read side's own precision. When comparing values for verification, use a
numeric tolerance rather than exact-string matching — `utils/fp_compare.py`, not a new ad-hoc check.

Channel modes: `"Stereo"` → single `EQBand` array; `"L/R"` → separate `EQBandL`/`EQBandR` arrays.
12-band devices report 12 bands *per channel* in L/R mode (24 total), not 12 split across both
(`docs/corrections.md`, 2026-07-03).

### Read
```
EQGetLV2SourceBandEx:{"source_name":"wifi","pluginURI":"http://moddevices.com/plugins/caps/EqNp"}
```
```json
{
  "EQStat": "On",
  "channelMode": "Stereo",
  "source_name": "wifi",
  "Name": "My Preset",
  "EQBand": [ ... ]
}
```
For `"L/R"` channel mode, the response contains `EQBandL`/`EQBandR` instead of `EQBand`.
`EQGetLV2BandEx` (bare pluginURI, no `source_name`) reads the current/live source instead of a
named one.

### Write
```
EQSetLV2SourceBand:{"source_name":"wifi","pluginURI":"...","channelMode":"Stereo","EQBand":[...]}
```
`EQSetLV2Band` (no `source_name`) writes the current/live source instead. `channelMode` is set
inline as part of this same write — the only reliable way to switch it (see "Dead commands" below).

**Switching a source's channel mode reveals separately-stored data for that mode — it is not reset
to defaults.** Bands are stored keyed by `(source_name, channelMode)`, not just `source_name`:
writing L/R data to a source previously in Stereo mode can surface a completely different,
pre-existing L/R-mode band set for any bands the write doesn't touch (`docs/corrections.md`,
2026-07-04). **Always include the full intended band set in the same call whenever you change
`channelMode`** — never assume a fresh/default state on a mode switch, and never rely on a partial
write to "top up" a mode you haven't fully specified.

**Known corner case (low-priority tech debt): the non-batch sequential write path is not atomic
across a mode switch.** `WiiMAdapter._write_peq_sequential`/`_write_peq_sequential_lr` (used
whenever `capabilities.supports_batch_write` is `False` — the conservative default, and also what a
*probe exception* falls back to, not just genuinely incapable hardware) send one band per
`EQSetLV2SourceBand` call with a 100ms gap, each call carrying the target `channelMode`. The array
sent is always the full, `max_bands`-padded set (see Band model above — unused bands are already
explicit OFF, not sparse), so this is *not* a missing-content problem. The issue is delivery
granularity: a band's decided-on final value (even OFF) has no effect until that band's own call has
actually gone out, so every call before the last leaves not-yet-sent bands holding whatever was last
stored for that `(source_name, channelMode)` slot — for a mode-switching write, this can be a
completely unrelated old filter curve. For the full ~1s+ duration of the sequential run, the device
processes live audio through this mix, and an interruption partway through (crash, network drop) can
leave the device in a state matching neither the old nor the new configuration. `SafeWrite`'s
rollback (`safe_write.py::_rollback`) shares this: it restores state via the same `write_peq()`, so
it takes the identical one-band-per-call route on the same non-batch devices (low practical risk
when the failed write changed `channelMode` — the mode being rolled back to was untouched by the
failed write — but shares the full risk otherwise). **Trigger requires both:** a device that failed
or lacks the batch-write probe, *and* a write that changes `channelMode`, in the same call — a narrow
intersection, and `SafeWrite`'s read-back verification already catches a wrong end state regardless.
Not queued for a code fix; see `docs/corrections.md`, 2026-07-04, for the full analysis and the
possible mitigations (batch-attempt-first override, `EQSourceOff` muting bracket) if this is ever
prioritized.

### Enable / disable
```
EQChangeSourceFX:{"EQLevel":1,"source_name":"wifi","pluginURI":"..."}   # enable
EQSourceOff:{"EQLevel":1,"source_name":"wifi","pluginURI":"..."}        # disable
```
Legacy current-source forms: `EQChangeFX:<pluginURI>`, bare `EQOff`. Confirmed round-trip against
real hardware (`docs/corrections.md`, 2026-07-03): read `EQStat` → disable → read (Off) → enable →
read (On), bands unchanged throughout. This is the *same command pair* as the RoomFit DSP Toggle
below — see the `source_name` reference above for what distinguishes them.

### Profile CRUD

| Operation | Command | Payload |
|---|---|---|
| List | `EQv2GetNewList:{"pluginURI":"...","EQLevel":1}` | — |
| Save | `EQSourceSave:{"pluginURI":"...","source_name":"wifi","Name":"..."}` | `source_name` **required, real value** |
| Load | `EQv2SourceLoad:{"EQLevel":1,"source_name":"wifi","pluginURI":"...","Name":"..."}` | `source_name` **required, real value — never omit** |
| Delete | `EQv2Delete:{"pluginURI":"...","Name":"..."}` | — |

Once saved, a PEQ preset is a portable, source-independent named object — loadable onto any source
via Load above. The `source_name` requirement is about *which source's current buffer* gets
captured/targeted by Save/Load — a separate concern from the saved object's portability.

**No stateless "peek" command exists** for inspecting a saved preset's bands without disturbing a
real source. Read the target source's current `Name` first, `EQv2SourceLoad` the preset onto it,
read its bands, then `EQv2SourceLoad` the original `Name` back to restore — slower, but the only
confirmed-safe pattern (`docs/corrections.md`, 2026-07-03).

### Dead commands — do not use

**Legacy preset family:** `EQGetLV2List` / `EQGetLV2NewList` / `EQSaveLV2Preset` /
`EQSaveLV2SourcePreset` / `EQLoadLV2Preset` / `EQLoadLV2SourcePreset` / `EQDeleteLV2Preset` /
`EQRenameLV2Preset` — every variant tested returns `{"status":"Failed"}`
(`docs/corrections.md`, 2026-07-03). Use the `EQv2*` family (Profile CRUD above) instead.

**Capability gap:** no known command renames a saved profile (`EQRenameLV2Preset` fails; nothing in
`EQv2*` does it either). Workaround: save-as-new-name + delete-old (loses `UpdateAt` metadata).

**`EQSetLV2ChannelMode`** — every tested source (`bluetooth`, `wifi`, `HDMI`) returns
`{"status":"Failed"}` (`docs/corrections.md`, 2026-07-04). No functional impact: `EQSetLV2SourceBand`'s
inline `channelMode` (see Write above) reliably switches mode on its own.

---

## RoomFit (Room Correction) API

RoomFit reuses the same LV2 PEQ commands as user PEQ, selected via `"EQLevel": 2`. There are no
separate `getRoomFitStatus`/`getRoomFitBands`/`setRoomFitBands` commands.

### Architecture

| Layer | Command(s) | Behavior |
|---|---|---|
| Profile storage | `EQv2GetNewList` / `EQSourceSave` / `EQv2Delete` | Named-profile CRUD |
| Working buffer | `EQv2SourceLoad` → `EQGetLV2SourceBandEx` / `EQSetLV2SourceBand` | Read/write bands of the loaded profile — device-global, persists across connections and reboots |
| DSP-active state | `EQChangeSourceFX` / `EQSourceOff` (toggle) + `EQGetLV2SourceBandEx` → `EQStat` (read) | What's actually applied to audio |

Unlike PEQ, a RoomFit read requires a prior `EQv2SourceLoad` to select the intended profile — the
buffer is global and reads whatever was loaded last, not "the" profile by default.

### Band read/write
```
EQGetLV2SourceBandEx:{"EQLevel":2,"source_name":"","pluginURI":"http://moddevices.com/plugins/caps/EqNp"}
EQSetLV2SourceBand:{"EQLevel":2,"source_name":"","pluginURI":"...","channelMode":"L/R","EQBandL":[...],"EQBandR":[...]}
```
Response format identical to PEQ (`channelMode`, `EQBandL`/`EQBandR` or `EQBand`, `Name`,
`EQStat`). Writes only touch the working buffer — must be followed by `EQSourceSave` to persist.

### Write workflow
1. `EQv2SourceLoad` — load target profile into the working buffer
2. `EQSetLV2SourceBand` (`EQLevel:2`, `source_name:""`) — modify bands
3. `EQSourceSave` (`EQLevel:2`, `Name:"<profile>"`) — persist

**Step 2 is where the 3-decimal write-rounding rule (see PEQ → Band model above) bites hardest in
practice** — the bug that rule documents was first found here: pushing REW-sourced L/R filters
straight to a RoomFit profile produced empty/flat bands (`docs/smoke_test_issues.md` #92, same root
cause as #93). Round every value to 3 decimal places before this step, regardless of channel mode.

**Saving to the currently-active profile name deactivates RoomFit** (device deselects it, user must
re-select in-app). Saving to a new/different name does not deactivate it, and deleting a
*non-active* profile doesn't deactivate it either — only overwriting the active name via Save does.
Recommended UX: save-as-new + tell the user to switch in-app, or save-to-active + warn about
deactivation.

The buffer keeps its data and adopts the saved name after a save — it's never cleared by deleting
other profiles, toggling RoomFit on/off, or a reboot, and leftover buffer data has no observable
effect on the WiiM app (which uses its own internal state for display, not the buffer). **The
reverse isn't true, though:** running a calibration or editing a profile through the WiiM app itself
can overwrite the buffer's contents — don't assume it's stable for an entire session if the user
might also be using the WiiM app at the same time.

### Previewing a saved profile without disrupting the active one
No stateless peek command exists. Read the active profile's `Name` first (via the empty-`source_name`
status read below), `EQv2SourceLoad` the target profile, read its bands, then `EQv2SourceLoad` the
original `Name` back to restore. This changes the working buffer and the app's "currently selected"
state during the preview window — warn the user.

### DSP on/off toggle
```
EQGetLV2SourceBandEx:{"EQLevel":2,"source_name":"","pluginURI":"..."}   # read: EQStat + Name
EQChangeSourceFX:{"EQLevel":2,"source_name":"","pluginURI":"..."}       # enable
EQSourceOff:{"EQLevel":2,"source_name":"","pluginURI":"..."}            # disable
```
Confirmed round-trip against real hardware (`docs/corrections.md`, 2026-07-02): read → disable
(`EQStat`→Off) → read → enable (`EQStat`→On) → read. `source_name` must be present as `""` — a
populated value is silently accepted (`{"status":"OK"}`) but applies to the wrong (per-source) scope
and has no effect on the global toggle; this is why the toggle was originally (wrongly) believed
impossible (`docs/corrections.md`, 2026-06-15 → 2026-07-02).

**Not implemented in `src/adapters/wiim_adapter.py`** — documented for API completeness; a GUI
toggle is intentionally out of scope (product decision, 2026-07-02).

### Profile CRUD

| Operation | Command | Payload |
|---|---|---|
| List | `EQv2GetNewList:{"pluginURI":"...","EQLevel":2}` | — |
| Save | `EQSourceSave:{"pluginURI":"...","Name":"...","EQLevel":2}` | `source_name` **omitted entirely** |
| Load | `EQv2SourceLoad:{"EQLevel":2,"pluginURI":"...","Name":"..."}` | `source_name` **omitted entirely** |
| Delete | `EQv2Delete:{"pluginURI":"...","Name":"...","EQLevel":2}` | — |

Older list variant: `EQv2GetList:<pluginURI>` (plain URI, PEQ profiles only, names without
metadata).

### Profile list response
```json
{
  "custom": [
    {"Name": "My RoomFit Profile", "channelMode": "L/R", "Type": "RC", "rc_output": "AUDIO_OUTPUT_SPEAKER_MODE", "UpdateAt": "1778180921516"}
  ],
  "preset": []
}
```
`Type` is `"RC"` only for profiles created by the device's own calibration process — profiles saved
via this app's `EQSourceSave` always get `Type:"Custom"`, regardless of payload fields
(`docs/corrections.md`, 2026-07-04). `UpdateAt` (Unix millis) is set by calibration; absent
otherwise.

### Capability detection

| Condition | Result |
|---|---|
| `EQv2GetNewList` + `EQLevel:2` returns non-empty `custom` | Device has RoomFit profiles |
| `EQGetLV2SourceBandEx` + `EQLevel:2` returns band data | RoomFit readable |
| `EQSourceSave`/`EQv2Delete` + `EQLevel:2` succeed | Save/delete work |
| Empty `custom` list AND `EQStat:Off` on band read | No RoomFit (e.g. WiiM Mini) |

WiiM Mini silently accepts all RoomFit commands (HTTP 200, valid-looking responses) despite having
no RoomFit hardware — there's no API-level distinction between "RoomFit off" and "RoomFit doesn't
exist." Treat the empty-list + `EQStat:Off` combination above as the signal, not the raw response
status (`docs/corrections.md`, 2026-06-14).

### Notes
- Same `param_name`/band-letter/`channelMode`/`EQStat` format as PEQ — `wiim_parser.py` and
  `wiim_generator.py` work unchanged for RoomFit data; only the adapter commands differ
  (`EQLevel:2`, empty `source_name`).
- WiiM Mini has no RoomFit at all (see capability matrix below).

---

## Legacy EQ (Non-PEQ) Commands — out of scope

The legacy graphic EQ/preset system. Documented for completeness only — this app uses exclusively
the LV2 PEQ API above; do not use these in implementation.

| Command | Response | Notes |
|---|---|---|
| `EQGetStat` | `{"EQStat":"On"}` | Whether any EQ (graphic or PEQ) is active |
| `EQGetList` | `["Flat","Rock","Custom"]` | Legacy graphic EQ preset names |
| `EQLoad:<name>` | OK | Load a legacy graphic EQ preset |

---

## Multiroom

- `GetMultiroomInfo` → group role: `0`=solo, `1`=master, `2`=slave. Informational only for this app.
- PEQ/RoomFit are per-device, not per-group — write directly to whichever device the user selected;
  no redirection to the master needed.
- Older firmware (< 4.2.8020) may put slave nodes on internal 10.10.10.x WiFi Direct addresses;
  modern firmware keeps all nodes on the LAN with normal IPs.

---

## Device Capability Matrix

| Device | PEQ | L/R filters | RoomFit | Batch write | Notes |
|---|---|---|---|---|---|
| WiiM Ultra | ✅ | ✅ | ✅ | untested (not owned) | Per-input PEQ, dedicated RoomFit band set |
| WiiM Amp Ultra | ✅ | ✅ | ✅ | ✅ confirmed | 12 bands on firmware 20260409+ (12 per channel in L/R mode); app UI only exposes 10, so this app's default cap matches the app, not just a safety margin |
| WiiM Amp Pro / Pro / Pro Plus / Amp / Sound / Sound Lite | ✅ | ✅ | ✅ | ✅ confirmed for Sound & Sound Lite; untested for Amp Pro/Pro/Pro Plus/Amp | Same as Ultra |
| WiiM Mini | ✅ | ✅ | ❌ | ❌ confirmed | No RoomFit (empty profile list, `EQStat:Off` on band read). The only owned/tested model that exercises the sequential write path (`_write_peq_sequential`/`_write_peq_sequential_lr`) — see the mode-switch tech debt note below |
| Generic LinkPlay | ❌ (assumed) | ❌ | ❌ | ❌ (assumed) | Untested against real hardware — always probe at runtime regardless |

Band count varies by device/firmware (10 standard, 12 on Amp Ultra 20260409+) — always probe
dynamically, never hard-code by model name alone; firmware updates can change behavior.

Some firmware supports writing all bands in a single `EQSetLV2Band` payload; sequential fallback via
`WiiMCommandQueue` covers devices needing single-band writes. Confirmed via the GUI Diagnostics
panel (device owner, 2026-07-04) across all 4 currently-owned devices: only **WiiM Mini** reports
`supports_batch_write: false` — WiiM Amp Ultra, WiiM Sound, and WiiM Sound Lite all report `true`.
See `docs/corrections.md`, 2026-07-04.

---

## Error Handling

| Scenario | Behavior |
|---|---|
| Command not recognized | `"unknown command"` or HTTP 400 |
| Command recognized but rejected (bad/missing param, wrong target) | `{"status":"Failed"}` — distinct from `"unknown command"`; check for this explicitly |
| Device offline | Connection timeout — catch `httpx.TimeoutException` |
| Self-signed cert | `verify=False` — expected, don't reject |
| Malformed JSON response | Log, raise `WiiMResponseError`, return safe default |
| Slave node targeted | Works directly, no redirect needed (PEQ/RoomFit are per-device) |

**`{"status":"OK"}` confirms the command was accepted — never that it did what you intended.** Hit
twice on real hardware: the RoomFit toggle accepting a populated `source_name` and doing nothing
(`docs/corrections.md`, 2026-07-02), and PEQ's `EQv2SourceLoad` accepting a missing `source_name`
and silently writing to the live source instead of the one requested (`docs/corrections.md`,
2026-07-03). Always verify the specific field you care about via a follow-up read — this is what
`SafeWrite`/`RoomFitSafeWrite` already do for the main write path; apply the same skepticism to
one-off diagnostic/admin calls.

---

## References

1. [HTTP API for WiiM PRODUCTS (official PDF)](https://www.wiimhome.com/pdf/HTTP%20API%20for%20WiiM%20Products.pdf)
2. [wiim-httpapi — community OpenAPI docs](https://github.com/cvdlinden/wiim-httpapi)
3. [pywiim API Reference](https://github.com/mjcumming/pywiim/blob/main/docs/integration/API_REFERENCE.md)
4. [pywiim peq.py source](https://github.com/mjcumming/pywiim/blob/main/pywiim/api/peq.py)
