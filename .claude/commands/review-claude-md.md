Review `CLAUDE.md` against the current codebase. Do not make changes — propose
them only. Check four things:

**1. Stale references.**
Extract every backticked file path, function name, class name, and test name from `CLAUDE.md` and
confirm each exists at the stated location via `grep`/`find` in `src/`. Do not rely on a fixed list
of examples — re-derive the list from the current file contents each time, since the set of named
symbols changes as CLAUDE.md is edited.
Also verify structural claims: anything CLAUDE.md says was removed, renamed, or no longer exists
should actually be absent from `src/`; anything it says is the current pattern should actually be
the pattern in use (not a superseded one).

**2. Missing rules.**
Did recent sessions involve a recurring mistake — the same class of bug fixed more than once, a
pattern that had to be corrected, a test that asserted the wrong thing, a missed parallel flow?
If yes, propose one specific addition: the rule text, the section it belongs in, and why it
belongs there rather than in a doc file. Before proposing, check whether the fact already lives in
`docs/` (architecture.md, wiim_api_notes.md, corrections.md, etc.) — if it does, propose a pointer
reference instead of restating it, unless the rule is one that must be caught *before* writing code
(i.e. it actually bites when missing from the file an agent reads every session).

**3. Redundant or superseded rules.**
Are any existing rules irrelevant because the code structure changed, the trap no longer exists,
or another rule covers the same ground more precisely? Is any rule's content already fully stated
elsewhere in `docs/` with no reason for CLAUDE.md to carry its own copy? Quote the candidate and
explain why it can be removed or shortened.

For each proposed change: quote the current text (or state "no current text" for additions),
show the proposed replacement or addition, and label it as STALE / MISSING / REDUNDANT.
Do not propose stylistic rewrites. If nothing needs changing, say so explicitly.

**4. Bloat.**
Has the file grown too large to be efficient? Does it contain too much prose, or too much noise
versus signal? Instructions should be terse and pragmatic, so they are easy to parse and difficult
to overlook.
