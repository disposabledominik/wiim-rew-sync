"""Unit tests for GUI dialogs.

Tests PushConfirmation dialog display, static confirm() method,
clamping summary, mode mismatch warning, and dry run state.

Requirements referenced: 6.1, 12.2, 12.3, 12.6.
"""

from __future__ import annotations

from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPushButton, QWidget

from src.gui.dialogs.push_confirmation import PushConfirmation


class TestPushConfirmation:
    """Tests for the PushConfirmation modal dialog."""

    def test_displays_device_info(self, qtbot) -> None:
        """Dialog shows device name, source, channel mode, and band count."""
        dialog = PushConfirmation(
            None,
            device_name="WiiM Pro Plus",
            source="HDMI",
            channel_mode="Stereo",
            band_count=8,
            dry_run=False,
        )
        qtbot.addWidget(dialog)

        # Grab all label texts from the dialog
        text = _all_label_text(dialog)

        assert "WiiM Pro Plus" in text
        assert "HDMI" in text
        assert "Stereo" in text
        assert "8" in text

    def test_title_push_mode(self, qtbot) -> None:
        """Window title says 'Confirm Push' when not dry run."""
        dialog = PushConfirmation(
            None, "Device", "WiFi", "Stereo", 5, dry_run=False
        )
        qtbot.addWidget(dialog)

        assert dialog.windowTitle() == "Confirm Push"

    def test_title_dry_run_mode(self, qtbot) -> None:
        """Window title says 'Confirm Preview' when dry run is active."""
        dialog = PushConfirmation(
            None, "Device", "WiFi", "Stereo", 5, dry_run=True
        )
        qtbot.addWidget(dialog)

        assert dialog.windowTitle() == "Confirm Preview"

    def test_dry_run_badge_visible(self, qtbot) -> None:
        """Dry run badge is shown when dry_run=True."""
        dialog = PushConfirmation(
            None, "Device", "WiFi", "Stereo", 5, dry_run=True
        )
        qtbot.addWidget(dialog)

        # Find by object name - widget exists and is not explicitly hidden
        dry_run_label = dialog.findChild(QWidget, "dry_run_badge")
        assert dry_run_label is not None
        assert not dry_run_label.isHidden()

    def test_no_dry_run_badge_when_off(self, qtbot) -> None:
        """No dry run badge when dry_run=False."""
        dialog = PushConfirmation(
            None, "Device", "WiFi", "Stereo", 5, dry_run=False
        )
        qtbot.addWidget(dialog)

        dry_run_label = dialog.findChild(QWidget, "dry_run_badge")
        assert dry_run_label is None

    def test_clamping_summary_shown(self, qtbot) -> None:
        """Clamping summary frame is displayed when clamping_summary is provided."""
        dialog = PushConfirmation(
            None,
            "Device",
            "WiFi",
            "Stereo",
            10,
            dry_run=False,
            clamping_summary="Band 3: gain clamped from +15.0 to +12.0 dB",
        )
        qtbot.addWidget(dialog)

        clamping_label = dialog.findChild(QLabel, "clamping_summary_label")
        assert clamping_label is not None
        assert "Band 3" in clamping_label.text()

    def test_no_clamping_frame_when_none(self, qtbot) -> None:
        """No clamping frame when clamping_summary is None."""
        dialog = PushConfirmation(
            None, "Device", "WiFi", "Stereo", 5, dry_run=False
        )
        qtbot.addWidget(dialog)

        clamping_frame = dialog.findChild(QWidget, "clamping_warning_frame")
        assert clamping_frame is None

    def test_mode_mismatch_warning_shown(self, qtbot) -> None:
        """Mode mismatch warning is displayed when mode_mismatch is provided."""
        dialog = PushConfirmation(
            None,
            "Device",
            "WiFi",
            "Stereo",
            5,
            dry_run=False,
            mode_mismatch="Profile is Stereo but device is in L/R mode",
        )
        qtbot.addWidget(dialog)

        mismatch_label = dialog.findChild(QLabel, "mode_mismatch_label")
        assert mismatch_label is not None
        assert "Stereo but device" in mismatch_label.text()

    def test_no_mismatch_frame_when_none(self, qtbot) -> None:
        """No mode mismatch frame when mode_mismatch is None."""
        dialog = PushConfirmation(
            None, "Device", "WiFi", "Stereo", 5, dry_run=False
        )
        qtbot.addWidget(dialog)

        mismatch_frame = dialog.findChild(QWidget, "mode_mismatch_frame")
        assert mismatch_frame is None

    def test_ok_button_text_push(self, qtbot) -> None:
        """Ok button says 'Push' when not in dry run mode."""
        dialog = PushConfirmation(
            None, "Device", "WiFi", "Stereo", 5, dry_run=False
        )
        qtbot.addWidget(dialog)

        button_box = dialog.findChild(QDialogButtonBox, "button_box")
        assert button_box is not None
        ok_btn = button_box.button(QDialogButtonBox.StandardButton.Ok)
        assert ok_btn is not None
        assert ok_btn.text() == "Push"

    def test_ok_button_text_preview(self, qtbot) -> None:
        """Ok button says 'Preview Only' in dry run mode."""
        dialog = PushConfirmation(
            None, "Device", "WiFi", "Stereo", 5, dry_run=True
        )
        qtbot.addWidget(dialog)

        button_box = dialog.findChild(QDialogButtonBox, "button_box")
        assert button_box is not None
        ok_btn = button_box.button(QDialogButtonBox.StandardButton.Ok)
        assert ok_btn is not None
        assert ok_btn.text() == "Preview Only"

    def test_accept_returns_accepted(self, qtbot) -> None:
        """Clicking Ok triggers accept (DialogCode.Accepted)."""
        dialog = PushConfirmation(
            None, "Device", "WiFi", "Stereo", 5, dry_run=False
        )
        qtbot.addWidget(dialog)

        button_box = dialog.findChild(QDialogButtonBox, "button_box")
        assert button_box is not None
        ok_btn = button_box.button(QDialogButtonBox.StandardButton.Ok)
        assert ok_btn is not None

        # Click ok - the dialog accepts
        with qtbot.waitSignal(dialog.accepted, timeout=1000):
            ok_btn.click()

        assert dialog.result() == QDialog.DialogCode.Accepted

    def test_reject_returns_rejected(self, qtbot) -> None:
        """Clicking Cancel triggers reject (DialogCode.Rejected)."""
        dialog = PushConfirmation(
            None, "Device", "WiFi", "Stereo", 5, dry_run=False
        )
        qtbot.addWidget(dialog)

        button_box = dialog.findChild(QDialogButtonBox, "button_box")
        assert button_box is not None
        cancel_btn = button_box.button(QDialogButtonBox.StandardButton.Cancel)
        assert cancel_btn is not None

        with qtbot.waitSignal(dialog.rejected, timeout=1000):
            cancel_btn.click()

        assert dialog.result() == QDialog.DialogCode.Rejected

    def test_static_confirm_true(self, qtbot) -> None:
        """Static confirm() returns True when user accepts."""
        with patch.object(PushConfirmation, "exec", return_value=QDialog.DialogCode.Accepted):
            result = PushConfirmation.confirm(
                None, "WiiM Mini", "WiFi", "Stereo", 10, dry_run=False
            )
        assert result is True

    def test_static_confirm_false(self, qtbot) -> None:
        """Static confirm() returns False when user cancels."""
        with patch.object(PushConfirmation, "exec", return_value=QDialog.DialogCode.Rejected):
            result = PushConfirmation.confirm(
                None, "WiiM Mini", "WiFi", "Stereo", 10, dry_run=False
            )
        assert result is False

    def test_consolidated_warnings(self, qtbot) -> None:
        """Both clamping and mode mismatch shown in a single dialog (Req 12.6)."""
        dialog = PushConfirmation(
            None,
            "WiiM Pro",
            "HDMI",
            "L/R",
            10,
            dry_run=False,
            clamping_summary="Band 1: Q clamped from 20.0 to 16.0",
            mode_mismatch="Profile is Stereo but device is in L/R mode",
        )
        qtbot.addWidget(dialog)

        # Both warning frames present in same dialog
        clamping_frame = dialog.findChild(QWidget, "clamping_warning_frame")
        mismatch_frame = dialog.findChild(QWidget, "mode_mismatch_frame")
        assert clamping_frame is not None
        assert mismatch_frame is not None


