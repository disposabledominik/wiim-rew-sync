"""Shared helper for QSS dynamic-property-driven styling.

Widgets that vary their QSS appearance at runtime (e.g. a label that
switches between the ``warning``/``error``/``success`` classes, or a row
that toggles a ``selected``/``active`` property) all need the same
three-step dance: set the property, then force Qt to re-evaluate the
stylesheet for that widget. This module is the single place that does it.
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget


def set_qss_property(widget: QWidget, name: str, value: object) -> None:
    """Set a dynamic property used by a QSS selector and force a style refresh.

    Qt caches a widget's matched stylesheet rules; changing a property that
    a QSS attribute selector (e.g. ``[class="warning"]``) depends on has no
    visible effect until ``unpolish``/``polish`` is called to force
    re-evaluation.
    """
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
