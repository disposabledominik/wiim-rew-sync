"""Tests for ProfileRepository — local JSON profile storage."""

from __future__ import annotations

import json
import unicodedata
from typing import Literal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.models.canonical import CanonicalFilter
from src.models.channel_mode import ChannelMode
from src.models.errors import ProfileNameCollisionError, ProfileNotFoundError
from src.models.profile import Profile
from src.repository.profile_repository import ProfileRepository
from src.tests.conftest import st_canonical_filter_list

# --- Fixtures ---


def _make_stereo_profile(name: str = "test-profile") -> Profile:
    """Create a minimal stereo profile for testing."""
    return Profile(
        name=name,
        channel_mode="stereo",
        filters=[
            CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=2.0, q=1.0),
            CanonicalFilter(type="LS", frequency_hz=100.0, gain_db=-3.0, q=0.7),
        ],
    )


def _make_lr_profile(name: str = "lr-profile") -> Profile:
    """Create a minimal L/R profile for testing."""
    return Profile(
        name=name,
        channel_mode="left",
        filters_l=[
            CanonicalFilter(type="PEAK", frequency_hz=500.0, gain_db=1.5, q=2.0),
        ],
        filters_r=[
            CanonicalFilter(type="HS", frequency_hz=8000.0, gain_db=-2.0, q=0.5),
        ],
    )


@pytest.fixture()
def repo(tmp_path: object) -> ProfileRepository:
    """Create a ProfileRepository using tmp_path as storage root."""
    from pathlib import Path

    return ProfileRepository(Path(str(tmp_path)))


# --- save + load round-trip ---


class TestSaveLoadRoundTrip:
    """Test save and load round-trip for both channel modes."""

    def test_stereo_round_trip(self, repo: ProfileRepository) -> None:
        """Stereo profile saves with 'filters' key and loads correctly."""
        profile = _make_stereo_profile()
        repo.save(profile)
        loaded = repo.load("test-profile")

        assert loaded.name == "test-profile"
        assert loaded.channel_mode == ChannelMode.STEREO
        assert loaded.filters is not None
        assert len(loaded.filters) == 2
        assert loaded.filters[0].frequency_hz == 1000.0
        assert loaded.filters_l is None
        assert loaded.filters_r is None

    def test_lr_round_trip(self, repo: ProfileRepository) -> None:
        """L/R profile saves with 'filters_l'/'filters_r' keys and loads correctly."""
        profile = _make_lr_profile()
        repo.save(profile)
        loaded = repo.load("lr-profile")

        assert loaded.name == "lr-profile"
        assert loaded.channel_mode == ChannelMode.LR
        assert loaded.filters_l is not None
        assert loaded.filters_r is not None
        assert len(loaded.filters_l) == 1
        assert len(loaded.filters_r) == 1
        assert loaded.filters is None

    def test_stereo_json_has_no_lr_keys(self, repo: ProfileRepository) -> None:
        """Stereo profile JSON file must not contain filters_l/filters_r."""
        profile = _make_stereo_profile()
        path = repo.save(profile)
        data = json.loads(path.read_text(encoding="utf-8"))

        assert "filters" in data
        assert "filters_l" not in data
        assert "filters_r" not in data

    def test_lr_json_has_no_filters_key(self, repo: ProfileRepository) -> None:
        """L/R profile JSON file must not contain 'filters' key."""
        profile = _make_lr_profile()
        path = repo.save(profile)
        data = json.loads(path.read_text(encoding="utf-8"))

        assert "filters_l" in data
        assert "filters_r" in data
        assert "filters" not in data


# --- list_all ---


class TestListAll:
    """Test list_all() returns case-insensitive sorted names."""

    def test_list_returns_sorted_case_insensitive(self, repo: ProfileRepository) -> None:
        """Profiles are sorted lexicographically, case-insensitive."""
        repo.save(_make_stereo_profile("Zebra"))
        repo.save(_make_stereo_profile("alpha"))
        repo.save(_make_stereo_profile("Beta"))

        profiles = repo.list_all()
        names = [p.name for p in profiles]
        assert names == ["alpha", "Beta", "Zebra"]

    def test_list_empty(self, repo: ProfileRepository) -> None:
        """Empty repository returns empty list."""
        assert repo.list_all() == []


# --- delete ---


