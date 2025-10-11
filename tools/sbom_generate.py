import os
import subprocess
import sys

OUTPUT_DIR = "build/reports"
os.makedirs(OUTPUT_DIR, exist_ok=True)

try:
    subprocess.run(
        [
            "cyclonedx-bom",
            "-o",
            f"{OUTPUT_DIR}/sbom.json",
            "-e",
            "json",
        ],
        check=True,
    )
    print("✅ SBOM generated successfully.")
except FileNotFoundError:
    print("⚠️ cyclonedx-bom not found. Skipping SBOM generation.")
    sys.exit(0)
except subprocess.CalledProcessError as exc:
    print(f"⚠️ SBOM generation failed (non-fatal): {exc}")
    sys.exit(0)
