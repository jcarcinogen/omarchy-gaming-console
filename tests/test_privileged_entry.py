#!/usr/bin/env python3
"""Privileged setup must not execute or reopen a user-writable checkout."""

from __future__ import annotations

import hashlib
import os
import pathlib
import runpy
import signal
import stat
import subprocess
import tempfile
import unittest
from typing import Any
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"


class PrivilegedEntryContract(unittest.TestCase):
    def load_engine_manager_template(self) -> dict[str, Any]:
        source = (ROOT / "packaging" / "engine-manager.py.in").read_text()
        source = source.replace("@REVIEWED_COMMIT@", "a" * 40)
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
            handle.write(source)
            path = pathlib.Path(handle.name)
        try:
            return runpy.run_path(str(path))
        finally:
            path.unlink()

    def test_visible_entry_points_do_not_pkexec_checkout_scripts(self) -> None:
        setup = (ROOT / "setup").read_text()
        uninstall = (ROOT / "uninstall").read_text()
        for text in (setup, uninstall):
            self.assertNotIn('pkexec "$INSTALLER"', text)
            self.assertNotIn('pkexec "$UNINSTALLER"', text)
            self.assertNotIn("pkexec \"$ROOT/", text)
            self.assertIn("enter-privileged", text)
        entry = (SYSTEM / "enter-privileged").read_text()
        helper = "/usr/lib/omarchy-gaming-console/engine-manager"
        self.assertIn(f'readonly HELPER={helper}', entry)
        self.assertIn('pkexec "$HELPER" "$mode"', entry)
        self.assertNotIn("privileged-bootstrap.py", entry)
        self.assertNotIn("python3", entry)
        self.assertNotIn("curl", entry)
        self.assertNotIn("git", entry)
        self.assertNotIn("http", entry)
        self.assertNotIn("/run/", entry)
        self.assertNotIn("install.sh", entry)
        self.assertNotIn("uninstall.sh", entry)

    def test_package_helper_pins_one_reviewed_commit_outside_the_plugin(self) -> None:
        template = (ROOT / "packaging" / "engine-manager.py.in").read_text()
        self.assertIn('REVIEWED_COMMIT = "@REVIEWED_COMMIT@"', template)
        self.assertIn('ORIGIN = "https://github.com/jcarcinogen/omarchy-gaming-console.git"', template)
        self.assertIn("len(REVIEWED_COMMIT) != 40", template)
        self.assertIn('run_git("fetch", "--quiet", "--depth", "1", "origin", REVIEWED_COMMIT', template)
        self.assertIn('head != REVIEWED_COMMIT', template)
        self.assertNotIn("ls-remote", template)
        self.assertNotIn("sys.argv[2]", template)

        pkgbuild = (ROOT / "packaging" / "PKGBUILD").read_text()
        manager_digest = hashlib.sha256((ROOT / "packaging" / "engine-manager.py.in").read_bytes()).hexdigest()
        self.assertIn("pkgname=omarchy-gaming-console-engine", pkgbuild)
        self.assertIn(f"sha256sums=('{manager_digest}'", pkgbuild)
        self.assertIn("install -Dm755", pkgbuild)
        self.assertNotIn("'SKIP'", pkgbuild)
        self.assertIn('fetch --quiet --depth 1 origin "$REVIEWED_COMMIT"', pkgbuild)
        self.assertIn('reviewed-commit "$pkgdir/usr/share/omarchy-gaming-console/reviewed-commit"', pkgbuild)
        self.assertIn("/usr/lib/omarchy-gaming-console/engine-manager", pkgbuild)
        self.assertIn("/usr/share/polkit-1/actions/org.omarchy.gaming-console.engine.policy", pkgbuild)

    def test_package_helper_terminates_and_reaps_timed_out_git_process_group(self) -> None:
        namespace = self.load_engine_manager_template()
        process = mock.Mock(pid=4321, returncode=None)
        process.communicate.side_effect = [
            subprocess.TimeoutExpired(["git", "fetch"], 1),
            ("", ""),
        ]
        with mock.patch.object(namespace["subprocess"], "Popen", return_value=process) as popen:
            with mock.patch.object(namespace["os"], "killpg") as killpg:
                with self.assertRaises(SystemExit) as raised:
                    namespace["git"]("fetch", "origin", "a" * 40, timeout_seconds=1)
        self.assertEqual(78, raised.exception.code)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        killpg.assert_called_once_with(4321, signal.SIGTERM)
        self.assertEqual(2, process.communicate.call_count)

    def test_package_helper_removes_root_stage_after_any_git_failure(self) -> None:
        namespace = self.load_engine_manager_template()
        with tempfile.TemporaryDirectory() as temporary:
            stage = pathlib.Path(temporary) / "stage"
            stage.mkdir()
            with mock.patch.object(namespace["tempfile"], "mkdtemp", return_value=str(stage)):
                with mock.patch.object(namespace["os"], "chown"):
                    with mock.patch.object(namespace["time"], "monotonic", return_value=0.0):
                        with mock.patch.dict(
                            namespace["fetch_reviewed_snapshot"].__globals__,
                            {"git": mock.Mock(side_effect=RuntimeError("fetch failed"))},
                        ):
                            with self.assertRaisesRegex(RuntimeError, "fetch failed"):
                                namespace["fetch_reviewed_snapshot"]()
            self.assertFalse(stage.exists())

    def test_polkit_policy_authorizes_only_the_root_owned_helper(self) -> None:
        policy = (ROOT / "packaging" / "org.omarchy.gaming-console.engine.policy").read_text()
        self.assertIn("/usr/lib/omarchy-gaming-console/engine-manager", policy)
        self.assertNotIn("/bin/bash", policy)
        self.assertNotIn("/usr/bin/python", policy)

    def test_engine_scripts_refuse_to_run_outside_a_sealed_stage(self) -> None:
        install = (SYSTEM / "install.sh").read_text()
        uninstall = (SYSTEM / "uninstall.sh").read_text()
        self.assertIn("== /run && ${script_dir##*/} == omarchy-gaming-console-stage.", install)
        self.assertLess(install.index("require_sealed_stage"), install.index("[[ -f $MANIFEST"))
        self.assertLess(uninstall.index("require_sealed_stage"), uninstall.index("[[ -f $STATE_FILE"))


