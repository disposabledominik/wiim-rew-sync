"""
Shared pytest fixtures and Hypothesis strategies for the WiiM ↔ REW PEQ Sync Tool test suite.

Strategies defined here (used across multiple PBT tasks):
  - st_canonical_filter()           — a single valid CanonicalFilter
  - st_canonical_filter_list()      — a list of valid CanonicalFilters
  - st_float_near_boundary()        — floats near a tolerance boundary
"""

from __future__ import annotations

from hypothesis import strategies as st


def st_float_near_boundary(center: float, tolerance: float) -> st.SearchStrategy[float]:
    """Generate floats near a boundary: within tolerance OR just outside."""
    return st.one_of(
        # Within tolerance (should match)
        st.floats(
            min_value=center - tolerance,
            max_value=center + tolerance,
            allow_nan=False,
            allow_infinity=False,
        ),
        # Just outside tolerance (should not match)
        st.floats(
            min_value=center + tolerance * 1.001,
            max_value=center + tolerance * 2,
            allow_nan=False,
            allow_infinity=False,
        ),
        st.floats(
            min_value=center - tolerance * 2,
            max_value=center - tolerance * 1.001,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
