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
  nonexistent ones — it never errors on an unrecognized source at the PEQ layer. This includes
  garbage strings (a stray test value, or a comma-joined string like `"wifi,bluetooth,auxIn"`) —
  the device stores a slot for whatever was written and will report it back later (e.g. via
  `EQGetSourceModes`, below). **This is not a multi-source or list-of-sources feature** — every
  PEQ/RoomFit command still only ever addresses one literal `source_name` string at a time. Never
  pass a comma-joined or otherwise multi-value string as `source_name`.
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

**Non-`Ex` forms** (`EQGetLV2Band`, `EQGetLV2SourceBand`) return responses identical to their `Ex`
counterparts (including `channelMode`) on every firmware tested so far (`docs/corrections.md`,
2026-07-10). This app uses the `Ex` forms exclusively.

**`EQGetSourceModes`** (bare, no payload) — not in the official API docs, confirmed real on hardware
(`docs/corrections.md`, 2026-07-10): returns every source's PEQ status in one call instead of one
`EQGetLV2SourceBandEx` round-trip per source:
```json
[{"source_name": "wifi", "Name": "M16", "NameL": "M16", "NameR": "M16", "NameLR": "", "NameMulti": "", "channelMode": "Stereo", "EQStat": "On", "pluginURI": "http://moddevices.com/plugins/caps/EqNp"}]
```
`Name` reports the Stereo-mode name, `NameLR` the L/R-mode name — both present simultaneously since
bands are stored keyed by `(source_name, channelMode)` (see Write below); only the slot matching the
source's *current* `channelMode` is live. Can also include rows for the legacy `Eq10HP` graphic-EQ
plugin instead of `EqNp`, and — since the device accepts and stores *any* `source_name` string ever
written, not just real inputs (see "Key rules" in Source Discovery above) — rows for arbitrary
garbage strings a client has written in the past, including comma-joined ones (e.g.
`"wifi,bluetooth,auxIn"`); **these are leftover junk slots, not evidence of a real multi-source
feature.** Filter for `pluginURI == EqNp` and a known real `source_name` if using this. Not used by
this app — equivalent per-source data is already available via `EQGetLV2SourceBandEx` — documented
for completeness only.

### Write
```
EQSetLV2SourceBand:{"source_name":"wifi","pluginURI":"...","channelMode":"Stereo","EQBand":[...]}
```
`EQSetLV2Band` (no `source_name`) writes the current/live source instead. `channelMode` is set
inline as part of this same write — this app's own write path relies on this, and it works reliably
on its own. A separate standalone command, `EQSetChannelMode` (see "Dead commands" below), is also
confirmed to switch mode without touching bands, but isn't used here since the inline form already
covers it in one call.

