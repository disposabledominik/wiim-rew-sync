#!/usr/bin/env bash
# tag_release.sh — create a consistently-formatted annotated release tag.
#
# Message format: "vX.Y.Z -- <theme>, <theme>, ..." where each <theme> is the
# title of one PR merged into the target ref since the previous vX.Y.Z tag.
# This mirrors the granularity .github/workflows/release.yml's
# `gh release create --generate-notes` already uses for the GitHub Release
# body (PR titles since the last tag) -- the tag message is a shorter,
# git-log-skimmable summary of the same information, not a separate
# changelog. A merge commit that isn't "Merge pull request #N from ..."
# (e.g. a manual merge) falls back to its own subject line as the theme.
#
# Usage:
#   scripts/tag_release.sh vX.Y.Z [--from=<tag-or-ref>] [--to=<ref>]
#                                  [--message=STR] [--push] [--dry-run]
#
#   vX.Y.Z         Required. New tag name; must match vMAJOR.MINOR.PATCH.
#   --from=REF     Base ref to diff from (default: the latest existing
#                  vX.Y.Z-format tag).
#   --to=REF       Ref to tag (default: HEAD).
#   --message=STR  Use this message verbatim instead of auto-generating one.
#   --push         Push the new tag to 'origin' after creating it (triggers
#                  release.yml). Omit to create locally and push by hand.
#   --dry-run      Print the resolved message and exit without creating the tag.
#
# Examples:
#   scripts/tag_release.sh v0.5.0 --push
#   scripts/tag_release.sh v0.6.0 --dry-run
#   scripts/tag_release.sh v1.0.0 --from=v0.4.0 --message="v1.0.0 -- First stable release"

set -euo pipefail

usage() {
  echo "Usage: $0 vX.Y.Z [--from=<tag-or-ref>] [--to=<ref>] [--message=STR] [--push] [--dry-run]" >&2
  exit 1
}

[[ $# -ge 1 ]] || usage
NEW_TAG="$1"
shift
[[ "$NEW_TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] \
  || { echo "ERROR: tag must match vMAJOR.MINOR.PATCH (got '$NEW_TAG')" >&2; exit 1; }

FROM_REF=""
TO_REF="HEAD"
MESSAGE=""
DO_PUSH=0
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --from=*) FROM_REF="${arg#--from=}" ;;
    --to=*) TO_REF="${arg#--to=}" ;;
    --message=*) MESSAGE="${arg#--message=}" ;;
    --push) DO_PUSH=1 ;;
    --dry-run) DRY_RUN=1 ;;
    *) echo "Unknown flag: $arg" >&2; usage ;;
  esac
done

if git rev-parse "$NEW_TAG" >/dev/null 2>&1; then
  echo "ERROR: tag '$NEW_TAG' already exists." >&2
  exit 1
fi

if [[ -z "$FROM_REF" ]]; then
  FROM_REF=$(git tag -l 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | head -n1)
  if [[ -z "$FROM_REF" ]]; then
    echo "ERROR: no prior vX.Y.Z tag found -- pass --from=<ref> explicitly for the first release." >&2
    exit 1
  fi
fi

if [[ -z "$MESSAGE" ]]; then
  # mapfile first, rather than piping straight into a `while read` loop --
  # git commands run inside the loop body would otherwise share the loop's
  # stdin (the process-substitution pipe) and can silently eat lines meant
  # for `read`, truncating the walk after the first merge commit.
  # --reverse for chronological (oldest-first) order, so the message reads
  # as "did X, then Y" rather than newest-merge-first.
  mapfile -t merge_hashes < <(git log "${FROM_REF}..${TO_REF}" --merges --first-parent --reverse --pretty=format:%H)

  themes=()
  for hash in "${merge_hashes[@]}"; do
    subject=$(git log -1 --pretty=format:%s "$hash")
    if [[ "$subject" =~ ^Merge\ pull\ request\ \#[0-9]+\ from ]]; then
      title=$(git log -1 --pretty=format:%b "$hash" | sed '/^$/d' | head -n1)
      themes+=("${title:-$subject}")
    else
      themes+=("$subject")
    fi
  done

  if [[ ${#themes[@]} -eq 0 ]]; then
    echo "ERROR: no merge commits found between $FROM_REF and $TO_REF -- pass --message explicitly." >&2
    exit 1
  fi

  joined=$(printf ', %s' "${themes[@]}")
  joined="${joined:2}"
  MESSAGE="${NEW_TAG} -- ${joined}"
fi

echo "Tag:     $NEW_TAG"
echo "Range:   ${FROM_REF}..${TO_REF}"
echo "Message: $MESSAGE"

if [[ "$DRY_RUN" == "1" ]]; then
  echo "(dry run -- no tag created)"
  exit 0
fi

git tag -a "$NEW_TAG" -m "$MESSAGE" "$TO_REF"
echo "Created annotated tag '$NEW_TAG' at $(git rev-parse --short "$TO_REF")."

if [[ "$DO_PUSH" == "1" ]]; then
  git push origin "$NEW_TAG"
  echo "Pushed '$NEW_TAG' to origin -- this triggers .github/workflows/release.yml."
else
  echo "Not pushed. Run: git push origin $NEW_TAG"
fi
