"""Install the command and its shared agent skill. No MCP configuration edits."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

repo = Path(__file__).resolve().parent.parent
uv = shutil.which("uv")
if not uv:
    raise SystemExit("uv is required for this installer; alternatively pip install . in a dedicated venv")
subprocess.run([uv, "tool", "install", "--force", "--reinstall", "--no-cache",
                "--python", sys.executable, str(repo)], check=True)
bin_dir = Path(subprocess.check_output([uv, "tool", "dir", "--bin"], text=True).strip())
installed_skills = json.loads(subprocess.check_output(
    [str(bin_dir / "blenderbox"), "skills", "install", "--agent", "all", "--force"], text=True))
print(json.dumps({"binary": str(bin_dir / "blenderbox"),
                  "skills": installed_skills["installations"]}, indent=2))
