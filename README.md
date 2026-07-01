# WiiM ↔ REW PEQ Sync Tool

A cross-platform, portable desktop application for transferring, synchronizing, and managing Parametric 
EQ (PEQ) and RoomFit filter configurations between Room EQ Wizard (REW) and WiiM devices on your local 
network.

No cloud services, no telemetry, no accounts — everything runs locally.

Open-source software licensed under the MIT License.

## Disclaimer

This is an independent open-source project.

- [WiiM](https://www.wiimhome.com/) and RoomFit™ are trademarks of Linkplay Technology Inc.
- REW ([Room EQ Wizard](https://www.roomeqwizard.com/)) is developed by John Mulcahy.

This project is not affiliated with, endorsed by, or sponsored by Linkplay Technology Inc. or John Mulcahy.

**This software is provided as-is with no warranty.
The authors assume no responsibility for any damage to your devices. 
Use at your own risk.**

## Features

- Auto-discover WiiM devices on the LAN (mDNS, with subnet-scan fallback)
- Read/write 10-band PEQ — stereo or independent left/right channel
- Import REW EQ text files and REW's HTTP API filter data
- Export WiiM PEQ to REW-compatible text files
- Local profile library: save, load, rename, delete, duplicate, tag
- RoomFit support (experimental, capability-gated per device)
- Per-model capability overrides via an editable `device_capabilities.json` in the app data
  directory (seeded from a bundled default on first run) — lets you correct or extend detected
  capabilities for a specific WiiM model without code changes
- Dry-run mode: preview a translated import before writing anything to a device
- Safe write protocol on every device write: backup → write → read back → verify → rollback on mismatch

## Installation

Requires Python 3.12+.

```bash
git clone <repo-url>
cd wiim-rew-sync
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Usage

### GUI

```bash
python packaging/entry_gui.py
```

A standalone packaged executable (no Python required) can be built per-platform — see
[packaging/README.md](packaging/README.md).

### CLI

The CLI was the original proof-of-concept and remains useful for scripting and headless use:

```bash
wiim-rew-sync list-devices
wiim-rew-sync list-sources --device <ip>
wiim-rew-sync get-filters --device <ip> --source wifi
wiim-rew-sync dry-run-import --file my_measurement.txt
wiim-rew-sync set-filters --file my_measurement.txt --device <ip> --source wifi
wiim-rew-sync peq-toggle --device <ip> --source wifi --state on
```

Run `wiim-rew-sync <command> --help` for the full option list, or `wiim-rew-sync --help` for all
commands (sources, RoomFit profiles, presets, etc.).

## Troubleshooting

**Device discovery slow or not finding your WiiM device on Windows?** Windows Firewall blocks
this app's inbound traffic on networks classified "Public", which silently breaks mDNS discovery
(the app falls back to a slower subnet scan with no error shown). Set your network to "Private"
under **Settings → Network & Internet → Wi-Fi → (your network name) → Network profile type**, then
restart the app. See the in-app Help → Troubleshooting guide
([source](src/gui/assets/help/troubleshooting.md)) for this and other common issues.

## Development

```bash
python3 -m pytest src/tests/test_<module>.py -v --no-cov   # targeted tests (fast)
python3 -m ruff check src/                                  # lint
python3 -m mypy src/                                        # type check
```

See [.kiro/steering/tech.md](.kiro/steering/tech.md) for the full test/lint/type-check workflow,
including why the full test suite shouldn't be run mid-task.

## Project Status

CLI proof-of-concept and GUI implementation are complete and have passed automated QA (470 tests,
96.5%+ coverage on the translation engine, zero lint/type errors). Hardware QA against physical
devices for the GUI-era flows is still pending — see [docs/qa_signoff.md](docs/qa_signoff.md).

## Documentation

Full documentation — architecture, API notes, QA reports, and the deferred-features backlog —
lives in [docs/](docs/README.md). Project context and mandatory domain rules for contributors are
in [.kiro/steering/](.kiro/steering).

## License

MIT — see [LICENSE](LICENSE). Third-party dependency licenses are listed in
[DEPENDENCIES.md](DEPENDENCIES.md).
