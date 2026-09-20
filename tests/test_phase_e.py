#!/usr/bin/env python3
"""Milestone 3 Phase E installation and recovery source contracts."""

from __future__ import annotations

import csv
import pathlib
import stat
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"


class PhaseESourceContracts(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text()

    def test_phase_e_entrypoints_exist_and_shell_sources_parse(self) -> None:
        paths = (
            ROOT / "setup",
            ROOT / "uninstall",
            SYSTEM / "install.sh",
            SYSTEM / "uninstall.sh",
        )
        for path in paths:
            self.assertTrue(path.is_file(), path)
            self.assertTrue(path.stat().st_mode & stat.S_IXUSR, path)
            subprocess.run(["bash", "-n", path], check=True)

    def test_manifest_declares_every_engine_object_explicitly(self) -> None:
        manifest = SYSTEM / "ownership.manifest"
        self.assertTrue(manifest.is_file())
        rows: list[list[str]] = []
        with manifest.open(newline="") as handle:
            for row in csv.reader(handle, delimiter="\t"):
                if row and not row[0].startswith("#"):
                    rows.append(row)
        self.assertTrue(rows)
        self.assertTrue(all(len(row) == 7 for row in rows), rows)
        destinations = {row[2] for row in rows}
        self.assertEqual(
            {
                "/usr/local/bin/omarchy-console-session",
                "/usr/local/bin/steamos-session-select",
                "/usr/local/bin/steamos-update",
                "/usr/bin/steamos-polkit-helpers/steamos-update",
                "/usr/local/bin/steamos-select-branch",
                "/usr/local/libexec/omarchy-switch-to-console",
                "/usr/local/share/wayland-sessions/omarchy-console.desktop",
                "/usr/share/polkit-1/actions/org.omarchy.gaming-console.policy",
                "/etc/sddm.conf.d/zz-omarchy-console-oneshot.conf",
            },
            destinations,
        )
        for kind, source, destination, mode, owner, group, link_target in rows:
            self.assertIn(kind, {"file", "symlink"})
            self.assertTrue(destination.startswith("/"))
            self.assertRegex(mode, r"^0[0-7]{3}$")
            self.assertEqual("root", owner)
            self.assertEqual("root", group)
            if kind == "file":
                self.assertTrue(source)
                self.assertTrue((SYSTEM / source).is_file(), source)
                self.assertEqual("-", link_target)
            else:
                self.assertEqual("-", source)
                self.assertEqual(
                    "/run/omarchy-gaming-console/sddm-oneshot.conf",
                    link_target,
                )

    def test_installer_declares_a_strict_predecessor_migration_and_shared_directory_rules(self) -> None:
        text = self.read("system/install.sh")
        self.assertIn("state_version=2", text)
        self.assertIn("9a13ce7b40b09ce48046a30d262b6cb9df72eac8fa7cff42695a3a43d8beb14f", text)
        self.assertIn("/usr/bin/steamos-polkit-helpers", text)
        self.assertIn("directory_created", text)
        self.assertIn("state repeats a destination", text)
        self.assertIn("state record is malformed", text)

    def test_uninstaller_knows_both_state_generations_and_preserves_shared_updater_assets(self) -> None:
        text = self.read("system/uninstall.sh")
        self.assertIn("/usr/bin/steamos-polkit-helpers/steamos-update", text)
        self.assertIn("directory_created", text)
        self.assertIn("Preserved modified or unsafe shared updater helper", text)
        self.assertIn("Preserved shared updater directory", text)

    def test_setup_uses_only_official_dependency_helpers(self) -> None:
        text = self.read("setup")
        self.assertIn("omarchy-pkg-add gamescope", text)
        self.assertIn("omarchy-install-gaming-steam", text)
        self.assertNotIn("pacman -S", text)
        self.assertNotIn("yay -S", text)

    def test_installer_has_versioned_root_owned_state_and_safe_adoption(self) -> None:
        text = self.read("system/install.sh")
        for required in (
            "/var/lib/omarchy-gaming-console",
            "install-state.tsv",
            "state_version",
            "ownership.manifest",
            "omarchy.desktop",
            "Session",
            "omarchy.desktop",
            "try-omarchy-runtime",
            "repair",
            "sha256sum",
        ):
            self.assertIn(required, text)
        self.assertNotIn("rm -rf", text)
        self.assertNotIn("killall", text)

    def test_uninstaller_is_state_driven_exact_and_non_recursive(self) -> None:
        text = self.read("system/uninstall.sh")
        for required in (
            "/var/lib/omarchy-gaming-console/install-state.tsv",
            "/run/omarchy-gaming-console/sddm-oneshot.conf",
            "omarchy-gaming-console-switch.service",
            "systemctl reset-failed sddm",
            "rmdir",
        ):
            self.assertIn(required, text)
        self.assertNotIn("rm -rf", text)
        self.assertNotIn("killall", text)
        self.assertNotIn("uwsm stop", text)

    def test_visible_scripts_keep_plugin_removal_separate_and_print_rescue(self) -> None:
        setup = self.read("setup")
        uninstall = self.read("uninstall")
        self.assertIn("Ctrl+Alt+F3", setup)
        self.assertIn("plugin remove", uninstall)
        self.assertIn("pkexec", setup)
        self.assertIn("pkexec", uninstall)

    def test_initial_install_warns_that_first_gamescope_steam_launch_can_be_black(self) -> None:
        setup = self.read("setup")
        self.assertIn("if [[ $mode == install ]]", setup)
        self.assertIn("On the first Console launch, Steam may take a little while to start inside Gamescope.", setup)
        self.assertIn("The screen may stay black briefly; please wait for Steam to appear.", setup)

    def test_guest_verification_covers_acceptance_matrix(self) -> None:
        text = self.read("tests/guest-verification/verify-phase-e-root")
        for marker in (
            "FIRST_INSTALL_PASS",
            "SECOND_INSTALL_IDEMPOTENT_PASS",
            "REPAIR_MISSING_PASS",
            "REPAIR_MODIFIED_PASS",
            "UNKNOWN_FILES_SURVIVE_PASS",
            "RESCUE_PASS",
            "UNINSTALL_PASS",
            "STOCK_HASHES_PASS",
        ):
            self.assertIn(marker, text)

    def test_updater_vm_harness_covers_migration_faults_and_preservation(self) -> None:
        text = self.read("tests/guest-verification/verify-updater-helper-root")
        for marker in (
            "LEGACY_MIGRATION_PASS",
            "UNKNOWN_STATE_REFUSAL_PASS",
            "DUPLICATE_STATE_REFUSAL_PASS",
            "MALFORMED_STATE_REFUSAL_PASS",
            "PREEXISTING_HELPER_COLLISION_PASS",
            "UNSAFE_DIRECTORY_REFUSAL_PASS",
            "IDEMPOTENT_REPAIR_PASS",
            "MODIFIED_HELPER_PRESERVED_PASS",
            "UNOWNED_HELPER_PRESERVED_PASS",
            "SYMLINKED_HELPER_PRESERVED_PASS",
            "SYMLINKED_PARENT_UNINSTALL_PRESERVES_PASS",
            "SHARED_DIRECTORY_PRESERVED_PASS",
            "DIRECTORY_METADATA_DRIFT_PRESERVED_PASS",
            "PROJECT_DIRECTORY_REMOVED_PASS",
            "EXACT_PATH_EXIT7_QUIET_PASS",
            "GENUINE_NONROOT_STATUS_PASS",
            "SOURCE_ONLY_UPGRADE_LIFECYCLE_PASS",
            "INTERRUPT_BEFORE_HELPER_PASS",
            "INTERRUPT_AFTER_HELPER_RECOVERY_REQUIRED_PASS",
            "INTERRUPT_AFTER_PUBLICATION_PASS",
            "UNKNOWN_REPLACEMENT_SURVIVES_PASS",
            "EXPLICIT_ORPHAN_RECOVERY_PASS",
            "STOCK_HASHES_UNCHANGED_PASS",
            "UPDATER_VM_HARNESS_PASS",
        ):
            self.assertIn(marker, text)
        self.assertIn("OGC_CONFIRMED_DISPOSABLE_UPDATER_FIXTURE", text)
        self.assertNotIn('rmdir -- "$UPDATER_DIR" 2>/dev/null || true', text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
