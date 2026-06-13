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
[Tests performed on 12.06.2026.]

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
[Tests performed on 12.06.2026.]

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
- [ ] Values match the input file exactly
- [ ] No "WiiM range warnings" section (all values in range)
- [ ] Exit code 0 (no error message)

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

- [ ] Warning message appears below the table

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
- [ ] Exit code 0
- [ ] "Verified successfully." is the final line
- [ ] Open the WiiM app → EQ/PEQ settings → verify:
  - Band 1: PK (Peak), 100 Hz, -3.5 dB, Q 1.41
  - Band 2: LS (Low Shelf), 80 Hz, +2.0 dB, Q 0.707
  - Band 3: HS (High Shelf), 10000 Hz, -1.5 dB, Q 0.5
  - Bands 4-10: OFF (disabled)

**Verify read-back matches:**
```bash
python3 -m src.cli.main get-filters --device <IP>
```
- [ ] Output matches what was written

**To restore original EQ:** Reset PEQ to flat in the WiiM app, or save your original settings before this test.

---

## Test 5: Error Handling

**Non-existent device:**
```bash
python3 -m src.cli.main get-filters --device 192.168.1.254
```
- [ ] Prints "Error: ..." to stderr (no Python traceback)
- [ ] Exit code 1

**Non-existent file:**
```bash
python3 -m src.cli.main dry-run-import --file /tmp/nonexistent.txt
```
- [ ] Prints "Error: cannot read file..." to stderr
- [ ] Exit code 1

**Invalid REW file:**
```bash
echo "Not a REW file" > /tmp/bad.txt
python3 -m src.cli.main dry-run-import --file /tmp/bad.txt
```
- [ ] Prints "Error: ..." to stderr
- [ ] Exit code 1

---

## Recording Results

After all tests, document findings below:

### Device Info
- Device model: _______________
- Firmware version: _______________
- `project` field value: _______________

### Test Results
| Test | Result | Notes |
|------|--------|-------|
| 1. Discovery | PASS / FAIL | |
| 2. Read filters | PASS / FAIL | |
| 3. Dry run import | PASS / FAIL | |
| 4. Write filters | PASS / FAIL | |
| 5. Error handling | PASS / FAIL | |

### API Deviations
Document any differences between expected and actual API behavior here. These will be added to `docs/corrections.md`.

| Expected | Actual | Impact |
|----------|--------|--------|
| | | |

---

## What To Do After

- If all tests PASS: Tell Kiro "All CLI hardware tests pass" and we proceed to the GUI phase.
- If any test FAILS: Copy the exact error output and share it. We'll fix the issue and re-test.
