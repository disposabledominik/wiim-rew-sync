Scan `CLAUDE.md` for references that are now factually wrong due to what was
changed in this session. Look for: renamed files, deleted modules or functions, moved helpers,
replaced patterns.

Extract every backticked file path, function name, class name, and test name from `CLAUDE.md` and
confirm each still exists at the stated location — do not rely on a fixed list of examples,
re-derive it from the file's current contents, since which symbols are named changes as CLAUDE.md
is edited over time.

List only concrete factual errors. One sentence per finding: quote the stale text, state what
it should say. Do not propose stylistic rewrites, new rules, or improvements — only factual
corrections caused by this session's changes. If nothing is stale, say so explicitly.
