import re
import subprocess


print("## 🚀 Release Changelog\n")

log = subprocess.run(
    ["git", "log", "--pretty=format:%s", "-n", "30"],
    capture_output=True,
    text=True,
    check=True,
).stdout

for line in log.split("\n"):
    if re.match(r"^(feat|fix|chore|ci|perf|refactor)", line):
        print(f"- {line}")
