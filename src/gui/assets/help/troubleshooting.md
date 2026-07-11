# Troubleshooting

Solutions for common issues you might encounter when using WiiM REW Sync.

## Device Not Found

If the app cannot discover your WiiM device, try the following:

### Check Network Connectivity

- Ensure your WiiM device is powered on and connected to your network.
- Confirm your computer and the WiiM device are on the same subnet
  (e.g., both on 192.168.1.x). Devices on different VLANs or subnets
  cannot see each other.
- If you use a mesh Wi-Fi system, ensure both devices are on the same
  network segment.

### Firewall and mDNS

The app uses mDNS (multicast DNS, UDP port 5353) to discover devices. mDNS
needs to both send and *receive* multicast traffic — if replies are
blocked, discovery silently falls through to the slower subnet scan every
time, with no error shown. If discovery consistently takes 10+ seconds
instead of 1-3 seconds, this is almost always the cause.

- **Windows network profile (most common cause)** — Windows Firewall
  allows this app's inbound traffic on networks classified **Private**,
  and blocks it on networks classified **Public**. Windows sometimes
  classifies even a trusted home Wi-Fi network as Public by default. To
  check and fix:
  1. Open **Settings → Network & Internet → Wi-Fi → (your network name)**.
  2. Set **Network profile type** to **Private**.
  3. Restart the app and retry discovery.
- **Windows Defender Firewall app rule** — If you didn't see an "Allow
  access" prompt the first time you ran the app, it may have been silently
  blocked. Check **Settings → Privacy & security → Windows Security →
  Firewall & network protection → Allow an app through firewall** and make
  sure this app is listed and allowed for Private networks.
- **Third-party firewalls** — Temporarily disable to test, then add an
  exception for the app (allow inbound UDP 5353).
- **Router settings** — Some routers block multicast between Wi-Fi and
  Ethernet. Check your router's "multicast" or "IGMP snooping" settings.

### Manual Fallback

If mDNS discovery fails, the app automatically tries a subnet scan as a
fallback. This can take 10-15 seconds longer (it probes every address on
your subnet) but can find devices that mDNS misses.

If the device still does not appear, verify it is reachable by navigating
to `http://<device-ip>:443/httpapi.asp?command=getStatusEx` in a browser.

## Parse Errors

If you see a parse error when importing a REW file:

### Unsupported File Format

- Ensure the file is a REW EQ text export (.txt), not a measurement file.
- The file should contain lines like:
  `Filter  1: ON  PK  Fc   100 Hz  Gain  -3.0 dB  Q  1.41`
- Files from other EQ tools may use different formats. Only REW's native
  export format is supported.

### Encoding Issues

- The file should be UTF-8 or ASCII encoded.
- If you see garbled characters in the error message, try re-exporting
  from REW with UTF-8 encoding.

### Too Many Filters

- WiiM devices support up to 10 PEQ bands (12 on some newer firmware
  versions). If your REW file contains more filters than your device
  supports, only the first N enabled filters are imported.
- The app shows a warning when filters are truncated.

## Push Failures

If a push fails partway through:

### Timeout During Write

- The device may be temporarily unreachable. Wait a few seconds and retry.
- Check that no other app (like WiiM Home) is writing to the device
  simultaneously.

### Verification Failed

After writing, the app reads back the filters to confirm they were applied
correctly. If verification fails, what happens next depends on whether you
were overwriting something that already existed:

- **Overwriting an existing PEQ source or RoomFit profile** — the app
  restores your previous settings from the automatic backup. Your original
  configuration is preserved.
- **Saving a brand-new RoomFit profile** — there is no previous state to
  restore, so the app deletes the newly-created profile instead. You're back
  to where you started, just without the (unverified) new profile.

Either way, a status message explains what went wrong and which of the two
outcomes occurred.

### Network Interrupted

If the network drops during a push:

- The app detects the failure and attempts a rollback.
- If rollback also fails (device unreachable), the app saves a local
  backup file and shows the file path so you can restore manually later.

## Rollback

### Automatic Rollback

The app automatically restores your previous settings when:

- Verification fails after a write (filters do not match what was sent)
- The write command returns an error from the device

You do not need to take any action. The rollback is immediate.

### Manual Undo

After a successful push, click "Undo" on the result screen to restore
your previous configuration. This is available immediately after pushing
and uses the same automatic backup.

For multi-source pushes, Undo restores all sources that were written to.

### Backup Files

If automatic rollback cannot reach the device, the backup is preserved
as a JSON file. You can find the path:

