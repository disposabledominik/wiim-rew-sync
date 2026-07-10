#!/usr/bin/env bash
# validate_new_wiim_commands.sh — hardware validation for WiiM commands that surfaced during
# API research but weren't yet confirmed against real hardware:
#   RoomCorrGet, RoomCorrGetMode, RoomCorrSet, RoomCorrSetLR, RoomCorrSetMode, setRoomCorrection,
#   EQv2Rename, EQSetChannelMode, EQGetLV2Band/EQGetLV2SourceBand (non-Ex), EQv2Load.
#
# Manual tool, not part of the pytest suite. Findings should feed docs/corrections.md and
# docs/wiim_api_notes.md updates per this project's # ASSUMPTION: workflow.
#
# Requires: curl, jq. Run from WSL2 bash (or Git Bash) against a real device on the LAN.
#
# Usage: ./validate_new_wiim_commands.sh <device-ip> [--writes] [--yes] [--source=NAME]
#                                         [--rename-target=NAME] [--results-file=PATH]
#        ./validate_new_wiim_commands.sh --summarize [results-file]
#   (no flags)      Section 1 only — read-only existence/shape checks. Always safe.
#   --writes        Also run Section 2 — write tests. Each backs up state first and
#                   restores it afterward, verifying the restore succeeded. The two
#                   riskiest sub-tests (RoomFit push, EQv2Rename) additionally prompt for
#                   confirmation unless --yes is also given.
#   --source=X      PEQ source_name to use for per-source tests (default: auto-detected
#                   via getAudioInputEnable, falling back to "wifi").
#   --rename-target=NAME
#                   Test EQv2Rename against this existing RoomFit profile name instead of
#                   requiring an "Auto"/"Auto_LR" auto-calibration profile — use this to
#                   test rename generality without redoing an on-device room calibration.
#   --results-file=PATH
#                   CSV file the per-device "theory check" row is appended to (default
#                   ./roomcorr_theory_results.csv). Run this script with --writes against
#                   every device using the SAME file (the default already does, as long as
#                   you run from the same directory each time), then run:
#                     ./validate_new_wiim_commands.sh --summarize
#                   to get the aggregate verdict on the "RoomCorrGetMode's response shape
#                   predicts whether RoomCorrSet actually mutates the buffer" theory
#                   (docs/corrections.md, 2026-07-10). Section 1 alone is enough to log the
#                   GetMode side; --writes is required for the Set-mutation side.

set -uo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: this script requires 'jq'. Install: sudo apt-get install -y jq" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# --summarize mode: aggregate every logged device's theory-check row and print
# a verdict. Bypasses the entire device-connection flow below.
# ---------------------------------------------------------------------------
summarize_theory_results() {
  local file="$1"
  if [[ ! -f "$file" ]]; then
    echo "No results file at '$file' yet — run this script with --writes against each" >&2
    echo "device first (each run appends one row to this file)." >&2
    exit 1
  fi
  echo "==================== THEORY SUMMARY: RoomCorrGetMode <-> RoomCorrSet ===================="
  printf '%-16s %-18s %-14s %-14s %-12s %s\n' "Device" "Model" "GetModeClass" "SetResult" "RC.Version" "Consistent?"
  local total=0 informative=0 consistent=0
  local rc_total=0 rc_consistent=0
  while IFS=',' read -r ip model getmode setres rcver; do
    [[ -z "$ip" || "$ip" == "device_ip" ]] && continue
    total=$((total + 1))
    rcver="${rcver:-n/a}"
    local mark="n/a ($setres)"
    if [[ "$setres" == "MUTATED" || "$setres" == "NOT_MUTATED" ]]; then
      informative=$((informative + 1))
      if { [[ "$getmode" == "REAL" && "$setres" == "MUTATED" ]] || [[ "$getmode" == "ALIASED" && "$setres" == "NOT_MUTATED" ]]; }; then
        mark="YES"
        consistent=$((consistent + 1))
      else
        mark="NO (breaks theory)"
      fi
      # Secondary theory: RC.Version:"1.1" predicts REAL/MUTATED; anything else (1.0,
      # ABSENT, FAILED, or any other value) predicts ALIASED/NOT_MUTATED. Only two
      # RC.Version values have been observed so far (docs/corrections.md, 2026-07-10) —
      # this checks whether that pattern keeps holding as more devices are added.
      if [[ "$rcver" != "n/a" && "$rcver" != "NOT_RUN" ]]; then
        rc_total=$((rc_total + 1))
        if { [[ "$rcver" == "1.1" && "$setres" == "MUTATED" ]] || { [[ "$rcver" != "1.1" ]] && [[ "$setres" == "NOT_MUTATED" ]]; }; }; then
          rc_consistent=$((rc_consistent + 1))
        fi
      fi
    fi
    printf '%-16s %-18s %-14s %-14s %-12s %s\n' "$ip" "$model" "$getmode" "$setres" "$rcver" "$mark"
  done <"$file"

  echo
  if [[ "$informative" -lt 2 ]]; then
    echo "VERDICT: INCONCLUSIVE — need at least 2 devices with an actual MUTATED/NOT_MUTATED"
    echo "Set-result (got $informative of $total logged). Re-run with --writes against more devices."
  elif [[ "$consistent" -eq "$informative" ]]; then
    echo "VERDICT: THEORY CONFIRMED across all $informative testable device(s) — RoomCorrGetMode's"
    echo "response shape (REAL vs ALIASED) perfectly predicted whether RoomCorrSet actually"
    echo "mutated the buffer."
  else
    echo "VERDICT: THEORY REFUTED — $((informative - consistent))/$informative testable device(s)"
    echo "broke the predicted correlation. See table above for which one(s)."
  fi

  if [[ "$rc_total" -ge 2 ]]; then
    echo
    if [[ "$rc_consistent" -eq "$rc_total" ]]; then
      echo "RC.VERSION SIGNAL: consistent across all $rc_total device(s) with a known RC.Version —"
      echo "\"RC.Version:1.1\" predicted MUTATED and anything else predicted NOT_MUTATED every time."
      echo "Still only a working assumption if all observed values are just \"1.0\"/\"1.1\" — a device"
      echo "reporting a different RC.Version would be a real test of the >=1.1 framing."
    else
      echo "RC.VERSION SIGNAL: broke on $((rc_total - rc_consistent))/$rc_total device(s) — RC.Version"
      echo "alone does NOT reliably predict RoomCorrSet's behavior. See table above."
    fi
  fi
}

if [[ "${1:-}" == "--summarize" ]]; then
  summarize_theory_results "${2:-./roomcorr_theory_results.csv}"
  exit 0
fi

WIIM_IP="${1:-}"
if [[ -z "$WIIM_IP" || "$WIIM_IP" == --* ]]; then
  echo "Usage: $0 <device-ip> [--writes] [--yes] [--source=NAME]" >&2
  exit 1
