# Future Phase Features (Backlog)

*These items are explicitly excluded from the MVP and CLI Proof of Concept phases.*

---

## Priority: Before GUI Phase

- [ ] **Test coverage for hardware-testing findings**: Add automated tests for all API behaviors discovered during manual hardware validation:
  - LP (mode 3) and HP (mode 5) filter type parsing and generation
  - 12-band devices (letters a-l, 48-entry arrays) alongside 10-band devices
  - `Muzo_Mini` recognized as a valid WiiM device in capability prober
  - mDNS enrichment (discovery calls `getStatusEx` to populate model/firmware)
  - CLI L/R auto-detection (when device is in L/R mode and no `--channel` specified)
  - CLI `list-sources` command output
  - Source name case sensitivity behavior (uppercase = Stereo, lowercase = L/R)

- [ ] **Rethink source discovery**: The WiiM API accepts any source name and returns valid PEQ data regardless of whether the physical input exists. Need a reliable mechanism to show only real inputs. Options to investigate:
  - Check if `getStatusEx` has model-specific input fields on other firmware versions
  - Try `GetAudioInputList` or similar undocumented endpoints on newer firmware
  - Maintain a model-to-inputs mapping table (fragile but functional)
  - Accept the limitation and let users configure which sources to show (per-device preference)

---

## Future Phase Features

- [ ] **Live REW Synchronization**: Auto-sync filters as they are tweaked in REW.
- [ ] **Profile Comparison & Diffing**: Visually or textually compare two PEQ profiles to highlight changes.
- [ ] **Multi-Device Deployment**: Push a single PEQ configuration to multiple grouped WiiM devices simultaneously.
- [ ] **Profile Cloud Sync**: Optional user-provided cloud storage (e.g., Google Drive/Dropbox API) for profile backups.
- [ ] **Target Curve Management**: Store and manage target response curves.
- [ ] **RoomFit Visualization**: If level 3/4 RoomFit capability is achieved, visualize the RoomFit corrections on a graph.
- [ ] **Measurement Import**: Import actual REW measurement data (not just filters) for advanced analysis.
- [ ] **Automatic PEQ Optimization**: Internal algorithms to suggest filter tweaks based on measurement data.
- [ ] **Advanced Filter Types**: All-Pass filters and specialized shelf variants (if added to WiiM firmware).