class TestDelete:
    """Test delete removes file and raises on missing."""

    def test_delete_removes_file(self, repo: ProfileRepository) -> None:
        """Delete removes the profile file from disk."""
        profile = _make_stereo_profile()
        repo.save(profile)
        repo.delete("test-profile")

        assert repo.list_all() == []

    def test_delete_missing_raises(self, repo: ProfileRepository) -> None:
        """Deleting a non-existent profile raises ProfileNotFoundError."""
        with pytest.raises(ProfileNotFoundError):
            repo.delete("nonexistent")


# --- rename ---


class TestRename:
    """Test rename updates name and file."""

    def test_rename_updates_name_and_file(self, repo: ProfileRepository) -> None:
        """Rename changes the name field and the filename."""
        repo.save(_make_stereo_profile("old-name"))
        repo.rename("old-name", "new-name")

        # Old name should not exist
        with pytest.raises(ProfileNotFoundError):
            repo.load("old-name")

        # New name should exist with correct data
        loaded = repo.load("new-name")
        assert loaded.name == "new-name"
        assert loaded.filters is not None
        assert len(loaded.filters) == 2

    def test_rename_to_nfc_nfd_equivalent_of_own_name_does_not_raise_or_lose_data(
        self, repo: ProfileRepository
    ) -> None:
        """Renaming a profile to a differently-composed (NFC vs NFD) but
        visually-identical form of its own current name must not raise
        ProfileNameCollisionError against itself, and -- critically -- must
        not delete the profile in the process. _profile_path() normalizes
        to NFC before building the path, so both names map to the same
        on-disk file; naively fixing only the collision check would leave
        rename()'s unconditional `if old_name != new_name: old_path.unlink()`
        deleting the file save() just wrote (old_name/new_name differ as raw
        strings even though they're the same file), silently destroying the
        renamed profile. This test only passes if the profile still loads
        correctly afterward -- checking for "no exception" alone would not
        have caught that data-loss bug."""
        nfc_name = unicodedata.normalize("NFC", "café")
        nfd_name = unicodedata.normalize("NFD", "café")
        assert nfc_name != nfd_name  # sanity: genuinely different raw strings
        assert unicodedata.normalize("NFC", nfd_name) == nfc_name  # same normalized path

        repo.save(_make_stereo_profile(nfc_name))

        repo.rename(nfc_name, nfd_name)  # must not raise

        loaded = repo.load(nfd_name)
        assert loaded.name == nfd_name
        assert loaded.filters is not None
        assert len(loaded.filters) == 2

    def test_rename_case_only_leaves_exactly_one_file(
        self, repo: ProfileRepository
    ) -> None:
        """A case-only rename ("MyPreset" -> "mypreset") must leave exactly
        one file on disk under the new name, on any filesystem.

        Regression test: an earlier fix used a casefolded string comparison
        to decide whether the old and new paths were "the same file," which
        is wrong on a case-sensitive filesystem (this project's own WSL2/
        Ubuntu ext4 test environment) -- there, "MyPreset.json" and
        "mypreset.json" really are two different files, so the casefolded
        comparison treated them as equal, skipped the unlink, and left the
        stale old-cased file behind as an orphan alongside the correctly
        renamed one. rename() now uses Path.samefile() (stat-based) instead,
        which asks the OS directly and is correct regardless of the
        filesystem's own case-folding behaviour.
        """
        repo.save(_make_stereo_profile("MyPreset"))

        repo.rename("MyPreset", "mypreset")

        on_disk = sorted(p.name for p in repo._profiles_dir.iterdir())
        assert on_disk == ["mypreset.json"]

        loaded = repo.load("mypreset")
        assert loaded.name == "mypreset"
        assert loaded.filters is not None
        assert len(loaded.filters) == 2

    def test_rename_to_name_colliding_with_unrelated_profile_still_raises(
        self, repo: ProfileRepository
    ) -> None:
        """A rename whose target normalizes to the same path as a
        genuinely unrelated, separately-saved profile must still raise --
        the NFC/NFD self-rename fix (expected_existing_name) must only
        exempt the caller's own known prior name, not any name. Renaming
        "widget" to the NFC form of "café" while an unrelated profile
        already occupies the NFD-equivalent (same normalized path) of
        "café" is a real foreign collision, not a self-rename."""
        nfc_name = unicodedata.normalize("NFC", "café")
        nfd_name = unicodedata.normalize("NFD", "café")
        assert unicodedata.normalize("NFC", nfd_name) == nfc_name  # same normalized path

        repo.save(_make_stereo_profile("widget"))
        repo.save(_make_stereo_profile(nfd_name))

        with pytest.raises(ProfileNameCollisionError):
            repo.rename("widget", nfc_name)

        # Neither profile should have been touched by the failed rename.
        assert repo.load("widget").name == "widget"
        assert repo.load(nfd_name).name == nfd_name


