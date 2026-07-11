#!/usr/bin/env bash
# cleanup_stray_peq_sources.sh — find and (optionally) attempt to clear stray EQLevel:1
# per-source PEQ slots left behind by garbage/comma-joined source_name values that were
# written to a device in the past (e.g. by the wizard's now-tracked multi-source
# state.selected_source bug, or by manual testing with a typo'd source name).
#
# There is NO documented WiiM command to delete a per-source live buffer slot —
# EQv2Delete only removes named profiles from EQv2GetNewList, a different storage layer
# entirely (docs/wiim_api_notes.md, PEQ Profile CRUD). This script exists to find out,
# empirically and safely, whether either of the two plausible mechanisms actually
# removes a stray row from EQGetSourceModes, or whether such rows are permanent/cosmetic.
#
# CONFIRMED RESULT (docs/corrections.md, 2026-07-10): both mechanisms return
# NOT REMOVABLE on every device tested (4 models) — a stray source_name slot's content
# can be reset, but the row itself never disappears from EQGetSourceModes. Broader API
# research turned up no other candidate command either. Treat stray slots as permanent.
# This script is kept in the repo, unmodified, in case a future firmware update changes
# this — re-running it would detect that automatically (a REMOVED result would be new
# and worth a fresh docs/corrections.md row).
#
# Requires: curl, jq. Run from WSL2 bash (or Git Bash) against a real device on the LAN.
#
# Usage: ./cleanup_stray_peq_sources.sh <device-ip> [--clean] [--yes]
#   (no flags)  Diagnose only — list every EQGetSourceModes row and flag which ones look
#               like stray/garbage source_name slots. Never writes anything.
#   --clean     For each flagged row, after per-row confirmation (or automatically with
#               --yes), attempt to clear it and report whether the row actually
#               disappeared from EQGetSourceModes afterward.
#   --yes       Skip the per-row confirmation prompt under --clean.
#
# Safety: operates ONLY at EQLevel:1 (PEQ). Never touches EQLevel:2 (RoomFit) — see the
# RoomFit isolation-boundary findings in docs/wiim_api_notes.md before ever considering
# that layer. A row is only ever a "candidate" if its source_name does NOT exactly match
# (case-sensitive) a real source reported by getAudioInputEnable/getAudioInputCapbility,
# nor a case-swapped variant of one (HDMI/hdmi are BOTH real, documented, per-channelMode
# slots — not stray). "udisk" is excluded too (a documented device-native non-PEQ-source
# quirk, unrelated to this app's bug). This filter is NOT overridable by any flag.

set -uo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: this script requires 'jq'. Install: sudo apt-get install -y jq" >&2
  exit 1
fi

WIIM_IP="${1:-}"
if [[ -z "$WIIM_IP" || "$WIIM_IP" == --* ]]; then
  echo "Usage: $0 <device-ip> [--clean] [--yes]" >&2
  exit 1
fi
shift

DO_CLEAN=0
AUTO_YES=0
for arg in "$@"; do
  case "$arg" in
    --clean) DO_CLEAN=1 ;;
    --yes) AUTO_YES=1 ;;
    *) echo "Unknown flag: $arg" >&2; exit 1 ;;
  esac
done

BASE="https://${WIIM_IP}/httpapi.asp"
PLUGIN_URI="http://moddevices.com/plugins/caps/EqNp"

log_pass() { printf '[PASS] %s\n' "$1"; }
log_fail() { printf '[FAIL] %s\n' "$1"; }
log_warn() { printf '[WARN] %s\n' "$1"; }
log_info() { printf '[INFO] %s\n' "$1"; }
log_skip() { printf '[SKIP] %s\n' "$1"; }

call() {
  curl -sk --max-time 5 -G --data-urlencode "command=$1" "$BASE"
}

is_recognized() {
  local lower
  lower=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')
  case "$lower" in
    *"unknown command"*|"") return 1 ;;
    *) return 0 ;;
  esac
}

confirm() {
  if [[ "$AUTO_YES" == "1" ]]; then return 0; fi
  local ans
  read -r -p "$1 [type YES to proceed, anything else skips]: " ans
  [[ "$ans" == "YES" ]]
}

# ---------------------------------------------------------------------------
# Connectivity + real-source set
# ---------------------------------------------------------------------------
log_info "Checking connectivity to $WIIM_IP ..."
status=$(call "getStatusEx")
if ! is_recognized "$status"; then
  log_fail "getStatusEx did not return a valid response — check IP/network. Raw: $status"
  exit 1
