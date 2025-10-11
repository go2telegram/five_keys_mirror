#!/usr/bin/env python3
"""Automate the merge-train workflow for codex-labelled PRs.

The script performs the following steps:

* Discover open PRs with the `codex` label via the GitHub CLI.
* For each PR:
  * Check it out into a dedicated local branch.
  * Rebase onto the latest `origin/main`.
  * Resolve simple conflicts in ``app/keyboards.py``, ``app/quiz/engine.py``
    and ``app/scheduler/service.py`` using the team-approved strategy.
  * Run ``python -m tools.self_audit --fast`` and ``pytest -q``.
* Collect all successfully validated branches into ``merge/train-v1.3.1``
  using fast-forward merges.
* Generate ``build/reports/merge_train.md`` with the status for every PR.

The script is intentionally verbose to make troubleshooting easier and to make
it fit for CI usage.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

import argparse
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / "build" / "reports" / "merge_train.md"
MERGE_TRAIN_BRANCH = "merge/train-v1.3.1"
CODEx_LABEL = "codex"


class MergeTrainError(RuntimeError):
    """Raised when the merge train cannot continue."""


@dataclass
class CommandResult:
    command: Sequence[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass
class PRStatus:
    number: int
    title: str
    url: str
    head_ref: str
    branch_name: str
    rebase_ok: bool = False
    audit_ok: bool = False
    pytest_ok: bool = False
    skipped: bool = False
    messages: list[str] = field(default_factory=list)

    def status_label(self) -> str:
        if self.skipped:
            return "skipped"
        if self.rebase_ok and self.audit_ok and self.pytest_ok:
            return "success"
        return "failed"

    def add_message(self, *parts: str) -> None:
        for part in parts:
            if part:
                self.messages.append(part)


@dataclass
class Context:
    starting_branch: str
    pr_statuses: list[PRStatus] = field(default_factory=list)


def run(cmd: Sequence[str], *, cwd: Path | None = None, check: bool = True) -> CommandResult:
    """Run a command capturing stdout/stderr."""

    process = subprocess.run(
        cmd,
        cwd=str(cwd or REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    result = CommandResult(cmd, process.returncode, process.stdout, process.stderr)
    if check and not result.ok:
        raise MergeTrainError(
            f"Command {' '.join(cmd)} failed with code {process.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


def ensure_clean_worktree() -> None:
    status = run(["git", "status", "--porcelain"], check=False)
    if status.stdout.strip():
        raise MergeTrainError(
            "Working tree is not clean. Please commit, stash or reset changes before running merge train."
        )


def detect_current_branch() -> str:
    result = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return result.stdout.strip()


def ensure_git_fetch() -> None:
    run(["git", "fetch", "origin"])


def check_requirements() -> None:
    if shutil.which("gh") is None:
        raise MergeTrainError("GitHub CLI (gh) is required for merge train operations.")


def fetch_codex_prs() -> list[PRStatus]:
    cmd = [
        "gh",
        "pr",
        "list",
        "--label",
        CODEx_LABEL,
        "--state",
        "open",
        "--json",
        "number,headRefName,title,url",
    ]
    result = run(cmd)
    data = json.loads(result.stdout)
    statuses: list[PRStatus] = []
    for item in data:
        number = int(item["number"])
        title = item["title"]
        url = item["url"]
        head_ref = item["headRefName"]
        branch = f"merge-train/pr-{number}"
        statuses.append(
            PRStatus(
                number=number,
                title=title,
                url=url,
                head_ref=head_ref,
                branch_name=branch,
            )
        )
    return statuses


def checkout_pr(pr: PRStatus) -> bool:
    cmd = [
        "gh",
        "pr",
        "checkout",
        str(pr.number),
        "--branch",
        pr.branch_name,
    ]
    result = run(cmd, check=False)
    if not result.ok:
        pr.add_message("failed to checkout PR", result.stderr.strip())
        return False
    return True


def rebase_onto_main(pr: PRStatus) -> bool:
    result = run(["git", "rebase", "origin/main"], check=False)
    if result.ok:
        pr.rebase_ok = True
        return True
    pr.add_message("rebase reported conflicts", result.stderr.strip())
    try:
        handle_conflicts(pr)
    except MergeTrainError as exc:
        pr.add_message(str(exc))
        run(["git", "rebase", "--abort"], check=False)
        return False

    continue_result = run(["git", "rebase", "--continue"], check=False)
    if not continue_result.ok:
        pr.add_message("rebase --continue failed", continue_result.stderr.strip())
        run(["git", "rebase", "--abort"], check=False)
        return False

    pr.rebase_ok = True
    return True


def handle_conflicts(pr: PRStatus) -> None:
    status = run(["git", "status", "--porcelain"], check=False)
    conflicted = [line[3:] for line in status.stdout.splitlines() if line.startswith("UU ")]
    if not conflicted:
        raise MergeTrainError("rebase failed but no conflicts reported by git")

    for rel_path in conflicted:
        path = REPO_ROOT / rel_path
        if rel_path == "app/keyboards.py":
            resolve_keyboard_conflict(path)
        elif rel_path == "app/quiz/engine.py":
            resolve_quiz_conflict(path)
        elif rel_path == "app/scheduler/service.py":
            resolve_scheduler_conflict(path)
        else:
            raise MergeTrainError(f"Unhandled merge conflict in {rel_path}")
        run(["git", "add", rel_path])


def resolve_keyboard_conflict(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    target_block = (
        "    kb.button(text=\"⚡ Тесты и диагностика\", callback_data=\"menu:tests\")\n"
        "    kb.button(text=\"🎯 Рекомендации\", callback_data=\"pick:menu\")\n"
        "    kb.button(text=\"🛍 Каталог\", callback_data=\"catalog:menu\")\n"
        "    kb.button(text=\"💎 Премиум\", callback_data=\"menu:premium\")\n"
        "    kb.button(text=\"👤 Профиль\", callback_data=\"profile:open\")\n"
        "    kb.button(text=\"ℹ️ Помощь\", callback_data=\"menu:help\")\n"
    )
    import re

    pattern = re.compile(
        r"(def kb_main\(\) -> InlineKeyboardMarkup:\n\s+kb = InlineKeyboardBuilder\(\)\n)(.*?)(\s+kb.adjust\(3, 3\)\n\s+return kb.as_markup\(\))",
        re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        raise MergeTrainError("Unable to locate kb_main definition for conflict resolution")

    new_text = match.group(1) + target_block + match.group(3)
    resolved = pattern.sub(new_text, text)
    path.write_text(resolved, encoding="utf-8")


def resolve_quiz_conflict(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "<<<<<<<" in text or ">>>>>>>" in text:
        target = QUIZ_SEND_PHOTO_BLOCK
        import re

        pattern = re.compile(r"async def _send_photo\([\s\S]*?\n\n", re.MULTILINE)
        if not pattern.search(text):
            raise MergeTrainError("Unable to identify _send_photo block in quiz engine")
        resolved = pattern.sub(target, text)
        text = resolved

        text = ensure_state_clear(text)
        text = ensure_remote_image_constants(text)
        path.write_text(text, encoding="utf-8")
    else:
        text = ensure_state_clear(text)
        text = ensure_remote_image_constants(text)
        path.write_text(text, encoding="utf-8")


def ensure_state_clear(text: str) -> str:
    if "await state.clear()" in text:
        return text
    return text.replace("await state.set_state(QuizSession.home)", "await state.set_state(QuizSession.home)\n    await state.clear()")


QUIZ_SEND_PHOTO_BLOCK = """async def _send_photo(
    message: Message,
    path_str: str | None,
    caption: str,
    *,
    reply_markup=None,
) -> Message | None:
    if not path_str:
        return None

    for source, candidate in _iter_photo_candidates(path_str):
        try:
            if source == \"local\":
                return await message.answer_photo(
                    photo=FSInputFile(str(candidate)),
                    caption=caption,
                    reply_markup=reply_markup,
                )

            from app.utils_media import fetch_image_as_file  # local import to avoid cycles

            proxy = await fetch_image_as_file(str(candidate))
            if not proxy:
                continue

            return await message.answer_photo(
                photo=proxy,
                caption=caption,
                reply_markup=reply_markup,
            )
        except TelegramBadRequest as exc:
            logger.warning(
                \"Failed to send quiz image %s via %s: %s\",
                path_str,
                source,
                exc,
            )
        except Exception as exc:  # pragma: no cover - network/runtime failures
            logger.warning(
                \"Unexpected error sending quiz image %s via %s: %s\",
                path_str,
                source,
                exc,
            )

    logger.warning(\"Quiz image unavailable, using text fallback: %s\", path_str)
    return None


"""


def ensure_remote_image_constants(text: str) -> str:
    if "DEFAULT_REMOTE_BASE" in text and "QUIZ_IMAGE_MODE" in text:
        return text
    if "DEFAULT_REMOTE_BASE" not in text:
        text = text.replace(
            "logger = logging.getLogger(__name__)",
            "logger = logging.getLogger(__name__)\n\nDEFAULT_REMOTE_BASE = (\n"
            "    \"https://raw.githubusercontent.com/go2telegram/media/1312d74492d26a8de5b8a65af38293fe6bf8ccc5/media/quizzes\"\n)\n\n",
        )
    if "QUIZ_IMAGE_MODE" not in text:
        text = text.replace(
            "PROJECT_ROOT = Path(__file__).resolve().parents[2]",
            "PROJECT_ROOT = Path(__file__).resolve().parents[2]\n_quiz_mode = os.getenv(\"QUIZ_IMAGE_MODE\", \"remote\").strip().lower()\nQUIZ_IMAGE_MODE = _quiz_mode if _quiz_mode in {\"remote\", \"local\"} else \"remote\"\nQUIZ_REMOTE_BASE = os.getenv(\"QUIZ_IMG_BASE\", DEFAULT_REMOTE_BASE).rstrip(\"/\")\n",
        )
    return text


SCHEDULER_BLOCK = """def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    \"\"\"
    Поднимаем APScheduler и запускаем джобу рассылки по расписанию.
    \"\"\"
    scheduler = AsyncIOScheduler(timezone=settings.TIMEZONE)
    weekdays = _parse_weekdays(getattr(settings, \"NOTIFY_WEEKDAYS\", \"\"))

    # Каждый день в NOTIFY_HOUR_LOCAL (локальное TZ); фильтр по weekday внутри job
    if getattr(settings, \"SCHEDULER_ENABLE_NUDGES\", True):
        trigger = CronTrigger(hour=settings.NOTIFY_HOUR_LOCAL, minute=0)
        scheduler.add_job(
            send_nudges,
            trigger=trigger,
            args=[bot, settings.TIMEZONE, weekdays],
            name=\"send_nudges\",
            misfire_grace_time=600,
            coalesce=True,
            max_instances=1,
        )

    scheduler.add_job(
        _log_heartbeat,
        trigger=IntervalTrigger(seconds=60),
        name=\"heartbeat\",
        misfire_grace_time=30,
        coalesce=True,
        max_instances=1,
    )

    if getattr(settings, \"WEEKLY_PLAN_ENABLED\", True):
        try:
            weekly_trigger = _parse_weekly_spec(getattr(settings, \"WEEKLY_PLAN_CRON\", \"\"))
        except ValueError:
            logging.getLogger(\"scheduler\").warning(
                \"invalid WEEKLY_PLAN_CRON, falling back to Monday 10:00\"
            )
            weekly_trigger = CronTrigger(day_of_week=\"mon\", hour=10, minute=0)
        scheduler.add_job(
            weekly_ai_plan_job,
            trigger=weekly_trigger,
            args=[bot, None],
            name=\"weekly_ai_plan\",
            misfire_grace_time=900,
            coalesce=True,
            max_instances=1,
        )

    if getattr(settings, \"RETENTION_ENABLED\", False):
        scheduler.add_job(
            send_retention_reminders,
            trigger=IntervalTrigger(hours=1),
            args=[bot],
            name=\"retention_followups\",
            misfire_grace_time=300,
            coalesce=True,
            max_instances=1,
        )

    if getattr(settings, \"ANALYTICS_EXPORT_ENABLED\", True):
        analytics_cron = getattr(settings, \"ANALYTICS_EXPORT_CRON\", None)
        if analytics_cron:
            try:
                analytics_trigger = CronTrigger.from_crontab(
                    analytics_cron, timezone=settings.TIMEZONE
                )
            except ValueError:
                logging.getLogger(\"scheduler\").warning(
                    \"invalid ANALYTICS_EXPORT_CRON, falling back to 21:00\"
                )
                analytics_trigger = CronTrigger(hour=21, minute=0, timezone=settings.TIMEZONE)
        else:
            analytics_trigger = CronTrigger(hour=21, minute=0, timezone=settings.TIMEZONE)

        scheduler.add_job(
            export_analytics_snapshot,
            trigger=analytics_trigger,
            name=\"analytics_export\",
            misfire_grace_time=900,
            coalesce=True,
            max_instances=1,
        )
    scheduler.start()
    return scheduler


"""


def resolve_scheduler_conflict(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "<<<<<<<" in text or ">>>>>>>" in text:
        import re

        pattern = re.compile(r"def start_scheduler\([\s\S]*?return scheduler\n\n", re.MULTILINE)
        if not pattern.search(text):
            raise MergeTrainError("Unable to identify start_scheduler block in scheduler service")
        resolved = pattern.sub(SCHEDULER_BLOCK, text)
        path.write_text(resolved, encoding="utf-8")
    else:
        path.write_text(text, encoding="utf-8")


TEST_COMMANDS: list[list[str]] = [
    [sys.executable, "tools/self_audit.py", "--fast"],
    ["pytest", "-q"],
]


def run_tests(pr: PRStatus) -> None:
    for cmd in TEST_COMMANDS:
        result = run(cmd, check=False)
        if cmd[0].endswith("self_audit.py"):
            if result.ok:
                pr.audit_ok = True
            else:
                pr.add_message("self_audit failed", result.stderr.strip())
                return
        else:
            if result.ok:
                pr.pytest_ok = True
            else:
                pr.add_message("pytest failed", result.stderr.strip())
                return


def checkout_branch(branch: str) -> None:
    run(["git", "checkout", branch])


def finalize_merge_train(prs: Iterable[PRStatus]) -> None:
    successful = [pr for pr in prs if pr.status_label() == "success"]
    if not successful:
        return

    run(["git", "checkout", "-B", MERGE_TRAIN_BRANCH, "origin/main"])
    for pr in successful:
        run(["git", "merge", "--ff-only", pr.branch_name])


def write_report(prs: Sequence[PRStatus]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Merge train v1.3.1", ""]
    lines.append("| PR | Title | Status | Notes |")
    lines.append("| --- | --- | --- | --- |")
    for pr in prs:
        notes = "<br/>".join(pr.messages) if pr.messages else ""
        lines.append(
            f"| [#{pr.number}]({pr.url}) | {pr.title} | {pr.status_label()} | {notes} |"
        )
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def process_prs(context: Context) -> None:
    for pr in context.pr_statuses:
        print(f"Processing PR #{pr.number} - {pr.title}")
        if not checkout_pr(pr):
            pr.skipped = True
            checkout_branch(context.starting_branch)
            continue

        if not rebase_onto_main(pr):
            checkout_branch(context.starting_branch)
            continue

        run_tests(pr)
        checkout_branch(context.starting_branch)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run merge train for codex PRs")
    parser.add_argument(
        "--no-finalize",
        action="store_true",
        help="Do not create merge/train branch (useful for dry runs)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    os.chdir(REPO_ROOT)

    try:
        check_requirements()
        ensure_clean_worktree()
        ensure_git_fetch()
        starting_branch = detect_current_branch()
        pr_statuses = fetch_codex_prs()
        context = Context(starting_branch=starting_branch, pr_statuses=pr_statuses)
        if not pr_statuses:
            print("No codex PRs found")
        else:
            process_prs(context)
            if not args.no_finalize:
                finalize_merge_train(context.pr_statuses)
        write_report(context.pr_statuses)
    except MergeTrainError as exc:
        print(f"Merge train failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