class TestPathTraversalSafety:
    """rename()/duplicate() set the new name directly, bypassing
    build_profile()'s cosmetic sanitization -- _profile_path() itself must
    still refuse to escape the profiles directory regardless of caller."""

    def test_rename_to_traversal_name_stays_inside_profiles_dir(
        self, repo: ProfileRepository
    ) -> None:
        """Renaming to a name containing '../' segments must not write
        outside repo._profiles_dir."""
        repo.save(_make_stereo_profile("original"))
        repo.rename("original", "../../../../tmp/evil")

        on_disk = list(repo._profiles_dir.iterdir())
        assert all(p.parent == repo._profiles_dir for p in on_disk)

    def test_duplicate_to_traversal_name_stays_inside_profiles_dir(
        self, repo: ProfileRepository
    ) -> None:
        """Duplicating to a name containing '../' segments must not write
        outside repo._profiles_dir."""
        repo.save(_make_stereo_profile("original"))
        repo.duplicate("original", "../../../../tmp/evil")

        on_disk = list(repo._profiles_dir.iterdir())
        assert all(p.parent == repo._profiles_dir for p in on_disk)


# --- duplicate ---


class TestDuplicate:
    """Test duplicate creates a copy with a new name."""

    def test_duplicate_creates_copy(self, repo: ProfileRepository) -> None:
        """Duplicate creates a new profile with same data but different name."""
        repo.save(_make_stereo_profile("original"))
        copy = repo.duplicate("original", "copy")

        assert copy.name == "copy"
        assert copy.filters is not None
        assert len(copy.filters) == 2

        # Original still exists
        original = repo.load("original")
        assert original.name == "original"

    def test_duplicate_missing_raises(self, repo: ProfileRepository) -> None:
        """Duplicating a non-existent profile raises ProfileNotFoundError."""
        with pytest.raises(ProfileNotFoundError):
            repo.duplicate("nonexistent", "copy")


# --- tags ---


class TestTags:
    """Test add_tag, remove_tag, and get_by_tag."""

    def test_add_tag_persists(self, repo: ProfileRepository) -> None:
        """Added tags persist across load cycles."""
        repo.save(_make_stereo_profile("tagged"))
        repo.add_tag("tagged", "room-correction")

        loaded = repo.load("tagged")
        assert "room-correction" in loaded.tags

    def test_add_tag_idempotent(self, repo: ProfileRepository) -> None:
        """Adding the same tag twice does not duplicate it."""
        repo.save(_make_stereo_profile("tagged"))
        repo.add_tag("tagged", "test")
        repo.add_tag("tagged", "test")

        loaded = repo.load("tagged")
        assert loaded.tags.count("test") == 1

    def test_remove_tag_persists(self, repo: ProfileRepository) -> None:
        """Removed tags persist across load cycles."""
        profile = _make_stereo_profile("tagged")
        profile.tags = ["keep", "remove"]
        repo.save(profile)

        repo.remove_tag("tagged", "remove")
        loaded = repo.load("tagged")
        assert "remove" not in loaded.tags
        assert "keep" in loaded.tags

    def test_get_by_tag_filters_correctly(self, repo: ProfileRepository) -> None:
        """get_by_tag returns only profiles with the given tag."""
        p1 = _make_stereo_profile("one")
        p1.tags = ["eq", "living-room"]
        repo.save(p1)

        p2 = _make_stereo_profile("two")
        p2.tags = ["eq"]
        repo.save(p2)

        p3 = _make_stereo_profile("three")
        p3.tags = ["bedroom"]
        repo.save(p3)

        results = repo.get_by_tag("eq")
        names = [p.name for p in results]
        assert "one" in names
        assert "two" in names
        assert "three" not in names


# --- schema migration ---


class TestSchemaMigration:
    """Test that load() applies schema migration for older profiles."""

    def test_load_applies_migration(self, repo: ProfileRepository) -> None:
        """A v0 profile (no schema_version, no tags) gets migrated on load."""
        # Write a raw v0 profile directly (no schema_version, no tags field)
        raw = {
            "name": "legacy",
            "channel_mode": "stereo",
            "filters": [
                {"type": "PEAK", "frequency_hz": 1000.0, "gain_db": 2.0, "q": 1.0},
            ],
        }
        path = repo._profiles_dir / "legacy.json"
        path.write_text(json.dumps(raw), encoding="utf-8")

        loaded = repo.load("legacy")
        assert loaded.schema_version == 1
        assert loaded.tags == []
        assert loaded.name == "legacy"
        assert loaded.filters is not None