fi
MODEL=$(jq -r '.project // "unknown"' <<<"$status")
log_info "Connected. project=$MODEL"

REAL_SOURCES=()
ae=$(call "getAudioInputEnable")
if is_recognized "$ae"; then
  while IFS= read -r m; do REAL_SOURCES+=("$m"); done < <(jq -r '.audioInput[]?.mode' <<<"$ae")
fi
ac=$(call "getAudioInputCapbility")
if is_recognized "$ac"; then
  while IFS= read -r m; do REAL_SOURCES+=("$m"); done < <(jq -r '.audioInput[]?.mode' <<<"$ac")
fi
if [[ "${#REAL_SOURCES[@]}" -eq 0 ]]; then
  log_warn "Neither getAudioInputEnable nor getAudioInputCapbility returned a source list (e.g. WiiM Mini) — falling back to a generic known-name set. Add this device's real source names to REAL_SOURCES below if it has an enumeration gap, to avoid misclassifying a real source as stray."
  REAL_SOURCES=(wifi bluetooth line-in optical HDMI hdmi auxIn)
fi
REAL_SOURCES+=(udisk)
log_info "Real/known source names for this device: ${REAL_SOURCES[*]}"

is_real_source() {
  local candidate="$1" s lower_candidate lower_s
  lower_candidate=$(printf '%s' "$candidate" | tr '[:upper:]' '[:lower:]')
  for s in "${REAL_SOURCES[@]}"; do
    lower_s=$(printf '%s' "$s" | tr '[:upper:]' '[:lower:]')
    [[ "$lower_candidate" == "$lower_s" ]] && return 0
  done
  return 1
}

# ---------------------------------------------------------------------------
# Enumerate + classify
# ---------------------------------------------------------------------------
modes=$(call "EQGetSourceModes")
if ! is_recognized "$modes"; then
  log_fail "EQGetSourceModes is not supported on this device/firmware — nothing to diagnose here."
  exit 1
fi

mapfile -t rows < <(jq -c --arg uri "$PLUGIN_URI" '.[] | select(.pluginURI==$uri)' <<<"$modes")
log_info "EQGetSourceModes returned ${#rows[@]} row(s) for pluginURI=EqNp (other pluginURI rows, e.g. legacy Eq10HP, are ignored)."

declare -a CANDIDATES=()
for row in "${rows[@]}"; do
  sn=$(jq -r '.source_name' <<<"$row")
  name=$(jq -r '.Name // empty' <<<"$row")
  cmode=$(jq -r '.channelMode // empty' <<<"$row")
  stat=$(jq -r '.EQStat // empty' <<<"$row")
  if [[ "$sn" == *","* ]]; then
    log_warn "CANDIDATE (comma-joined, cannot be a real single input): source_name='$sn' Name='$name' channelMode='$cmode' EQStat='$stat'"
    CANDIDATES+=("$sn")
  elif ! is_real_source "$sn"; then
    log_warn "CANDIDATE (not a known real source): source_name='$sn' Name='$name' channelMode='$cmode' EQStat='$stat'"
    CANDIDATES+=("$sn")
  else
    log_pass "Real source, not touched: source_name='$sn' Name='$name' channelMode='$cmode' EQStat='$stat'"
  fi
done

if [[ "${#CANDIDATES[@]}" -eq 0 ]]; then
  echo
  log_pass "No stray/candidate source_name rows found. Nothing to clean up."
  exit 0
fi

echo
log_info "${#CANDIDATES[@]} candidate stray row(s) found: ${CANDIDATES[*]}"

if [[ "$DO_CLEAN" != "1" ]]; then
  echo
  log_info "Diagnose-only run (no --clean given). Re-run with --clean to attempt removal of the candidates above."
  exit 0
fi

