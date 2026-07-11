"""Device capability and info models."""

from pydantic import BaseModel


class DeviceInfo(BaseModel):
    """Discovered device information."""

    ip: str
    name: str
    model: str
    firmware: str
    uuid: str = ""


class DeviceCapabilities(BaseModel):
    """Runtime-probed capability set of a discovered WiiM device.

    RoomFit support is three independent booleans (subsystem present /
    band-buffer readable / save-write confirmed), not a graduated level --
    the old 0-4 ``roomfit_level`` ladder encoded probe *progress* rather
    than device reality and was removed (docs/corrections.md, 2026-07-10).

    ``supports_batch_write`` is tri-state: ``None`` means "not yet
    determined" -- the first real push attempts the batch form and records
    the outcome (see ``WiiMAdapter.write_peq``), replacing the old
    write-probe at connect time.
    """

    supports_peq: bool = False
    supports_roomfit: bool = False
    supports_roomfit_read: bool = False
    supports_roomfit_write: bool = False
    supports_lr_filters: bool = False
    supports_profile_enumeration: bool = False
    supports_batch_write: bool | None = None
    # RC subsystem version from GetAcousticCapability (e.g. "1.0", "1.1");
    # empty when the device has no RC block or the command is unsupported.
    # Confirmed discriminator for the RoomCorr* command family's behavior
    # (docs/wiim_api_notes.md, Calibration-result push commands).
    rc_version: str = ""
    max_filters: int = 0
    model: str = ""
    firmware: str = ""
    uuid: str = ""
    mac_address: str = ""
    source_names: list[str] = []
    supported_filter_types: list[str] = []
    source_aliases: dict[str, str] = {}
    # Provenance flags -- both set in device_capability_file.py's merge_into(),
    # the single merge point every probe() call flows through. Let the GUI
    # warn the user when displayed capabilities didn't come purely from live
    # device probing.
    capability_file_override: bool = False
    used_generic_capabilities: bool = False
