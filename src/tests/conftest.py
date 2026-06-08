"""
Shared pytest fixtures and Hypothesis strategies for the WiiM ↔ REW PEQ Sync Tool test suite.

Strategies defined here (used across multiple PBT tasks):
  - st_canonical_filter()           — a single valid CanonicalFilter
  - st_canonical_filter_list()      — a list of valid CanonicalFilters
  - st_float_near_boundary()        — floats near a tolerance boundary
"""

from __future__ import annotations

# Strategies will be implemented in later tasks (Tasks 5, 8, 11, 12).
# This file is a placeholder that ensures the tests/ package is recognised
# by pytest and that shared fixtures are importable.
