"""Push Confirmation Dialog - pre-push summary modal.

Displays a consolidated summary of the push operation parameters and
requires explicit user confirmation before the Safe Write Protocol executes.

Consolidates all relevant information (device, source, channel mode, band count,
dry run state, clamping summary, mode mismatch) into a single dialog to avoid
sequential confirmation fatigue (Req 12.6).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from src.gui.constants import (
    SPACING_MD,
    SPACING_SM,
)


class PushConfirmation(QDialog):
    """Pre-push summary modal dialog.

    Shows all push parameters in a single consolidated view and asks
    the user to confirm or cancel before the Safe Write Protocol runs.

    Use the static ``confirm()`` method for standard usage.
    """

    def __init__(
        self,
        parent: QWidget | None,
        device_name: str,
        source: str,
        channel_mode: str,
        band_count: int,
        dry_run: bool,
        *,
        clamping_summary: str | None = None,
        mode_mismatch: str | None = None,
    ) -> None:
        """Initialize the push confirmation dialog.

        Args:
            parent: Parent widget (may be None).
            device_name: Name of the target WiiM device.
            source: Audio source/input name (e.g. "HDMI", "WiFi").
            channel_mode: Channel mode string (e.g. "Stereo", "L/R").
            band_count: Number of active filter bands being pushed.
            dry_run: Whether this is a dry-run (preview only) operation.
            clamping_summary: Optional summary of clamped filter values.
            mode_mismatch: Optional warning about channel mode mismatch.
        """
        super().__init__(parent)
        self.setWindowTitle("Confirm Push" if not dry_run else "Confirm Preview")
        self.setMinimumWidth(420)
        self.setModal(True)

        self._setup_ui(
            device_name,
            source,
            channel_mode,
            band_count,
            dry_run,
            clamping_summary,
            mode_mismatch,
        )

    def _setup_ui(
        self,
        device_name: str,
        source: str,
        channel_mode: str,
        band_count: int,
        dry_run: bool,
        clamping_summary: str | None,
        mode_mismatch: str | None,
    ) -> None:
        """Build the dialog layout."""
        layout = QVBoxLayout(self)
        layout.setSpacing(SPACING_MD)

        # --- Header ---
        if dry_run:
            header_text = "Preview Operation Summary"
        else:
            header_text = "Push to Device"
        header = QLabel(f"<h3>{header_text}</h3>")
        header.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(header)

        # --- Dry run badge ---
        if dry_run:
            dry_run_label = QLabel("DRY RUN — no changes will be made to your device")
            dry_run_label.setObjectName("dry_run_badge")
            dry_run_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(dry_run_label)

        # --- Summary info ---
        info_frame = QFrame()
        info_frame.setObjectName("push_summary_frame")
        info_frame.setFrameShape(QFrame.Shape.StyledPanel)
        info_layout = QVBoxLayout(info_frame)
        info_layout.setSpacing(SPACING_SM)

        info_layout.addWidget(self._info_row("Device:", device_name))
        info_layout.addWidget(self._info_row("Source:", source))
        info_layout.addWidget(self._info_row("Channel mode:", channel_mode))
        info_layout.addWidget(self._info_row("Active bands:", str(band_count)))

        layout.addWidget(info_frame)

        # --- Clamping summary (orange warning) ---
        if clamping_summary:
            clamping_frame = QFrame()
            clamping_frame.setObjectName("clamping_warning_frame")
            clamping_frame.setProperty("class", "warningBox")
            clamping_layout = QVBoxLayout(clamping_frame)
            clamping_layout.setSpacing(SPACING_SM)

            clamping_header = QLabel("<b>⚠ Values clamped to device limits</b>")
            clamping_header.setTextFormat(Qt.TextFormat.RichText)
            clamping_header.setProperty("class", "warning")
            clamping_layout.addWidget(clamping_header)

            clamping_body = QLabel(clamping_summary)
            clamping_body.setObjectName("clamping_summary_label")
            clamping_body.setWordWrap(True)
            clamping_body.setTextFormat(Qt.TextFormat.PlainText)
            clamping_layout.addWidget(clamping_body)

            layout.addWidget(clamping_frame)

        # --- Mode mismatch warning ---
        if mode_mismatch:
            mismatch_frame = QFrame()
            mismatch_frame.setObjectName("mode_mismatch_frame")
            mismatch_frame.setProperty("class", "warningBox")
            mismatch_layout = QVBoxLayout(mismatch_frame)
            mismatch_layout.setSpacing(SPACING_SM)

            mismatch_header = QLabel("<b>⚠ Channel mode mismatch</b>")
            mismatch_header.setTextFormat(Qt.TextFormat.RichText)
            mismatch_header.setProperty("class", "warning")
            mismatch_layout.addWidget(mismatch_header)

            mismatch_body = QLabel(mode_mismatch)
            mismatch_body.setObjectName("mode_mismatch_label")
            mismatch_body.setWordWrap(True)
            mismatch_body.setTextFormat(Qt.TextFormat.PlainText)
            mismatch_layout.addWidget(mismatch_body)

            layout.addWidget(mismatch_frame)

        # --- Button box (Ok / Cancel) ---
        layout.addSpacing(SPACING_SM)
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.setObjectName("button_box")

        ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button is not None:
            if dry_run:
                ok_button.setText("Preview Only")
            else:
                ok_button.setText("Push")
            ok_button.setFocus()

        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    @staticmethod
    def _info_row(label: str, value: str) -> QWidget:
        """Create a horizontal label: value row widget."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(SPACING_SM)

        lbl = QLabel(f"<b>{label}</b>")
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setFixedWidth(110)
        row_layout.addWidget(lbl)

        val = QLabel(value)
        val.setTextFormat(Qt.TextFormat.PlainText)
        row_layout.addWidget(val, 1)

        return row

    @staticmethod
    def confirm(
        parent: QWidget | None,
        device_name: str,
        source: str,
        channel_mode: str,
        band_count: int,
        dry_run: bool,
        *,
        clamping_summary: str | None = None,
        mode_mismatch: str | None = None,
    ) -> bool:
        """Show the push confirmation dialog and return True if user confirmed.

        This is the primary entry point. Consolidates all push information
        into a single confirmation dialog (Req 12.6).

        Args:
            parent: Parent widget (may be None).
            device_name: Name of the target WiiM device.
            source: Audio source/input name.
            channel_mode: Channel mode (e.g. "Stereo", "L/R").
            band_count: Number of active filter bands.
            dry_run: Whether dry-run mode is active.
            clamping_summary: Summary text of clamped values (Req 12.2).
            mode_mismatch: Warning text for mode mismatch (Req 12.3).

        Returns:
            True if user clicked Ok/Push, False if cancelled.
        """
        dialog = PushConfirmation(
            parent,
            device_name,
            source,
            channel_mode,
            band_count,
            dry_run,
            clamping_summary=clamping_summary,
            mode_mismatch=mode_mismatch,
        )
        return dialog.exec() == QDialog.DialogCode.Accepted
