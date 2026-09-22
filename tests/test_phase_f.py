#!/usr/bin/env python3
"""Milestone 4 Phase F CLI/status and Quattro source contracts."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import pathlib
import runpy
import shutil
import stat
import subprocess
import tempfile
import unittest
from typing import Any
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
CLI = ROOT / "bin" / "omarchy-gaming-console"

DESTINATIONS = {
    "omarchy-console-session": "/usr/local/bin/omarchy-console-session",
    "steamos-session-select": "/usr/local/bin/steamos-session-select",
    "steamos-update": "/usr/local/bin/steamos-update",
    "steamos-update-polkit": "/usr/bin/steamos-polkit-helpers/steamos-update",
    "steamos-select-branch": "/usr/local/bin/steamos-select-branch",
    "omarchy-switch-to-console": "/usr/local/libexec/omarchy-switch-to-console",
    "omarchy-console.desktop": "/usr/local/share/wayland-sessions/omarchy-console.desktop",
    "org.omarchy.gaming-console.policy": "/usr/share/polkit-1/actions/org.omarchy.gaming-console.policy",
}
ROUTE = "/etc/sddm.conf.d/zz-omarchy-console-oneshot.conf"
PAYLOAD = "/run/omarchy-gaming-console/sddm-oneshot.conf"


class StatusFixture:
    def __init__(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.bin = self.root / "usr/bin"
        self.bin.mkdir(parents=True)
        self.write("usr/local/share/wayland-sessions/omarchy.desktop", "[Desktop Entry]\nName=Omarchy\nExec=uwsm start -S -F\n", 0o644)
        self.write("etc/sddm.conf.d/autologin.conf", "[Autologin]\nUser=testuser\nSession=omarchy.desktop\n", 0o644)
        self.command("pacman", "printf '%s\\n' 'try-omarchy-runtime 4.0.3-1'\n")
        self.command("pkaction", "printf '%s\\n' 'org.omarchy.gaming-console.switch'\n")
        self.command("systemd-detect-virt", "printf '%s\\n' qemu\n")
        self.command("hostnamectl", "printf '%s\\n' omarchy-vm\n")
        self.command("Hyprland", "exit 0\n")
        self.command("foot", "exit 0\n")

    def close(self) -> None:
        self.temp.cleanup()

    def path(self, absolute: str) -> pathlib.Path:
        return self.root / absolute.lstrip("/")

    def write(self, relative: str, content: str, mode: int = 0o755) -> pathlib.Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        path.chmod(mode)
        return path

    def command(self, name: str, body: str) -> None:
        self.write(f"usr/bin/{name}", f"#!/usr/bin/env bash\n{body}", 0o755)

    def install_engine(self) -> None:
        for source, destination in DESTINATIONS.items():
            if source == "steamos-update-polkit":
                source = "steamos-update"
            target = self.path(destination)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SYSTEM / source, target)
            target.chmod(0o755 if destination.endswith(("session", "update", "branch", "console")) or "/bin/" in destination or "/libexec/" in destination else 0o644)
        route = self.path(ROUTE)
        route.parent.mkdir(parents=True, exist_ok=True)
        route.symlink_to(PAYLOAD)
        state_dir = self.path("/var/lib/omarchy-gaming-console")
        state_dir.mkdir(parents=True)
        state_dir.chmod(0o700)
        manifest = SYSTEM / "ownership.manifest"
        lines = [
            "state_version\t2",
            "project_version\t0.0.0",
            f"manifest_sha256\t{hashlib.sha256(manifest.read_bytes()).hexdigest()}",
            "install_phase\tcomplete",
            "directory_created\t/usr/bin/steamos-polkit-helpers\t1",
        ]
        with manifest.open(newline="") as handle:
            for kind, source, destination, mode, owner, group, target in csv.reader(handle, delimiter="\t"):
                if kind.startswith("#"):
                    continue
                recorded = hashlib.sha256((SYSTEM / source).read_bytes()).hexdigest() if kind == "file" else target
                lines.append(f"object\t{kind}\t{destination}\t{mode}\t{owner}\t{group}\t{recorded}")
        self.write("var/lib/omarchy-gaming-console/install-state.tsv", "\n".join(lines) + "\n", 0o600)

    def status(self) -> dict[str, Any]:
        env = os.environ | {
            "OGC_STATUS_TESTING": "1",
            "OGC_STATUS_TEST_ROOT": str(self.root),
        }
        result = subprocess.run(
            [CLI, "status", "--json"],
            env=env,
            check=False,
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            raise AssertionError(f"status failed rc={result.returncode}: {result.stderr}")
        return json.loads(result.stdout)


class PhaseFStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = StatusFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def assert_schema(self, payload: dict[str, Any], state: str) -> None:
        self.assertEqual(1, payload["schema"])
        self.assertEqual(state, payload["state"])
        self.assertIsInstance(payload["omarchy"], str)
        self.assertIsInstance(payload["hostname"], str)
        self.assertIsInstance(payload["reasons"], list)
        self.assertIsInstance(payload["owned"], list)
        checks = payload["checks"]
        self.assertIsInstance(checks, dict)
        for name in (
            "omarchy_desktop",
            "console_desktop",
            "autologin_untouched",
            "oneshot_absent_at_rest",
            "steamos_session_select",
            "gamescope",
            "steam",
            "embedded_env_ok",
            "engine_helper",
        ):
            self.assertIn(name, checks)
            self.assertIsInstance(checks[name], bool)

    def test_not_installed_when_no_engine_objects_exist(self) -> None:
        payload = self.fixture.status()
        self.assert_schema(payload, "not_installed")
        self.assertFalse(payload["checks"]["console_desktop"])
        self.assertFalse(payload["checks"]["engine_helper"])

    def test_status_detects_the_package_owned_engine_helper(self) -> None:
        self.fixture.write("usr/lib/omarchy-gaming-console/engine-manager", "#!/bin/sh\nexit 0\n", 0o755)
        payload = self.fixture.status()
        self.assertTrue(payload["checks"]["engine_helper"])

    def test_incomplete_when_only_part_of_engine_exists(self) -> None:
        target = self.fixture.path(DESTINATIONS["omarchy-console.desktop"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SYSTEM / "omarchy-console.desktop", target)
        target.chmod(0o644)
        payload = self.fixture.status()
        self.assert_schema(payload, "incomplete")

    def test_ready_on_exact_vm_dummy_boundary_without_claiming_gamescope(self) -> None:
        self.fixture.install_engine()
        payload = self.fixture.status()
        self.assert_schema(payload, "ready")
        self.assertFalse(payload["checks"]["gamescope"])
        self.assertFalse(payload["checks"]["steam"])
        self.assertTrue(payload["checks"]["vm_dummy_boundary"])
        self.assertTrue(any("dummy" in reason.lower() for reason in payload["reasons"]))

    def test_update_required_when_complete_owned_tree_differs_from_source(self) -> None:
        self.fixture.install_engine()
        target = self.fixture.path(DESTINATIONS["steamos-update"])
        target.write_text("#!/bin/sh\nexit 0\n")
        target.chmod(0o755)
        payload = self.fixture.status()
        self.assert_schema(payload, "update_required")

    def test_incomplete_when_exact_legacy_local_helper_lacks_the_polkit_path(self) -> None:
        self.fixture.install_engine()
        self.fixture.path(DESTINATIONS["steamos-update-polkit"]).unlink()
        payload = self.fixture.status()
        self.assert_schema(payload, "incomplete")

    def test_unsafe_when_shared_updater_directory_is_a_symlink(self) -> None:
        self.fixture.install_engine()
        helper = self.fixture.path(DESTINATIONS["steamos-update-polkit"])
        helper.unlink()
        helper.parent.rmdir()
        helper.parent.symlink_to(self.fixture.path("usr/local/bin"), target_is_directory=True)
        payload = self.fixture.status()
        self.assert_schema(payload, "unsafe")

    def test_status_leaves_private_state_validation_to_root_lifecycle(self) -> None:
        self.fixture.install_engine()
        state = self.fixture.path("/var/lib/omarchy-gaming-console/install-state.tsv")
        duplicate = next(line for line in state.read_text().splitlines() if line.startswith("object\t"))
        state.write_text(state.read_text() + duplicate + "\n")
        state.chmod(0o600)
        payload = self.fixture.status()
        self.assert_schema(payload, "ready")

    def test_ready_status_does_not_read_root_only_installation_state(self) -> None:
        self.fixture.install_engine()
        environment = {
            "OGC_STATUS_TESTING": "1",
            "OGC_STATUS_TEST_ROOT": str(self.fixture.root),
        }
        with mock.patch.dict(os.environ, environment, clear=False):
            namespace = runpy.run_path(str(CLI))
        original_lstat = pathlib.Path.lstat

        def deny_private_state(path: pathlib.Path, *args: object, **kwargs: object) -> os.stat_result:
            if path.name == "install-state.tsv":
                raise PermissionError(13, "Permission denied", str(path))
            return original_lstat(path, *args, **kwargs)

        with mock.patch.dict(os.environ, environment, clear=False):
            with mock.patch.object(pathlib.Path, "lstat", deny_private_state):
                payload = namespace["status_payload"]()
        self.assert_schema(payload, "ready")

    def test_unsafe_when_stock_autologin_is_hijacked(self) -> None:
        self.fixture.install_engine()
        self.fixture.write("etc/sddm.conf.d/autologin.conf", "[Autologin]\nUser=testuser\nSession=omarchy-console.desktop\n", 0o644)
        payload = self.fixture.status()
        self.assert_schema(payload, "unsafe")

    def test_unsupported_when_omarchy_four_is_absent(self) -> None:
        self.fixture.command("pacman", "exit 1\n")
        payload = self.fixture.status()
        self.assert_schema(payload, "unsupported")

    def test_switch_fails_closed_before_confirmation_when_not_ready(self) -> None:
        env = os.environ | {
            "OGC_STATUS_TESTING": "1",
            "OGC_STATUS_TEST_ROOT": str(self.fixture.root),
            "OGC_CLI_TEST_TTY": "1",
        }
        result = subprocess.run(
            [CLI, "switch"],
            env=env,
            input="yes\n",
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(78, result.returncode)
        self.assertIn("Refusing to switch while status is not_installed", result.stderr)


class PhaseFSourceContracts(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text()

    def test_cli_is_executable_and_accepts_only_fixed_subcommands(self) -> None:
        self.assertTrue(CLI.is_file())
        self.assertTrue(CLI.stat().st_mode & stat.S_IXUSR)
        result = subprocess.run([CLI, "arbitrary", "/tmp/x"], check=False, text=True, capture_output=True)
        self.assertEqual(64, result.returncode)
        text = CLI.read_text()
        for subcommand in ("status", "setup", "switch", "repair", "uninstall", "helper-instructions"):
            self.assertIn(subcommand, text)
        namespace = runpy.run_path(str(CLI))
        self.assertEqual(
            "This will close the Omarchy desktop and any open applications. Save your work first.",
            namespace["SWITCH_WARNING"],
        )
        self.assertIn("/usr/local/libexec/omarchy-switch-to-console", text)
        self.assertNotIn("shell=True", text)

    def test_helper_instructions_point_to_the_one_copy_readme_step(self) -> None:
        result = subprocess.run(
            [CLI, "helper-instructions"],
            env=os.environ | {"OGC_CLI_TEST_TTY": "1"},
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(0, result.returncode)
        self.assertIn("Engine Helper Required", result.stdout)
        self.assertIn(
            "https://github.com/jcarcinogen/omarchy-gaming-console#first-time-setup",
            result.stdout,
        )
        self.assertIn("Copy the single terminal block", result.stdout)

    def test_embedded_environment_contract_requires_two_xwaylands(self) -> None:
        text = CLI.read_text()
        self.assertIn('"/usr/bin/gamescope --steam --mangoapp --xwayland-count 2"', text)

    def test_visible_launcher_detaches_all_standard_streams(self) -> None:
        namespace = runpy.run_path(str(CLI))
        popen = mock.Mock()
        with mock.patch.object(namespace["pathlib"].Path, "is_file", return_value=True):
            with mock.patch.object(namespace["subprocess"], "Popen", popen):
                self.assertEqual(0, namespace["launch_visible"]([str(CLI), "switch"]))
        _, kwargs = popen.call_args
        self.assertTrue(kwargs["start_new_session"])
        self.assertIs(subprocess.DEVNULL, kwargs["stdin"])
        self.assertIs(subprocess.DEVNULL, kwargs["stdout"])
        self.assertIs(subprocess.DEVNULL, kwargs["stderr"])

    def test_manifest_has_exact_phase_f_kinds_and_entry_points(self) -> None:
        manifest = json.loads(self.read("manifest.json"))
        self.assertEqual(["bar-widget", "overlay", "service"], manifest["kinds"])
        self.assertEqual("right", manifest["barWidget"]["defaultSection"])
        self.assertEqual(
            {"barWidget": "BarWidget.qml", "overlay": "Overlay.qml", "service": "Service.qml"},
            manifest["entryPoints"],
        )

    def test_bar_widget_is_proxy_only(self) -> None:
        text = self.read("BarWidget.qml")
        self.assertIn("Style.bar.statusSlot", text)
        self.assertIn("shell.toggle", text)
        self.assertNotIn("Loader", text)
        self.assertNotIn("PanelWindow", text)
        self.assertNotIn("IpcHandler", text)

    def test_service_is_sole_ipc_owner_and_uses_generation_guard(self) -> None:
        service = self.read("Service.qml")
        overlay = self.read("Overlay.qml")
        bar = self.read("BarWidget.qml")
        self.assertIn("import Quickshell.Io", service)
        self.assertEqual(1, service.count("IpcHandler"))
        self.assertNotIn("IpcHandler", overlay)
        self.assertNotIn("IpcHandler", bar)
        self.assertIn("generation", service)
        self.assertIn("status", service)
        self.assertIn("--json", service)
        self.assertNotIn("bash", service)
        self.assertNotIn("required property", service)

    def test_overlay_is_single_panel_owner_with_escape_paths_and_fixed_actions(self) -> None:
        text = self.read("Overlay.qml")
        self.assertEqual(1, text.count("PanelWindow"))
        self.assertIn("PanelKeyCatcher", text)
        self.assertIn('sequence: "Escape"', text)
        for label in (
            "Install Game Mode",
            "View what will change",
            "Cancel",
            "Switch to Console",
            "Check setup",
            "Repair setup",
            "Uninstall Game Mode",
            "Engine Helper Required",
            "Open installation instructions",
        ):
            self.assertIn(label, text)
        self.assertIn('root.run("helperInstructions")', text)
        self.assertIn('statusPayload.checks.engine_helper === false', text)

        service = self.read("Service.qml")
        self.assertIn('"helperInstructions": [root.cliPath, "helper-instructions"]', service)

    def test_overlay_hides_only_the_redundant_ready_reason(self) -> None:
        text = self.read("Overlay.qml")
        self.assertIn('readonly property string redundantReadyReason: "The complete system engine is installed and safe."', text)
        self.assertIn("readonly property bool hasOnlyRedundantReadyReason:", text)
        self.assertIn("!root.hasOnlyRedundantReadyReason", text)

    def test_qml_process_commands_are_argv_arrays_without_shell_assembly(self) -> None:
        for relative in ("Service.qml", "Overlay.qml", "BarWidget.qml"):
            text = self.read(relative)
            self.assertNotIn("bash -c", text)
            self.assertNotIn("[\"bash\", \"-c\"", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
