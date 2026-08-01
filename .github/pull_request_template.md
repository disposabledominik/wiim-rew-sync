## Summary

-

## Test plan

- [ ] `pytest` for touched module(s) — `python3 -m pytest src/tests/test_<module>.py -v --no-cov`
- [ ] `ruff check src/` — zero errors
- [ ] `mypy src/` — zero errors
- [ ] If this PR fixes a logged GUI bug, `docs/smoke_test_issues.md`'s Status + Fix Commit for
      that row are updated in this same PR (CLAUDE.md's same-commit rule) — not "N/A" by default,
      actually check the row.
