"""Profile repository - local JSON-based profile storage and management."""

from __future__ import annotations

import builtins
import json
from pathlib import Path

from src.models.errors import ProfileNotFoundError
from src.models.profile import Profile
from src.translator.schema_migrator import migrate_profile


class ProfileRepository:
    """Manages local profile persistence as JSON files.

    Profiles are stored in ``storage_root/profiles/<name>.json``.
    """

    def __init__(self, storage_root: Path) -> None:
        """Initialise the repository with the given storage root.

        Creates the profiles subdirectory if it does not exist.
        """
        self._profiles_dir = storage_root / "profiles"
        self._profiles_dir.mkdir(parents=True, exist_ok=True)

    @property
    def storage_root(self) -> Path:
        """Return the base storage directory (parent of profiles subdir)."""
        return self._profiles_dir.parent

    def _profile_path(self, name: str) -> Path:
        """Return the file path for a profile by name."""
        return self._profiles_dir / f"{name}.json"

    def save(self, profile: Profile) -> Path:
        """Save a profile to disk as JSON.

        Stereo profiles use the ``filters`` key only.
        L/R profiles use ``filters_l`` and ``filters_r`` only.
        The Pydantic model_validator already enforces this, so we serialize
        and exclude None fields to keep the JSON clean.
        """
        path = self._profile_path(profile.name)
        data = profile.model_dump(mode="python")
        # Remove None filter keys to enforce channel-mode consistency in JSON
        if profile.channel_mode == "stereo":
            data.pop("filters_l", None)
            data.pop("filters_r", None)
        else:
            data.pop("filters", None)
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        return path

    def load(self, name: str) -> Profile:
        """Load a profile by name.

        Applies schema migration if needed, then validates with Pydantic.

        Raises:
            ProfileNotFoundError: If no profile with that name exists.
        """
        path = self._profile_path(name)
        if not path.exists():
            raise ProfileNotFoundError(f"Profile '{name}' not found")

        raw = json.loads(path.read_text(encoding="utf-8"))

        # Apply schema migration (upgrades old versions to current)
        raw = migrate_profile(raw)

        # Validate via Pydantic (enforces channel-mode/filter-key consistency)
        return Profile.model_validate(raw)

    def list(self) -> list[Profile]:
        """Return all profiles sorted by name (lexicographic, case-insensitive)."""
        profiles: list[Profile] = []
        for path in self._profiles_dir.glob("*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                raw = migrate_profile(raw)
                profile = Profile.model_validate(raw)
                profiles.append(profile)
            except (json.JSONDecodeError, ValueError, KeyError):
                # Skip invalid profile files
                continue
        profiles.sort(key=lambda p: (p.name.lower(), p.name))
        return profiles

    def delete(self, name: str) -> None:
        """Delete a profile by name.

        Raises:
            ProfileNotFoundError: If no profile with that name exists.
        """
        path = self._profile_path(name)
        if not path.exists():
            raise ProfileNotFoundError(f"Profile '{name}' not found")
        path.unlink()

    def rename(self, old_name: str, new_name: str) -> None:
        """Rename a profile (updates both filename and name field inside JSON).

        Raises:
            ProfileNotFoundError: If the old profile does not exist.
        """
        old_path = self._profile_path(old_name)
        if not old_path.exists():
            raise ProfileNotFoundError(f"Profile '{old_name}' not found")

        # Load, update name, save to new path, remove old
        profile = self.load(old_name)
        # Create updated profile with new name
        data = profile.model_dump(mode="python")
        data["name"] = new_name
        new_profile = Profile.model_validate(data)
        self.save(new_profile)

        # Remove old file (only if new_name != old_name)
        if old_name != new_name:
            old_path.unlink()

    def duplicate(self, name: str, new_name: str) -> Profile:
        """Create a copy of a profile with a new name.

        Raises:
            ProfileNotFoundError: If the source profile does not exist.
        """
        source_path = self._profile_path(name)
        if not source_path.exists():
            raise ProfileNotFoundError(f"Profile '{name}' not found")

        profile = self.load(name)
        data = profile.model_dump(mode="python")
        data["name"] = new_name
        new_profile = Profile.model_validate(data)
        self.save(new_profile)
        return new_profile

    def add_tag(self, name: str, tag: str) -> None:
        """Add a tag to a profile and persist.

        Raises:
            ProfileNotFoundError: If the profile does not exist.
        """
        profile = self.load(name)
        if tag not in profile.tags:
            profile.tags.append(tag)
            self.save(profile)

    def remove_tag(self, name: str, tag: str) -> None:
        """Remove a tag from a profile and persist.

        Raises:
            ProfileNotFoundError: If the profile does not exist.
        """
        profile = self.load(name)
        if tag in profile.tags:
            profile.tags.remove(tag)
            self.save(profile)

    def get_by_tag(self, tag: str) -> builtins.list[Profile]:
        """Return all profiles that have the given tag."""
        return [p for p in self.list() if tag in p.tags]