fi
shift

RUN_WRITES=0
AUTO_YES=0
TEST_SOURCE=""
RENAME_TARGET=""
RESULTS_FILE="./roomcorr_theory_results.csv"
for arg in "$@"; do
  case "$arg" in
    --writes) RUN_WRITES=1 ;;
    --yes) AUTO_YES=1 ;;
    --source=*) TEST_SOURCE="${arg#--source=}" ;;
    --rename-target=*) RENAME_TARGET="${arg#--rename-target=}" ;;
    --results-file=*) RESULTS_FILE="${arg#--results-file=}" ;;
    *) echo "Unknown flag: $arg" >&2; exit 1 ;;
  esac
done

BASE="https://${WIIM_IP}/httpapi.asp"
PLUGIN_URI="http://moddevices.com/plugins/caps/EqNp"

# Theory-check state, populated by section1 (GETMODE_CLASS, RC_VERSION) and
# section2_roomfit (SET_MUTATION_RESULT), printed and logged to $RESULTS_FILE at the
# end of the run.
GETMODE_CLASS="NOT_RUN"
SET_MUTATION_RESULT="NOT_RUN"
RC_VERSION="NOT_RUN"

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
# Connectivity + context
# ---------------------------------------------------------------------------
log_info "Checking connectivity to $WIIM_IP ..."
status=$(call "getStatusEx")
if ! is_recognized "$status"; then
  log_fail "getStatusEx did not return a valid response — check IP/network. Raw: $status"
  exit 1
fi
MODEL=$(jq -r '.project // "unknown"' <<<"$status")
EQVERSION=$(jq -r '.EQVersion // empty' <<<"$status")
log_info "Connected. project=$MODEL EQVersion=${EQVERSION:-unknown}"

if [[ -z "$TEST_SOURCE" ]]; then
  ae=$(call "getAudioInputEnable")
  if is_recognized "$ae"; then
    TEST_SOURCE=$(jq -r '[.audioInput[]? | select(.enable==1) | .mode][0] // empty' <<<"$ae")
  fi
  TEST_SOURCE="${TEST_SOURCE:-wifi}"
fi
log_info "Using source_name='$TEST_SOURCE' for per-source tests (override with --source=NAME)"

# ---------------------------------------------------------------------------
# Section 1 — read-only existence/shape checks. Always runs, always safe.
# ---------------------------------------------------------------------------
section1() {
  echo
  echo "==================== SECTION 1: read-only existence/shape checks ===================="

  local r
  r=$(call "RoomCorrGet")
  if is_recognized "$r"; then
    log_warn "RoomCorrGet: device RECOGNIZES this command (unexpected — prior research found no trace of it). Raw: $r"
  else
    log_pass "RoomCorrGet: confirmed NOT a real command. Raw: $r"
  fi

  r=$(call "EQGetSourceModes")
  if is_recognized "$r"; then
    log_warn "EQGetSourceModes: device RECOGNIZES this command (unexpected). Raw: $r"
  else
    log_pass "EQGetSourceModes: confirmed NOT a real command. Raw: $r"
  fi

  # Classify RoomCorrGetMode's response shape — this is the read-only half of the
  # "GetMode shape predicts RoomCorrSet mutation" theory (docs/corrections.md, 2026-07-10).
  # Confirmed split so far: WiiM Sound/Sound Lite return a real {"Mode":"Playback"} body;
  # WiiM Amp Ultra/Mini instead return the same profile-dump shape as RoomCorrGet (no "Mode"
  # key at all) — i.e. it isn't implemented as its own command on those two.
  r=$(call "RoomCorrGetMode")
  if ! is_recognized "$r"; then
    GETMODE_CLASS="NOT_RECOGNIZED"
    log_warn "RoomCorrGetMode: NOT recognized on this device/firmware. Raw: $r"
  elif jq -e 'has("Mode")' <<<"$r" >/dev/null 2>&1; then
    GETMODE_CLASS="REAL"
    log_pass "RoomCorrGetMode: returns a real {\"Mode\":...} response (distinct handler). Raw: $r"
  elif jq -e '(has("EQBand") or has("EQBandL"))' <<<"$r" >/dev/null 2>&1; then
    GETMODE_CLASS="ALIASED"
    log_warn "RoomCorrGetMode: falls through to the same profile-dump shape as RoomCorrGet — not a distinct command on this device. Raw: $r"
  else
    GETMODE_CLASS="OTHER"
    log_warn "RoomCorrGetMode: recognized but matches neither the Mode-shape nor the RoomCorrGet-shape. Raw: $r"
  fi

  # GetAcousticCapability: general subsystem-version report, not itself part of the
  # RoomCorr* family. Its RC.Version field is confirmed to track RoomCorrGetMode's shape
  # and RoomCorrSet's mutation result (docs/corrections.md, 2026-07-10): "1.1" (WiiM Sound,
  # WiiM Sound Lite) is where the family is genuinely implemented; "1.0" (WiiM Amp Ultra) is
  # where it's aliased/inert. WiiM Mini has no RC capability at all (command fails outright).
  r=$(call "GetAcousticCapability")
  if is_recognized "$r" && [[ "$(jq -r '.status // empty' <<<"$r")" != "Failed" ]]; then
    RC_VERSION=$(jq -r '.RC.Version // "MISSING"' <<<"$r")
    log_info "GetAcousticCapability: RC.Version=$RC_VERSION. Raw: $r"
  else
    RC_VERSION="ABSENT"
    log_warn "GetAcousticCapability: not supported on this device (status Failed or unrecognized) — likely no RC subsystem at all. Raw: $r"
  fi

  local ex nonex
  ex=$(call "EQGetLV2BandEx:${PLUGIN_URI}")
  nonex=$(call "EQGetLV2Band:${PLUGIN_URI}")
  echo "--- EQGetLV2BandEx (bare) ---"; jq . <<<"$ex" 2>/dev/null || echo "$ex"
  echo "--- EQGetLV2Band (bare, no Ex) ---"; jq . <<<"$nonex" 2>/dev/null || echo "$nonex"
  if is_recognized "$nonex"; then
    log_info "EQGetLV2Band (non-Ex) is still recognized — compare the two bodies above for a channelMode field difference."
  else
    log_info "EQGetLV2Band (non-Ex) NOT recognized on this firmware — Ex form is the only live one here."
  fi

  local exs nonexs
  exs=$(call "EQGetLV2SourceBandEx:{\"source_name\":\"${TEST_SOURCE}\",\"pluginURI\":\"${PLUGIN_URI}\"}")
  nonexs=$(call "EQGetLV2SourceBand:{\"source_name\":\"${TEST_SOURCE}\",\"pluginURI\":\"${PLUGIN_URI}\"}")
  echo "--- EQGetLV2SourceBandEx (source=$TEST_SOURCE) ---"; jq . <<<"$exs" 2>/dev/null || echo "$exs"
  echo "--- EQGetLV2SourceBand (non-Ex, source=$TEST_SOURCE) ---"; jq . <<<"$nonexs" 2>/dev/null || echo "$nonexs"
  if is_recognized "$nonexs"; then
    log_info "EQGetLV2SourceBand (non-Ex) is still recognized — check whether channelMode is present/absent vs the Ex response."
  else
    log_info "EQGetLV2SourceBand (non-Ex) NOT recognized on this firmware."
  fi
}

