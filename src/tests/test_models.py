"""Unit tests for core Pydantic models — validation rejection and Profile channel-mode validator."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError as PydanticValidationError

from src.models.canonical import CanonicalFilter
from src.models.capabilities import DeviceCapabilities, DeviceInfo
from src.models.channel_mode import get_lr_filters, is_lr_mode
from src.models.errors import (
    BackupError,
    ParseError,
    ProfileNotFoundError,
    REWMeasurementNotFoundError,
    REWNotConnectedError,
    SchemaVersionError,
    ValidationError,
    WiiMConnectionError,
    WiiMResponseError,
    WiiMREWSyncError,
    WiiMTimeoutError,
)
from src.models.peq import build_peq_settings
from src.models.profile import BackupRecord, Profile, build_profile
from src.translator import ValidationWarning

# ---------------------------------------------------------------------------
# CanonicalFilter validation tests
# ---------------------------------------------------------------------------


class TestCanonicalFilter:
    """Tests for CanonicalFilter field validation."""

    def test_valid_peak_filter(self) -> None:
        f = CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=3.5, q=1.41)
        assert f.type == "PEAK"
        assert f.frequency_hz == 1000.0
        assert f.gain_db == 3.5
        assert f.q == 1.41

    def test_valid_off_filter(self) -> None:
        f = CanonicalFilter(type="OFF", frequency_hz=100.0, gain_db=0.0, q=1.0)
        assert f.type == "OFF"

    def test_valid_ls_filter(self) -> None:
        f = CanonicalFilter(type="LS", frequency_hz=80.0, gain_db=-6.0, q=0.7)
        assert f.type == "LS"

    def test_valid_hs_filter(self) -> None:
        f = CanonicalFilter(type="HS", frequency_hz=10000.0, gain_db=2.0, q=0.5)
        assert f.type == "HS"

    def test_frequency_at_lower_boundary(self) -> None:
        f = CanonicalFilter(type="PEAK", frequency_hz=10.0, gain_db=0.0, q=1.0)
        assert f.frequency_hz == 10.0

    def test_frequency_at_upper_boundary(self) -> None:
        f = CanonicalFilter(type="PEAK", frequency_hz=22000.0, gain_db=0.0, q=1.0)
        assert f.frequency_hz == 22000.0

    def test_frequency_below_minimum_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="frequency_hz"):
            CanonicalFilter(type="PEAK", frequency_hz=9.9, gain_db=0.0, q=1.0)

    def test_frequency_above_maximum_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="frequency_hz"):
            CanonicalFilter(type="PEAK", frequency_hz=22001.0, gain_db=0.0, q=1.0)

    def test_q_zero_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="q"):
            CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=0.0, q=0.0)

    def test_q_negative_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="q"):
            CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=0.0, q=-0.5)

    def test_q_small_positive_accepted(self) -> None:
        f = CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=0.0, q=0.001)
        assert f.q == 0.001

    def test_gain_db_no_range_constraint(self) -> None:
        """Gain has no model-level constraint — clamping happens in WiiM generator."""
        f = CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=50.0, q=1.0)
        assert f.gain_db == 50.0

    def test_invalid_type_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            CanonicalFilter(type="NOTCH", frequency_hz=1000.0, gain_db=0.0, q=1.0)


# ---------------------------------------------------------------------------
# is_lr_mode / get_lr_filters tests
# ---------------------------------------------------------------------------


class TestIsLrMode:
    """Tests for is_lr_mode() -- accepts both ChannelMode enum values and
    legacy string variants, moved here from src.gui.shared_helpers (no Qt
    dependency, belongs with ChannelMode)."""

    @pytest.mark.parametrize(
        "value", ["lr", "l/r", "L/R", "left", "right", "LR", "Lr"]
    )
    def test_lr_variants_detected(self, value: str) -> None:
        assert is_lr_mode(value) is True

    def test_stereo_string_is_false(self) -> None:
        assert is_lr_mode("Stereo") is False


class TestGetLrFilters:
    """Tests for get_lr_filters() -- requires explicit wizard-state
    filters_l/filters_r, never guesses a channel split."""

    def test_without_state_data_raises(self) -> None:
        state = SimpleNamespace(filters_l=None, filters_r=None)
        with pytest.raises(ValueError, match="refusing to guess channel split"):
            get_lr_filters(state)

    def test_returns_explicit_state_filters(self) -> None:
        left = _sample_filters()
        right = [CanonicalFilter(type="PEAK", frequency_hz=2000.0, gain_db=0.0, q=1.0)]
        state = SimpleNamespace(filters_l=left, filters_r=right)
        assert get_lr_filters(state) == (left, right)

    def test_empty_filters_l_raises_same_as_none(self) -> None:
        """An empty list for one channel is treated the same as a missing
        one -- a manually edited or older-format profile could otherwise end
        up with one channel empty and the other populated, silently pushing
        a flattened channel instead of raising (branch-quality review,
        2026-07-18)."""
        right = _sample_filters()
        state = SimpleNamespace(filters_l=[], filters_r=right)
        with pytest.raises(ValueError, match="refusing to guess channel split"):
            get_lr_filters(state)

    def test_empty_filters_r_raises_same_as_none(self) -> None:
        left = _sample_filters()
        state = SimpleNamespace(filters_l=left, filters_r=[])
        with pytest.raises(ValueError, match="refusing to guess channel split"):
            get_lr_filters(state)


# ---------------------------------------------------------------------------
# build_peq_settings tests
# ---------------------------------------------------------------------------


class TestBuildPeqSettings:
    """Tests for build_peq_settings() -- PEQSettings construction from a
    combined filter list plus channel mode, moved here from
    src.gui.shared_helpers (no Qt dependency, belongs with the model it
    constructs)."""

    def test_lr_without_explicit_filters_raises(self) -> None:
        """L/R mode without filters_l/filters_r must raise, never guess a split."""
        filters = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0 * (i + 1), gain_db=0.0, q=1.0)
            for i in range(5)
        ]
        with pytest.raises(ValueError, match="refusing to guess channel split"):
            build_peq_settings("wifi", filters, "L/R")

    def test_stereo_uses_combined_filters(self) -> None:
        filters = [CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=3.0, q=1.0)]
        settings = build_peq_settings("wifi", filters, "Stereo")
        assert settings.bands == filters
        assert settings.bands_l == []
        assert settings.bands_r == []

    def test_lr_with_explicit_filters_splits_correctly(self) -> None:
        left = [CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=1.0, q=1.0)]
        right = [CanonicalFilter(type="PEAK", frequency_hz=2000.0, gain_db=2.0, q=1.0)]
        settings = build_peq_settings(
            "wifi", [], "L/R", filters_l=left, filters_r=right
        )
        assert settings.bands_l == left
        assert settings.bands_r == right
        assert settings.bands == []

    def test_lr_with_empty_filters_l_raises(self) -> None:
        """An empty (not just missing) channel must raise too -- see
        TestGetLrFilters.test_empty_filters_l_raises_same_as_none."""
        right = [CanonicalFilter(type="PEAK", frequency_hz=2000.0, gain_db=2.0, q=1.0)]
        with pytest.raises(ValueError, match="refusing to guess channel split"):
            build_peq_settings("wifi", [], "L/R", filters_l=[], filters_r=right)


# ---------------------------------------------------------------------------
# Profile channel-mode validator tests
# ---------------------------------------------------------------------------


def _sample_filters() -> list[CanonicalFilter]:
    return [CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=0.0, q=1.0)]


class TestProfileValidator:
    """Tests for Profile @model_validator enforcing channel-mode/filter-key consistency."""

    def test_stereo_with_filters_valid(self) -> None:
        p = Profile(name="test", channel_mode="stereo", filters=_sample_filters())
        assert p.filters is not None
        assert p.filters_l is None
        assert p.filters_r is None

    def test_lr_with_filters_l_r_valid(self) -> None:
        p = Profile(
            name="test",
            channel_mode="left",
            filters_l=_sample_filters(),
            filters_r=_sample_filters(),
        )
        assert p.filters_l is not None
        assert p.filters_r is not None
        assert p.filters is None

    def test_right_mode_with_filters_l_r_valid(self) -> None:
        p = Profile(
            name="test",
            channel_mode="right",
            filters_l=_sample_filters(),
            filters_r=_sample_filters(),
        )
        assert p.filters_l is not None
        assert p.filters_r is not None

    def test_stereo_missing_filters_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="Stereo profile must have 'filters'"):
            Profile(name="test", channel_mode="stereo")

    def test_stereo_with_filters_l_rejected(self) -> None:
        with pytest.raises(
            PydanticValidationError, match="Stereo profile must not have 'filters_l'/'filters_r'"
        ):
            Profile(
                name="test",
                channel_mode="stereo",
                filters=_sample_filters(),
                filters_l=_sample_filters(),
            )

    def test_stereo_with_filters_r_rejected(self) -> None:
        with pytest.raises(
            PydanticValidationError, match="Stereo profile must not have 'filters_l'/'filters_r'"
        ):
            Profile(
                name="test",
                channel_mode="stereo",
                filters=_sample_filters(),
                filters_r=_sample_filters(),
            )

    def test_lr_missing_filters_l_rejected(self) -> None:
        with pytest.raises(
            PydanticValidationError, match="L/R profile must have 'filters_l' and 'filters_r'"
        ):
            Profile(name="test", channel_mode="left", filters_r=_sample_filters())

    def test_lr_missing_filters_r_rejected(self) -> None:
        with pytest.raises(
            PydanticValidationError, match="L/R profile must have 'filters_l' and 'filters_r'"
        ):
            Profile(name="test", channel_mode="left", filters_l=_sample_filters())

    def test_lr_with_filters_key_rejected(self) -> None:
        with pytest.raises(
            PydanticValidationError, match="L/R profile must not have 'filters' key"
        ):
            Profile(
                name="test",
                channel_mode="left",
                filters=_sample_filters(),
                filters_l=_sample_filters(),
                filters_r=_sample_filters(),
            )


# ---------------------------------------------------------------------------
# build_profile tests
# ---------------------------------------------------------------------------


class TestBuildProfile:
    """Tests for build_profile() -- Profile construction with name
    sanitization and channel-mode splitting, moved here from
    src.gui.shared_helpers (no Qt dependency, belongs with the model it
    constructs)."""

    def test_removes_slashes_from_name(self) -> None:
        profile = build_profile("L/R preset", _sample_filters(), "Stereo")
        assert "/" not in profile.name

    def test_removes_all_unsafe_chars_from_name(self) -> None:
        profile = build_profile('test:file*"name<>|', _sample_filters(), "Stereo")
        for ch in '/\\:*?"<>|':
            assert ch not in profile.name

    def test_empty_name_after_sanitizing_falls_back_to_untitled(self) -> None:
        profile = build_profile("/\\:*?", _sample_filters(), "Stereo")
        assert profile.name == "Untitled Preset"

    def test_lr_without_explicit_filters_raises(self) -> None:
        with pytest.raises(ValueError, match="refusing to guess channel split"):
            build_profile("Test", _sample_filters(), "L/R")

    def test_lr_with_explicit_filters_preserves_split(self) -> None:
        filters_l = _sample_filters()
        filters_r = [CanonicalFilter(type="PEAK", frequency_hz=2000.0, gain_db=0.0, q=1.0)]
        profile = build_profile(
            "Test", [], "L/R", filters_l=filters_l, filters_r=filters_r
        )
        assert profile.filters_l == filters_l
        assert profile.filters_r == filters_r

    def test_stereo_keeps_filters_in_single_list(self) -> None:
        filters = _sample_filters()
        profile = build_profile("Test", filters, "Stereo")
        assert profile.filters == filters

    def test_lr_with_empty_filters_r_raises(self) -> None:
        """An empty (not just missing) channel must raise too -- see
        TestGetLrFilters.test_empty_filters_r_raises_same_as_none."""
        filters_l = _sample_filters()
        with pytest.raises(ValueError, match="refusing to guess channel split"):
            build_profile("Test", [], "L/R", filters_l=filters_l, filters_r=[])


# ---------------------------------------------------------------------------
# Profile.band_counts tests
# ---------------------------------------------------------------------------


class TestProfileBandCounts:
    """Tests for Profile.band_counts() -- active/total band counting, moved
    here from src.gui.views.my_presets_view's _count_bands() (no Qt
    dependency, belongs with the model)."""

    def test_stereo_counts_active_and_total(self) -> None:
        filters = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=3.0, q=1.0),
            CanonicalFilter(type="PEAK", frequency_hz=200.0, gain_db=0.0, q=1.0),
            CanonicalFilter(type="PEAK", frequency_hz=300.0, gain_db=-1.5, q=1.0),
        ]
        profile = build_profile("Test", filters, "Stereo")
        assert profile.band_counts() == (2, 3)

    def test_lr_uses_left_channel_as_representative(self) -> None:
        filters_l = [CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=2.0, q=1.0)]
        filters_r = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=2.0, q=1.0),
            CanonicalFilter(type="PEAK", frequency_hz=200.0, gain_db=1.0, q=1.0),
        ]
        profile = build_profile(
            "Test", [], "L/R", filters_l=filters_l, filters_r=filters_r
        )
        # Left channel has 1 band (active); right has 2 -- representative
        # count must be the left channel's, not a combined/right count.
        assert profile.band_counts() == (1, 1)

    def test_no_filters_returns_zero_zero(self) -> None:
        profile = build_profile("Test", [], "Stereo")
        assert profile.band_counts() == (0, 0)


# ---------------------------------------------------------------------------
# BackupRecord tests
# ---------------------------------------------------------------------------


class TestBackupRecord:
    """Tests for BackupRecord model."""

    def test_valid_backup_record(self) -> None:
        br = BackupRecord(
            name="auto-backup",
            channel_mode="stereo",
            filters=_sample_filters(),
            timestamp="2024-01-15T10:30:00Z",
            device_uuid="abc-123",
            firmware_version="4.8.5",
            trigger="pre_write",
        )
        assert br.profile_type == "backup"
        assert br.trigger == "pre_write"
        assert br.timestamp == "2024-01-15T10:30:00Z"

    def test_backup_record_pre_rollback(self) -> None:
        br = BackupRecord(
            name="rollback-backup",
            channel_mode="left",
            filters_l=_sample_filters(),
            filters_r=_sample_filters(),
            timestamp="2024-01-15T10:31:00Z",
            device_uuid="abc-123",
            firmware_version="4.8.5",
            trigger="pre_rollback",
        )
        assert br.trigger == "pre_rollback"


# ---------------------------------------------------------------------------
# Exception hierarchy tests
# ---------------------------------------------------------------------------


class TestExceptionHierarchy:
    """Tests for the domain exception hierarchy."""

    def test_base_exception(self) -> None:
        assert issubclass(WiiMREWSyncError, Exception)

    def test_parse_error_inheritance(self) -> None:
        assert issubclass(ParseError, WiiMREWSyncError)

    def test_parse_error_with_line_number(self) -> None:
        err = ParseError("bad token", line_number=42)
        assert err.line_number == 42
        assert "Line 42" in str(err)

    def test_parse_error_without_line_number(self) -> None:
        err = ParseError("general parse error")
        assert err.line_number is None
        assert "general parse error" in str(err)

    def test_validation_error_inheritance(self) -> None:
        assert issubclass(ValidationError, WiiMREWSyncError)

    def test_connection_error_inheritance(self) -> None:
        assert issubclass(WiiMConnectionError, WiiMREWSyncError)

    def test_timeout_error_inheritance(self) -> None:
        assert issubclass(WiiMTimeoutError, WiiMConnectionError)

    def test_response_error_inheritance(self) -> None:
        assert issubclass(WiiMResponseError, WiiMREWSyncError)

    def test_rew_not_connected_inheritance(self) -> None:
        assert issubclass(REWNotConnectedError, WiiMREWSyncError)

    def test_rew_measurement_not_found_inheritance(self) -> None:
        assert issubclass(REWMeasurementNotFoundError, WiiMREWSyncError)

    def test_profile_not_found_inheritance(self) -> None:
        assert issubclass(ProfileNotFoundError, WiiMREWSyncError)

    def test_backup_error_inheritance(self) -> None:
        assert issubclass(BackupError, WiiMREWSyncError)

    def test_schema_version_error_inheritance(self) -> None:
        assert issubclass(SchemaVersionError, WiiMREWSyncError)


# ---------------------------------------------------------------------------
# ValidationWarning dataclass tests
# ---------------------------------------------------------------------------


class TestValidationWarning:
    """Tests for ValidationWarning dataclass."""

    def test_basic_warning(self) -> None:
        w = ValidationWarning(
            field="gain_db",
            message="Gain exceeds ±12 dB limit",
            original_value=15.0,
            clamped_value=12.0,
        )
        assert w.field == "gain_db"
        assert w.message == "Gain exceeds ±12 dB limit"
        assert w.original_value == 15.0
        assert w.clamped_value == 12.0

    def test_warning_without_clamped_value(self) -> None:
        w = ValidationWarning(
            field="q",
            message="Q value unusual",
            original_value=0.001,
        )
        assert w.clamped_value is None


# ---------------------------------------------------------------------------
# DeviceCapabilities and DeviceInfo tests
# ---------------------------------------------------------------------------


class TestDeviceModels:
    """Tests for DeviceCapabilities and DeviceInfo."""

    def test_device_info_creation(self) -> None:
        di = DeviceInfo(
            ip="192.168.1.100",
            name="Living Room",
            model="WiiM Pro",
            firmware="4.8.5",
            uuid="device-uuid-123",
        )
        assert di.ip == "192.168.1.100"

    def test_device_capabilities_defaults(self) -> None:
        dc = DeviceCapabilities()
        assert dc.supports_peq is False
        assert dc.max_filters == 0
        assert dc.source_names == []
