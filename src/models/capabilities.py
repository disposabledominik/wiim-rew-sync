"""Device capability and info models."""

from typing import Literal

from pydantic import BaseModel


class DeviceInfo(BaseModel):
    """Discovered device information."""

    ip: str
    name: str
    model: str
    firmware: str
    uuid: str = ""
    role: Literal["solo", "master", "slave"] = "solo"


class DeviceCapabilities(BaseModel):
    """Runtime-probed capability set of a discovered WiiM device."""

    supports_peq: bool = False
    supports_roomfit: bool = False
    supports_roomfit_read: bool = False
    supports_roomfit_write: bool = False
    roomfit_level: int = 0
    supports_lr_filters: bool = False
    supports_profile_enumeration: bool = False
    supports_batch_write: bool = False
    max_filters: int = 0
    model: str = ""
    firmware: str = ""
    uuid: str = ""
    mac_address: str = ""
    role: Literal["solo", "master", "slave"] = "solo"
    source_names: list[str] = []
    supported_filter_types: list[str] = []
    source_aliases: dict[str, str] = {}
