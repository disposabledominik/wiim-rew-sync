"""Wizard step pages for the guided workflow.

Each page is a self-contained QWidget representing one step in the adaptive
wizard flow (Connect, EQ Type, Source, Filters, Review, Name Profile, Push).
Pages emit signals; the WizardController handles transitions and data flow.
"""

from __future__ import annotations
