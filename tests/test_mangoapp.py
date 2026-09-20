"""MangoApp is a Console dependency, not a global game injection setting."""
from pathlib import Path
import unittest
from tests.test_phase_f import StatusFixture

ROOT = Path(__file__).resolve().parents[1]


class MangoAppDependencyTests(unittest.TestCase):
    def test_hardware_missing_mangoapp_is_not_ready(self):
        fixture = StatusFixture()
        try:
            fixture.install_engine()
            fixture.command("systemd-detect-virt", "exit 1\n")
            fixture.command("hostnamectl", "printf hardware\n")
            fixture.command("gamescope", "exit 0\n")
            fixture.command("steam", "exit 0\n")
            self.assertEqual(fixture.status()["state"], "incomplete")
            fixture.command("mangoapp", "exit 0\n")
            status = fixture.status()
            self.assertEqual(status["state"], "ready")
            self.assertTrue(status["checks"]["mangoapp"])
        finally:
            fixture.close()

    def test_visible_setup_and_root_preflight_require_mangoapp(self):
        self.assertIn("omarchy-pkg-add mangohud", (ROOT / "setup").read_text())
        self.assertIn("-x /usr/bin/mangoapp", (ROOT / "system/install.sh").read_text())
        self.assertIn("-x /usr/bin/mangoapp", (ROOT / "system/omarchy-console-session").read_text())


if __name__ == "__main__":
    unittest.main()
