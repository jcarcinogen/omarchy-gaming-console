#!/usr/bin/env python3
"""Privileged setup must not execute or reopen a user-writable checkout."""

from __future__ import annotations

import os
import pathlib
import stat
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"


class PrivilegedEntryContract(unittest.TestCase):
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
        self.assertIn('git("fetch", "--depth", "1", "origin", REVIEWED_COMMIT', template)
        self.assertIn('head != REVIEWED_COMMIT', template)
        self.assertNotIn("ls-remote", template)
        self.assertNotIn("sys.argv[2]", template)

        pkgbuild = (ROOT / "packaging" / "PKGBUILD").read_text()
        self.assertIn("pkgname=omarchy-gaming-console-engine", pkgbuild)
        self.assertIn("install -Dm755", pkgbuild)
        self.assertNotIn("'SKIP'", pkgbuild)
        self.assertIn('fetch --quiet --depth 1 origin "$REVIEWED_COMMIT"', pkgbuild)
        self.assertIn('reviewed-commit "$pkgdir/usr/share/omarchy-gaming-console/reviewed-commit"', pkgbuild)
        self.assertIn("/usr/lib/omarchy-gaming-console/engine-manager", pkgbuild)
        self.assertIn("/usr/share/polkit-1/actions/org.omarchy.gaming-console.engine.policy", pkgbuild)

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
