import os
import re
import subprocess


def next_tag() -> str:
    tags = subprocess.run([
        "git",
        "tag",
    ], capture_output=True, text=True, check=False).stdout.split()
    rc = [t for t in tags if re.match(r"v\d+\.\d+\.\d+", t)]
    rc.sort()
    if not rc:
        return "v1.3.1"
    last = rc[-1]
    major, minor, patch = map(int, last[1:].split("."))
    return f"v{major}.{minor}.{patch + 1}"


if __name__ == "__main__":
    tag = next_tag()
    os.environ["TAG_NAME"] = tag
    subprocess.run([
        "git",
        "tag",
        "-a",
        tag,
        "-m",
        f"Auto-release {tag}",
    ], check=True)
    subprocess.run(["git", "push", "origin", tag], check=True)
    print(f"✅ Created tag {tag}")
