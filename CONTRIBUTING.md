# Contributing

Thank you for helping improve Five Keys Bot! This guide walks through the local setup, coding conventions, and quality checks expected before submitting a pull request.

## Workflow at a glance

1. **Fork** the repository and create a branch from `main`.
2. **Sync** your fork regularly to keep dependencies and migrations up to date.
3. **Develop** changes with tests, docs, and migrations updated as needed.
4. **Open a pull request** targeting `main` and link any related issues.

We squash-merge PRs, so feel free to push incremental commits while iterating.

## Environment setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements-dev.txt
cp .env.example .env  # customise secrets before running the bot
alembic upgrade head
```

The bot runs via `python run.py`. Docker Compose (`docker compose up --build`) starts PostgreSQL, Redis, Grafana, and the bot for full-stack testing.

## Branching & commit style

- Use descriptive branch names such as `feature/admin-digest` or `fix/metrics-latency`.
- Keep commits scoped and meaningful ("Add Grafana dashboards" instead of "Fix stuff").
- Reference issues in commit messages or PR description when applicable (e.g. `Fixes #123`).

## Coding standards

- Code is formatted and linted by [Ruff](https://docs.astral.sh/ruff/). Keep lines ≤ 100 characters.
- Prefer async/await patterns consistent with Aiogram 3.
- Avoid leaking secrets — use utilities in `app/security.py` to mask sensitive data.
- Store persistent data in PostgreSQL models (`app/db/models.py`) and keep Redis for ephemeral usage.
- Update or add Alembic migrations for schema changes.

## Required checks

Run the following before opening a PR:

```bash
ruff check
mypy --config-file pyproject.toml
bandit -r app --confidence-level MEDIUM
python -m compileall app doctor.py
python tools/stress_test.py --updates 100 --concurrency 10 --max-duration 10
```

If external services (e.g. PostgreSQL) are required, start them via Docker Compose or local instances before executing the commands.

> ⚠️ `bandit` and the stress test require optional dependencies defined in `requirements-dev.txt`.

## Documentation expectations

- Update the [README](README.md) if behaviour or setup steps change.
- Expand the MkDocs site under `docs/` for new features or API surface area.
- Keep docstrings informative so `mkdocstrings` can generate useful reference pages.

## Pull request checklist

- [ ] Tests and linters pass locally.
- [ ] Database migrations cover any schema change.
- [ ] Documentation (README, docs site) is updated when functionality, APIs, or setup changes.
- [ ] Secrets are redacted in logs and screenshots.
- [ ] CI status checks are green.

Once everything looks good, request a review from a maintainer. Welcome aboard!
