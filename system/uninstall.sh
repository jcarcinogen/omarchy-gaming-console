#!/usr/bin/env bash
# Exact, state-driven uninstaller for the Omarchy Gaming Console system engine.
set -euo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin
umask 077

readonly STATE_DIR=/var/lib/omarchy-gaming-console
readonly STATE_FILE=/var/lib/omarchy-gaming-console/install-state.tsv
readonly RUNTIME_DIR=/run/omarchy-gaming-console
readonly PAYLOAD=/run/omarchy-gaming-console/sddm-oneshot.conf
readonly UNIT=omarchy-gaming-console-switch.service
readonly LOCK=/run/lock/omarchy-gaming-console-install.lock
readonly SWITCH_LOCK=/run/lock/omarchy-gaming-console-switch.lock
readonly STOCK_DESKTOP=/usr/local/share/wayland-sessions/omarchy.desktop
readonly AUTOLOGIN=/etc/sddm.conf.d/autologin.conf
readonly UPDATER_DIR=/usr/bin/steamos-polkit-helpers
readonly UPDATER_HELPER=$UPDATER_DIR/steamos-update
readonly PREDECESSOR_MANIFEST_SHA256=9a13ce7b40b09ce48046a30d262b6cb9df72eac8fa7cff42695a3a43d8beb14f

state_version=0
directory_created=0

[[ $# == 0 ]] || { printf 'Usage: %s\n' "$0" >&2; exit 64; }
[[ $EUID == 0 ]] || { printf 'Run through the visible uninstall entry point.\n' >&2; exit 77; }

log() { printf '%s\n' "$*"; }
die() { printf 'REFUSE: %s\n' "$*" >&2; exit 78; }

for command in awk flock grep loginctl mktemp readlink rmdir sha256sum stat systemctl; do
  command -v "$command" >/dev/null 2>&1 || die "required command is missing: $command"
done
[[ -f $STATE_FILE && ! -L $STATE_FILE ]] || die 'recorded installation state is missing or unsafe'
[[ $(stat -c '%u:%g:%a' "$STATE_DIR") == 0:0:700 ]] || die 'installation state directory ownership/mode is unsafe'
[[ $(stat -c '%u:%g:%a' "$STATE_FILE") == 0:0:600 ]] || die 'installation state file ownership/mode is unsafe'


exec 9>"$LOCK"
flock -x 9

allowed_record() {
  local kind=$1 destination=$2
  case "$kind:$destination" in
    file:/usr/local/bin/omarchy-console-session|\
    file:/usr/local/bin/steamos-session-select|\
    file:/usr/local/bin/steamos-update|\
    file:/usr/bin/steamos-polkit-helpers/steamos-update|\
    file:/usr/local/bin/steamos-select-branch|\
    file:/usr/local/libexec/omarchy-switch-to-console|\
    file:/usr/local/share/wayland-sessions/omarchy-console.desktop|\
    file:/usr/share/polkit-1/actions/org.omarchy.gaming-console.policy|\
    symlink:/etc/sddm.conf.d/zz-omarchy-console-oneshot.conf)
      return 0
      ;;
  esac
  return 1
}

predecessor_record_valid() {
  local kind=$1 destination=$2 declared_mode=$3 owner=$4 group=$5 recorded=$6
  case "$kind|$destination|$declared_mode|$owner|$group|$recorded" in
    "file|/usr/local/bin/omarchy-console-session|0755|root|root|fe73f4f816bb139391ebdf6ddb0fc3bca7d374ed115de8b485b756364c2bf5b7"|\
    "file|/usr/local/bin/steamos-session-select|0755|root|root|039894329a382dd6f11007faf73971dd53da8d498be853718a772c97ea03c460"|\
    "file|/usr/local/bin/steamos-update|0755|root|root|ffec208fbc702284884f2e26095b8d49b9c98455c8bf1e3b7fc7049701c26741"|\
    "file|/usr/local/bin/steamos-select-branch|0755|root|root|ac2852f2bb8b67b84fa506133ab0184d9091d521fabc0f18235be1a1e98befdd"|\
    "file|/usr/local/libexec/omarchy-switch-to-console|0755|root|root|1c3b62baea3870f40945783064f4c561799a5fc8762a05acc68226418a8c6e0b"|\
    "file|/usr/local/share/wayland-sessions/omarchy-console.desktop|0644|root|root|c46c565a65dc338062466b722a7505bdb0959fcc05d24f36b21023a6d7907bd8"|\
    "file|/usr/share/polkit-1/actions/org.omarchy.gaming-console.policy|0644|root|root|ecf940f89b352ec38776096abcc2281f896a6a19ac9e8cdc2b02ab99c7844bcf"|\
    "symlink|/etc/sddm.conf.d/zz-omarchy-console-oneshot.conf|0777|root|root|/run/omarchy-gaming-console/sddm-oneshot.conf") return 0 ;;
  esac
  return 1
}

