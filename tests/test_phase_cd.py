#!/usr/bin/env python3
"""Milestone 2 Phase C/D source-contract tests."""

from __future__ import annotations

import os
import pathlib
import stat
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"


class SourceContractTests(unittest.TestCase):
    def read(self, name: str) -> str:
        return (SYSTEM / name).read_text()

    def test_expected_phase_cd_files_exist(self) -> None:
        expected = {
            "omarchy-console-session",
            "omarchy-console.desktop",
            "steamos-session-select",
            "steamos-update",
            "steamos-select-branch",
            "omarchy-switch-to-console",
            "org.omarchy.gaming-console.policy",
        }
        self.assertTrue(expected.issubset({p.name for p in SYSTEM.iterdir() if p.is_file()}))

    def test_shell_sources_parse_and_are_executable(self) -> None:
        for name in (
            "omarchy-console-session",
            "steamos-session-select",
            "steamos-update",
            "steamos-select-branch",
            "omarchy-switch-to-console",
        ):
            path = SYSTEM / name
            self.assertTrue(path.stat().st_mode & stat.S_IXUSR, name)
            subprocess.run(["bash", "-n", path], check=True)

    def test_console_desktop_is_a_sibling_without_uwsm(self) -> None:
        text = self.read("omarchy-console.desktop")
        self.assertIn("Name=Gamescope Console\n", text)
        self.assertNotIn("uwsm", text.lower())
        self.assertIn("Exec=/usr/local/bin/omarchy-console-session\n", text)
        self.assertIn("DesktopNames=gamescope\n", text)

    def test_hardware_wrapper_has_exact_session_boundary(self) -> None:
        text = self.read("omarchy-console-session")
        self.assertIn("unset DISPLAY WAYLAND_DISPLAY XDG_DESKTOP_PORTAL_DIR", text)
        self.assertIn("export XDG_SESSION_TYPE=wayland", text)
        self.assertIn("/usr/bin/gamescope --steam --mangoapp --", text)
        self.assertIn("/usr/bin/steam -gamepadui -steamos3", text)
        self.assertIn("systemd-detect-virt", text)
        self.assertIn("omarchy-vm", text)

    def test_switch_helper_contains_fail_closed_and_volatile_contracts(self) -> None:
        text = self.read("omarchy-switch-to-console")
        for required in (
            "PKEXEC_UID",
            "sddm-autologin",
            "seat0",
            "autologin Session is not omarchy.desktop",
            "readonly RUNTIME_DIR=/run/omarchy-gaming-console",
            "readonly PAYLOAD=$RUNTIME_DIR/sddm-oneshot.conf",
            "/etc/sddm.conf.d/zz-omarchy-console-oneshot.conf",
            "flock",
            "systemd-run",
            "systemctl restart sddm",
            "Desktop",
            "gamescope",
        ):
            self.assertIn(required, text)
        self.assertNotIn("killall", text)
        self.assertNotIn("uwsm stop", text)
        self.assertIn("--property=Restart=on-abnormal", text)
        self.assertNotIn("--property=Restart=on-failure", text)
        self.assertIn('rmdir -- "$RUNTIME_DIR"', text)

    def test_polkit_policy_names_only_the_fixed_helper(self) -> None:
        text = self.read("org.omarchy.gaming-console.policy")
        self.assertIn("org.omarchy.gaming-console.switch", text)
        self.assertIn(
            "<annotate key=\"org.freedesktop.policykit.exec.path\">"
            "/usr/local/libexec/omarchy-switch-to-console</annotate>",
            text,
        )
        self.assertNotIn("systemctl", text)
        self.assertNotIn("allow_active>yes", text)


class SteamStubBehaviorTests(unittest.TestCase):
    def test_branch_queries_return_only_fixed_omarchy_channel(self) -> None:
        for query in ("-c", "-l"):
            with self.subTest(query=query):
                result = subprocess.run(
                    [SYSTEM / "steamos-select-branch", query],
                    check=False, text=True, capture_output=True,
                )
                self.assertEqual((0, "Omarchy\n", ""),
                                 (result.returncode, result.stdout, result.stderr))

    def test_fixed_branch_selection_is_quiet_and_refuses_other_requests(self) -> None:
        for args, code in ((["stable"], 0), ([], 1), (["beta"], 1),
                           (["-c", "-l"], 1), (["stable", "extra"], 1),
                           ([""], 1), (["--help"], 1)):
            with self.subTest(args=args):
                result = subprocess.run(
                    [SYSTEM / "steamos-select-branch", *args],
                    check=False, text=True, capture_output=True,
                )
                self.assertEqual(code, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertEqual(code != 0, bool(result.stderr))

    def test_update_reports_no_steam_managed_os_updates_without_output(self) -> None:
        # CachyOS documents these Steam calls. Even unknown requests cannot
        # perform an update or claim that Omarchy package freshness was checked.
        for args in ([], ["check"], ["--supports-duplicate-detection"],
                     ["--enable-duplicate-detection", "check"],
                     ["--enable-duplicate-detection"], ["unexpected", "argument"]):
            with self.subTest(args=args):
                result = subprocess.run(
                    [SYSTEM / "steamos-update", *args],
                    check=False, text=True, capture_output=True,
                )
                self.assertEqual((7, "", ""),
                                 (result.returncode, result.stdout, result.stderr))

    def test_session_select_logs_all_dummy_arguments_and_signals_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            state = pathlib.Path(temp) / "state"
            sleeper = subprocess.Popen(["sleep", "30"])
            env = os.environ | {
                "HOME": temp,
                "XDG_STATE_HOME": str(state),
                "OGC_DUMMY": "1",
                "OGC_DUMMY_SESSION_PID": str(sleeper.pid),
            }
            try:
                result = subprocess.run(
                    [SYSTEM / "steamos-session-select", "plasma", "two words"],
                    env=env,
                    check=False,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                sleeper.wait(timeout=3)
                log = (state / "omarchy-gaming-console" / "steamos-session-select.log").read_text()
                self.assertIn("plasma", log)
                self.assertIn("two\\ words", log)
            finally:
                if sleeper.poll() is None:
                    sleeper.terminate()
                    sleeper.wait(timeout=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
