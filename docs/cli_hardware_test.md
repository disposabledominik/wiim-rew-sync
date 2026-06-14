# CLI Hardware Validation — Manual Test Procedure

Task 32 phase gate. All tests must pass before GUI development begins.

---

## Setup

```bash
cd /mnt/c/Users/domin/Desktop/Misc/_dev/wiim-rew-sync

# Create and activate virtual environment (first time only)
python3 -m venv .venv
source .venv/bin/activate

# Install the project
pip install -e ".[dev]"
```

For subsequent sessions, just activate:
```bash
source .venv/bin/activate
```

**Prerequisite:** Your WiiM device must be powered on and connected to the same local network (Wi-Fi or Ethernet) as your PC.

---

## Test 1: Device Discovery

**Command:**
```bash
python3 -m src.cli.main list-devices
```

**Expected output:**
```
Name            | IP             | Model          | Firmware    | Role
----------------+----------------+----------------+-------------+------
<device name>   | 192.168.x.x   | WiiM_<model>   | x.x.x.x    | solo
```

**Pass criteria:**
- [x] Your WiiM device appears in the table
- [x] Name, IP, model, and firmware are all non-empty
- [x] Model starts with "WiiM_" (e.g., WiiM_Pro, WiiM_Mini, WiiM_Ultra), except for WiiM Mini which is listed as "Muzo_Mini".
[Tests performed on 12.06.2026., repeated on 14.06.2026.]

**If no devices found:**
- Try a longer timeout: `python3 -m src.cli.main --timeout 10 list-devices`
- Verify PC and WiiM are on the same subnet
- Check if your router isolates Wi-Fi clients

**Record:** Note the IP address — you'll use it in all subsequent tests as `<IP>`.

---

## Test 2: Read Current Filters

**First, discover available sources:**
```bash
python3 -m src.cli.main list-sources --device <IP>
```
This shows which input sources have PEQ data. Use the source name exactly as shown (case matters: `HDMI` not `hdmi`).

**Command:**
```bash
python3 -m src.cli.main get-filters --device <IP> --source <SOURCE>
```
Replace `<SOURCE>` with a source from `list-sources` (e.g. `wifi`, `HDMI`, `bluetooth`).

**Expected output:**
```
Source: <source> | Mode: stereo

Band | Type | Frequency (Hz) | Gain (dB) | Q
-----+------+----------------+-----------+------
1    | PEAK | 80.00          | -4.00     | 1.410
2    | OFF  | 1000.00        | 0.00      | 1.000
...
10   | OFF  | 1000.00        | 0.00      | 1.000
```

**Pass criteria:**
- [x] Shows 10-12 bands (newer firmware has 12 bands; extra 2 are OFF by default)
- [x] Type values are PEAK, LS, HS, HP, LP, OFF, or ?N (unknown mode N)
- [x] Frequency, gain, and Q are valid numbers
- [x] Compare 2-3 active bands against what the WiiM app shows — values must match
- [x] If device is in L/R mode, both "Left channel:" and "Right channel:" tables appear
[Tests performed on 12.06.2026., repeated on 14.06.2026.]

**Note on source names:** Source names are case-sensitive. Uppercase (e.g. `HDMI`) returns the Stereo PEQ slot. Lowercase (e.g. `hdmi`) returns the L/R slot. Use `list-sources` to find the correct spelling.

---

## Test 3: Dry Run Import

**Create a test REW file:**
```bash
cat > /tmp/test_eq.txt << 'EOF'
Equaliser: Parametric EQ
Filter  1: ON  PK       Fc   100.00 Hz  Gain  -3.50 dB  Q  1.410
Filter  2: ON  LS       Fc    80.00 Hz  Gain   2.00 dB  Q  0.707
Filter  3: ON  HS       Fc 10000.00 Hz  Gain  -1.50 dB  Q  0.500
Filter  4: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter  5: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter  6: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter  7: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter  8: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter  9: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter 10: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
EOF
```

**Command:**
```bash
python3 -m src.cli.main dry-run-import --file /tmp/test_eq.txt
```

**Expected output:**
```
Band | Type | Frequency (Hz) | Gain (dB) | Q
-----+------+----------------+-----------+------
1    | PEAK | 100.00         | -3.50     | 1.410
2    | LS   | 80.00          | 2.00      | 0.707
3    | HS   | 10000.00       | -1.50     | 0.500
4    | OFF  | 1000.00        | 0.00      | 1.000
...
10   | OFF  | 1000.00        | 0.00      | 1.000
```

**Pass criteria:**
- [x] Values match the input file exactly
- [x] No "WiiM range warnings" section (all values in range)
- [x] Exit code 0 (no error message)
[Tests performed on 14.06.2026.]

