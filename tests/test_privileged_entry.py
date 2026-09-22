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
        self.assertNotIn("privileged-bootstrap.py", entry)
        self.assertNotIn("python3 -I -c", entry)
        self.assertNotIn("O_NOFOLLOW", entry)
        self.assertNotIn("pkexec \"$INSTALLER\"", entry)
        self.assertNotIn("pkexec \"$UNINSTALLER\"", entry)
        self.assertNotIn("install.sh", entry)
        self.assertNotIn("uninstall.sh", entry)
        self.assertIn("https://raw.githubusercontent.com/jcarcinogen/omarchy-gaming-console/main/system/trust-fetch.py", entry)
        self.assertIn("https://api.github.com/repos/jcarcinogen/omarchy-gaming-console/contents/system/trust-fetch.py?ref=main", entry)
        self.assertIn("/run/omarchy-gaming-console-trust-fetch.py", entry)
        self.assertIn("git hash-object", entry)
        self.assertLess(entry.index("git hash-object"), entry.index('python3 -I "$TRUST"'))

    def test_trust_fetch_is_authenticated_outside_the_checkout(self) -> None:
        import importlib.util

        text = (SYSTEM / "trust-fetch.py").read_text()
        self.assertIn("https://github.com/jcarcinogen/omarchy-gaming-console.git", text)
        self.assertIn("ls-remote", text)
        self.assertLess(text.index("ls-remote"), text.index("execv"))
        self.assertNotIn("EXPECTED", text)
        spec = importlib.util.spec_from_file_location("trust_fetch", SYSTEM / "trust-fetch.py")
        if spec is None or spec.loader is None:
            self.fail("trust-fetch could not be loaded")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertFalse(module.authenticated_copy(str(SYSTEM / "trust-fetch.py"), 0, 0o100644, False))
        self.assertFalse(module.authenticated_copy(module.AUTHENTICATED_COPY, 1000, 0o100644, False))
        self.assertFalse(module.authenticated_copy(module.AUTHENTICATED_COPY, 0, 0o100644, True))
        self.assertFalse(module.authenticated_copy(module.AUTHENTICATED_COPY, 0, 0o100666, False))
        self.assertTrue(module.authenticated_copy(module.AUTHENTICATED_COPY, 0, 0o100644, False))

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
