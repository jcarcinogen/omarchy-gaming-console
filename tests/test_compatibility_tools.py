import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MANAGER = ROOT / "bin/omarchy-gaming-console-compatibility-tools"


class CompatibilityToolTests(unittest.TestCase):
    def fixture_archive(self, root: Path, directory: str, tool_id: str) -> tuple[Path, str]:
        archive = root / f"{directory}.tar.gz"
        manifest = (
            '"compatibilitytools"\n{\n  "compat_tools"\n  {\n'
            f'    "{tool_id}"\n    {{\n      "install_path" "."\n'
            f'      "display_name" "{tool_id}"\n    }}\n  }}\n}}\n'
        ).encode()
        with tarfile.open(archive, "w:gz") as handle:
            for name, data, mode in (
                (f"{directory}/compatibilitytool.vdf", manifest, 0o644),
                (f"{directory}/toolmanifest.vdf", b'"manifest" { "version" "2" }\n', 0o644),
                (f"{directory}/proton", b"#!/bin/sh\nexit 0\n", 0o755),
            ):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = mode
                handle.addfile(info, io.BytesIO(data))
        return archive, hashlib.sha512(archive.read_bytes()).hexdigest()

    def run_manager(self, command: str, *, selected: str = "", preexisting: bool = False, modify: bool = False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            steam = home / ".local/share/Steam"
            tools_dir = steam / "compatibilitytools.d"
            config = steam / "config/config.vdf"
            tools_dir.mkdir(parents=True)
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text('{\n  "CompatToolMapping"\n  {\n' + selected + "\n  }\n}\n")
            config_before = config.read_bytes()
            records = []
            for directory_name, tool_id in (("Test-Cachy-x86_64", "test-cachy"), ("Test-GE-x86_64", "test-ge")):
                archive, digest = self.fixture_archive(root, directory_name, tool_id)
                records.append({
                    "name": tool_id,
                    "release": "fixture",
                    "archive": archive.name,
                    "url": archive.as_uri(),
                    "sha512": digest,
                    "directory": directory_name,
                    "tool_id": tool_id,
                })
            if preexisting:
                existing = tools_dir / records[0]["directory"]
                existing.mkdir()
                (existing / "keep.txt").write_text("pre-existing\n")
            env = os.environ.copy()
            env.update({
                "HOME": str(home),
                "XDG_DATA_HOME": str(home / ".local/share"),
                "XDG_STATE_HOME": str(home / ".local/state"),
                "XDG_CACHE_HOME": str(home / ".cache"),
                "OGC_COMPAT_TESTING": "1",
                "OGC_COMPAT_RELEASES_JSON": json.dumps(records),
            })
            install = subprocess.run([str(MANAGER), "install"], env=env, text=True, capture_output=True, timeout=20)
            if command == "install":
                result = install
            else:
                self.assertEqual(install.returncode, 0, install.stderr)
                if modify:
                    (tools_dir / records[1]["directory"] / "proton").write_text("user change\n")
                result = subprocess.run([str(MANAGER), command], env=env, text=True, capture_output=True, timeout=20)
            state_path = home / ".local/state/omarchy-gaming-console/compatibility-tools.json"
            state = json.loads(state_path.read_text()) if state_path.exists() else None
            snapshot = {
                "result": result,
                "config_unchanged": config.read_bytes() == config_before,
                "dirs": {r["tool_id"]: (tools_dir / r["directory"]).exists() for r in records},
                "preexisting_content": (tools_dir / records[0]["directory"] / "keep.txt").read_text()
                if (tools_dir / records[0]["directory"] / "keep.txt").exists() else None,
                "state": state,
            }
            return snapshot

    def test_visible_setup_and_uninstall_delegate_user_owned_tools_without_root(self):
        setup = (ROOT / "setup").read_text()
        uninstall = (ROOT / "uninstall").read_text()
        self.assertIn('COMPAT_MANAGER=$ROOT/bin/omarchy-gaming-console-compatibility-tools', setup)
        self.assertIn('"$COMPAT_MANAGER" install', setup)
        self.assertIn('(( EUID != 0 ))', setup)
        self.assertIn('COMPAT_MANAGER=$ROOT/bin/omarchy-gaming-console-compatibility-tools', uninstall)
        self.assertIn('"$COMPAT_MANAGER" uninstall', uninstall)
        self.assertIn('(( EUID != 0 ))', uninstall)
        self.assertNotIn('pkexec "$COMPAT_MANAGER"', setup + uninstall)

    def test_install_adds_verified_tools_without_changing_steam_mappings(self):
        snapshot = self.run_manager("install")
        self.assertEqual(snapshot["result"].returncode, 0, snapshot["result"].stderr)
        self.assertTrue(snapshot["config_unchanged"])
        self.assertEqual(snapshot["dirs"], {"test-cachy": True, "test-ge": True})
        self.assertEqual([item["owned"] for item in snapshot["state"]["tools"]], [True, True])

    def test_install_preserves_preexisting_tool_and_records_it_as_external(self):
        snapshot = self.run_manager("install", preexisting=True)
        self.assertEqual(snapshot["result"].returncode, 0, snapshot["result"].stderr)
        self.assertEqual(snapshot["preexisting_content"], "pre-existing\n")
        self.assertFalse(snapshot["state"]["tools"][0]["owned"])
        self.assertTrue(snapshot["state"]["tools"][1]["owned"])

    def test_uninstall_removes_only_unchanged_owned_tools(self):
        snapshot = self.run_manager("uninstall")
        self.assertEqual(snapshot["result"].returncode, 0, snapshot["result"].stderr)
        self.assertTrue(snapshot["config_unchanged"])
        self.assertEqual(snapshot["dirs"], {"test-cachy": False, "test-ge": False})

    def test_uninstall_preserves_selected_or_modified_owned_tools(self):
        selected = '    "123" { "name" "test-cachy" }'
        snapshot = self.run_manager("uninstall", selected=selected, modify=True)
        self.assertEqual(snapshot["result"].returncode, 0, snapshot["result"].stderr)
        self.assertTrue(snapshot["config_unchanged"])
        self.assertEqual(snapshot["dirs"], {"test-cachy": True, "test-ge": True})
        statuses = {item["tool_id"]: item["status"] for item in snapshot["state"]["tools"]}
        self.assertEqual(statuses, {"test-cachy": "preserved-selected", "test-ge": "preserved-modified"})


if __name__ == "__main__":
    unittest.main()
