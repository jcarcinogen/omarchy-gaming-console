"""Rescue-card regressions found by the Phase G real-TTY acceptance."""
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLEANUP = "sudo rmdir -- /run/omarchy-gaming-console"


class RescueCardTests(unittest.TestCase):
    def test_install_and_uninstall_flush_before_reporting_completion(self):
        for name, marker in (("install.sh", 'log "Omarchy Gaming Console engine ${mode} complete."'),
                             ("uninstall.sh", "log 'Omarchy Gaming Console engine uninstall complete.'")):
            text = (ROOT / "system" / name).read_text()
            self.assertIn("/usr/bin/sync", text)
            self.assertLess(text.index("/usr/bin/sync"), text.index(marker))

    def test_setup_and_rescue_document_remove_empty_runtime(self):
        for relative in ("setup", "docs/rescue.md"):
            with self.subTest(path=relative):
                text = (ROOT / relative).read_text()
                self.assertIn(CLEANUP, text)
                self.assertNotIn("rm -rf", text)

    def test_rmdir_preserves_unknown_runtime_content(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = pathlib.Path(directory) / "runtime"
            runtime.mkdir()
            unknown = runtime / "unknown.keep"
            unknown.write_text("preserve")
            result = subprocess.run(["rmdir", "--", str(runtime)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(unknown.read_text(), "preserve")
            unknown.unlink()
            subprocess.run(["rmdir", "--", str(runtime)], check=True)
            self.assertFalse(runtime.exists())


if __name__ == "__main__":
    unittest.main()
