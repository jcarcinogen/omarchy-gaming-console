#!/usr/bin/env python3
"""Behavioral tests for strict updater-helper ownership-state migration."""

from __future__ import annotations

import csv
import hashlib
import os
import pathlib
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
INSTALLER = SYSTEM / "install.sh"
MANIFEST = SYSTEM / "ownership.manifest"
PREDECESSOR_HASH = "9a13ce7b40b09ce48046a30d262b6cb9df72eac8fa7cff42695a3a43d8beb14f"
ROUTE = "/etc/sddm.conf.d/zz-omarchy-console-oneshot.conf"
PAYLOAD = "/run/omarchy-gaming-console/sddm-oneshot.conf"
UPDATER_DIR = "/usr/bin/steamos-polkit-helpers"


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_rows() -> list[list[str]]:
    with MANIFEST.open(newline="") as handle:
        return [row for row in csv.reader(handle, delimiter="\t") if row and not row[0].startswith("#")]


def current_state(phase: str = "complete", created: int = 1) -> str:
    lines = [
        "state_version\t2",
        "project_version\t0.0.0",
        f"manifest_sha256\t{digest(MANIFEST)}",
        f"install_phase\t{phase}",
        f"directory_created\t{UPDATER_DIR}\t{created}",
    ]
    for kind, source, destination, mode, owner, group, target in manifest_rows():
        recorded = digest(SYSTEM / source) if kind == "file" else target
        lines.append(f"object\t{kind}\t{destination}\t{mode}\t{owner}\t{group}\t{recorded}")
    return "\n".join(lines) + "\n"


def predecessor_state() -> str:
    records = [
        ("file", "/usr/local/bin/omarchy-console-session", "0755", "fe73f4f816bb139391ebdf6ddb0fc3bca7d374ed115de8b485b756364c2bf5b7"),
        ("file", "/usr/local/bin/steamos-session-select", "0755", "039894329a382dd6f11007faf73971dd53da8d498be853718a772c97ea03c460"),
        ("file", "/usr/local/bin/steamos-update", "0755", "ffec208fbc702284884f2e26095b8d49b9c98455c8bf1e3b7fc7049701c26741"),
        ("file", "/usr/local/bin/steamos-select-branch", "0755", "ac2852f2bb8b67b84fa506133ab0184d9091d521fabc0f18235be1a1e98befdd"),
        ("file", "/usr/local/libexec/omarchy-switch-to-console", "0755", "1c3b62baea3870f40945783064f4c561799a5fc8762a05acc68226418a8c6e0b"),
        ("file", "/usr/local/share/wayland-sessions/omarchy-console.desktop", "0644", "c46c565a65dc338062466b722a7505bdb0959fcc05d24f36b21023a6d7907bd8"),
        ("file", "/usr/share/polkit-1/actions/org.omarchy.gaming-console.policy", "0644", "ecf940f89b352ec38776096abcc2281f896a6a19ac9e8cdc2b02ab99c7844bcf"),
        ("symlink", ROUTE, "0777", PAYLOAD),
    ]
    lines = ["state_version\t1", "project_version\t0.0.0", f"manifest_sha256\t{PREDECESSOR_HASH}"]
    lines.extend(f"object\t{kind}\t{destination}\t{mode}\troot\troot\t{recorded}" for kind, destination, mode, recorded in records)
    return "\n".join(lines) + "\n"


class InstallerStateValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        text = INSTALLER.read_text()
        start = text.index("state_has_destination() {")
        end = text.index("validate_manifest() {")
        cls.functions = text[start:end]

    def validate(self, state: str, source_dir: pathlib.Path = SYSTEM) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            temp = pathlib.Path(temporary)
            state_dir = temp / "state"
            state_dir.mkdir()
            state_file = state_dir / "install-state.tsv"
            state_file.write_text(state)
            fake_bin = temp / "bin"
            fake_bin.mkdir()
            stat = fake_bin / "stat"
            stat.write_text("#!/bin/sh\ncase \"$3\" in *install-state.tsv) printf '0:0:600\\n';; *) printf '0:0:700\\n';; esac\n")
            stat.chmod(0o755)
            functions = self.functions.replace("/run/omarchy-gaming-console-state.XXXXXX", str(temp / "seen.XXXXXX"))
            script = f"""
set -euo pipefail
PATH={shlex.quote(str(fake_bin))}:{shlex.quote(os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"))}
STATE_DIR={shlex.quote(str(state_dir))}
STATE_FILE={shlex.quote(str(state_file))}
SOURCE_DIR={shlex.quote(str(source_dir))}
MANIFEST={shlex.quote(str(source_dir / "ownership.manifest"))}
ROUTE={shlex.quote(ROUTE)}
PAYLOAD={shlex.quote(PAYLOAD)}
UPDATER_DIR={shlex.quote(UPDATER_DIR)}
PREDECESSOR_MANIFEST_SHA256={PREDECESSOR_HASH}
project_version=0.0.0
existing_state_version=0
directory_created=0
die() {{ printf 'REFUSE: %s\\n' "$*" >&2; exit 78; }}
{functions}
validate_existing_state
printf 'VALID version=%s directory_created=%s\\n' "$existing_state_version" "$directory_created"
"""
            return subprocess.run(["bash", "-c", script], text=True, capture_output=True, check=False)

    def test_exact_eight_object_predecessor_is_accepted_for_migration(self) -> None:
        result = self.validate(predecessor_state())
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("VALID version=1 directory_created=0\n", result.stdout)

    def test_current_complete_state_roundtrips(self) -> None:
        result = self.validate(current_state(phase="complete", created=1))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("VALID version=2 directory_created=1\n", result.stdout)

    def test_pending_intent_state_is_not_accepted_as_ownership(self) -> None:
        result = self.validate(current_state(phase="pending", created=1))
        self.assertEqual(78, result.returncode)

    def test_source_only_upgrade_accepts_structurally_valid_recorded_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = pathlib.Path(temporary) / "system"
            shutil.copytree(SYSTEM, source)
            with (source / "steamos-update").open("a") as handle:
                handle.write("\n# source-only upgrade fixture\n")
            result = self.validate(current_state(), source)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_unknown_predecessor_hash_is_refused(self) -> None:
        state = predecessor_state().replace(PREDECESSOR_HASH, "0" * 64)
        result = self.validate(state)
        self.assertEqual(78, result.returncode)
        self.assertIn("unknown predecessor manifest hash", result.stderr)

    def test_duplicate_destination_is_refused(self) -> None:
        state = predecessor_state()
        duplicate = next(line for line in state.splitlines() if line.startswith("object\t"))
        result = self.validate(state + duplicate + "\n")
        self.assertEqual(78, result.returncode)
        self.assertIn("state repeats a destination", result.stderr)

    def test_malformed_or_arbitrary_current_record_is_refused(self) -> None:
        state = current_state()
        malformed = state.replace(
            "object\tfile\t/usr/local/bin/omarchy-console-session\t0755",
            "object\tfile\t/tmp/arbitrary-destination\t0755",
        )
        result = self.validate(malformed)
        self.assertEqual(78, result.returncode)
        self.assertIn("state record is malformed", result.stderr)