# ---------------------------------------------------------------------------
# Cleanup attempts — EXPERIMENTAL. No known-working command exists yet; this is how
# we find out. Two mechanisms are tried per candidate, cheapest/safest first:
#   1. EQv2Delete with the row's own Name (only if non-empty) — speculative, since
#      EQv2Delete is documented to operate on the profile list, not a live per-source
#      buffer; worst case it's a no-op/Failed.
#   2. Overwrite the slot's bands with an all-OFF default template (mode=-1 on every
#      band, matching how unused bands are already represented elsewhere in this app)
#      at EQLevel:1 for that exact source_name + its currently-reported channelMode.
# After each attempt, EQGetSourceModes is re-read to see whether the row is gone,
# content-reset-but-still-listed, or unaffected.
# ---------------------------------------------------------------------------
for sn in "${CANDIDATES[@]}"; do
  echo
  echo "==================== Cleaning candidate: '$sn' ===================="
  if is_real_source "$sn"; then
    log_fail "SAFETY ABORT: '$sn' matches a real source name — refusing to touch it. (This should be unreachable; report as a bug in this script's classification.)"
    continue
  fi
  if ! confirm "Attempt to clear stray source_name='$sn' on $WIIM_IP (EQLevel:1 only)?"; then
    log_skip "Skipped '$sn' by operator."
    continue
  fi

  buf=$(call "EQGetLV2SourceBandEx:{\"source_name\":\"${sn}\",\"pluginURI\":\"${PLUGIN_URI}\"}")
  if ! is_recognized "$buf"; then
    log_warn "Could not read band data for '$sn' — skipping."
    continue
  fi
  orig_name=$(jq -r '.Name // empty' <<<"$buf")
  cmode=$(jq -r '.channelMode // empty' <<<"$buf")

  # Attempt 1: EQv2Delete with the row's own Name, if it has one.
  if [[ -n "$orig_name" ]]; then
    del_resp=$(call "EQv2Delete:{\"pluginURI\":\"${PLUGIN_URI}\",\"Name\":\"${orig_name}\",\"EQLevel\":1}")
    log_info "EQv2Delete attempt (Name='$orig_name') raw response: $del_resp"
  else
    log_info "Row has no Name — skipping the EQv2Delete attempt (nothing to delete by name)."
  fi

  after_delete=$(call "EQGetSourceModes")
  still_present=$(jq -r --arg sn "$sn" --arg uri "$PLUGIN_URI" '[.[] | select(.source_name==$sn and .pluginURI==$uri)] | length' <<<"$after_delete" 2>/dev/null || echo 1)
  if [[ "$still_present" == "0" ]]; then
    log_pass "REMOVED via EQv2Delete: '$sn' no longer appears in EQGetSourceModes."
    continue
  fi

  # Attempt 2: overwrite bands with an all-OFF template at this source_name/channelMode.
  local_bandkey=$([[ "$cmode" == "L/R" ]] && echo "L/R" || echo "Stereo")
  if [[ "$local_bandkey" == "L/R" ]]; then
    off_bandL=$(jq -c '.EQBandL | map(if .param_name | endswith("_mode") then .value=-1 else . end)' <<<"$buf")
    off_bandR=$(jq -c '.EQBandR | map(if .param_name | endswith("_mode") then .value=-1 else . end)' <<<"$buf")
    clear_resp=$(call "EQSetLV2SourceBand:{\"source_name\":\"${sn}\",\"pluginURI\":\"${PLUGIN_URI}\",\"channelMode\":\"L/R\",\"EQBandL\":${off_bandL},\"EQBandR\":${off_bandR}}")
  else
    off_band=$(jq -c '.EQBand | map(if .param_name | endswith("_mode") then .value=-1 else . end)' <<<"$buf")
    clear_resp=$(call "EQSetLV2SourceBand:{\"source_name\":\"${sn}\",\"pluginURI\":\"${PLUGIN_URI}\",\"channelMode\":\"Stereo\",\"EQBand\":${off_band}}")
  fi
  log_info "All-OFF band overwrite raw response: $clear_resp"
  call "EQSourceOff:{\"EQLevel\":1,\"source_name\":\"${sn}\",\"pluginURI\":\"${PLUGIN_URI}\"}" >/dev/null

  after_clear=$(call "EQGetSourceModes")
  row_after=$(jq -c --arg sn "$sn" --arg uri "$PLUGIN_URI" '[.[] | select(.source_name==$sn and .pluginURI==$uri)][0] // empty' <<<"$after_clear" 2>/dev/null)
  if [[ -z "$row_after" ]]; then
    log_pass "REMOVED via all-OFF band overwrite: '$sn' no longer appears in EQGetSourceModes."
  else
    row_name_after=$(jq -r '.Name // empty' <<<"$row_after")
    row_stat_after=$(jq -r '.EQStat // empty' <<<"$row_after")
    log_warn "NOT REMOVABLE: '$sn' still appears in EQGetSourceModes after both attempts (Name now '$row_name_after', EQStat now '$row_stat_after'). This device likely tracks the source_name key permanently once written — cosmetic-only, no known API removes it."
  fi
done

echo
echo "==================== DONE ===================="
log_info "If any candidate turned out REMOVABLE or NOT REMOVABLE, log the result in docs/corrections.md and update docs/wiim_api_notes.md's Source Discovery 'Key rules' section accordingly — this script's outcome is new hardware evidence, not yet documented."
