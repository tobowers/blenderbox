"""Standalone executable contracts; native signing is covered by integration."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from blenderbox.macos import headless_binary


def native_command(args, **options):
    if args[0] == "/bin/cp":
        shutil.copy2(args[-2], args[-1])
    return subprocess.CompletedProcess(args, 0)


class HeadlessExecutable(unittest.TestCase):
    @patch("blenderbox.macos.subprocess.run", side_effect=native_command)
    def test_executable_is_separate_and_concurrent_setup_is_idempotent(self, run):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            contents = root / "Blender.app" / "Contents"
            (contents / "MacOS").mkdir(parents=True)
            binary = contents / "MacOS" / "Blender"
            binary.write_text("fake executable")
            (contents / "Resources").mkdir()
            original = plistlib.dumps({"CFBundleIdentifier": "org.blenderfoundation.blender",
                                      "CFBundleExecutable": "Blender", "CFBundleVersion": "1",
                                      "CFBundleDocumentTypes": [{"CFBundleTypeRole": "Editor"}],
                                      "UTExportedTypeDeclarations": [], "UTImportedTypeDeclarations": []})
            (contents / "Info.plist").write_bytes(original)
            with ThreadPoolExecutor(max_workers=4) as pool:
                paths = list(pool.map(lambda _: headless_binary(binary, root / "state"), range(4)))
            self.assertEqual(len(set(paths)), 1)
            target = Path(paths[0])
            self.assertNotEqual(target, binary)
            self.assertFalse(target.is_symlink())
            self.assertNotEqual(target.stat().st_ino, binary.stat().st_ino)
            self.assertEqual(target.read_bytes(), binary.read_bytes())
            self.assertFalse((target.parent.parent / "Info.plist").exists())
            self.assertFalse(any(part.endswith(".app") for part in target.parts))
            self.assertEqual((target.parent.parent / "Resources").resolve(), contents / "Resources")
            self.assertEqual((contents / "Info.plist").read_bytes(), original)
            # Forks can reuse a standalone cached executable without nesting.
            self.assertEqual(headless_binary(target, root / "state"), str(target))
            self.assertEqual(run.call_count, 2, "Repeated setup must not copy or sign again")
            (contents / "Info.plist").write_bytes(plistlib.dumps({"CFBundleVersion": "2"}))
            self.assertNotEqual(headless_binary(binary, root / "state"), str(target))

    def test_standalone_executable_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory).resolve() / "blender"
            binary.touch()
            self.assertEqual(headless_binary(binary, Path(directory) / "state"), str(binary))
            self.assertFalse((Path(directory) / "state").exists())
