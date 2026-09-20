#!/usr/bin/env bash
# Root installer/repairer for the Omarchy Gaming Console system engine.
set -euo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin
umask 077

readonly state_version=2
readonly project_version=0.0.0
readonly PREDECESSOR_MANIFEST_SHA256=9a13ce7b40b09ce48046a30d262b6cb9df72eac8fa7cff42695a3a43d8beb14f
readonly STATE_DIR=/var/lib/omarchy-gaming-console
readonly STATE_FILE=$STATE_DIR/install-state.tsv
readonly LOCK=/run/lock/omarchy-gaming-console-install.lock
readonly STOCK_DESKTOP=/usr/local/share/wayland-sessions/omarchy.desktop
readonly AUTOLOGIN=/etc/sddm.conf.d/autologin.conf
readonly ROUTE=/etc/sddm.conf.d/zz-omarchy-console-oneshot.conf
readonly PAYLOAD=/run/omarchy-gaming-console/sddm-oneshot.conf
readonly UPDATER_DIR=/usr/bin/steamos-polkit-helpers
readonly UPDATER_HELPER=$UPDATER_DIR/steamos-update
readonly SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly MANIFEST=$SOURCE_DIR/ownership.manifest

existing_state_version=0
directory_created=0

mode=${1:-install}
[[ $# -le 1 && ( $mode == install || $mode == repair ) ]] || {
  printf 'Usage: %s [install|repair]\n' "$0" >&2
  exit 64
}
[[ $EUID == 0 ]] || { printf 'Run through the visible setup entry point.\n' >&2; exit 77; }

log() { printf '%s\n' "$*"; }
die() { printf 'REFUSE: %s\n' "$*" >&2; exit 78; }

for command in awk cmp flock getent grep id install ln mkdir mv pacman pkaction readlink sha256sum stat; do
  command -v "$command" >/dev/null 2>&1 || die "required command is missing: $command"
done
[[ -f $MANIFEST && ! -L $MANIFEST ]] || die 'ownership.manifest is missing or is a symlink'
exec 9>"$LOCK"
flock -x 9

owned_root_file() {
  local path=$1 owner file_mode
  [[ -f $path && ! -L $path ]] || return 1
  owner=$(stat -c '%u:%g' "$path")
  file_mode=$(stat -c '%a' "$path")
  [[ $owner == 0:0 ]] || return 1
  (( (8#$file_mode & 8#022) == 0 ))
}

ini_values() {
  local file=$1 wanted=$2
  awk -F= -v wanted="$wanted" '
    /^[[:space:]]*\[/ {
      section=$0
      gsub(/[[:space:]]/, "", section)
      next
    }
    section == "[Autologin]" {
      key=$1
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", key)
      if (key == wanted) {
        value=substr($0, index($0, "=") + 1)
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
        print value
      }
    }
  ' "$file"
}

single_ini_value() {
  local file=$1 key=$2 values count
  values=$(ini_values "$file" "$key")
  count=$(printf '%s\n' "$values" | awk 'NF { n++ } END { print n+0 }')
  [[ $count == 1 ]] || return 1
  printf '%s\n' "$values"
}

is_try_omarchy_vm() {
  [[ $(systemd-detect-virt 2>/dev/null || true) == qemu ]] &&
    [[ $(hostnamectl --static 2>/dev/null || true) == omarchy-vm ]]
}

preflight_omarchy() {
  local package_line version
  package_line=$(pacman -Q try-omarchy-runtime 2>/dev/null || pacman -Q omarchy 2>/dev/null || true)
  [[ -n $package_line ]] || die 'Omarchy package metadata is unavailable'
  version=${package_line##* }
  [[ $version == 4.* ]] || die "Omarchy 4 is required (found $version)"
  [[ -x /usr/bin/omarchy-pkg-add && -x /usr/bin/omarchy-install-gaming-steam ]] || {
    die 'official Omarchy dependency helpers are missing'
  }
}

check_conflicts() {
  local file name
  shopt -s nullglob nocaseglob
  for file in /etc/sddm.conf.d/*; do
    [[ $file == "$AUTOLOGIN" || $file == "$ROUTE" ]] && continue
    name=${file##*/}
    [[ $name != *deckshift* && $name != *wopr* ]] || die "conflicting SDDM drop-in: $file"
    if [[ -f $file ]] && { ini_values "$file" Session | awk 'NF { found=1 } END { exit !found }'; }; then
      die "another SDDM drop-in overrides Autologin Session: $file"
    fi
  done
  if [[ -f /etc/sddm.conf ]] && { ini_values /etc/sddm.conf Session | awk 'NF { found=1 } END { exit !found }'; }; then
    die '/etc/sddm.conf overrides Autologin Session'
  fi
  for file in /usr/local/share/wayland-sessions/*deckshift* /usr/local/share/wayland-sessions/*wopr* /usr/share/wayland-sessions/*deckshift* /usr/share/wayland-sessions/*wopr*; do
    [[ -e $file ]] && die "conflicting session product: $file"
  done
  shopt -u nocaseglob
}

preflight_baseline() {
  local session user uid
  owned_root_file "$STOCK_DESKTOP" || die 'stock omarchy.desktop is missing or unsafe'
  grep -Eq '^Exec=.*\buwsm\b' "$STOCK_DESKTOP" || die 'stock omarchy.desktop does not launch uwsm'
  owned_root_file "$AUTOLOGIN" || die 'autologin.conf is missing or unsafe'
  session=$(single_ini_value "$AUTOLOGIN" Session) || die 'autologin Session must appear exactly once'
  user=$(single_ini_value "$AUTOLOGIN" User) || die 'autologin User must appear exactly once'
  [[ $session == omarchy.desktop ]] || die 'autologin Session is not omarchy.desktop'
  uid=$(id -u "$user" 2>/dev/null || true)
  [[ $uid =~ ^[1-9][0-9]*$ ]] || die 'autologin user is not a local non-root account'
  if [[ -e $ROUTE || -L $ROUTE ]]; then
    [[ -L $ROUTE && $(readlink "$ROUTE") == "$PAYLOAD" ]] || die 'SDDM route conflicts with accepted ADR 0001'
    [[ $(stat -c '%u:%g' "$ROUTE") == 0:0 ]] || die 'existing SDDM route is not root-owned'
  fi
  check_conflicts
}

preflight_dependencies() {
  if is_try_omarchy_vm; then
    [[ -x /usr/bin/Hyprland && -x /usr/bin/foot ]] || die 'Try Omarchy VM dummy dependencies are missing'
    log 'Disposable Try Omarchy VM detected; using the reviewed dummy dependency boundary.'
  else
    [[ -x /usr/bin/gamescope && -x /usr/bin/steam && -x /usr/bin/mangoapp ]] || {
      die 'gamescope, Steam, and MangoHud/mangoapp must be installed by the visible setup entry point'
    }
  fi
}

state_has_destination() {
  local wanted=$1
  (( existing_state_version > 0 )) || return 1
  awk -F '\t' -v wanted="$wanted" '$1 == "object" && $3 == wanted { found=1 } END { exit !found }' "$STATE_FILE"
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
    "symlink|$ROUTE|0777|root|root|$PAYLOAD") return 0 ;;
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

validate_existing_state() {
  local tag a b c d e f extra
  local version_count=0 project_count=0 manifest_count=0 phase_count=0 directory_count=0 object_count=0
  local manifest_hash= phase= created= seen
  if [[ ! -e $STATE_FILE && ! -L $STATE_FILE ]]; then
    if [[ -e $STATE_DIR || -L $STATE_DIR ]]; then
      [[ -d $STATE_DIR && ! -L $STATE_DIR && $(stat -c '%u:%g:%a' "$STATE_DIR") == 0:0:700 ]] || die 'installation state directory ownership/mode is unsafe'
    fi
    return 0
  fi
  [[ -f $STATE_FILE && ! -L $STATE_FILE ]] || die 'installation state is not a regular file'
  [[ $(stat -c '%u:%g:%a' "$STATE_DIR") == 0:0:700 ]] || die 'installation state directory ownership/mode is unsafe'
  [[ $(stat -c '%u:%g:%a' "$STATE_FILE") == 0:0:600 ]] || die 'installation state file ownership/mode is unsafe'
  seen=$(mktemp /run/omarchy-gaming-console-state.XXXXXX)
  trap 'rm -f "$seen"' RETURN
  while IFS=$'\t' read -r tag a b c d e f extra; do
    case $tag in
      state_version)
        [[ -n $a && -z ${b:-} ]] || die 'state_version record is malformed'
        version_count=$((version_count + 1)); existing_state_version=$a
        ;;
      project_version)
        [[ -n $a && -z ${b:-} ]] || die 'project_version record is malformed'
        [[ $a == "$project_version" ]] || die 'project_version record is unknown'
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
        ! grep -Fxq -- "$b" "$seen" || die "state repeats a destination: $b"
        printf '%s\n' "$b" >>"$seen"
        object_count=$((object_count + 1))
        ;;
      *) die "state contains an unknown record: ${tag:-empty}" ;;
    esac
  done <"$STATE_FILE"
  [[ $version_count == 1 && $project_count == 1 && $manifest_count == 1 ]] || die 'state metadata must appear exactly once'
  case $existing_state_version in
    1)
      [[ $manifest_hash == "$PREDECESSOR_MANIFEST_SHA256" ]] || die 'unknown predecessor manifest hash'
      [[ $phase_count == 0 && $directory_count == 0 && $object_count == 8 ]] || die 'predecessor state is incomplete'
      while IFS=$'\t' read -r tag a b c d e f extra; do
        [[ $tag != object ]] || predecessor_record_valid "$a" "$b" "$c" "$d" "$e" "$f" || die "state record is malformed: $b"
      done <"$STATE_FILE"
      directory_created=0
      ;;
    2)
      [[ $phase_count == 1 && $directory_count == 1 && $object_count == 9 ]] || die 'current state is incomplete'
      [[ $phase == complete ]] || die 'incomplete ownership state requires bounded manual recovery'
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

validate_manifest() {
  local kind source destination declared_mode owner group link_target extra seen_file
  seen_file=$(mktemp /run/omarchy-gaming-console-manifest.XXXXXX)
  trap 'rm -f "$seen_file"' RETURN
  while IFS=$'\t' read -r kind source destination declared_mode owner group link_target extra; do
    [[ -n $kind && $kind != \#* ]] || continue
    [[ -z ${extra:-} ]] || die 'ownership.manifest has too many fields'
    [[ $kind == file || $kind == symlink ]] || die "unsupported manifest object: $kind"
    [[ $destination == /* && $destination != *$'\n'* && $destination != *$'\r'* ]] || die 'manifest destination is unsafe'
    ! grep -Fxq -- "$destination" "$seen_file" || die "duplicate manifest destination: $destination"
    printf '%s\n' "$destination" >>"$seen_file"
    [[ $declared_mode =~ ^0[0-7]{3}$ && $owner == root && $group == root ]] || die "invalid ownership declaration: $destination"
    case $kind in
      file)
        [[ $source != */* && $source != . && $source != .. && $link_target == - ]] || die "unsafe manifest source: $source"
        [[ -f $SOURCE_DIR/$source && ! -L $SOURCE_DIR/$source ]] || die "manifest source is missing or unsafe: $source"
        ;;
      symlink)
        [[ $source == - && $destination == "$ROUTE" && $link_target == "$PAYLOAD" ]] || die 'manifest symlink is not the accepted ADR route'
        ;;
    esac
  done <"$MANIFEST"
  trap - RETURN
  rm -f "$seen_file"
}

file_matches() {
  local source=$1 destination=$2 declared_mode=$3
  [[ -f $destination && ! -L $destination ]] || return 1
  [[ $(stat -c '%u:%g:%a' "$destination") == 0:0:${declared_mode#0} ]] || return 1
  cmp -s "$source" "$destination"
}

safe_root_directory() {
  local path=$1 owner directory_mode
  [[ -d $path && ! -L $path ]] || return 1
  owner=$(stat -c '%u:%g' "$path")
  directory_mode=$(stat -c '%a' "$path")
  [[ $owner == 0:0 ]] || return 1
  (( (8#$directory_mode & 8#022) == 0 ))
}

prepare_updater_directory() {
  safe_root_directory /usr || die 'shared updater parent /usr is unsafe'
  safe_root_directory /usr/bin || die 'shared updater parent /usr/bin is unsafe'
  if [[ -e $UPDATER_DIR || -L $UPDATER_DIR ]]; then
    safe_root_directory "$UPDATER_DIR" || die 'shared updater directory is unsafe'
    if (( existing_state_version != 2 )); then
      directory_created=0
    fi
  else
    install -d -m 0755 -o root -g root "$UPDATER_DIR"
    directory_created=1
  fi
}

recorded_hash_for_destination() {
  local wanted=$1
  awk -F '\t' -v wanted="$wanted" '$1 == "object" && $3 == wanted { print $7; found=1 } END { exit !found }' "$STATE_FILE"
}

file_matches_recorded() {
  local destination=$1 declared_mode=$2 recorded=$3
  [[ -f $destination && ! -L $destination ]] || return 1
  [[ $(stat -c '%u:%g:%a' "$destination") == 0:0:${declared_mode#0} ]] || return 1
  [[ $(sha256sum "$destination" | awk '{print $1}') == "$recorded" ]]
}

symlink_matches() {
  local destination=$1 link_target=$2
  [[ -L $destination ]] || return 1
  [[ $(readlink "$destination") == "$link_target" ]] || return 1
  [[ $(stat -c '%u:%g' "$destination") == 0:0 ]]
}

validate_destinations_before_write() {
  local kind source destination declared_mode owner group link_target extra recorded
  while IFS=$'\t' read -r kind source destination declared_mode owner group link_target extra; do
    [[ -n $kind && $kind != \#* ]] || continue
    if [[ ! -e $destination && ! -L $destination ]]; then
      continue
    fi
    if [[ $destination == "$UPDATER_HELPER" ]]; then
      state_has_destination "$destination" || die "unrecorded shared updater helper preserved: $destination; recovery requires verifying that exact path is the interrupted orphan, then rm -f -- '$UPDATER_HELPER' and rmdir -- '$UPDATER_DIR' only if empty"
      recorded=$(recorded_hash_for_destination "$destination")
      file_matches_recorded "$destination" "$declared_mode" "$recorded" || die "shared updater helper changed or is unsafe; preserved for manual recovery: $destination"
      if [[ $mode == install ]]; then
        file_matches "$SOURCE_DIR/$source" "$destination" "$declared_mode" || die "owned file changed; run setup repair: $destination"
      fi
      continue
    fi
    if state_has_destination "$destination"; then
      if [[ $mode == install ]]; then
        if [[ $kind == file ]]; then
          file_matches "$SOURCE_DIR/$source" "$destination" "$declared_mode" || die "owned file changed; run setup repair: $destination"
        else
          symlink_matches "$destination" "$link_target" || die "owned route changed; run setup repair: $destination"
        fi
      fi
      continue
    fi
    if [[ $kind == file ]]; then
      file_matches "$SOURCE_DIR/$source" "$destination" "$declared_mode" || die "refusing to overwrite an unrecorded file: $destination"
      log "Adopting an exact reviewed predecessor: $destination"
    else
      symlink_matches "$destination" "$link_target" || die "refusing to overwrite an unrecorded route: $destination"
      log "Adopting the exact accepted ADR route: $destination"
    fi
  done <"$MANIFEST"
}

apply_manifest() {
  local kind source destination declared_mode owner group link_target extra parent
  while IFS=$'\t' read -r kind source destination declared_mode owner group link_target extra; do
    [[ -n $kind && $kind != \#* ]] || continue
    parent=${destination%/*}
    [[ -d $parent && ! -L $parent ]] || install -d -m 0755 -o root -g root "$parent"
    if [[ $kind == file ]]; then
      if file_matches "$SOURCE_DIR/$source" "$destination" "$declared_mode"; then
        log "Unchanged: $destination"
      else
        install -m "$declared_mode" -o "$owner" -g "$group" "$SOURCE_DIR/$source" "$destination"
        log "Installed: $destination"
      fi
    else
      if symlink_matches "$destination" "$link_target"; then
        log "Unchanged: $destination"
      else
        rm -f -- "$destination"
        ln -s -- "$link_target" "$destination"
        chown -h root:root "$destination"
        log "Installed route: $destination -> $link_target"
      fi
    fi
  done <"$MANIFEST"
}

verify_manifest_applied() {
  local kind source destination declared_mode owner group link_target extra
  while IFS=$'\t' read -r kind source destination declared_mode owner group link_target extra; do
    [[ -n $kind && $kind != \#* ]] || continue
    if [[ $kind == file ]]; then
      file_matches "$SOURCE_DIR/$source" "$destination" "$declared_mode" || die "installed object verification failed: $destination"
    else
      symlink_matches "$destination" "$link_target" || die "installed route verification failed: $destination"
    fi
  done <"$MANIFEST"
}

write_state() {
  local temp manifest_hash kind source destination declared_mode owner group link_target extra object_hash
  install -d -m 0700 -o root -g root "$STATE_DIR"
  temp=$STATE_DIR/.install-state.tsv.$$
  manifest_hash=$(sha256sum "$MANIFEST" | awk '{print $1}')
  {
    printf 'state_version\t%s\n' "$state_version"
    printf 'project_version\t%s\n' "$project_version"
    printf 'manifest_sha256\t%s\n' "$manifest_hash"
    printf 'install_phase\tcomplete\n'
    printf 'directory_created\t%s\t%s\n' "$UPDATER_DIR" "$directory_created"
    while IFS=$'\t' read -r kind source destination declared_mode owner group link_target extra; do
      [[ -n $kind && $kind != \#* ]] || continue
      if [[ $kind == file ]]; then
        object_hash=$(sha256sum "$SOURCE_DIR/$source" | awk '{print $1}')
      else
        object_hash=$link_target
      fi
      printf 'object\t%s\t%s\t%s\t%s\t%s\t%s\n' "$kind" "$destination" "$declared_mode" "$owner" "$group" "$object_hash"
    done <"$MANIFEST"
  } >"$temp"
  chown root:root "$temp"
  chmod 0600 "$temp"
  mv -f "$temp" "$STATE_FILE"
}

preflight_omarchy
preflight_baseline
preflight_dependencies
validate_manifest
validate_existing_state
validate_destinations_before_write
prepare_updater_directory
apply_manifest
verify_manifest_applied

pkaction --action-id org.omarchy.gaming-console.switch >/dev/null 2>&1 || {
  die 'installed polkit action is not visible'
}
[[ ! -e $PAYLOAD && ! -L $PAYLOAD ]] || die 'a volatile Console request is armed after setup'
write_state

# Report completion only after filesystem changes reach the backing device.
/usr/bin/sync

log "Omarchy Gaming Console engine ${mode} complete."
log "Ownership state: $STATE_FILE"
