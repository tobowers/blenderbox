"""Run macOS Blender as a standalone executable outside its desktop app bundle."""
import fcntl
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile

from .protocol import BoxError


def headless_binary(executable, root):
    """Clone the executable and link resources; leave standalone binaries alone.

    A symlink to the executable can still identify with the desktop app. Use
    a distinct executable inode and no Info.plist or .app directory, so a
    windowless worker cannot claim the desktop bundle's identity.
    """
    binary = Path(executable).resolve()
    contents = binary.parent.parent
    if binary.parent.name != "MacOS" or contents.name != "Contents":
        return str(binary)
    source_plist = contents / "Info.plist"
    if not source_plist.is_file():
        return str(binary)
    try:
        stat = binary.stat()
        fingerprint = f"{binary}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}".encode()
        digest = hashlib.sha256(fingerprint + source_plist.read_bytes()).hexdigest()[:16]
        cache = root / "engines"
        cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        engine = cache / digest
        target = engine / "MacOS" / binary.name
        with (cache / "setup.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if target.is_file():
                return str(target)
            temporary = Path(tempfile.mkdtemp(prefix=".engine-", dir=cache))
            try:
                (temporary / "MacOS").mkdir()
                copied_binary = temporary / "MacOS" / binary.name
                # APFS clones share data blocks. Other filesystems use a normal copy.
                cloned = subprocess.run(["/bin/cp", "-c", str(binary), str(copied_binary)],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
                if cloned.returncode:
                    shutil.copy2(binary, copied_binary)
                # The vendor signature seals the original bundle's Info.plist.
                # Sign only this relocated copy, retaining its runtime flags and
                # entitlements; the installed desktop app is never modified.
                subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-",
                                "--preserve-metadata=entitlements,flags,runtime",
                                "--identifier", f"org.blenderbox.cli.{digest}", str(copied_binary)],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
                for child in contents.iterdir():
                    if child.name not in {"Info.plist", "MacOS", "PkgInfo", "_CodeSignature"}:
                        (temporary / child.name).symlink_to(child)
                for child in binary.parent.iterdir():
                    if child.name != binary.name:
                        (temporary / "MacOS" / child.name).symlink_to(child)
                if engine.exists():
                    shutil.rmtree(engine)
                temporary.rename(engine)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        return str(target)
    except (OSError, subprocess.SubprocessError) as exc:
        raise BoxError("engine_setup", f"Cannot prepare standalone Blender executable: {exc}") from exc
