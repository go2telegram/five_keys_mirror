import pathlib
import subprocess

OUTPUT_DIR = pathlib.Path("build/reports")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

subprocess.run("pip install cyclonedx-bom -q", shell=True, check=True)
subprocess.run(f"cyclonedx-bom -o {OUTPUT_DIR / 'sbom.json'} -e json", shell=True, check=True)
subprocess.run(f"cyclonedx-bom -o {OUTPUT_DIR / 'sbom.xml'} -e xml", shell=True, check=True)
print("SBOM created:", OUTPUT_DIR / "sbom.json", OUTPUT_DIR / "sbom.xml")
