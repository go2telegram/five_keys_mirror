# Development workflow

Guidance for iterating on the codebase efficiently and safely.

## Toolchain

| Purpose | Command |
| ------- | ------- |
| Linting | `ruff check` |
| Type checking | `mypy --config-file pyproject.toml` |
| Security audit | `bandit -r app --confidence-level MEDIUM` |
| Bytecode check | `python -m compileall app doctor.py` |
| Load testing | `python tools/stress_test.py --updates 200 --concurrency 20` |

> Install development dependencies via `pip install -r requirements-dev.txt` to get Ruff, Mypy, Bandit, and MkDocs.

## Database migrations

Alembic tracks schema evolution. Generate a migration stub with:

```bash
alembic revision -m "short description"
```

Edit the generated file in `alembic/versions/` to include `op.create_table`, `op.add_column`, etc., then apply it with `alembic upgrade head`.

## Running tests with Docker Compose

```bash
docker compose up --build -d
alembic upgrade head
docker compose exec bot ruff check
docker compose exec bot mypy --config-file pyproject.toml
```

Stop the stack when finished:

```bash
docker compose down
```

## Observability checklist

- Confirm `/metrics` exposes the Prometheus counters/histograms referenced in dashboards.
- Use Grafana (localhost:3000) to review latency, uptime, and error rate panels.
- `doctor.py` should report "OK" and indicate when recovery events occur.

## Writing documentation

MkDocs powers the documentation site:

```bash
mkdocs serve
```

Add pages under `docs/` and extend the navigation in `mkdocs.yml`. `mkdocstrings` renders API references directly from docstrings.

## Pull request expectations

- Small, focused changes are easier to review.
- Include screenshots or metrics when altering user-visible behaviour.
- Update the stress-test baselines if workloads change.
- Ensure new modules include docstrings so they appear in the API reference.
