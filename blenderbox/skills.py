"""Offline discovery and installation of package-bundled agent skills."""
from importlib import resources
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from .protocol import BoxError


def bundle_root():
    try:
        return resources.files("blenderbox_skills")
    except ModuleNotFoundError:
        # Support running directly from the checkout as well as installed wheels.
        return Path(__file__).resolve().parent.parent / "skills"


def bundled_files(name):
    root = bundle_root()
    if not any(p.name == name and p.is_dir() and p.joinpath("SKILL.md").is_file() for p in root.iterdir()):
        raise BoxError("unknown_skill", f"No bundled skill named {name!r}; run blenderbox skills list")
    skill = root.joinpath(name)
    files = {}

    def read(directory, prefix=""):
        for path in directory.iterdir():
            relative = prefix + path.name
            if path.is_dir():
                read(path, relative + "/")
            elif path.is_file():
                files[relative] = path.read_bytes()

    read(skill)
    return files


def list_skills():
    found = []
    for path in sorted(bundle_root().iterdir(), key=lambda p: p.name):
        if not path.is_dir() or not path.joinpath("SKILL.md").is_file():
            continue
        text = path.joinpath("SKILL.md").read_text(encoding="utf-8")
        frontmatter = text.split("---", 2)[1]
        description = next((line.partition(":")[2].strip().strip('"\'') for line in frontmatter.splitlines()
                            if line.startswith("description:")), "")
        found.append({"name": path.name, "description": description,
                      "files": sorted(bundled_files(path.name))})
    return found


def show_skill(name="blenderbox", file="SKILL.md"):
    files = bundled_files(name)
    if file not in files:
        raise BoxError("skill_file_not_found", f"Unknown bundled file: {file}; see skills list")
    return {"name": name, "file": file, "content": files[file].decode("utf-8")}


def destinations(agents=None, path=None):
    if path:
        return [Path(path).expanduser().resolve()]
    home = Path.home()
    codex_home = Path(os.environ.get("CODEX_HOME", str(home / ".codex"))).expanduser()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))).expanduser()
    targets = {"codex": codex_home / "skills", "claude": home / ".claude/skills",
               "opencode": config_home / "opencode/skills", "shared": home / ".agents/skills"}
    selected = agents or ["codex"]
    if "all" in selected:
        selected = list(targets)
    return list(dict.fromkeys(targets[agent].resolve() for agent in selected))


def install_skill(name="blenderbox", agents=None, path=None, force=False, dry_run=False):
    files = bundled_files(name)
    plans = []
    for parent in destinations(agents, path):
        target = parent / name
        if target.is_symlink() or (target.exists() and not target.is_dir()):
            raise BoxError("invalid_skill_destination", f"Skill destination must be a regular directory: {target}")
        exists = target.exists()
        identical = False
        if exists:
            current = {p.relative_to(target).as_posix(): p.read_bytes()
                       for p in target.rglob("*") if p.is_file()}
            identical = current == files
        if exists and not identical and not force and not dry_run:
            raise BoxError("skill_exists", f"Skill differs at {target}; use --force to replace it")
        status = "unchanged" if identical else "updated" if exists else "installed"
        if dry_run and not identical:
            status = "conflict" if exists and not force else "would_replace" if exists else "would_install"
        plans.append({"path": str(target), "status": status})
    # Preflight all destinations before making any changes.
    if not dry_run:
        for plan in plans:
            if plan["status"] == "unchanged":
                continue
            target = Path(plan["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=".blenderbox-install-", dir=target.parent))
            backup = None
            try:
                for relative, content in files.items():
                    output = staging / relative
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(content)
                if target.exists():
                    backup = target.with_name(".blenderbox-previous-" + uuid.uuid4().hex)
                    target.rename(backup)
                try:
                    staging.rename(target)
                except OSError:
                    if backup:
                        backup.rename(target)
                        backup = None
                    raise
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
                if backup and backup.exists():
                    shutil.rmtree(backup)
    return {"name": name, "dry_run": dry_run, "installations": plans}