# --- Property-Based Tests (Hypothesis) ---

# --- Task 26: profile channel-mode key invariant (PBT) ---


@st.composite
def st_stereo_profile(draw: st.DrawFn) -> Profile:
    """Generate a valid stereo Profile with random filter contents."""
    filters = draw(st_canonical_filter_list(min_size=1, max_size=10))
    name = draw(
        st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N")))
    )
    return Profile(name=name, channel_mode="stereo", filters=filters)


@st.composite
def st_lr_profile(draw: st.DrawFn) -> Profile:
    """Generate a valid L/R Profile with random filter contents."""
    filters_l = draw(st_canonical_filter_list(min_size=1, max_size=10))
    filters_r = draw(st_canonical_filter_list(min_size=1, max_size=10))
    name = draw(
        st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N")))
    )
    channel_mode: Literal["left", "right"] = draw(st.sampled_from(["left", "right"]))
    return Profile(
        name=name, channel_mode=channel_mode, filters_l=filters_l, filters_r=filters_r
    )


@given(profile=st.one_of(st_stereo_profile(), st_lr_profile()))
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
def test_channel_mode_key_invariant(profile: Profile, tmp_path: object) -> None:
    """Property: save/load round-trip preserves correct filter key structure.

    Stereo: loaded profile has `filters` set, `filters_l`/`filters_r` are None.
    L/R: loaded profile has `filters_l` and `filters_r` set, `filters` is None.

    **Validates: Requirements 9.2, 9.3, 9.4**
    """
    import tempfile
    from pathlib import Path

    work_dir = Path(tempfile.mkdtemp(dir=str(tmp_path)))
    repo = ProfileRepository(work_dir)
    repo.save(profile)
    loaded = repo.load(profile.name)

    if profile.channel_mode == ChannelMode.STEREO:
        assert loaded.filters is not None, "Stereo profile must have 'filters'"
        assert loaded.filters_l is None, "Stereo profile must not have 'filters_l'"
        assert loaded.filters_r is None, "Stereo profile must not have 'filters_r'"
        assert loaded.filters == profile.filters
    else:
        assert loaded.filters_l is not None, "L/R profile must have 'filters_l'"
        assert loaded.filters_r is not None, "L/R profile must have 'filters_r'"
        assert loaded.filters is None, "L/R profile must not have 'filters'"
        assert loaded.filters_l == profile.filters_l
        assert loaded.filters_r == profile.filters_r

    assert loaded.channel_mode == profile.channel_mode
    assert loaded.name == profile.name


# --- Task 27: profile list sort-order invariant (PBT) ---


@given(
    names=st.lists(
        st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"))),
        min_size=1,
        max_size=10,
        unique=True,
    )
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_list_sort_order_invariant(names: list[str], tmp_path: object) -> None:
    """Property: list() returns profiles in ascending lexicographic order (case-insensitive).

    For any set of profiles saved in any order, list() returns them sorted by
    name.lower().

    Names that are distinct Python strings but normalize to the same Unicode
    NFC form (e.g. composed vs. decomposed accented characters) map to the
    same filename and are an intentional collision — saving the second one
    raises ``ProfileNameCollisionError`` instead of silently overwriting the
    first, so only the first-saved name of each normalized group ends up in
    the listing.

    **Validates: Requirements 9.6**
    """
    import tempfile
    from pathlib import Path

    work_dir = Path(tempfile.mkdtemp(dir=str(tmp_path)))
    repo = ProfileRepository(work_dir)

    saved_names: list[str] = []
    seen_normalized: set[str] = set()
    for name in names:
        profile = Profile(
            name=name,
            channel_mode="stereo",
            filters=[CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=0.0, q=1.0)],
        )
        normalized = unicodedata.normalize("NFC", name)
        if normalized in seen_normalized:
            with pytest.raises(ProfileNameCollisionError):
                repo.save(profile)
            continue
        seen_normalized.add(normalized)
        repo.save(profile)
        saved_names.append(name)

    listed = repo.list_all()
    listed_names = [p.name for p in listed]
    expected = sorted(saved_names, key=lambda n: (n.lower(), n))
    assert listed_names == expected
