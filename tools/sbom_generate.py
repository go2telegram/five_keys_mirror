import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

import pathlib
import subprocess

ALLOW_OFFLINE = os.getenv("ALLOW_OFFLINE_AUDIT", "").lower() in {"1", "true", "yes"}

OUTPUT_DIR = pathlib.Path("build/reports")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def _run(command: str) -> None:
    try:
        subprocess.run(command, shell=True, check=True)
    except subprocess.CalledProcessError as exc:
        if ALLOW_OFFLINE:
            print(f"⚠️ {command} failed ({exc.returncode}); skipping SBOM generation (offline mode)")
            raise SystemExit(0)
        raise


_run("pip install cyclonedx-bom -q")
_run(f"cyclonedx-bom -o {OUTPUT_DIR / 'sbom.json'} -e json")
_run(f"cyclonedx-bom -o {OUTPUT_DIR / 'sbom.xml'} -e xml")
print("SBOM created:", OUTPUT_DIR / "sbom.json", OUTPUT_DIR / "sbom.xml")
