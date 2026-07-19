"""Profile repository - local JSON-based profile storage and management."""

from __future__ import annotations

import json
import logging
import unicodedata
from pathlib import Path

from src.models.channel_mode import ChannelMode
from src.models.errors import ProfileNameCollisionError, ProfileNotFoundError
from src.models.profile import Profile
from src.translator.schema_migrator import migrate_profile
from src.utils.path_safety import sanitize_path_segment

logger = logging.getLogger("wiim_rew_sync.app")


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
        """Return the file path for a profile by name.

        Names are normalized to Unicode NFC before deriving the filename so
        that visually-identical names (e.g. composed vs. decomposed forms)
        always map to the same path, instead of colliding unpredictably on
        normalization-insensitive filesystems like NTFS.

        ``sanitize_path_segment`` is a traversal backstop, not the cosmetic
        filename sanitization ``build_profile()`` already applies to
        ``profile.name`` -- it guarantees this method can never be tricked
        into escaping ``_profiles_dir`` even for callers (``rename()``,
        ``duplicate()``) that set a name directly without going through
        ``build_profile()`` first.
        """
        normalized = unicodedata.normalize("NFC", name)
        safe_name = sanitize_path_segment(normalized, fallback="Untitled Preset")
        return self._profiles_dir / f"{safe_name}.json"

    def save(self, profile: Profile, *, expected_existing_name: str | None = None) -> Path:
        """Save a profile to disk as JSON.

        Stereo profiles use the ``filters`` key only.
        L/R profiles use ``filters_l`` and ``filters_r`` only.
        The Pydantic model_validator already enforces this, so we serialize
        and exclude None fields to keep the JSON clean.

        Args:
            expected_existing_name: If the path already holds a profile with
                exactly this name, it's not treated as a foreign collision --
                used by ``rename()`` so renaming a profile to a differently
                -composed (NFC/NFD) but visually-identical form of its own
                current name doesn't raise against itself.

        Raises:
            ProfileNameCollisionError: If ``profile.name`` normalizes to the
                same filename as an existing profile with a different name
                (would otherwise silently overwrite unrelated data).
        """
        path = self._profile_path(profile.name)
        if path.exists():
            existing_raw = json.loads(path.read_text(encoding="utf-8"))
            existing_name = existing_raw.get("name")
            if (
                existing_name is not None
                and existing_name != profile.name
                and existing_name != expected_existing_name
            ):
                raise ProfileNameCollisionError(
                    f"Profile name '{profile.name}' collides with existing "
                    f"profile '{existing_name}' (same filename after Unicode "
                    "normalization)"
                )
        data = profile.model_dump(mode="python")
        # Remove None filter keys to enforce channel-mode consistency in JSON
        if profile.channel_mode == ChannelMode.STEREO:
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

    def list_all(self) -> list[Profile]:
        """Return all profiles sorted by name (lexicographic, case-insensitive)."""
        profiles: list[Profile] = []
        for path in self._profiles_dir.glob("*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                raw = migrate_profile(raw)
                profile = Profile.model_validate(raw)
                profiles.append(profile)
            except (json.JSONDecodeError, ValueError, KeyError) as exc:
                logger.warning("Skipping unreadable profile %s: %s", path, exc)
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
        self.save(new_profile, expected_existing_name=old_name)

        # Remove the old file only if it's a *different* file on disk than
        # what save() just wrote. Path.samefile() (stat-based: same
        # device+inode) is used rather than string/Path equality, because
        # whether two differently-spelled names collapse to the *same
        # physical file* depends on the actual filesystem's case-folding
        # behaviour, not on how Python happens to compare path strings.
        # Path equality is case-insensitive on Windows (WindowsPath) but
        # always case-sensitive on POSIX (PosixPath is a plain string
        # compare, even on a case-insensitive volume like default macOS) --
        # and a casefold comparison has the opposite problem: it collapses
        # a case-only rename ("MyPreset" -> "mypreset") into "same path" even
        # on this project's own case-sensitive WSL2/Ubuntu ext4 test
        # environment, where they are genuinely two different files, which
        # would skip the unlink and leave the stale old-cased file behind
        # as an orphan. samefile() asks the OS directly, so it's correct on
        # both case-sensitive and case-insensitive filesystems.
        new_path = self._profile_path(new_name)
        if not old_path.exists() or not old_path.samefile(new_path):
            old_path.unlink(missing_ok=True)

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

    def get_by_tag(self, tag: str) -> list[Profile]:
        """Return all profiles that have the given tag."""
        return [p for p in self.list_all() if tag in p.tags]