class SharedHelperBehaviorTests(unittest.TestCase):
    def test_repair_refuses_modified_recorded_shared_helper(self) -> None:
        text = INSTALLER.read_text()
        state_fn = text[text.index("state_has_destination() {"):text.index("predecessor_record_valid() {")]
        helper_fns = text[text.index("recorded_hash_for_destination() {"):text.index("symlink_matches() {")]
        validate_fn = text[text.index("validate_destinations_before_write() {"):text.index("apply_manifest() {")]
        with tempfile.TemporaryDirectory() as temporary:
            temp = pathlib.Path(temporary)
            helper = temp / "shared" / "steamos-update"
            helper.parent.mkdir()
            helper.write_text("foreign replacement\n")
            helper.chmod(0o755)
            manifest = temp / "manifest"
            manifest.write_text(f"file\tsteamos-update\t{helper}\t0755\troot\troot\t-\n")
            recorded = digest(SYSTEM / "steamos-update")
            state = temp / "state"
            state.write_text(f"object\tfile\t{helper}\t0755\troot\troot\t{recorded}\n")
            fake_bin = temp / "bin"
            fake_bin.mkdir()
            stat_shim = fake_bin / "stat"
            stat_shim.write_text("#!/bin/sh\nprintf '0:0:755\\n'\n")
            stat_shim.chmod(0o755)
            script = f"""
set -euo pipefail
PATH={shlex.quote(str(fake_bin))}:{shlex.quote(os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"))}
{state_fn}
{helper_fns}
{validate_fn}
STATE_FILE={shlex.quote(str(state))}
MANIFEST={shlex.quote(str(manifest))}
SOURCE_DIR={shlex.quote(str(SYSTEM))}
UPDATER_HELPER={shlex.quote(str(helper))}
existing_state_version=2
mode=repair
die() {{ printf 'REFUSE: %s\\n' "$*" >&2; exit 78; }}
validate_destinations_before_write
"""
            result = subprocess.run(["bash", "-c", script], text=True, capture_output=True, check=False)
        self.assertEqual(78, result.returncode, result.stdout + result.stderr)
        self.assertIn("shared updater helper", result.stderr)

    def assert_uninstall_parent_behavior(self, symlinked: bool) -> None:
        text = (SYSTEM / "uninstall.sh").read_text()
        functions = text[text.index("safe_root_directory() {"):text.index("console_session_active() {")]
        start = text.index("while IFS=", text.index('systemctl reset-failed "$UNIT"'))
        end = text.index("\nif (( state_version == 2 ))", start)
        loop = text[start:end]
        with tempfile.TemporaryDirectory() as temporary:
            temp = pathlib.Path(temporary)
            outside = temp / "outside"
            outside.mkdir()
            victim = outside / "steamos-update"
            victim.write_bytes((SYSTEM / "steamos-update").read_bytes())
            victim.chmod(0o755)
            shared = temp / "shared"
            if symlinked:
                shared.symlink_to(outside, target_is_directory=True)
            else:
                shared = outside
            helper = shared / "steamos-update"
            state = temp / "state"
            state.write_text(f"object\tfile\t{helper}\t0755\troot\troot\t{digest(victim)}\n")
            functions = functions.replace("/usr/bin", str(temp)).replace("/usr", str(temp))
            script = f"""
set -euo pipefail
STATE_FILE={shlex.quote(str(state))}
UPDATER_HELPER={shlex.quote(str(helper))}
UPDATER_DIR={shlex.quote(str(shared))}
allowed_record() {{ return 0; }}
log() {{ :; }}
stat() {{ case "$2" in '%u:%g') printf '0:0\\n';; '%a') printf '755\\n';; '%u:%g:%a') printf '0:0:755\\n';; *) return 1;; esac; }}
{functions}
{loop}
"""
            result = subprocess.run(["bash", "-c", script], text=True, capture_output=True, check=False)
            survived = victim.exists()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(symlinked, survived)

    def test_uninstall_preserves_helper_when_shared_parent_is_symlinked(self) -> None:
        self.assert_uninstall_parent_behavior(symlinked=True)

    def test_uninstall_removes_exact_helper_with_safe_parent(self) -> None:
        self.assert_uninstall_parent_behavior(symlinked=False)

    def test_repair_preserves_existing_shared_directory_mode(self) -> None:
        text = INSTALLER.read_text()
        start = text.index("safe_root_directory() {")
        end = text.index("symlink_matches() {", start)
        functions = text[start:end]
        with tempfile.TemporaryDirectory() as temporary:
            temp = pathlib.Path(temporary)
            usr = temp / "usr"
            bin_dir = usr / "bin"
            shared = bin_dir / "steamos-polkit-helpers"
            shared.mkdir(parents=True)
            usr.chmod(0o755)
            bin_dir.chmod(0o755)
            shared.chmod(0o700)
            functions = functions.replace("safe_root_directory /usr/bin ||", f"safe_root_directory {bin_dir} ||")
            functions = functions.replace("safe_root_directory /usr ||", f"safe_root_directory {usr} ||")
            fake_bin = temp / "fake-bin"
            fake_bin.mkdir()
            stat_shim = fake_bin / "stat"
            stat_shim.write_text("#!/bin/sh\nif [ \"$1\" = -c ]; then case \"$2\" in '%u:%g') printf '0:0\\n';; '%a') /usr/bin/stat -f '%Lp' \"$3\";; esac; else /usr/bin/stat \"$@\"; fi\n")
            stat_shim.chmod(0o755)
            script = f"""
set -euo pipefail
PATH={shlex.quote(str(fake_bin))}:{shlex.quote(os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"))}
UPDATER_DIR={shlex.quote(str(shared))}
existing_state_version=2
directory_created=1
die() {{ printf 'REFUSE: %s\\n' "$*" >&2; exit 78; }}
{functions}
prepare_updater_directory
stat -f '%Lp' {shlex.quote(str(shared))}
"""
            result = subprocess.run(["bash", "-c", script], text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("700", result.stdout.strip())

    def test_vm_fault_builder_creates_each_transformed_fixture(self) -> None:
        harness = (ROOT / "tests/guest-verification/verify-updater-helper-root").read_text()
        function = harness[harness.index("make_fault_source() {"):harness.index("run_expected_interrupt() {")]
        with tempfile.TemporaryDirectory() as temporary:
            temp = pathlib.Path(temporary)
            source = temp / "source"
            (source / "system").mkdir(parents=True)
            (source / "system/install.sh").write_text(INSTALLER.read_text())
            work = temp / "work"
            work.mkdir()
            for mode in ("before-helper", "after-helper", "after-publication"):
                script = f"set -euo pipefail\nSOURCE={shlex.quote(str(source))}\nWORK={shlex.quote(str(work))}\n{function}\nmake_fault_source fixture-{mode} {mode}\n"
                result = subprocess.run(["bash", "-c", script], text=True, capture_output=True)
                self.assertEqual(0, result.returncode, result.stderr)
                target = work / f"fixture-{mode}/system/install.sh"
                self.assertTrue(target.is_file())
                self.assertIn("exit 99", target.read_text())
                self.assertNotEqual(INSTALLER.read_text(), target.read_text())

    def test_installer_publishes_only_final_committed_state(self) -> None:
        text = INSTALLER.read_text()
        self.assertNotIn("write_state pending", text)
        self.assertNotIn("install_phase\tpending", text)
        main = text[text.index("\npreflight_omarchy\n"):]
        self.assertLess(main.index("\napply_manifest\n"), main.index("\nwrite_state\n"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