- In the error message shown on screen
- In Settings under "Paths" (backup directory)

To manually restore: re-connect to your device, load the backup file as
a preset from My Saved Presets, and push it again.

## Wrong Capabilities Detected for Your Device

If the app gets your device's capabilities wrong — e.g. shows RoomFit as
unavailable when your model supports it, omits a source you actually have,
or applies the wrong max-band limit — you can correct this without waiting
for an app update, by editing `device_capabilities.json` in the app data
folder (path shown in Settings under "Paths"). It's seeded from a bundled
default on first run; restart the app after editing to pick up changes.

This file is for advanced users comfortable editing JSON. Malformed entries
are skipped (logged, not crashed) and the app falls back to its normal
detection for that device.

### File Format

The file has one top-level `models` object. Each key is a device model name
exactly as the device reports it (e.g. `"WiiM_Amp"`), mapped to an object of
overrides:

```json
{
  "models": {
    "WiiM_Mini": {
      "aliases": ["Muzo_Mini"],
      "supports_roomfit": false,
      "supports_roomfit_read": false,
      "supports_roomfit_write": false,
      "supports_lr_filters": true,
      "supports_profile_enumeration": true,
      "supports_batch_write": false,
      "max_bands": 10,
      "supported_filter_types": ["PEAK", "LS", "HS"],
      "sources": ["wifi", "bluetooth", "line-in"],
      "source_aliases": {"line-in": "AUX"}
    }
  }
}
```

Every field is optional — only include the ones you want to override. Any
field you omit keeps whatever the app's normal runtime detection found for
your device.

| Field | Type | Meaning |
|---|---|---|
| `aliases` | list of text | Alternate model names that should match this same entry (e.g. an older firmware reports a different model string for the same hardware). Matching ignores case, spaces, and underscores. |
| `supports_roomfit` | true/false | Whether the device supports RoomFit at all. |
| `supports_roomfit_read` | true/false | Whether RoomFit profiles can be read from the device. |
| `supports_roomfit_write` | true/false | Whether RoomFit profiles can be written to the device. |
| `roomfit_level` | number | Legacy field from older app versions (a 0-4 level). Still accepted: it maps onto the three `supports_roomfit*` fields above when those aren't set explicitly. New entries should use the true/false fields instead. |
| `supports_lr_filters` | true/false | Whether independent Left/Right channel filters are supported. |
| `supports_profile_enumeration` | true/false | Whether the device can list its saved PEQ/RoomFit profiles. |
| `supports_batch_write` | true/false | Whether all bands can be written in a single command instead of one at a time. |
| `max_bands` | number | Maximum PEQ/RoomFit bands to use for this model. This is a ceiling, not an override — it can lower the number of bands the app uses below what your device actually reports, but never raise it above that. |
| `supported_filter_types` | list of text | Which filter types this model accepts, e.g. `["PEAK", "LS", "HS", "LP", "HP"]`. |
| `sources` | list of text | The list of audio source names shown for this model (e.g. `"wifi"`, `"bluetooth"`, `"optical"`, `"line-in"`, `"HDMI"`, `"auxIn"`). |
| `source_aliases` | object of text:text | Maps an internal source name to a friendlier display name shown in the app, e.g. `{"line-in": "AUX"}`. |

A model not listed in the file at all keeps fully automatic, runtime-probed
behavior — this file only needs entries for the specific models you want to
correct or extend.

## REW API Connection Issues

If "Pull from REW" is not working:

- Ensure REW is running on your computer.
- In REW, go to Preferences and enable the HTTP server.
- REW's API listens on port 4735 by default. Ensure nothing else is using
  that port.
- If REW was started after this app, the connection will be detected
  automatically on next operation.

## Getting More Help

### Support Bundle

If you encounter an issue you cannot resolve, generate a support bundle:

1. Go to Settings (sidebar).
2. Scroll to the "Support" section.
3. Click "Generate Support Bundle."

This creates a zip file containing your app logs and configuration
(no personal data or EQ settings). Share this file when seeking help.

### Log Files

The app maintains three log files:

- **app.log** — General application events
- **wiim_api.log** — All communication with your WiiM device
- **rew_api.log** — All communication with REW

Find log files via Settings. Log files rotate automatically and do not
grow indefinitely.

### Diagnostics Panel

For advanced troubleshooting, open the Diagnostics panel from the menu.
This developer tool lets you:

- Send raw API commands to your WiiM device
- View the device's full capability information
- Browse recent API logs
