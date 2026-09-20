"""Execute a path-relocated wrapper against isolated DRM and binary fixtures.

No real Gamescope, device access, or privileged system writes are performed.
The character-device fixture points to /dev/null; Gamescope is an argv probe.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DrmAdmissionTests(unittest.TestCase):
    def run_wrapper(self, node=None, character=True, gamescope_exit=0, portal_exit=0, display_mode=None, native_kind=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binaries = root / "bin"
            drm = root / "dri"
            binaries.mkdir()
            drm.mkdir()
            if node:
                if character:
                    (drm / node).symlink_to("/dev/null")
                else:
                    (drm / node).write_text("not a device")
            for name, text in {
                "systemd-detect-virt": "#!/bin/sh\nexit 1\n",
                "hostnamectl": "#!/bin/sh\nprintf hardware-test\n",
                "steam": "#!/bin/sh\nexit 99\n",
                "mangoapp": "#!/bin/sh\nexit 0\n",
                "gamescope": "#!/bin/sh\nprintf 'GAMESCOPE_ARG=%s\\n' \"$@\"\nprintf 'MODE_SAVE=%s\\n' \"${GAMESCOPE_MODE_SAVE_FILE:-}\"\n[ -f \"${GAMESCOPE_MODE_SAVE_FILE:-}\" ] && printf 'MODE_FILE_EXISTS=yes\\n'\n" + f"exit {int(gamescope_exit)}\n",
                "systemctl": "#!/bin/sh\nprintf 'PORTAL_STOP=%s\\n' \"$@\"\n" + f"exit {int(portal_exit)}\n",
                "logger": "#!/bin/sh\nprintf 'CLEANUP_WARNING=%s\\n' \"$@\"\n",
            }.items():
                p = binaries / name
                p.write_text(text)
                p.chmod(0o755)
            text = (ROOT / "system/omarchy-console-session").read_text()
            text = text.replace("/usr/bin/", str(binaries) + "/")
            text = text.replace("/dev/dri/", str(drm) + "/")
            script = root / "wrapper"
            script.write_text(text)
            env = os.environ.copy()
            env["HOME"] = str(root)
            env["XDG_CONFIG_HOME"] = str(root / "config")
            if display_mode is not None:
                config = root / "config/omarchy-gaming-console"
                config.mkdir(parents=True)
                (config / "display-mode").write_text(display_mode)
            config = root / "config/omarchy-gaming-console"
            native = config / "modes.cfg"
            if native_kind:
                config.mkdir(parents=True, exist_ok=True)
                if native_kind == "directory":
                    native.mkdir()
                elif native_kind == "fifo":
                    os.mkfifo(native)
                elif native_kind == "symlink":
                    outside = root / "outside"
                    outside.write_text("preserve me\n")
                    native.symlink_to(outside)
                elif native_kind == "dangling":
                    native.symlink_to(root / "absent")
                elif native_kind == "parent_symlink":
                    config.rmdir()
                    outside = root / "outside"
                    outside.mkdir()
                    config.symlink_to(outside, target_is_directory=True)
                else:
                    native.write_text("Fixture display:3840x2160@120 0\n")
            env.pop("OGC_DUMMY", None)
            result = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env, timeout=5)
            from types import SimpleNamespace
            return SimpleNamespace(
                returncode=result.returncode, stdout=result.stdout, stderr=result.stderr,
                native_data=native.read_text() if native.is_file() and not native.is_symlink() else None,
                native_mode=native.stat().st_mode & 0o777 if native.is_file() else None,
            )

    def test_native_mode_save_path_is_namespaced_and_created_before_gamescope(self):
        result = self.run_wrapper("card1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"MODE_SAVE=/.*/config/omarchy-gaming-console/modes.cfg\n")
        self.assertIn("MODE_FILE_EXISTS=yes\n", result.stdout)

    def test_native_mode_file_preserves_existing_user_choices(self):
        result = self.run_wrapper("card1", native_kind="existing")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.native_data, "Fixture display:3840x2160@120 0\n")
        self.assertEqual(self.run_wrapper("card1").native_mode, 0o600)

    def test_native_mode_file_rejects_unsafe_objects(self):
        for kind in ("directory", "fifo", "symlink", "dangling", "parent_symlink"):
            with self.subTest(kind=kind):
                result = self.run_wrapper("card1", native_kind=kind)
                self.assertEqual(result.returncode, 78, result.stdout + result.stderr)
                self.assertNotIn("GAMESCOPE_ARG=", result.stdout)

    def test_steam_output_mode_feedback_uses_multiple_xwayland_servers(self):
        # Gamescope 3.16.28 updates Steam's root output after DRM modesets
        # only when g_nXWaylandCount > 1. One server leaves its mode stale.
        for mode in (None, "3840 2160 120\n"):
            with self.subTest(mode=mode):
                result = self.run_wrapper("card1", display_mode=mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                args = [line.removeprefix("GAMESCOPE_ARG=")
                        for line in result.stdout.splitlines()
                        if line.startswith("GAMESCOPE_ARG=")]
                self.assertIn("--xwayland-count", args)
                index = args.index("--xwayland-count")
                self.assertEqual(args[index + 1], "2")
                self.assertLess(index, args.index("--"))
                self.assertEqual(args.count("--xwayland-count"), 1)

    def test_mangoapp_enabled_for_default_and_explicit_modes(self):
        for mode in (None, "3840 2160 120\n"):
            result = self.run_wrapper("card1", display_mode=mode)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.count("GAMESCOPE_ARG=--mangoapp\n"), 1)

    def test_explicit_user_mode_becomes_fixed_numeric_arguments(self):
        result = self.run_wrapper("card1", display_mode="3840 2160 120\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        for flag, value in (("-W", "3840"), ("-H", "2160"), ("-r", "120")):
            self.assertIn(f"GAMESCOPE_ARG={flag}\nGAMESCOPE_ARG={value}\n", result.stdout)

    def test_invalid_mode_data_refuses_without_launching_gamescope(self):
        cases = ("", "3840 2160 0\n", "1 2160 120\n", "99999 2160 120\n",
                 "3840 2160 1001\n", "3840 2160 120; touch /tmp/no\n",
                 "$(id) 2160 120\n", "3840 2160 120\nextra\n", "3840 2160 120\n\n",
                 "03840 2160 120\n", "9" * 256)
        for mode in cases:
            with self.subTest(mode=mode):
                result = self.run_wrapper("card1", display_mode=mode)
                self.assertEqual(result.returncode, 78, result.stdout + result.stderr)
                self.assertNotIn("GAMESCOPE_ARG", result.stdout)

    def test_missing_mode_keeps_gamescope_defaults(self):
        result = self.run_wrapper("card1")
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("GAMESCOPE_ARG=-r\n", result.stdout)
        self.assertNotIn("GAMESCOPE_ARG=-W\n", result.stdout)

    def test_console_teardown_stops_stale_portal_after_gamescope(self):
        result = self.run_wrapper("card1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PORTAL_STOP=--user", result.stdout)
        self.assertIn("PORTAL_STOP=stop", result.stdout)
        self.assertIn("PORTAL_STOP=xdg-desktop-portal.service", result.stdout)
        self.assertGreater(result.stdout.index("PORTAL_STOP="), result.stdout.index("GAMESCOPE_ARG="))

    def test_failed_gamescope_still_cleans_portal_and_preserves_exit(self):
        result = self.run_wrapper("card1", gamescope_exit=7)
        self.assertEqual(result.returncode, 7)
        self.assertIn("PORTAL_STOP=xdg-desktop-portal.service", result.stdout)

    def test_failed_portal_cleanup_logs_without_hiding_gamescope_result(self):
        result = self.run_wrapper("card1", gamescope_exit=7, portal_exit=1)
        self.assertEqual(result.returncode, 7)
        self.assertIn("CLEANUP_WARNING=", result.stdout)

    def test_card0_and_multi_digit_primary_nodes_are_supported(self):
        for node in ("card0", "card10"):
            with self.subTest(node=node):
                self.assertEqual(self.run_wrapper(node).returncode, 0)

    def test_missing_primary_or_render_only_refuses(self):
        for node in (None, "renderD128"):
            with self.subTest(node=node):
                result = self.run_wrapper(node)
                self.assertEqual(result.returncode, 69)
                self.assertNotIn("GAMESCOPE_ARG", result.stdout)

    def test_regular_file_named_card_is_not_a_drm_device(self):
        result = self.run_wrapper("card1", character=False)
        self.assertEqual(result.returncode, 69)
        self.assertNotIn("GAMESCOPE_ARG", result.stdout)

    def test_card1_without_card0_launches_gamescope(self):
        result = self.run_wrapper("card1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("GAMESCOPE_ARG=--steam", result.stdout)
        self.assertIn("GAMESCOPE_ARG=-gamepadui", result.stdout)
        self.assertIn("GAMESCOPE_ARG=-steamos3", result.stdout)


if __name__ == "__main__":
    unittest.main()
