# Release Process

How to cut a release, from a green `development` branch to a published GitHub Release.
Read time: ~2 minutes. Come back here every time you cut a release -- don't wing it from memory.

## Steps

1. **Merge `development` into `main`.** `main` only ever receives merges from `development`
   (see [CLAUDE.md](../CLAUDE.md)) -- no separate PR needed for this step, since the actual
   review already happened on the PRs that landed on `development`.
   ```bash
   git push origin origin/development:main
   ```

2. **Tag the resulting commit** with [`scripts/tag_release.sh`](../scripts/tag_release.sh) --
   never write the tag message by hand, so every release reads the same way:
   ```bash
   scripts/tag_release.sh vX.Y.Z --push
   ```
   Run with `--dry-run` first to preview the message before creating anything. Version numbers
   are semver (`vMAJOR.MINOR.PATCH`): bump PATCH for a fix-only release, MINOR for new features,
   MAJOR for a breaking change.

3. **Pushing the tag triggers [`release.yml`](../.github/workflows/release.yml)** automatically:
   `pip-audit` gate -> build on Windows/macOS/Linux -> a **draft** GitHub Release with
   auto-generated notes and the three build artifacts attached.

4. **Review and publish the draft release**: <https://github.com/disposabledominik/wiim-rew-sync/releases>.
   Edit the auto-generated notes if needed, then publish.

## What keeps releases consistent

- **PR titles are the source of truth.** They feed both the auto-generated GitHub Release notes
  and the tag message from `tag_release.sh` -- write each one as you'd want it to read in a
  changelog. CI's `pr-title` job ([`ci.yml`](../.github/workflows/ci.yml)) rejects empty,
  too-short, or placeholder (`wip`, `fix`, ...) titles as a floor, not a style guide.
- **Never hand-write a tag message** -- always go through `tag_release.sh`.
- **Never rewrite an already-pushed tag.** Force-recreating one re-triggers `release.yml` and
  will fail outright if that tag already has a published Release attached.