**Test clamping warning:**
```bash
cat > /tmp/hot_eq.txt << 'EOF'
Equaliser: Parametric EQ
Filter  1: ON  PK       Fc   100.00 Hz  Gain  18.00 dB  Q  1.410
Filter  2: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter  3: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter  4: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter  5: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter  6: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter  7: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter  8: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter  9: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter 10: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
EOF
python3 -m src.cli.main dry-run-import --file /tmp/hot_eq.txt
```

**Expected:** Table shows gain 18.00 in the filter list, PLUS a "WiiM range warnings:" section showing gain will be clamped to +12.0 dB.

- [x] Warning message appears below the table
[Tests performed on 14.06.2026.]

---

## Test 4: Write Filters (Safe Write Protocol)

⚠️ **This modifies your device's EQ settings.** A backup is created automatically before writing.

**Command:**
```bash
python3 -m src.cli.main set-filters --file /tmp/test_eq.txt --device <IP> --source <SOURCE>
```
Use the same `<SOURCE>` from Test 2. If omitted, defaults to "wifi".

**Expected output:**
```
Probing device capabilities...
Backing up...
Writing...
Verifying...
Done!
Verified successfully.
```

**Pass criteria:**
- [x] Exit code 0
- [x] "Verified successfully." is the final line
- [x] Open the WiiM app → EQ/PEQ settings → verify:
  - Band 1: PK (Peak), 100 Hz, -3.5 dB, Q 1.41
  - Band 2: LS (Low Shelf), 80 Hz, +2.0 dB, Q 0.707
  - Band 3: HS (High Shelf), 10000 Hz, -1.5 dB, Q 0.5
  - Bands 4-10: OFF (disabled)
[Tests performed on 14.06.2026.]

**Verify read-back matches:**
```bash
python3 -m src.cli.main get-filters --device <IP>
```
- [x] Output matches what was written
[Tests performed on 14.06.2026.]

**Test L/R write with two files:**
```bash
cat > /tmp/eq_left.txt << 'EOF'
Equaliser: Parametric EQ
Filter  1: ON  PK       Fc    50.00 Hz  Gain  -6.00 dB  Q  3.000
Filter  2: ON  PK       Fc   200.00 Hz  Gain  -4.00 dB  Q  5.000
Filter  3: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter  4: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter  5: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter  6: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter  7: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter  8: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter  9: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter 10: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
EOF
cat > /tmp/eq_right.txt << 'EOF'
Equaliser: Parametric EQ
Filter  1: ON  PK       Fc    60.00 Hz  Gain  -5.00 dB  Q  2.500
Filter  2: ON  PK       Fc   250.00 Hz  Gain  -3.00 dB  Q  4.000
Filter  3: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter  4: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter  5: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter  6: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter  7: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter  8: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter  9: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
Filter 10: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000
EOF
python3 -m src.cli.main set-filters --file /tmp/eq_left.txt --file-right /tmp/eq_right.txt --device <IP> --source <SOURCE>
```

**Pass criteria (L/R write):**
- [x] Exit code 0, "Verified successfully."
- [x] `get-filters` shows both "Left channel:" and "Right channel:" tables
- [x] Left band 1: PK 50 Hz, -6.0 dB, Q 3.0 | Right band 1: PK 60 Hz, -5.0 dB, Q 2.5
- [x] WiiM app shows L/R mode with different filters per channel
[Tests performed on 14.06.2026.]

**To restore original EQ:** Reset PEQ to flat in the WiiM app, or save your original settings before this test.

---

## Test 5: Error Handling

**Non-existent device:**
```bash
python3 -m src.cli.main get-filters --device 192.168.1.254
```
- [x] Prints "Error: ..." to stderr (no Python traceback)
- [x] Exit code 1
[Tests performed on 14.06.2026.]

**Non-existent file:**
```bash
python3 -m src.cli.main dry-run-import --file /tmp/nonexistent.txt
```
- [x] Prints "Error: cannot read file..." to stderr
- [x] Exit code 1
[Tests performed on 14.06.2026.]

**Invalid REW file:**
```bash
echo "Not a REW file" > /tmp/bad.txt
python3 -m src.cli.main dry-run-import --file /tmp/bad.txt
```
- [x] Prints "Error: ..." to stderr
- [x] Exit code 1
[Tests performed on 14.06.2026.]

---

## Recording Results

After all tests, document findings below:

### Device Info
- Device model: WiiM Mini, Amp Ultra & Sound
- Firmware version: WiiM Mini (20260608), Amp Ultra (20260409), Sound (20260408)
- `project` field value: _______________

### Test Results
| Test | Result | Notes |
|------|--------|-------|
| 1. Discovery | PASS | |
| 2. Read filters | PASS | |
| 3. Dry run import | PASS | |
| 4. Write filters | PASS | |
| 5. Error handling | PASS | |