def _all_label_text(dialog: PushConfirmation) -> str:
    """Collect all QLabel text from the dialog into a single string."""
    from PySide6.QtWidgets import QLabel

    labels = dialog.findChildren(QLabel)
    return " ".join(label.text() for label in labels)


# ---------------------------------------------------------------------------
# CrashDialog tests (Req 24.6, 24.7, 24.13)
# ---------------------------------------------------------------------------

from src.gui.dialogs.crash_dialog import CrashDialog  # noqa: E402


class TestCrashDialog:
    """Tests for the CrashDialog modal dialog."""

    def test_displays_error_message(self, qtbot) -> None:
        """Dialog shows the error message text."""
        dialog = CrashDialog(
            None,
            error_message="ZeroDivisionError: division by zero",
            log_path="/home/user/.config/wiim-rew-sync/logs/app.log",
        )
        qtbot.addWidget(dialog)

        error_label = dialog.findChild(QLabel, "crash_error_message")
        assert error_label is not None
        assert "ZeroDivisionError" in error_label.text()

    def test_displays_log_path(self, qtbot) -> None:
        """Dialog shows the log file path (Req 24.7)."""
        log_path = "/home/user/.config/wiim-rew-sync/logs/app.log"
        dialog = CrashDialog(None, "Some error", log_path)
        qtbot.addWidget(dialog)

        log_label = dialog.findChild(QLabel, "crash_log_path_label")
        assert log_label is not None
        assert log_path in log_label.text()

    def test_displays_description(self, qtbot) -> None:
        """Dialog shows 'The app encountered an unexpected error' (Req 24.7)."""
        dialog = CrashDialog(None, "err", "/logs/app.log")
        qtbot.addWidget(dialog)

        desc_label = dialog.findChild(QLabel, "crash_description_label")
        assert desc_label is not None
        assert "unexpected error" in desc_label.text().lower()

    def test_has_view_logs_button(self, qtbot) -> None:
        """Dialog includes a 'View Logs' button (Req 24.7)."""
        dialog = CrashDialog(None, "err", "/logs/app.log")
        qtbot.addWidget(dialog)

        btn = dialog.findChild(QPushButton, "crash_view_logs_btn")
        assert btn is not None
        assert "View Logs" in btn.text()

    def test_has_support_bundle_button(self, qtbot) -> None:
        """Dialog includes a 'Generate Support Bundle' button (Req 24.13)."""
        dialog = CrashDialog(None, "err", "/logs/app.log")
        qtbot.addWidget(dialog)

        btn = dialog.findChild(QPushButton, "crash_support_bundle_btn")
        assert btn is not None
        assert "Support Bundle" in btn.text()

    def test_has_close_button(self, qtbot) -> None:
        """Dialog has a Close button."""
        dialog = CrashDialog(None, "err", "/logs/app.log")
        qtbot.addWidget(dialog)

        btn = dialog.findChild(QPushButton, "crash_close_btn")
        assert btn is not None
        assert "Close" in btn.text()

    def test_close_button_returns_close(self, qtbot) -> None:
        """Clicking Close sets result_action to 'close'."""
        dialog = CrashDialog(None, "err", "/logs/app.log")
        qtbot.addWidget(dialog)

        btn = dialog.findChild(QPushButton, "crash_close_btn")
        assert btn is not None

        with qtbot.waitSignal(dialog.accepted, timeout=1000):
            btn.click()

        assert dialog.result_action == "close"

    def test_view_logs_button_returns_view_logs(self, qtbot) -> None:
        """Clicking View Logs sets result_action to 'view_logs'."""
        dialog = CrashDialog(None, "err", "/logs/app.log")
        qtbot.addWidget(dialog)

        btn = dialog.findChild(QPushButton, "crash_view_logs_btn")
        assert btn is not None

        with qtbot.waitSignal(dialog.accepted, timeout=1000):
            btn.click()

        assert dialog.result_action == "view_logs"

    def test_support_bundle_button_returns_support_bundle(self, qtbot) -> None:
        """Clicking Generate Support Bundle sets result_action to 'support_bundle'."""
        dialog = CrashDialog(None, "err", "/logs/app.log")
        qtbot.addWidget(dialog)

        btn = dialog.findChild(QPushButton, "crash_support_bundle_btn")
        assert btn is not None

        with qtbot.waitSignal(dialog.accepted, timeout=1000):
            btn.click()

        assert dialog.result_action == "support_bundle"

    def test_static_show_crash_close(self, qtbot) -> None:
        """Static show_crash() returns 'close' when user clicks Close."""
        with patch.object(CrashDialog, "exec", return_value=QDialog.DialogCode.Accepted):
            result = CrashDialog.show_crash(None, "err", "/logs/app.log")
        assert result == "close"

    def test_static_show_crash_view_logs(self, qtbot) -> None:
        """Static show_crash() returns 'view_logs' when user clicks View Logs."""
        def fake_exec(self):
            self._result_action = CrashDialog.VIEW_LOGS
            return QDialog.DialogCode.Accepted

        with patch.object(CrashDialog, "exec", fake_exec):
            result = CrashDialog.show_crash(None, "err", "/logs/app.log")
        assert result == "view_logs"

    def test_static_show_crash_support_bundle(self, qtbot) -> None:
        """Static show_crash() returns 'support_bundle' when user clicks bundle btn."""
        def fake_exec(self):
            self._result_action = CrashDialog.SUPPORT_BUNDLE
            return QDialog.DialogCode.Accepted

        with patch.object(CrashDialog, "exec", fake_exec):
            result = CrashDialog.show_crash(None, "err", "/logs/app.log")
        assert result == "support_bundle"

    def test_dialog_is_modal(self, qtbot) -> None:
        """Dialog is modal (non-dismissable except via buttons)."""
        dialog = CrashDialog(None, "err", "/logs/app.log")
        qtbot.addWidget(dialog)

        assert dialog.isModal()

    def test_error_message_is_selectable(self, qtbot) -> None:
        """Error message text is selectable for copy (Req 24.7)."""
        dialog = CrashDialog(None, "RuntimeError: oops", "/logs/app.log")
        qtbot.addWidget(dialog)

        error_label = dialog.findChild(QLabel, "crash_error_message")
        assert error_label is not None
        flags = error_label.textInteractionFlags()
        assert flags & Qt.TextInteractionFlag.TextSelectableByMouse

    def test_log_path_is_selectable(self, qtbot) -> None:
        """Log path text is selectable for easy copy."""
        dialog = CrashDialog(None, "err", "/some/path/app.log")
        qtbot.addWidget(dialog)

        log_label = dialog.findChild(QLabel, "crash_log_path_label")
        assert log_label is not None
        flags = log_label.textInteractionFlags()
        assert flags & Qt.TextInteractionFlag.TextSelectableByMouse


