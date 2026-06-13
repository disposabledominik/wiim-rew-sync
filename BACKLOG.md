# Future Phase Features (Backlog)

*These items are explicitly excluded from the MVP and CLI Proof of Concept phases.*

---

## Priority: Before GUI Phase

- [x] **Test coverage for hardware-testing findings**: Add automated tests for all API behaviors discovered during manual hardware validation (completed as Task 51).

- [ ] **Rethink source discovery**: The WiiM API accepts any source name and returns valid PEQ data regardless of whether the physical input exists. Need a reliable mechanism to show only real inputs. Options to investigate:
  - Check if `getStatusEx` has model-specific input fields on other firmware versions
  - Try `GetAudioInputList` or similar undocumented endpoints on newer firmware

- [ ] **HP/LP capability detection and write-time validation**: Add a `supports_hp_lp: bool` flag to `DeviceCapabilities`. During `_probe_peq()`, set it to `True` if mode 3 or 5 is seen in the EQBand response. In `dry-run-import`, warn if the import contains HP/LP filters targeting a device without support. The safe-write verify step already catches the mismatch at write time, but a pre-write warning improves UX. (WiiM Mini currently doesn't support HP/LP; newer firmware may add it.)
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