### API Deviations
Document any differences between expected and actual API behavior here. These will be added to `docs/corrections.md`.

| Expected | Actual | Impact |
|----------|--------|--------|
| | | |

---

## What To Do After

- If all tests PASS: Tell Kiro "All CLI hardware tests pass" and we proceed to the GUI phase.
- If any test FAILS: Copy the exact error output and share it. We'll fix the issue and re-test.

---

## Test 6: RoomFit Read/Write

Only applicable to devices that support RoomFit (all WiiM devices except Mini).

**Prerequisite:** A RoomFit profile must exist on the device (created via WiiM app calibration or previous `set-roomfit-filters`). Use `list-roomfit-profiles` to find profile names.

### 6a: RoomFit Profile List

**Command:**
```bash
python3 -m src.cli.main list-roomfit-profiles --device <IP>
```

**Pass criteria:**
- [x] Shows a table of RoomFit profiles (Name | Channel Mode | Type)
- [x] Profiles created by WiiM calibration show `Type: RC`
- [x] WiiM Mini returns "Dedicated RoomFit filters not available on this device (room correction uses PEQ bands instead)" (exit code 1)
- [x] Exit code 0 on supported devices

### 6b: RoomFit Read

**Command:**
```bash
python3 -m src.cli.main get-roomfit-filters --device <IP> --source <SOURCE> --profile <PROFILE_NAME>
```
Use a profile name from the `list-roomfit-profiles` output.

**Pass criteria:**
- [ ] Returns RoomFit band data for the specified profile
- [ ] Band count matches device capability (10 or 12 bands)
- [ ] Values match what the WiiM app shows for that profile
- [ ] WiiM Mini returns an appropriate error message (dedicated RoomFit filters not available)
- [ ] Exit code 0 on success, 1 on unsupported device

### 6c: RoomFit Write (new profile)

**Command:**
```bash
python3 -m src.cli.main set-roomfit-filters --device <IP> --source <SOURCE> --profile "_TestRC_DeleteMe" --file /tmp/test_eq.txt
```

**Pass criteria:**
- [ ] Saves REW filters to a new RoomFit profile name
- [ ] Existing active RoomFit profile remains active and undisturbed
- [ ] New profile appears in `list-roomfit-profiles` output
- [ ] New profile appears in WiiM app → Room Correction → profile list
- [ ] Reading the new profile back shows the written EQ values:
  ```bash
  python3 -m src.cli.main get-roomfit-filters --device <IP> --source <SOURCE> --profile "_TestRC_DeleteMe"
  ```
- [ ] Exit code 0 on success

### 6d: RoomFit API Semantics (reference for test interpretation)

- `get-roomfit-filters` loads the profile into the API buffer first, then reads bands
- `set-roomfit-filters` writes to the buffer, then saves to the named profile
- Saving to a NEW name: safe, does not disrupt active profile
- Saving to the ACTIVE profile name: deactivates RoomFit (user must re-select in WiiM app)
- WiiM Mini accepts commands but produces no-op results (known quirk, see `corrections.md`)

---

## Test 7: PEQ Device Profiles

Tests the PEQ preset list/save/load commands against real hardware.

### 7a: List PEQ profiles

**Command:**
```bash
python3 -m src.cli.main list-peq-profiles --device <IP>
```

**Pass criteria:**
- [ ] Shows a table of PEQ presets stored on the device (Name | Channel Mode)
- [ ] Factory presets (e.g. "Flat", "Rock") appear in output if present
- [ ] Custom presets previously saved via WiiM app appear
- [ ] Exit code 0 (even if list is empty)

### 7b: Save active PEQ as device preset

**Command:**
```bash
# First write some filters, then save as a named preset
python3 -m src.cli.main set-filters --file /tmp/test_eq.txt --device <IP> --source <SOURCE> --save-as "_TestPreset_DeleteMe"
```

**Pass criteria:**
- [ ] `set-filters` succeeds with "Verified successfully."
- [ ] Post-save message confirms profile saved
- [ ] `list-peq-profiles` now shows "_TestPreset_DeleteMe" in the list
- [ ] WiiM app → EQ → Preset list shows "_TestPreset_DeleteMe"
- [ ] Selecting "_TestPreset_DeleteMe" in the WiiM app loads the correct filter values

### 7c: Verify PEQ save doesn't disrupt live state

- [ ] After saving, the active EQ bands are unchanged (PEQ remains applied to audio)
- [ ] No disconnect, no reloading, no deactivation (unlike RoomFit)

### 7d: Cleanup

```bash
# Delete the test preset (or do manually in app if CLI delete not implemented)
```
- [ ] Test preset removed from device

---
---

## Updated Task 32 Phase Gate Scope

Tests 1–5 must pass before GUI work begins (original scope).
Tests 6–7 validate RoomFit and PEQ profile commands added in wave 14.9.