# ---------------------------------------------------------------------------
# OnboardingOverlay tests (Req 23.1, 23.2, 23.3, 23.5, 23.7)
# ---------------------------------------------------------------------------

from src.gui.dialogs.onboarding_overlay import OnboardingOverlay  # noqa: E402


class TestOnboardingOverlay:
    """Tests for the OnboardingOverlay first-run welcome widget."""

    def test_title_displays(self, qtbot) -> None:
        """Overlay shows 'Welcome to WiiM PEQ Sync' title (Req 23.1)."""
        overlay = OnboardingOverlay()
        qtbot.addWidget(overlay)

        title_label = overlay.findChild(QLabel, "onboarding_title")
        assert title_label is not None
        assert "Welcome to WiiM PEQ Sync" in title_label.text()

    def test_subtitle_describes_app(self, qtbot) -> None:
        """Overlay shows app purpose description (Req 23.1)."""
        overlay = OnboardingOverlay()
        qtbot.addWidget(overlay)

        subtitle = overlay.findChild(QLabel, "onboarding_subtitle")
        assert subtitle is not None
        assert "room correction filters" in subtitle.text()
        assert "REW" in subtitle.text()
        assert "WiiM" in subtitle.text()

    def test_three_capability_cards_present(self, qtbot) -> None:
        """Overlay displays 3 capability cards (Req 23.2)."""
        overlay = OnboardingOverlay()
        qtbot.addWidget(overlay)

        # Title labels are tagged with the shared "onboardingCapTitle" QSS class
        titles = [
            lbl.text()
            for lbl in overlay.findChildren(QLabel)
            if lbl.property("class") == "onboardingCapTitle"
        ]

        assert "Import Filters" in titles
        assert "Push Safely" in titles
        assert "Save Presets" in titles

    def test_capability_card_descriptions(self, qtbot) -> None:
        """Each capability card has a one-sentence description (Req 23.2)."""
        overlay = OnboardingOverlay()
        qtbot.addWidget(overlay)

        # Description labels are tagged with the shared "onboardingCapDesc" QSS class
        descriptions = [
            lbl.text()
            for lbl in overlay.findChildren(QLabel)
            if lbl.property("class") == "onboardingCapDesc"
        ]

        assert any("REW" in text for text in descriptions)
        assert any("backup" in text for text in descriptions)
        assert any("library" in text for text in descriptions)

    def test_get_started_button_present(self, qtbot) -> None:
        """Overlay has a 'Get Started' button (Req 23.3)."""
        overlay = OnboardingOverlay()
        qtbot.addWidget(overlay)

        btn = overlay.findChild(QLabel, "get_started_button")
        assert btn is not None
        assert "Get Started" in btn.text()

    def test_get_started_emits_signal_and_hides(self, qtbot) -> None:
        """Clicking 'Get Started' emits get_started_clicked and hides overlay (Req 23.3)."""
        overlay = OnboardingOverlay()
        qtbot.addWidget(overlay)
        overlay.show()

        with qtbot.waitSignal(overlay.get_started_clicked, timeout=1000):
            overlay._on_get_started()

        assert not overlay.isVisible()

    def test_overlay_has_semi_transparent_background(self, qtbot) -> None:
        """Overlay is styled-background enabled so QSS can paint the dark backdrop."""
        overlay = OnboardingOverlay()
        qtbot.addWidget(overlay)

        # The semi-transparent backdrop color lives in the QSS theme files,
        # targeted via objectName; this attribute is what makes that paint.
        assert overlay.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        assert overlay.objectName() == "onboarding_overlay"

    def test_overlay_object_name(self, qtbot) -> None:
        """Overlay has proper object name for QSS targeting."""
        overlay = OnboardingOverlay()
        qtbot.addWidget(overlay)

        assert overlay.objectName() == "onboarding_overlay"


