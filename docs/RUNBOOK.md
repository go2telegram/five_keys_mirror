# Release Runbook

This runbook describes how to prepare, execute, and roll back a production release of `five_keys_bot`.

## 1. Pre-flight checklist

1. Ensure you are on the latest `main` branch:
   ```bash
   git checkout main
   tools/git_clean.sh
   ```
2. Verify the environment matrix and confirm which configuration will be used for the release (see [Environment matrix](./ENVIRONMENT_MATRIX.md)).
3. Export required secrets to your shell (for production this includes `BOT_TOKEN`, database DSN, and monitoring credentials).
4. Confirm that `/ping`, `/metrics`, and `/doctor` respond locally by starting the bot in dry-run mode:
   ```bash
   DEV_DRY_RUN=1 BOT_TOKEN=dummy python run.py
   ```
   Use `Ctrl+C` to stop once endpoints are verified.

## 2. Build and self-audit

1. Install dependencies if needed:
   ```bash
   pip install -r requirements.txt -r requirements-dev.txt
   ```
2. Run the self audit and unit tests:
   ```bash
   python tools/self_audit.py --no-net --out build/reports/self_audit_local.md
   pytest
   ```
3. Confirm there are no generated artifacts staged for commit (`app/build_info.py`, `_alembic_tmp_*` migrations). The pre-commit hook `prevent-generated-artifacts` will fail otherwise.
4. Review `build/reports/self_audit_local.md` and note any warnings that must be acknowledged in the release notes.

## 3. Migration safety

1. Apply database migrations locally:
   ```bash
   alembic upgrade head
   ```
2. If the command reports `_alembic_tmp_*` tables, run the doctor repair:
   ```bash
   curl -XPOST "http://127.0.0.1:8080/doctor?repair=1"
   ```
   Re-run the migration command afterwards to ensure the fix succeeded.

## 4. Release execution

1. Update `app/build_info.py` if you are preparing an official build:
   ```bash
   python tools/write_build_info.py
   ```
2. Commit all changes and push to the release branch.
3. Trigger the GitHub Actions workflow `release`. It automatically:
   - runs the self audit in CI,
   - executes the test suite,
   - publishes a GitHub Release with the self-audit summary,
   - uploads build metadata to the release assets.
4. When the workflow completes, open the draft release and ensure the body contains the self-audit summary. Add additional operator notes if necessary using the [release template](../.github/release-template.md).

## 5. Rollback procedure

1. Identify the last known good tag (for automated releases it follows `vYYYY.MM.DD.HHMM`).
2. Redeploy the previous tag or merge commit via your deployment tooling.
3. If database migrations introduced issues, use Alembic to roll back cautiously:
   ```bash
   alembic downgrade -1
   ```
   Validate `/doctor` and `/metrics` before reopening Telegram traffic.
4. Communicate the rollback in the incident channel and capture follow-up actions.

## 6. Post-release verification

1. Monitor `/metrics` to ensure counters increase as expected.
2. Run `/doctor` in the admin chat (`/doctor`) to confirm build metadata, webhook status, and recent events look healthy.
3. Archive the CI self-audit report for the release in your internal knowledge base.