# ---------------------------------------------------------------------------
# Section 2.1 — RoomCorrSet / RoomCorrSetLR / RoomCorrSetMode / setRoomCorrection
# ---------------------------------------------------------------------------
section2_roomfit() {
  echo
  echo "==================== SECTION 2.1: RoomFit push commands ===================="
  log_warn "RISK: writes to the device's live RoomFit buffer. If the selected profile has Type=\"RC\" (device calibration), this may overwrite its Type/UpdateAt metadata with no API-level way to restore \"RC\" status — only re-running full calibration can. Bands/Name/EQStat ARE backed up and restored by this script; the Type flag is not."
  if ! confirm "Proceed with RoomFit push-command test on $WIIM_IP?"; then
    log_skip "RoomFit push test skipped by operator."
    SET_MUTATION_RESULT="SKIPPED_BY_OPERATOR"
    return
  fi

  # Hardware evidence (two devices, one run each): on a device with an empty RoomFit
  # profile list, EQLevel:2 calls do NOT behave as an isolated namespace — bare RoomCorrGet
  # returned EQLevel:1 "wifi" data instead of an EQLevel:2 buffer, and this section's own
  # EQLevel:2 EQChangeSourceFX/EQSourceOff/RoomCorrSetMode calls left the real "wifi"
  # EQLevel:1 source's channelMode/Name altered afterward (L/R "Closed LR" -> Stereo
  # "Auto") even though orig_name was captured as empty and nothing here explicitly wrote
  # to "wifi". This directly contradicts this project's documented invariant that EQLevel:1
  # and EQLevel:2 are fully independent storage namespaces — that invariant appears to only
  # hold on devices with real RoomFit hardware/profiles. Refuse to run any further EQLevel:2
  # writes here without that hardware, rather than risk silently corrupting the live
  # source's real PEQ state again.
  local rf_list rf_custom_count
  rf_list=$(call "EQv2GetNewList:{\"pluginURI\":\"${PLUGIN_URI}\",\"EQLevel\":2}")
  rf_custom_count=$(jq -r '(.custom // []) | length' <<<"$rf_list" 2>/dev/null || echo 0)
  if [[ "$rf_custom_count" == "0" ]]; then
    log_skip "No RoomFit profiles exist on this device (empty custom list) — treating as no real RoomFit hardware. Skipping the reverse-engineered RoomCorr*/RoomCorrSetMode/setRoomCorrection write tests (previously observed to alter the real EQLevel:1 '${TEST_SOURCE}' source's channelMode/Name here)."
    SET_MUTATION_RESULT="SKIPPED_NO_ROOMFIT"
    section2_isolation_check
    return
  fi

  local buf orig_name orig_stat orig_mode
  buf=$(call "EQGetLV2SourceBandEx:{\"EQLevel\":2,\"source_name\":\"\",\"pluginURI\":\"${PLUGIN_URI}\"}")
  if ! is_recognized "$buf"; then
    log_skip "Device does not respond to RoomFit band read (EQLevel:2) — likely no RoomFit hardware. Skipping."
    SET_MUTATION_RESULT="SKIPPED_NO_ROOMFIT"
    return
  fi
  orig_name=$(jq -r '.Name // empty' <<<"$buf")
  orig_stat=$(jq -r '.EQStat // empty' <<<"$buf")
  orig_mode=$(jq -r '.channelMode // empty' <<<"$buf")
  log_info "Backed up RoomFit buffer: Name='$orig_name' EQStat='$orig_stat' channelMode='$orig_mode'"

  # Mutate one band's gain by a small, detectable, easily-reversible amount instead of
  # echoing back identical data — otherwise {"status":"OK"} can't be distinguished from a
  # silent no-op (this project's own error-handling doctrine: OK confirms accepted, never
  # that it did what was intended).
  local cur_gain delta new_gain ts resp payload
  if [[ "$orig_mode" == "L/R" ]]; then
    cur_gain=$(jq -r '.EQBandL[] | select(.param_name=="a_gain") | .value' <<<"$buf")
  else
    cur_gain=$(jq -r '.EQBand[] | select(.param_name=="a_gain") | .value' <<<"$buf")
  fi
  delta=$(awk -v g="$cur_gain" 'BEGIN{print (g<=6)?0.5:-0.5}')
  new_gain=$(awk -v g="$cur_gain" -v d="$delta" 'BEGIN{printf "%.3f", g+d}')
  log_info "Mutating a_gain: $cur_gain -> $new_gain (will be verified, then restored from the saved profile via EQv2SourceLoad)"

  # Hardware evidence (3 devices): the mutation succeeded on WiiM Sound (EQStat was Off at
  # the time, and the buffer's Name unconditionally flipped to "Auto" on success — matching
  # the calibration-result-push theory) but failed on Amp Ultra twice (EQStat was On both
  # times). Confound: device model changed too. Isolate the EQStat variable directly: force
  # it Off first (restored at the end regardless, same as the setRoomCorrection differential
  # test below), so a failure here can't be blamed on EQStat being On.
  if [[ "$orig_stat" != "Off" ]]; then
    log_info "Forcing EQStat Off before the mutation attempt, to isolate whether RoomCorrSet only writes while RoomFit is inactive (will be restored to '$orig_stat' at the end)."
    call "EQSourceOff:{\"EQLevel\":2,\"source_name\":\"\",\"pluginURI\":\"${PLUGIN_URI}\"}" >/dev/null
  fi

  # Hardware evidence (two devices): sending EQBand(L/R) without a "Name" key returns
  # {"status":"OK"} but the buffer read back afterward is byte-identical to before — the
  # write did not take effect despite being "accepted". Retry with "Name" included (the
  # currently-selected profile's own name) in case the command requires it to know which
  # stored profile's buffer to target, the same way EQSourceSave does.
  local after after_name after_gain_key after_gain mutation_confirmed
  mutation_confirmed=0
  for variant in without_name with_name; do
    if [[ "$variant" == "with_name" && -z "$orig_name" ]]; then
      continue  # nothing to name it with
    fi
    ts=$(date +%s%3N)
    if [[ "$orig_mode" == "L/R" ]]; then
      local bandL bandR
      bandL=$(jq -c --argjson nv "$new_gain" 'map(if .param_name=="a_gain" then .value=$nv else . end)' <<<"$(jq -c '.EQBandL' <<<"$buf")")
      bandR=$(jq -c '.EQBandR' <<<"$buf")
      if [[ "$variant" == "with_name" ]]; then
        payload=$(jq -nc --arg uri "$PLUGIN_URI" --arg name "$orig_name" --argjson bl "$bandL" --argjson br "$bandR" --argjson ts "$ts" \
          '{"EQLevel":2,"pluginURI":$uri,"Name":$name,"EQBandL":$bl,"EQBandR":$br,"UpdateAt":$ts,"rc_output":"AUDIO_OUTPUT_SPEAKER_MODE"}')
      else
        payload=$(jq -nc --arg uri "$PLUGIN_URI" --argjson bl "$bandL" --argjson br "$bandR" --argjson ts "$ts" \
          '{"EQLevel":2,"pluginURI":$uri,"EQBandL":$bl,"EQBandR":$br,"UpdateAt":$ts,"rc_output":"AUDIO_OUTPUT_SPEAKER_MODE"}')
      fi
      resp=$(call "RoomCorrSetLR:${payload}")
      log_info "RoomCorrSetLR ($variant) raw response: $resp"
    else
      local band
      band=$(jq -c --argjson nv "$new_gain" 'map(if .param_name=="a_gain" then .value=$nv else . end)' <<<"$(jq -c '.EQBand' <<<"$buf")")
      if [[ "$variant" == "with_name" ]]; then
        payload=$(jq -nc --arg uri "$PLUGIN_URI" --arg name "$orig_name" --argjson b "$band" --argjson ts "$ts" \
          '{"EQLevel":2,"pluginURI":$uri,"Name":$name,"EQBand":$b,"UpdateAt":$ts,"rc_output":"AUDIO_OUTPUT_SPEAKER_MODE"}')
      else
        payload=$(jq -nc --arg uri "$PLUGIN_URI" --argjson b "$band" --argjson ts "$ts" \
          '{"EQLevel":2,"pluginURI":$uri,"EQBand":$b,"UpdateAt":$ts,"rc_output":"AUDIO_OUTPUT_SPEAKER_MODE"}')
      fi
      resp=$(call "RoomCorrSet:${payload}")
      log_info "RoomCorrSet ($variant) raw response: $resp"
    fi

    if is_recognized "$resp"; then
      log_pass "Command ($variant) was RECOGNIZED by the device. Raw: $resp"
    else
      log_warn "Command ($variant) NOT recognized — prior findings may not apply to this firmware/model. Raw: $resp"
    fi

    after=$(call "EQGetLV2SourceBandEx:{\"EQLevel\":2,\"source_name\":\"\",\"pluginURI\":\"${PLUGIN_URI}\"}")
    after_name=$(jq -r '.Name // empty' <<<"$after")
    after_gain_key=$([[ "$orig_mode" == "L/R" ]] && echo "EQBandL" || echo "EQBand")
    after_gain=$(jq -r --arg k "$after_gain_key" '.[$k][] | select(.param_name=="a_gain") | .value' <<<"$after")
    log_info "Buffer Name after push ($variant): '$after_name' (was '$orig_name')."
    if [[ "$after_gain" == "$new_gain" ]]; then
      log_pass "MUTATION CONFIRMED ($variant): a_gain actually changed to $after_gain on the device — this is a real write, not a silent no-op."
      mutation_confirmed=1
      break
    else
      log_warn "a_gain after push ($variant) is '$after_gain', expected '$new_gain' — command was accepted but the buffer doesn't show the change."
    fi
  done
  if [[ "$mutation_confirmed" == "0" ]]; then
    log_warn "Neither payload variant produced a detectable change — RoomCorrSet/RoomCorrSetLR remain UNCONFIRMED as real writes on this device/firmware despite returning {\"status\":\"OK\"}."
    SET_MUTATION_RESULT="NOT_MUTATED"
  else
    SET_MUTATION_RESULT="MUTATED"
  fi

  if [[ -n "$orig_name" ]]; then
    call "EQv2SourceLoad:{\"EQLevel\":2,\"pluginURI\":\"${PLUGIN_URI}\",\"Name\":\"${orig_name}\"}" >/dev/null
  fi
  if [[ "$orig_stat" == "Off" ]]; then
    call "EQSourceOff:{\"EQLevel\":2,\"source_name\":\"\",\"pluginURI\":\"${PLUGIN_URI}\"}" >/dev/null
  elif [[ "$orig_stat" == "On" ]]; then
    call "EQChangeSourceFX:{\"EQLevel\":2,\"source_name\":\"\",\"pluginURI\":\"${PLUGIN_URI}\"}" >/dev/null
  fi

  local final final_name final_stat final_gain_key final_gain
  final=$(call "EQGetLV2SourceBandEx:{\"EQLevel\":2,\"source_name\":\"\",\"pluginURI\":\"${PLUGIN_URI}\"}")
  final_name=$(jq -r '.Name // empty' <<<"$final")
  final_stat=$(jq -r '.EQStat // empty' <<<"$final")
  final_gain_key=$([[ "$(jq -r '.channelMode // empty' <<<"$final")" == "L/R" ]] && echo "EQBandL" || echo "EQBand")
  final_gain=$(jq -r --arg k "$final_gain_key" '.[$k][]? | select(.param_name=="a_gain") | .value' <<<"$final")
  if [[ "$final_name" == "$orig_name" && "$final_stat" == "$orig_stat" && "$final_gain" == "$cur_gain" ]]; then
    log_pass "Restore verified: Name, EQStat, and a_gain match pre-test state ('$orig_name'/'$orig_stat'/'$cur_gain')."
  else
    log_fail "RESTORE MISMATCH — expected Name='$orig_name' EQStat='$orig_stat' a_gain='$cur_gain', got Name='$final_name' EQStat='$final_stat' a_gain='$final_gain'. CHECK THE DEVICE/APP MANUALLY NOW."
  fi

  # --- setRoomCorrection: does it actually toggle EQStat, or is it unrelated metadata? ---
  # Testable only from a known Off state — EQStat was already On above, so force it Off
  # first via the already-confirmed-safe toggle, then see whether setRoomCorrection alone
  # flips it back On.
  echo
  log_info "Differential test: does setRoomCorrection actually control EQStat?"
  call "EQSourceOff:{\"EQLevel\":2,\"source_name\":\"\",\"pluginURI\":\"${PLUGIN_URI}\"}" >/dev/null
  local pre_toggle_stat
  pre_toggle_stat=$(jq -r '.EQStat // empty' <<<"$(call "EQGetLV2SourceBandEx:{\"EQLevel\":2,\"source_name\":\"\",\"pluginURI\":\"${PLUGIN_URI}\"}")")
  if [[ "$pre_toggle_stat" != "Off" ]]; then
    log_warn "Could not force EQStat to Off (got '$pre_toggle_stat') — skipping setRoomCorrection differential test."
  elif [[ -n "$EQVERSION" ]]; then
    resp=$(call "setRoomCorrection:${EQVERSION}")
    log_info "setRoomCorrection:${EQVERSION} raw response: $resp"
    local post_toggle_stat
    post_toggle_stat=$(jq -r '.EQStat // empty' <<<"$(call "EQGetLV2SourceBandEx:{\"EQLevel\":2,\"source_name\":\"\",\"pluginURI\":\"${PLUGIN_URI}\"}")")
    if [[ "$post_toggle_stat" == "On" ]]; then
      log_pass "setRoomCorrection DOES control EQStat: flipped Off -> On on its own."
    else
      log_warn "setRoomCorrection did NOT change EQStat (still '$post_toggle_stat') — likely unrelated metadata (e.g. just records an RC_Version string), not an enable toggle."
    fi

    # Validation check: does it accept an obviously-invalid version string too?
    local garbage_resp
    garbage_resp=$(call "setRoomCorrection:not_a_real_version_99")
    log_info "setRoomCorrection:not_a_real_version_99 (garbage input) raw response: $garbage_resp"
    if [[ "$garbage_resp" == "$resp" ]]; then
      log_warn "Garbage RC_Version produced the same response as the real one — this command does not appear to validate its argument, so acceptance alone doesn't confirm '$EQVERSION' is a meaningful value."
    else
      log_info "Garbage RC_Version produced a different response — some validation may be happening."
    fi
  fi

  # RoomCorrSetMode's valid values are confirmed via hardware testing to be the exhaustive,
  # exact-case pair "Measure"/"Playback" (NOT "MEASURE"/"PLAYBACK" — the earlier all-caps
  # guess is why it returned {"status":"Failed"}).
  # "Playback" is the normal/idle state so it's safe to round-trip; "Measure" is the
  # in-progress-calibration state and may affect live DSP/audio behavior, so it gets its
  # own confirmation on top of this section's overall one.
  log_info "RoomCorrSetMode: testing confirmed values Measure/Playback (not the earlier incorrect all-caps guess)."
  resp=$(call "RoomCorrSetMode:Playback")
  log_info "RoomCorrSetMode:Playback raw response: $resp"
  if is_recognized "$resp" && [[ "$(jq -r '.status // empty' <<<"$resp" 2>/dev/null)" == "OK" ]]; then
    log_pass "RoomCorrSetMode:Playback accepted with status OK."
  else
    log_warn "RoomCorrSetMode:Playback did not return status OK. Raw: $resp"
  fi

  if confirm "Also test RoomCorrSetMode:Measure? This is the in-progress-calibration state and may affect live DSP/audio behavior; script will set it back to Playback immediately after."; then
    resp=$(call "RoomCorrSetMode:Measure")
    log_info "RoomCorrSetMode:Measure raw response: $resp"
    call "RoomCorrSetMode:Playback" >/dev/null
    log_info "Reverted to RoomCorrSetMode:Playback."
  else
    log_skip "RoomCorrSetMode:Measure test skipped by operator."
  fi

  # Restore EQStat to its true original value after all the above probing.
  local final2_stat
  final2_stat=$(jq -r '.EQStat // empty' <<<"$(call "EQGetLV2SourceBandEx:{\"EQLevel\":2,\"source_name\":\"\",\"pluginURI\":\"${PLUGIN_URI}\"}")")
  if [[ "$final2_stat" != "$orig_stat" ]]; then
    log_warn "EQStat changed after exploratory calls (was '$orig_stat', now '$final2_stat') — restoring."
    if [[ "$orig_stat" == "Off" ]]; then
      call "EQSourceOff:{\"EQLevel\":2,\"source_name\":\"\",\"pluginURI\":\"${PLUGIN_URI}\"}" >/dev/null
    else
      call "EQChangeSourceFX:{\"EQLevel\":2,\"source_name\":\"\",\"pluginURI\":\"${PLUGIN_URI}\"}" >/dev/null
    fi
  fi
}

# ---------------------------------------------------------------------------
# Section 2.1b — EQLevel isolation check (production-command safety)
#
# Runs only when section2_roomfit found no RoomFit profiles (i.e. skipped its own
# tests). A prior run on a RoomFit-less device left the real EQLevel:1 "wifi"
# source's channelMode/Name altered after a sequence that included several
# reverse-engineered-only commands (RoomCorrSetMode, setRoomCorrection) alongside
# EQChangeSourceFX/EQSourceOff at EQLevel:2 — the latter two are NOT reverse-engineered,
# they're this project's own shipped commands, used by capability_prober.py during
# normal RoomFit capability probing. This test isolates each one alone to find out
# whether a real, already-shipped code path can corrupt EQLevel:1 state on this class
# of device, as opposed to it only being an artifact of this script's own exploratory
# commands.
# ---------------------------------------------------------------------------
section2_isolation_check() {
  echo
  echo "==================== SECTION 2.1b: EQLevel isolation check (production-command safety) ===================="
  log_warn "This device has no RoomFit profiles. Testing whether this app's OWN production commands (EQChangeSourceFX/EQSourceOff at EQLevel:2 — used by capability_prober.py) bleed into the real EQLevel:1 '${TEST_SOURCE}' source here. Each command is tested alone and restored immediately."
  if ! confirm "Proceed with the EQLevel isolation check on '${TEST_SOURCE}'?"; then
    log_skip "Isolation check skipped by operator."
    return
  fi

  local before b_name b_mode b_stat
  before=$(call "EQGetLV2SourceBandEx:{\"source_name\":\"${TEST_SOURCE}\",\"pluginURI\":\"${PLUGIN_URI}\"}")
  if ! is_recognized "$before"; then
    log_skip "Could not read '${TEST_SOURCE}' state — skipping isolation check."
    return
  fi
  b_name=$(jq -r '.Name // empty' <<<"$before")
  b_mode=$(jq -r '.channelMode // empty' <<<"$before")
  b_stat=$(jq -r '.EQStat // empty' <<<"$before")
  log_info "Baseline '${TEST_SOURCE}': Name='$b_name' channelMode='$b_mode' EQStat='$b_stat'"

  local cmd
  for cmd in EQChangeSourceFX EQSourceOff; do
    call "${cmd}:{\"EQLevel\":2,\"source_name\":\"\",\"pluginURI\":\"${PLUGIN_URI}\"}" >/dev/null
    local after a_name a_mode a_stat
    after=$(call "EQGetLV2SourceBandEx:{\"source_name\":\"${TEST_SOURCE}\",\"pluginURI\":\"${PLUGIN_URI}\"}")
    a_name=$(jq -r '.Name // empty' <<<"$after")
    a_mode=$(jq -r '.channelMode // empty' <<<"$after")
    a_stat=$(jq -r '.EQStat // empty' <<<"$after")
    if [[ "$a_name" != "$b_name" || "$a_mode" != "$b_mode" ]]; then
      log_fail "PRODUCTION-COMMAND BLEED CONFIRMED: bare '${cmd}:{\"EQLevel\":2,...}' ALONE changed '${TEST_SOURCE}' from Name='$b_name'/channelMode='$b_mode' to Name='$a_name'/channelMode='$a_mode'. This exact command is used by capability_prober.py in normal operation on real devices — flag for investigation there, not just this script."
      if [[ -n "$b_name" ]]; then
        call "EQv2SourceLoad:{\"source_name\":\"${TEST_SOURCE}\",\"pluginURI\":\"${PLUGIN_URI}\",\"Name\":\"${b_name}\"}" >/dev/null
      fi
    else
      log_pass "'${cmd}' alone did NOT change '${TEST_SOURCE}' Name/channelMode."
    fi
    if [[ "$a_stat" != "$b_stat" ]]; then
      if [[ "$b_stat" == "Off" ]]; then
        call "EQSourceOff:{\"source_name\":\"${TEST_SOURCE}\",\"pluginURI\":\"${PLUGIN_URI}\"}" >/dev/null
      else
        call "EQChangeSourceFX:{\"source_name\":\"${TEST_SOURCE}\",\"pluginURI\":\"${PLUGIN_URI}\"}" >/dev/null
      fi
    fi
  done

  local final final_name final_mode final_stat
  final=$(call "EQGetLV2SourceBandEx:{\"source_name\":\"${TEST_SOURCE}\",\"pluginURI\":\"${PLUGIN_URI}\"}")
  final_name=$(jq -r '.Name // empty' <<<"$final")
  final_mode=$(jq -r '.channelMode // empty' <<<"$final")
  final_stat=$(jq -r '.EQStat // empty' <<<"$final")
  if [[ "$final_name" == "$b_name" && "$final_mode" == "$b_mode" && "$final_stat" == "$b_stat" ]]; then
    log_pass "Final restore verified: '${TEST_SOURCE}' matches baseline (Name='$b_name' channelMode='$b_mode' EQStat='$b_stat')."
  else
    log_fail "RESTORE MISMATCH after isolation check — expected Name='$b_name' channelMode='$b_mode' EQStat='$b_stat', got Name='$final_name' channelMode='$final_mode' EQStat='$final_stat'. CHECK THE DEVICE/APP MANUALLY NOW."
  fi
}

# ---------------------------------------------------------------------------
# Section 2.2 — EQv2Rename
# ---------------------------------------------------------------------------
section2_rename() {
  echo
  echo "==================== SECTION 2.2: EQv2Rename ===================="
  # --rename-target may name either a RoomFit (EQLevel:2) profile or a plain PEQ
  # (EQLevel:1) preset — this command was first confirmed only against RoomFit's
  # Auto/Auto_LR profile, so which EQLevel(s) it actually works on is itself an open
  # question. Search both lists rather than assuming.
  local rf_list peq_list orig_name found_level
  rf_list=$(call "EQv2GetNewList:{\"pluginURI\":\"${PLUGIN_URI}\",\"EQLevel\":2}")
  found_level=""
  orig_name=""

  if [[ -n "$RENAME_TARGET" ]]; then
    if is_recognized "$rf_list"; then
      orig_name=$(jq -r --arg n "$RENAME_TARGET" '[.custom[]? | select(.Name==$n) | .Name][0] // empty' <<<"$rf_list")
      [[ -n "$orig_name" ]] && found_level=2
    fi
    if [[ -z "$orig_name" ]]; then
      peq_list=$(call "EQv2GetNewList:{\"pluginURI\":\"${PLUGIN_URI}\",\"EQLevel\":1}")
      if is_recognized "$peq_list"; then
        orig_name=$(jq -r --arg n "$RENAME_TARGET" '[(.custom[]?), (.preset[]?)] | [.[] | select(.Name==$n) | .Name][0] // empty' <<<"$peq_list")
        [[ -n "$orig_name" ]] && found_level=1
      fi
    fi
    if [[ -z "$orig_name" ]]; then
      log_skip "--rename-target='$RENAME_TARGET' not found in either RoomFit (EQLevel:2) or PEQ (EQLevel:1) profile lists."
      return
    fi
    log_info "Using explicit --rename-target='$orig_name' at EQLevel:$found_level (not the Auto/Auto_LR-only case — this tests whether EQv2Rename is general-purpose)."
  else
    if is_recognized "$rf_list"; then
      orig_name=$(jq -r '[.custom[]? | select(.Name=="Auto" or .Name=="Auto_LR") | .Name][0] // empty' <<<"$rf_list")
      [[ -n "$orig_name" ]] && found_level=2
    fi
    if [[ -z "$orig_name" ]]; then
      log_skip "No 'Auto'/'Auto_LR' RoomFit profile found — EQv2Rename was only confirmed against that specific auto-calibration profile so far. Run an on-device RoomFit calibration first, or pass --rename-target=NAME to test against an existing PEQ/RoomFit preset instead."
      return
    fi
  fi

  log_warn "RISK: renaming existing profile '$orig_name' (EQLevel:$found_level) to a temp name and back. If rename-back fails, the profile is left under the temp name and must be renamed back manually in the app. If this is your currently-active profile, its live Name association may also need reattaching afterward (same caveat as a raw band write)."
  if ! confirm "Proceed with EQv2Rename round-trip test on profile '$orig_name' (EQLevel:$found_level)?"; then
    log_skip "EQv2Rename test skipped by operator."
    return
  fi

  local list_cmd
  list_cmd="EQv2GetNewList:{\"pluginURI\":\"${PLUGIN_URI}\",\"EQLevel\":${found_level}}"

  local tmp_name ts resp1 resp2
  tmp_name="TmpRenameTest_$(date +%s)"
  ts=$(date +%s%3N)
  resp1=$(call "EQv2Rename:{\"EQLevel\":${found_level},\"pluginURI\":\"${PLUGIN_URI}\",\"Name\":\"${orig_name}\",\"newName\":\"${tmp_name}\",\"UpdateAt\":${ts}}")
  log_info "Rename forward raw response: $resp1"

  local list2 now_has_tmp now_has_orig
  list2=$(call "$list_cmd")
  now_has_tmp=$(jq -r --arg n "$tmp_name" '[(.custom[]?), (.preset[]?)] | map(select(.Name==$n)) | length' <<<"$list2")
  now_has_orig=$(jq -r --arg n "$orig_name" '[(.custom[]?), (.preset[]?)] | map(select(.Name==$n)) | length' <<<"$list2")
  if [[ "$now_has_tmp" -gt 0 && "$now_has_orig" -eq 0 ]]; then
    log_pass "EQv2Rename WORKS (EQLevel:$found_level): profile renamed from '$orig_name' to '$tmp_name'."
  else
    log_warn "EQv2Rename did not produce the expected rename (tmp present=$now_has_tmp, orig still present=$now_has_orig). Raw list: $list2"
  fi

  local ts2
  ts2=$(date +%s%3N)
  resp2=$(call "EQv2Rename:{\"EQLevel\":${found_level},\"pluginURI\":\"${PLUGIN_URI}\",\"Name\":\"${tmp_name}\",\"newName\":\"${orig_name}\",\"UpdateAt\":${ts2}}")
  log_info "Rename back raw response: $resp2"

  local list3 final_has_orig final_has_tmp
  list3=$(call "$list_cmd")
  final_has_orig=$(jq -r --arg n "$orig_name" '[(.custom[]?), (.preset[]?)] | map(select(.Name==$n)) | length' <<<"$list3")
  final_has_tmp=$(jq -r --arg n "$tmp_name" '[(.custom[]?), (.preset[]?)] | map(select(.Name==$n)) | length' <<<"$list3")
  if [[ "$final_has_orig" -gt 0 && "$final_has_tmp" -eq 0 ]]; then
    log_pass "Restore verified: profile is back to '$orig_name'."
  else
    log_fail "RESTORE MISMATCH after rename-back — profile may still be named '$tmp_name'. CHECK THE APP/DEVICE MANUALLY NOW and rename it back to '$orig_name' if needed."
  fi
}

# ---------------------------------------------------------------------------
# Section 2.3 — EQSetChannelMode
# ---------------------------------------------------------------------------
section2_channelmode() {
  echo
  echo "==================== SECTION 2.3: EQSetChannelMode (source=$TEST_SOURCE) ===================="
  local buf orig_mode orig_stat orig_name new_mode orig_band orig_bandL orig_bandR
  buf=$(call "EQGetLV2SourceBandEx:{\"source_name\":\"${TEST_SOURCE}\",\"pluginURI\":\"${PLUGIN_URI}\"}")
  if ! is_recognized "$buf"; then
    log_skip "Could not read current band/mode for source '$TEST_SOURCE' — skipping."
    return
  fi
  orig_mode=$(jq -r '.channelMode // empty' <<<"$buf")
  orig_stat=$(jq -r '.EQStat // empty' <<<"$buf")
  orig_name=$(jq -r '.Name // empty' <<<"$buf")
  if [[ "$orig_mode" == "Stereo" ]]; then
    orig_band=$(jq -c '.EQBand' <<<"$buf"); new_mode="L/R"
  else
    orig_bandL=$(jq -c '.EQBandL' <<<"$buf"); orig_bandR=$(jq -c '.EQBandR' <<<"$buf"); new_mode="Stereo"
  fi
  log_warn "About to flip channelMode for source '$TEST_SOURCE' from '$orig_mode' to '$new_mode' and back. Briefly changes the audible EQ shape if PEQ is enabled on this source."
  if ! confirm "Proceed with EQSetChannelMode round-trip test on source '$TEST_SOURCE'?"; then
    log_skip "EQSetChannelMode test skipped by operator."
    return
  fi

  local resp after after_mode
  resp=$(call "EQSetChannelMode:{\"EQLevel\":1,\"source_name\":\"${TEST_SOURCE}\",\"pluginURI\":\"${PLUGIN_URI}\",\"channelMode\":\"${new_mode}\"}")
  log_info "EQSetChannelMode raw response: $resp"

  after=$(call "EQGetLV2SourceBandEx:{\"source_name\":\"${TEST_SOURCE}\",\"pluginURI\":\"${PLUGIN_URI}\"}")
  after_mode=$(jq -r '.channelMode // empty' <<<"$after")
  if [[ "$after_mode" == "$new_mode" ]]; then
    log_pass "EQSetChannelMode WORKS: channelMode is now '$after_mode' (confirms this — not EQSetLV2ChannelMode — is the real working command)."
  else
    log_warn "channelMode after call is '$after_mode', expected '$new_mode'. Raw: $after"
  fi

  local restore_payload
  if [[ "$orig_mode" == "Stereo" ]]; then
    restore_payload="{\"source_name\":\"${TEST_SOURCE}\",\"pluginURI\":\"${PLUGIN_URI}\",\"channelMode\":\"Stereo\",\"EQBand\":${orig_band}}"
  else
    restore_payload="{\"source_name\":\"${TEST_SOURCE}\",\"pluginURI\":\"${PLUGIN_URI}\",\"channelMode\":\"L/R\",\"EQBandL\":${orig_bandL},\"EQBandR\":${orig_bandR}}"
  fi
  call "EQSetLV2SourceBand:${restore_payload}" >/dev/null

  # A raw EQSetLV2SourceBand write drops the source's Name association even when the
  # bands are byte-identical (docs/wiim_api_notes.md, PEQ Write section) — re-attach it
  # via EQv2SourceLoad, which also unconditionally turns EQStat on as a side effect, so
  # the EQStat fix-up below must run AFTER this, not before.
  if [[ -n "$orig_name" ]]; then
    call "EQv2SourceLoad:{\"source_name\":\"${TEST_SOURCE}\",\"pluginURI\":\"${PLUGIN_URI}\",\"Name\":\"${orig_name}\"}" >/dev/null
  fi

  if [[ "$orig_stat" == "Off" ]]; then
    call "EQSourceOff:{\"source_name\":\"${TEST_SOURCE}\",\"pluginURI\":\"${PLUGIN_URI}\"}" >/dev/null
  elif [[ "$orig_stat" == "On" ]]; then
    call "EQChangeSourceFX:{\"source_name\":\"${TEST_SOURCE}\",\"pluginURI\":\"${PLUGIN_URI}\"}" >/dev/null
  fi

  local final final_mode final_stat final_name
  final=$(call "EQGetLV2SourceBandEx:{\"source_name\":\"${TEST_SOURCE}\",\"pluginURI\":\"${PLUGIN_URI}\"}")
  final_mode=$(jq -r '.channelMode // empty' <<<"$final")
  final_stat=$(jq -r '.EQStat // empty' <<<"$final")
  final_name=$(jq -r '.Name // empty' <<<"$final")
  if [[ "$final_mode" == "$orig_mode" && "$final_stat" == "$orig_stat" && "$final_name" == "$orig_name" ]]; then
    log_pass "Restore verified: channelMode, EQStat, and Name match pre-test state ('$orig_mode'/'$orig_stat'/'$orig_name')."
  else
    log_fail "RESTORE MISMATCH — expected channelMode='$orig_mode' EQStat='$orig_stat' Name='$orig_name', got channelMode='$final_mode' EQStat='$final_stat' Name='$final_name'. CHECK THE DEVICE/APP MANUALLY NOW."
  fi
}

# ---------------------------------------------------------------------------
# Section 2.4 — EQv2Load (no source_name)
# ---------------------------------------------------------------------------
section2_eqv2load() {
  echo
  echo "==================== SECTION 2.4: EQv2Load (no source_name) ===================="
  local list target
  list=$(call "EQv2GetNewList:{\"pluginURI\":\"${PLUGIN_URI}\",\"EQLevel\":1}")
  target=$(jq -r '[(.custom[]?.Name), (.preset[]?.Name)] | map(select(. != null)) | .[0] // empty' <<<"$list")
  if [[ -z "$target" ]]; then
    log_skip "No saved PEQ preset found to test EQv2Load against — save one via the app first if you want to test this."
    return
  fi

  local buf orig_name orig_stat
  buf=$(call "EQGetLV2SourceBandEx:{\"source_name\":\"${TEST_SOURCE}\",\"pluginURI\":\"${PLUGIN_URI}\"}")
  orig_name=$(jq -r '.Name // empty' <<<"$buf")
  orig_stat=$(jq -r '.EQStat // empty' <<<"$buf")
  log_warn "About to call EQv2Load (no source_name) with existing preset '$target' to see which source/buffer it actually affects. May silently change whichever source is currently LIVE/ACTIVE — not necessarily '$TEST_SOURCE' (same trap documented for EQv2SourceLoad)."
  if ! confirm "Proceed with EQv2Load test?"; then
    log_skip "EQv2Load test skipped by operator."
    return
  fi

  local resp after after_name
  resp=$(call "EQv2Load:{\"pluginURI\":\"${PLUGIN_URI}\",\"Name\":\"${target}\"}")
  log_info "EQv2Load raw response: $resp"

  after=$(call "EQGetLV2SourceBandEx:{\"source_name\":\"${TEST_SOURCE}\",\"pluginURI\":\"${PLUGIN_URI}\"}")
  after_name=$(jq -r '.Name // empty' <<<"$after")
  if [[ "$after_name" == "$target" ]]; then
    log_pass "EQv2Load DID affect source '$TEST_SOURCE' (Name is now '$after_name')."
  else
    log_warn "Source '$TEST_SOURCE' Name is unchanged ('$after_name') — EQv2Load may have targeted a different (live/active) source instead. Manually check every source in the app."
  fi

  if [[ -n "$orig_name" ]]; then
    call "EQv2SourceLoad:{\"source_name\":\"${TEST_SOURCE}\",\"pluginURI\":\"${PLUGIN_URI}\",\"Name\":\"${orig_name}\"}" >/dev/null
  fi
  if [[ "$orig_stat" == "Off" ]]; then
    call "EQSourceOff:{\"source_name\":\"${TEST_SOURCE}\",\"pluginURI\":\"${PLUGIN_URI}\"}" >/dev/null
  fi

  local final final_name final_stat
  final=$(call "EQGetLV2SourceBandEx:{\"source_name\":\"${TEST_SOURCE}\",\"pluginURI\":\"${PLUGIN_URI}\"}")
  final_name=$(jq -r '.Name // empty' <<<"$final")
  final_stat=$(jq -r '.EQStat // empty' <<<"$final")
  if [[ "$final_name" == "$orig_name" && "$final_stat" == "$orig_stat" ]]; then
    log_pass "Restore verified for source '$TEST_SOURCE'."
  else
    log_fail "RESTORE MISMATCH for source '$TEST_SOURCE' — expected Name='$orig_name' EQStat='$orig_stat', got Name='$final_name' EQStat='$final_stat'. CHECK THE DEVICE/APP MANUALLY NOW."
  fi

  log_warn "IMPORTANT: if EQv2Load actually affected a DIFFERENT source, this script did not detect or restore it. Manually check all sources in the app after this test."
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
section1

if [[ "$RUN_WRITES" == "1" ]]; then
  echo
  echo "######## WRITE TESTS ENABLED (--writes) ########"
  section2_roomfit
  section2_rename
  section2_channelmode
  section2_eqv2load
else
  echo
  log_info "Write-tests (RoomFit push family, EQv2Rename, EQSetChannelMode, EQv2Load) were SKIPPED. Re-run with --writes (and optionally --yes) to run them — each backs up and restores state, with confirmation prompts for the higher-risk ones."
fi

echo
echo "==================== THEORY CHECK (this device): RoomCorrGetMode <-> RoomCorrSet ===================="
echo "RoomCorrGetMode classification: $GETMODE_CLASS"
echo "GetAcousticCapability RC.Version: $RC_VERSION"
echo "RoomCorrSet mutation result:    $SET_MUTATION_RESULT"
if [[ "$SET_MUTATION_RESULT" == "MUTATED" || "$SET_MUTATION_RESULT" == "NOT_MUTATED" ]]; then
  if { [[ "$GETMODE_CLASS" == "REAL" && "$SET_MUTATION_RESULT" == "MUTATED" ]] || [[ "$GETMODE_CLASS" == "ALIASED" && "$SET_MUTATION_RESULT" == "NOT_MUTATED" ]]; }; then
    log_pass "This device is CONSISTENT with the theory."
  else
    log_fail "This device CONTRADICTS the theory (GetMode='$GETMODE_CLASS', Set='$SET_MUTATION_RESULT')."
  fi
else
  log_info "Set-mutation result ('$SET_MUTATION_RESULT') isn't a MUTATED/NOT_MUTATED data point — this device alone can't confirm/refute the theory. Run with --writes to get one (Mini is intentionally exempt — no real RoomFit storage to safely test)."
fi

if [[ ! -f "$RESULTS_FILE" ]]; then
  echo "device_ip,model,getmode_class,set_mutation_result,rc_version" >"$RESULTS_FILE"
fi
echo "${WIIM_IP},${MODEL},${GETMODE_CLASS},${SET_MUTATION_RESULT},${RC_VERSION}" >>"$RESULTS_FILE"
log_info "Row appended to $RESULTS_FILE. Once every device has been run (Section 1 alone logs the GetMode/RC.Version side; --writes is needed for the Set side), run:"
log_info "  $0 --summarize $([[ "$RESULTS_FILE" != "./roomcorr_theory_results.csv" ]] && echo "$RESULTS_FILE")"
log_info "to get the aggregate CONFIRMED/REFUTED verdict."

echo
echo "==================== DONE ===================="