# ---------------------------------------------------------------------------
# UnsavedChangesDialog tests
# ---------------------------------------------------------------------------

from unittest.mock import patch as _patch  # noqa: E402 (appended section)

from src.gui.dialogs.unsaved_changes_dialog import UnsavedChangesDialog  # noqa: E402


class TestUnsavedChangesDialog:
    """Tests for the UnsavedChangesDialog modal dialog (Req 12.5)."""

    def test_dialog_is_modal(self, qtbot) -> None:
        """Dialog is modal to prevent interaction with underlying window."""
        dialog = UnsavedChangesDialog(None)
        qtbot.addWidget(dialog)

        assert dialog.isModal()

    def test_window_title(self, qtbot) -> None:
        """Window title is 'Unsaved Changes'."""
        dialog = UnsavedChangesDialog(None)
        qtbot.addWidget(dialog)

        assert dialog.windowTitle() == "Unsaved Changes"

    def test_warning_icon_present(self, qtbot) -> None:
        """Warning icon is displayed in the header."""
        dialog = UnsavedChangesDialog(None)
        qtbot.addWidget(dialog)

        icon = dialog.findChild(QLabel, "warning_icon")
        assert icon is not None
        assert "\u26a0" in icon.text()

    def test_title_label_present(self, qtbot) -> None:
        """Title label displays 'Unsaved Changes'."""
        dialog = UnsavedChangesDialog(None)
        qtbot.addWidget(dialog)

        title = dialog.findChild(QLabel, "dialog_title")
        assert title is not None
        assert "Unsaved Changes" in title.text()

    def test_message_label_present(self, qtbot) -> None:
        """Message explains unsaved filter changes."""
        dialog = UnsavedChangesDialog(None)
        qtbot.addWidget(dialog)

        message = dialog.findChild(QLabel, "dialog_message")
        assert message is not None
        assert "unsaved filter changes" in message.text()

    def test_two_buttons_present(self, qtbot) -> None:
        """Dialog has Discard and Continue Working buttons."""
        dialog = UnsavedChangesDialog(None)
        qtbot.addWidget(dialog)

        from PySide6.QtWidgets import QPushButton

        discard = dialog.findChild(QPushButton, "discard_button")
        cancel = dialog.findChild(QPushButton, "cancel_button")

        assert discard is not None
        assert cancel is not None

    def test_discard_button_click_returns_discard(self, qtbot) -> None:
        """Clicking Discard sets choice to 'discard' and accepts dialog."""
        dialog = UnsavedChangesDialog(None)
        qtbot.addWidget(dialog)

        from PySide6.QtWidgets import QPushButton

        discard_btn = dialog.findChild(QPushButton, "discard_button")
        assert discard_btn is not None

        with qtbot.waitSignal(dialog.accepted, timeout=1000):
            discard_btn.click()

        assert dialog.choice == "discard"

    def test_cancel_button_click_returns_cancel(self, qtbot) -> None:
        """Clicking Cancel sets choice to 'cancel' and rejects dialog."""
        dialog = UnsavedChangesDialog(None)
        qtbot.addWidget(dialog)

        from PySide6.QtWidgets import QPushButton

        cancel_btn = dialog.findChild(QPushButton, "cancel_button")
        assert cancel_btn is not None

        with qtbot.waitSignal(dialog.rejected, timeout=1000):
            cancel_btn.click()

        assert dialog.choice == "cancel"

    def test_default_choice_is_cancel(self, qtbot) -> None:
        """Default choice before any button press is 'cancel'."""
        dialog = UnsavedChangesDialog(None)
        qtbot.addWidget(dialog)

        assert dialog.choice == "cancel"

    def test_static_confirm_discard_discard(self, qtbot) -> None:
        """Static confirm_discard() returns 'discard' when user clicks Discard."""
        with _patch.object(UnsavedChangesDialog, "exec", return_value=QDialog.DialogCode.Accepted):
            with _patch.object(
                UnsavedChangesDialog,
                "choice",
                new_callable=lambda: property(lambda self: "discard"),
            ):
                result = UnsavedChangesDialog.confirm_discard(None)
        assert result == "discard"

    def test_static_confirm_discard_cancel(self, qtbot) -> None:
        """Static confirm_discard() returns 'cancel' when user clicks Cancel."""
        with _patch.object(UnsavedChangesDialog, "exec", return_value=QDialog.DialogCode.Rejected):
            result = UnsavedChangesDialog.confirm_discard(None)
        assert result == "cancel"