current_record_valid() {
  local kind=$1 destination=$2 declared_mode=$3 owner=$4 group=$5 recorded=$6
  case "$kind|$destination|$declared_mode|$owner|$group" in
    file\|/usr/local/bin/omarchy-console-session\|0755\|root\|root|\
    file\|/usr/local/bin/steamos-session-select\|0755\|root\|root|\
    file\|/usr/local/bin/steamos-update\|0755\|root\|root|\
    file\|/usr/bin/steamos-polkit-helpers/steamos-update\|0755\|root\|root|\
    file\|/usr/local/bin/steamos-select-branch\|0755\|root\|root|\
    file\|/usr/local/libexec/omarchy-switch-to-console\|0755\|root\|root|\
    file\|/usr/local/share/wayland-sessions/omarchy-console.desktop\|0644\|root\|root|\
    file\|/usr/share/polkit-1/actions/org.omarchy.gaming-console.policy\|0644\|root\|root)
      [[ $recorded =~ ^[0-9a-f]{64}$ ]]
      ;;
    symlink\|/etc/sddm.conf.d/zz-omarchy-console-oneshot.conf\|0777\|root\|root)
      [[ $recorded == "$PAYLOAD" ]]
      ;;
    *) return 1 ;;
  esac
}

validate_state_records() {
  local tag a b c d e f extra seen manifest_hash= phase= created=
  local version_count=0 project_count=0 manifest_count=0 phase_count=0 directory_count=0 object_count=0
  seen=$(mktemp /run/omarchy-gaming-console-uninstall.XXXXXX)
  trap 'rm -f "$seen"' RETURN
  while IFS=$'\t' read -r tag a b c d e f extra; do
    case $tag in
      state_version)
        [[ -n $a && -z ${b:-} ]] || die 'state_version record is malformed'
        version_count=$((version_count + 1)); state_version=$a
        ;;
      project_version)
        [[ $a == 0.0.0 && -z ${b:-} ]] || die 'project_version record is malformed'
        project_count=$((project_count + 1))
        ;;
      manifest_sha256)
        [[ $a =~ ^[0-9a-f]{64}$ && -z ${b:-} ]] || die 'manifest_sha256 record is malformed'
        manifest_count=$((manifest_count + 1)); manifest_hash=$a
        ;;
      install_phase)
        [[ $a == complete && -z ${b:-} ]] || die 'install_phase record is malformed'
        phase_count=$((phase_count + 1)); phase=$a
        ;;
      directory_created)
        [[ $a == "$UPDATER_DIR" && ( $b == 0 || $b == 1 ) && -z ${c:-} ]] || die 'directory_created record is malformed'
        directory_count=$((directory_count + 1)); created=$b
        ;;
      object)
        [[ -n $a && -n $b && -n $c && -n $d && -n $e && -n $f && -z ${extra:-} ]] || die "state record is malformed: ${b:-unknown}"
        allowed_record "$a" "$b" || die "state contains an undeclared destination: $b"
        ! grep -Fxq -- "$b" "$seen" || die "state repeats a destination: $b"
        printf '%s\n' "$b" >>"$seen"
        object_count=$((object_count + 1))
        ;;
      *) die "state contains an unknown record: ${tag:-empty}" ;;
    esac
  done <"$STATE_FILE"
  [[ $version_count == 1 && $project_count == 1 && $manifest_count == 1 ]] || die 'state metadata must appear exactly once'
  case $state_version in
    1)
      [[ $manifest_hash == "$PREDECESSOR_MANIFEST_SHA256" && $phase_count == 0 && $directory_count == 0 && $object_count == 8 ]] || die 'predecessor state is not exact'
      while IFS=$'\t' read -r tag a b c d e f extra; do
        [[ $tag != object ]] || predecessor_record_valid "$a" "$b" "$c" "$d" "$e" "$f" || die "state record is malformed: $b"
      done <"$STATE_FILE"
      directory_created=0
      ;;
    2)
      [[ $manifest_hash =~ ^[0-9a-f]{64}$ && $phase == complete && $phase_count == 1 && $directory_count == 1 && $object_count == 9 ]] || die 'current state is not exact'
      while IFS=$'\t' read -r tag a b c d e f extra; do
        [[ $tag != object ]] || current_record_valid "$a" "$b" "$c" "$d" "$e" "$f" || die "state record is malformed: $b"
      done <"$STATE_FILE"
      directory_created=$created
      ;;
    *) die 'unsupported installation state version' ;;
  esac
  trap - RETURN
  rm -f "$seen"
}

