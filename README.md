# WiiM ↔ REW PEQ Sync Tool

*Built with AI, human-supervised and hardware-tested — see [docs/](docs/README.md) for the QA process.*

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

## Getting Started

Download the pre-built executable for your platform below — no Python required. Launch it like any
other desktop app; the in-app Help → Getting Started guide walks through connecting to a device and
pushing your first set of filters. Prefer to build from source instead? See
[packaging/README.md](packaging/README.md).

### Download

Get the build for your platform from the [latest release](https://github.com/disposabledominik/wiim-rew-sync/releases/latest):
`WiiM-REW-Sync-<version>-windows-x64.zip`, `-macos.zip`, or `-linux-x64.zip`.

Each release asset's filename includes its version (e.g. `WiiM-REW-Sync-v1.2.0-windows-x64.zip`),
so downloads from different releases never collide on disk -- that also means there's no longer a
stable per-OS filename to link to directly, hence the link above going to the release page rather
than straight to a file. Each zip includes a `SHA256SUMS.txt` for its own contents; the release
page also attaches a combined `SHA256SUMS.txt` covering all three zips, for verifying a download
before extracting it.

> **Testing status:** Only the **Windows** build has been verified on real hardware so far. The
> macOS and Linux builds come from the same automated pipeline and are expected to work, but
> haven't been hardware-tested yet — please [open an issue](https://github.com/disposabledominik/wiim-rew-sync/issues)
> if you run into problems on those platforms.

macOS builds are currently unsigned, so Gatekeeper will block the first launch — see
[packaging/README.md](packaging/README.md#macos-app-bundle) for the one-command workaround.

## Troubleshooting

**Device discovery slow or not finding your WiiM device on Windows?** Windows Firewall blocks
this app's inbound traffic on networks classified "Public", which silently breaks mDNS discovery
(the app falls back to a slower subnet scan with no error shown). Set your network to "Private"
under **Settings → Network & Internet → Wi-Fi → (your network name) → Network profile type**, then
restart the app. See the in-app Help → Troubleshooting guide
([source](src/gui/assets/help/troubleshooting.md)) for this and other common issues.

## Project Status

The app is actively developed and used; hardware QA against physical devices is ongoing — see
[docs/qa_signoff.md](docs/qa_signoff.md) and [docs/backlog.md](docs/backlog.md) for current status
and known issues.

## Documentation

Full documentation — architecture, API notes, QA reports, and the deferred-features backlog —
lives in [docs/](docs/README.md).

## Contributing

Want to run from source, use the CLI, or contribute code? See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE). Third-party dependency licenses are listed in
[DEPENDENCIES.md](DEPENDENCIES.md).