from src.gui.dialogs.quick_setup_dialog import QuickSetupDialog  # noqa: E402


class TestQuickSetupDialog:
    """Tests for the single-layout QuickSetupDialog (both sections always present)."""

    def test_both_sections_always_present(self, qtbot) -> None:
        """EQ Type and Source sections both exist regardless of need_* flags."""
        dialog = QuickSetupDialog(None, need_eq_type=False, need_source=False)
        qtbot.addWidget(dialog)

        assert hasattr(dialog, "_peq_radio")
        assert hasattr(dialog, "_roomfit_radio")
        assert hasattr(dialog, "_source_section")

    def test_size_unchanged_between_eq_type_selections(self, qtbot) -> None:
        """Selecting RoomFit greys the source section out, not hides it (no reflow)."""
        dialog = QuickSetupDialog(
            None, need_eq_type=True, need_source=True,
            available_sources=["wifi", "bluetooth"],
        )
        qtbot.addWidget(dialog)
        dialog.show()

        size_before = dialog.sizeHint()
        dialog._roomfit_radio.setChecked(True)
        size_after = dialog.sizeHint()

        assert dialog._source_section.isVisible()
        assert size_before == size_after

    def test_roomfit_selected_disables_source_section(self, qtbot) -> None:
        """Source section is disabled (greyed), not hidden, when RoomFit is chosen."""
        dialog = QuickSetupDialog(None, need_eq_type=True, need_source=True)
        qtbot.addWidget(dialog)
        dialog.show()

        dialog._roomfit_radio.setChecked(True)

        assert dialog._source_section.isVisible()
        assert not dialog._source_section.isEnabled()

    def test_locked_eq_type_section_disabled_but_shown(self, qtbot) -> None:
        """need_eq_type=False shows the fixed value, disabled."""
        dialog = QuickSetupDialog(
            None, need_eq_type=False, need_source=True, current_eq_type="roomfit",
        )
        qtbot.addWidget(dialog)

        assert dialog._roomfit_radio.isChecked()
        assert not dialog._eq_section.isEnabled()

    def test_locked_source_section_disabled_but_shown(self, qtbot) -> None:
        """need_source=False shows the fixed sources, disabled."""
        dialog = QuickSetupDialog(
            None, need_eq_type=True, need_source=False,
            available_sources=["wifi", "HDMI"], current_sources=["HDMI"],
        )
        qtbot.addWidget(dialog)
        dialog.show()

        assert dialog._source_section.isVisible()
        assert not dialog._source_section.isEnabled()
        assert dialog._source_checkboxes["HDMI"].isChecked()

    def test_roomfit_disabled_when_device_does_not_support_it(self, qtbot) -> None:
        """supports_roomfit=False disables the RoomFit radio with a tooltip."""
        dialog = QuickSetupDialog(
            None, need_eq_type=True, need_source=True, supports_roomfit=False,
        )
        qtbot.addWidget(dialog)

        assert not dialog._roomfit_radio.isEnabled()
        assert dialog._roomfit_radio.toolTip() != ""

    def test_accept_returns_selected_sources(self, qtbot) -> None:
        """Accepting with PEQ and a checked source returns that source list."""
        dialog = QuickSetupDialog(
            None, need_eq_type=True, need_source=True,
            available_sources=["wifi", "optical"],
        )
        qtbot.addWidget(dialog)

        dialog._source_checkboxes["optical"].setChecked(True)
        dialog._on_accept()

        assert dialog.eq_type == "peq"
        assert "optical" in dialog.selected_sources

    def test_ok_disabled_until_source_checked_when_needed(self, qtbot) -> None:
        """OK stays disabled while need_source=True and PEQ has no source checked."""
        dialog = QuickSetupDialog(
            None, need_eq_type=False, need_source=True,
            available_sources=["wifi"], current_sources=[],
        )
        qtbot.addWidget(dialog)

        for cb in dialog._source_checkboxes.values():
            cb.setChecked(False)
        dialog._update_ok_enabled()

        ok_btn = dialog._button_box.button(QDialogButtonBox.StandardButton.Ok)
        assert not ok_btn.isEnabled()