**A raw `EQSetLV2Band`/`EQSetLV2SourceBand` write drops the source's `Name` association even when
the band values are byte-identical to what's already there** (confirmed on real hardware, `docs/
corrections.md` 2026-07-05): reading a source's bands, then writing the exact same bands straight
back, leaves `EQStat` and the actual filter values unchanged but `Name` comes back `""` on the next
read. This is the write-side counterpart to the RoomFit save-then-delete orphaning documented in the
RoomFit section below — any code that reads bands and writes them back (even unmodified, e.g. to
probe write-capability or as part of a round-trip check) must capture the pre-write `Name` and
`source_name` and restore it via `EQv2SourceLoad` afterward, or the device will silently show "no
active preset" where a real one was selected moments before.

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

### Write workflow
`SafeWrite` (`src/adapters/safe_write.py`) implements the mandatory backup/write/read-back/
verify/rollback protocol above plus the `EQv2SourceLoad` unconditional-enable rule (RoomFit section,
rule 4 below — confirmed for PEQ too, `docs/corrections.md` #192). On a successful write it turns
PEQ on for the source if it was off (deliberate behavior, not suppressed); on failure it restores
the source's original enable-state. `SafeWrite.undo()` restores a previous push's bands and
enable-state together. See `docs/corrections.md` for the redesign rationale (mirrors RoomFit's
push/undo behavior below).

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
| Load | `EQv2SourceLoad:{"source_name":"wifi","pluginURI":"...","Name":"..."}` | `source_name` **required, real value — never omit**; `EQLevel` omitted (device defaults to 1) |
| Delete | `EQv2Delete:{"pluginURI":"...","Name":"..."}` | — |
| Rename | `EQv2Rename:{"pluginURI":"...","Name":"<old>","newName":"<new>"}` | Confirmed working via direct hardware round-trip on ordinary PEQ presets on two device models (`docs/corrections.md`, 2026-07-10) — see "Dead commands" below for the superseded "no rename works" claim. |

Once saved, a PEQ preset is a portable, source-independent named object — loadable onto any source
via Load above. The `source_name` requirement is about *which source's current buffer* gets
captured/targeted by Save/Load — a separate concern from the saved object's portability.

**No stateless "peek" command exists** for inspecting a saved preset's bands without disturbing a
real source. Read the target source's current `Name` first, `EQv2SourceLoad` the preset onto it,
read its bands, then `EQv2SourceLoad` the original `Name` back to restore — slower, but the only
confirmed-safe pattern (`docs/corrections.md`, 2026-07-03). `read_peq_preset_preview()` also
restores the source's original `EQStat` afterward, since `EQv2SourceLoad` turns it on unconditionally
(RoomFit section rule 4 below — confirmed for PEQ too, `docs/corrections.md` #192).

### Dead commands — do not use

**Legacy preset family:** `EQGetLV2List` / `EQGetLV2NewList` / `EQSaveLV2Preset` /
`EQSaveLV2SourcePreset` / `EQLoadLV2Preset` / `EQLoadLV2SourcePreset` / `EQDeleteLV2Preset` /
`EQRenameLV2Preset` — every variant tested returns `{"status":"Failed"}`
(`docs/corrections.md`, 2026-07-03). Use the `EQv2*` family (Profile CRUD above) instead.

**`EQSetLV2ChannelMode`** — every tested source (`bluetooth`, `wifi`, `HDMI`) returns
`{"status":"Failed"}` (`docs/corrections.md`, 2026-07-04). Use `EQSetChannelMode` instead (below), or
the inline `channelMode` field on `EQSetLV2SourceBand` (see Write above), which this app uses.

**`EQSetChannelMode:{"EQLevel":<1|2>,"source_name":"...","pluginURI":"...","channelMode":"Stereo"|"L/R"}`**
— confirmed working via hardware round-trip on two device models (`docs/corrections.md`, 2026-07-10):
switches mode standalone, without an accompanying band write. Not used by this app (the inline form
on `EQSetLV2SourceBand` already covers the same need in one call).

---

## RoomFit (Room Correction) API

RoomFit reuses the same LV2 PEQ commands as user PEQ, selected via `"EQLevel": 2`. There are no
separate `getRoomFitStatus`/`getRoomFitBands`/`setRoomFitBands` commands.

### Architecture

| Layer | Command(s) | Behavior |
|---|---|---|
| Profile storage | `EQv2GetNewList` / `EQSourceSave` / `EQv2Delete` | Named-profile CRUD |
| Working buffer | `EQv2SourceLoad` → `EQGetLV2SourceBandEx` / `EQSetLV2SourceBand` | Read/write bands of the loaded profile — device-global, persists across connections and reboots |
| DSP on/off toggle | `EQChangeSourceFX` / `EQSourceOff` (toggle) + `EQGetLV2SourceBandEx` → `EQStat` (read) | Whether the selected profile is actually applied to audio |

Unlike PEQ, a RoomFit read requires a prior `EQv2SourceLoad` to select the intended profile — the
buffer is global and reads whatever was loaded last, not "the" profile by default.

### Operational rules

1. **Any read of a named profile is a real write to the "selected" state -- and to `EQStat` --
   not a side-effect-free peek.** `EQv2SourceLoad`-ing a profile to read its bands makes it the
   buffer's `Name` (and therefore what `get_roomfit_status()` reports as selected), and, per rule 4
   below, unconditionally turns `EQStat` on if it was off. Code that reads purely to inspect a
   profile (previews, verification reads) must capture the previously-selected `Name` **and**
   `EQStat` first and restore both afterward if they shouldn't change
   (`WiiMAdapter.restore_roomfit_selection_and_enable_state()`).
2. **A profile stays "selected" even while `EQStat` is `"Off"`.** Disabling RoomFit doesn't deselect
   the working buffer's `Name` — it just stops applying it. The instant `EQStat` flips back on,
   whatever's selected is immediately applied to live audio. There is no "disabled and deselected"
   state to fall back on.
3. **Saving under a throwaway name and then deleting it orphans the buffer.** The buffer adopts
   whichever name it was last saved under; deleting that same profile leaves `Name` pointing at
   something that no longer exists (reads back `""`). Any such save-then-delete sequence must
   capture the real pre-save `Name` and restore it via `EQv2SourceLoad` afterward.
4. **`EQv2SourceLoad` unconditionally turns `EQStat` on as a side effect of loading a profile.**
   Confirmed for both RoomFit's global buffer and PEQ's per-source form (`docs/corrections.md`
   #192). `EQSourceSave` does not. Code performing a load-then-something sequence must treat
   `EQStat` with the same care as rule 3, or avoid the sequence entirely when `EQStat` is off and a
   real profile is selected. Reference implementations: `CapabilityProber._probe_roomfit()`'s
   level-4 guard, `WiiMAdapter.restore_roomfit_selection_and_enable_state()` (RoomFit),
   `read_peq_preset_preview()` (PEQ).
5. **`source_name` must be `""` (present, empty) for band read/write and the DSP toggle**
   (`EQGetLV2SourceBandEx`/`EQSetLV2SourceBand`/`EQChangeSourceFX`/`EQSourceOff`); profile-CRUD
   commands (`EQv2SourceLoad`/`EQv2Delete`/`EQv2GetNewList`/`EQSourceSave`) omit it entirely instead.
   Getting this wrong doesn't error — it silently targets an orphaned per-source slot instead of
   RoomFit's real global state. `encode_wiim_command()` enforces this distinction.
6. Saving to the currently-active profile's own name does not deactivate it — the profile stays
   selected and active with its updated content.

Discovery history and hardware-test detail for each rule above: `docs/corrections.md` (search
RoomFit).

### Band read/write
```
EQGetLV2SourceBandEx:{"EQLevel":2,"source_name":"","pluginURI":"http://moddevices.com/plugins/caps/EqNp"}
EQSetLV2SourceBand:{"EQLevel":2,"source_name":"","pluginURI":"...","channelMode":"L/R","EQBandL":[...],"EQBandR":[...]}
```
Response format identical to PEQ (`channelMode`, `EQBandL`/`EQBandR` or `EQBand`, `Name`,
`EQStat`). Writes only touch the working buffer — must be followed by `EQSourceSave` to persist.

### Write workflow
1. `EQv2SourceLoad` — load target profile into the working buffer
2. `EQSetLV2SourceBand` (`EQLevel:2`, `source_name:""`) — modify bands (round every value to 3
   decimal places first — see PEQ → Band model's write-rounding rule; `docs/smoke_test_issues.md`
   #92/#93 is why this matters for RoomFit specifically)
3. `EQSourceSave` (`EQLevel:2`, `Name:"<profile>"`) — persist

`RoomFitSafeWrite` (`src/adapters/safe_write.py`) implements this workflow plus the mandatory
backup/verify/rollback protocol and rules 1-4 above — use it, not `write_roomfit()` directly. On a
successful push it makes the written profile active and turns RoomFit on if it was off (deliberate
behavior, not suppressed); on failure it restores whatever was selected and enabled beforehand.

### Previewing a saved profile without disrupting the active one
No stateless peek command exists (rule 1). Read the active profile's `Name` first (via the
empty-`source_name` status read below), `EQv2SourceLoad` the target profile, read its bands, then
`EQv2SourceLoad` the original `Name` back to restore. This changes the working buffer and the app's
"currently selected" state during the preview window.

### DSP on/off toggle
```
EQGetLV2SourceBandEx:{"EQLevel":2,"source_name":"","pluginURI":"..."}   # read: EQStat + Name
EQChangeSourceFX:{"EQLevel":2,"source_name":"","pluginURI":"..."}       # enable
EQSourceOff:{"EQLevel":2,"source_name":"","pluginURI":"..."}            # disable
```
Implemented as `WiiMAdapter.enable_roomfit()`/`disable_roomfit()`/`set_roomfit_enabled()`, used
internally by `RoomFitSafeWrite`'s push/undo protocol (rule 2). There is no standalone, user-facing
manual toggle in the GUI — these methods are never exposed as an independent user action (product
decision, `docs/corrections.md` 2026-07-02).

### Profile CRUD

| Operation | Command | Payload |
|---|---|---|
| List | `EQv2GetNewList:{"pluginURI":"...","EQLevel":2}` | — |
| Save | `EQSourceSave:{"pluginURI":"...","Name":"...","EQLevel":2}` | `source_name` **omitted entirely** |
| Load | `EQv2SourceLoad:{"EQLevel":2,"pluginURI":"...","Name":"..."}` | `source_name` **omitted entirely** |
| Delete | `EQv2Delete:{"pluginURI":"...","Name":"...","EQLevel":2}` | — |
| Rename | `EQv2Rename:{"pluginURI":"...","Name":"<old>","newName":"<new>","EQLevel":2}` | Confirmed working via hardware round-trip, both on the auto-calibration profile and on ordinary saved RoomFit profiles (`docs/corrections.md`, 2026-07-10) |

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
| Empty `custom` list on `EQv2GetNewList` + `EQLevel:2` | No RoomFit (e.g. WiiM Mini) |

WiiM Mini silently accepts all RoomFit commands (HTTP 200, valid-looking responses) despite having
no RoomFit hardware — there's no API-level distinction between "RoomFit off" and "RoomFit doesn't
exist," and `EQStat` on a RoomFit-less device is not reliably `Off` at rest. Treat the empty-`custom`
-list condition above as the sole signal, not `EQStat` or the raw response status (`docs/
corrections.md`, 2026-06-14, 2026-07-10).

### Calibration-result push commands — out of scope, not used by this app

A second, separate command family exists alongside the `EQLevel:2` LV2 commands above, confirmed
real against hardware across three device models (`docs/corrections.md`, 2026-07-10), but not used
anywhere in this app:

| Command | Payload | Behavior |
|---|---|---|
| `RoomCorrGet` | bare, no payload | Reads "whatever's currently relevant" rather than a fixed RoomFit buffer: `EQLevel:2`/`source_name:"default"` data on a device with real RoomFit profiles, but `EQLevel:1`/live-PEQ-source data on a device with none. |
| `RoomCorrSet:{"EQLevel":2,"pluginURI":"...","EQBand":[...],"UpdateAt":<ms>,"rc_output":"AUDIO_OUTPUT_SPEAKER_MODE"}` | mono | Pushes a calibration result into the RoomFit buffer. Where the write took visible effect, the buffer's `Name` was unconditionally overwritten to `"Auto"` regardless of what was requested — consistent with this being the calibration-completion push, where a fresh profile defaults to `Auto`/`Auto_LR` unless the user renames it. |
| `RoomCorrSetLR:{...,"EQBandL":[...],"EQBandR":[...],...}` | stereo/LR | Same, L/R variant. |
| `RoomCorrSetMode:Measure` / `RoomCorrSetMode:Playback` | bare enum value, exact case confirmed against hardware | Recognized (not "unknown command") but returned `{"status":"Failed"}` on every device model tested. |
| `setRoomCorrection:<RC_Version>` | bare version string | Recognized, returns a plain `"OK"` string (not JSON). Confirmed on two devices **not** to control `EQStat`; accepts an obviously-invalid string identically to a real one — no input validation observed. Effect unconfirmed. |
| `RoomCorrGetMode` | bare, no payload | Recognized on all 4 devices tested, but its response shape is inconsistent: on WiiM Sound and WiiM Sound Lite it returns the expected `{"Mode":"Playback"}` (mirroring `RoomCorrSetMode`'s enum); on WiiM Amp Ultra and WiiM Mini it instead returns the same full profile-dump shape as `RoomCorrGet` (`EQLevel`/`source_name`/`Name`/`EQBand`/`EQStat`, no `Mode` field at all) — i.e. it's not implemented as a distinct command on those two, it just falls through to the `RoomCorrGet` handler. |

**`GetAcousticCapability`** (bare, no payload; not itself part of the `RoomCorr*` family) — a general
subsystem-version report (`PEQ`/`GEQ`/`RC`/`HeadphoneEQ`/`SubLPF`/etc., each with its own `Version`
field). Returns `{"status":"Failed"}` on devices with no acoustic-capability subsystem at all (WiiM
Mini). Its `RC.Version` field turns out to be the real explanation for this family's behavior below.

**Do not use this family.** It duplicates functionality already covered by the confirmed `EQLevel:2`
LV2 commands above, and on RoomFit-less devices it has been observed to corrupt a real `EQLevel:1`
source's `channelMode`/`Name` — this app's own confirmed `EQChangeSourceFX`/`EQSourceOff` calls do
not have this effect. **Confirmed (`docs/corrections.md`, 2026-07-10):** this family's inconsistent
write behavior tracks `GetAcousticCapability`'s `RC.Version` field, not a calibration-session gate:
`RC.Version:"1.1"` (WiiM Sound, WiiM Sound Lite) is exactly where `RoomCorrGetMode` returns a real
`{"Mode":...}` response and `RoomCorrSet` actually mutates the buffer; `RC.Version:"1.0"` (WiiM Amp
Ultra) is exactly where both are aliased/inert. WiiM Mini has no `RC` capability at all
(`GetAcousticCapability` itself fails), consistent with having no RoomFit hardware. Only two
`RC.Version` values have been observed so far — treat "`RC.Version >= 1.1`" as the working
assumption, not a confirmed threshold; a device reporting some other version is untested. Full
investigation trail: `docs/corrections.md`, 2026-07-10.

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