class SealedSnapshotTests(unittest.TestCase):
    def test_checkout_digest_matches_the_reviewed_payload(self) -> None:
        from importlib.machinery import SourceFileLoader

        module = SourceFileLoader(
            "ogc_privileged_bootstrap",
            str(SYSTEM / "privileged-bootstrap.py"),
        ).load_module()
        self.assertEqual(module.payload_digest(SYSTEM), module.EXPECTED)

    def test_nofollow_read_rejects_a_replaced_symlink(self) -> None:
        from importlib.machinery import SourceFileLoader

        module = SourceFileLoader(
            "ogc_privileged_bootstrap",
            str(SYSTEM / "privileged-bootstrap.py"),
        ).load_module()
        with tempfile.TemporaryDirectory() as temporary:
            source = pathlib.Path(temporary) / "system"
            source.mkdir()
            target = pathlib.Path(temporary) / "swapped"
            target.write_text("attacker\n")
            (source / "ownership.manifest").symlink_to(target)
            dir_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                with self.assertRaises(module.Refused):
                    module.read_nofollow(dir_fd, "ownership.manifest")
            finally:
                os.close(dir_fd)

    def test_snapshot_keeps_bytes_read_before_a_later_replacement(self) -> None:
        from importlib.machinery import SourceFileLoader

        module = SourceFileLoader(
            "ogc_privileged_bootstrap",
            str(SYSTEM / "privileged-bootstrap.py"),
        ).load_module()
        with tempfile.TemporaryDirectory() as temporary:
            temp = pathlib.Path(temporary)
            source = temp / "system"
            source.mkdir()
            for name, digest in module.EXPECTED.items():
                (source / name).write_bytes((SYSTEM / name).read_bytes())
            payload = module.read_payload(source)
            (source / "ownership.manifest").write_text("replaced after the privileged read\n")
            stage = module.seal_snapshot(payload, temp / "run")
            self.assertTrue(stage.name.startswith("omarchy-gaming-console-stage."))
            self.assertEqual((SYSTEM / "ownership.manifest").read_bytes(), (stage / "ownership.manifest").read_bytes())
            mode = stat.S_IMODE((stage / "ownership.manifest").stat().st_mode)
            self.assertEqual(0, mode & 0o022)
            self.assertFalse((stage / "ownership.manifest").is_symlink())


if __name__ == "__main__":
    unittest.main(verbosity=2)