safe_root_directory() {
  local path=$1 owner directory_mode
  [[ -d $path && ! -L $path ]] || return 1
  owner=$(stat -c '%u:%g' "$path")
  directory_mode=$(stat -c '%a' "$path")
  [[ $owner == 0:0 ]] || return 1
  (( (8#$directory_mode & 8#022) == 0 ))
}

safe_updater_parent_chain() {
  safe_root_directory /usr &&
    safe_root_directory /usr/bin &&
    safe_root_directory "$UPDATER_DIR"
}

console_session_active() {
  local sid
  while read -r sid _; do
    [[ -n $sid ]] || continue
    [[ $(loginctl show-session "$sid" -p Seat --value 2>/dev/null) == seat0 ]] || continue
    [[ $(loginctl show-session "$sid" -p State --value 2>/dev/null) == active ]] || continue
    [[ $(loginctl show-session "$sid" -p Desktop --value 2>/dev/null) == gamescope ]] || continue
    return 0
  done < <(loginctl list-sessions --no-legend --no-pager)
  return 1
}

validate_stock_baseline() {
  [[ -f $STOCK_DESKTOP && ! -L $STOCK_DESKTOP ]] || die 'stock omarchy.desktop is missing'
  [[ -f $AUTOLOGIN && ! -L $AUTOLOGIN ]] || die 'stock autologin.conf is missing'
  awk -F= '
    /^[[:space:]]*\[/ { section=$0; gsub(/[[:space:]]/, "", section); next }
    section == "[Autologin]" {
      key=$1; gsub(/[[:space:]]/, "", key)
      if (key == "Session") {
        value=substr($0, index($0, "=") + 1); gsub(/[[:space:]]/, "", value)
        if (value == "omarchy.desktop") good++
        total++
      }
    }
    END { exit !(good == 1 && total == 1) }
  ' "$AUTOLOGIN" || die 'stock autologin Session is not exactly omarchy.desktop'
}

validate_state_records
validate_stock_baseline

# End or recover any in-flight visit before removing the executable, policy,
# session, or fixed route that the supervisor needs.
if systemctl is-active --quiet "$UNIT"; then
  log 'Stopping the active Console supervisor and waiting for its recovery path.'
  systemctl stop "$UNIT"
fi

exec 8>"$SWITCH_LOCK"
flock -x 8
rm -f -- "$PAYLOAD"
if console_session_active; then
  log 'Console is active without its supervisor; restarting SDDM to stock Omarchy.'
  systemctl reset-failed sddm >/dev/null 2>&1 || true
  systemctl restart sddm
fi
systemctl reset-failed "$UNIT" >/dev/null 2>&1 || true

while IFS=$'\t' read -r tag kind destination declared_mode owner group recorded extra; do
  [[ $tag == object ]] || continue
  allowed_record "$kind" "$destination" || die "state changed during uninstall: $destination"
  if [[ $destination == "$UPDATER_HELPER" ]]; then
    if ! safe_updater_parent_chain; then
      log "Preserved shared updater subtree because its parent chain is unsafe: $UPDATER_DIR"
    elif [[ ! -e $destination && ! -L $destination ]]; then
      :
    elif [[ -f $destination && ! -L $destination ]] &&
       [[ $(stat -c '%u:%g:%a' "$destination") == 0:0:755 ]] &&
       [[ $(sha256sum "$destination" | awk '{print $1}') == "$recorded" ]]; then
      rm -f -- "$destination"
      log "Removed owned object: $destination"
    else
      log "Preserved modified or unsafe shared updater helper: $destination"
    fi
    continue
  fi
  if [[ ! -e $destination && ! -L $destination ]]; then
    continue
  fi
  rm -f -- "$destination"
  log "Removed owned object: $destination"
done <"$STATE_FILE"

if (( state_version == 2 )) && (( directory_created == 1 )); then
  if safe_root_directory /usr && safe_root_directory /usr/bin && [[ -d $UPDATER_DIR && ! -L $UPDATER_DIR && $(stat -c '%u:%g:%a' "$UPDATER_DIR") == 0:0:755 ]]; then
    if rmdir -- "$UPDATER_DIR" 2>/dev/null; then
      log "Removed empty project-owned updater directory: $UPDATER_DIR"
    else
      log "Preserved non-empty project-owned updater directory: $UPDATER_DIR"
    fi
  elif [[ -e $UPDATER_DIR || -L $UPDATER_DIR ]]; then
    log "Preserved modified or unsafe shared updater directory: $UPDATER_DIR"
  fi
elif [[ -e $UPDATER_DIR || -L $UPDATER_DIR ]]; then
  log "Preserved shared updater directory: $UPDATER_DIR"
fi

systemctl daemon-reload
rm -f -- "$STATE_FILE"
rmdir -- "$RUNTIME_DIR" 2>/dev/null || true
if rmdir -- "$STATE_DIR" 2>/dev/null; then
  log "Removed empty state directory: $STATE_DIR"
else
  log "Preserved non-empty state directory: $STATE_DIR"
fi

# Report completion only after filesystem changes reach the backing device.
/usr/bin/sync

log 'Omarchy Gaming Console engine uninstall complete.'
