import os
import datetime
import subprocess


def get_commit_hash():
    return subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()


def get_tag_name():
    tag = os.getenv("TAG_NAME")
    if tag:
        return tag
    tag = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return tag or "v0.0.0"


def update_build_info():
    version = get_tag_name()
    commit = get_commit_hash()
    timestamp = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"

    path = "app/build_info.py"
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write(
            f'''BUILD = {{
    "version": "{version}",
    "commit": "{commit}",
    "timestamp": "{timestamp}"
}}
'''
        )
    print(f"✅ build_info.py updated → {version} ({commit})")


if __name__ == "__main__":
    update_build_info()
