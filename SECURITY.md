# Security & Dependency Management

This project ships with automated tooling for vulnerability scanning, static analysis, and software bill of materials (SBOM) generation.

## Local workflows

```bash
python tools/security_audit.py
python tools/sbom_generate.py
```

The audit command runs the following tools and aggregates the results into `build/reports/`:

- [`pip-audit`](https://pypi.org/project/pip-audit/) for Python package CVEs
- [`safety`](https://pypi.org/project/safety/) for additional advisory coverage
- [`bandit`](https://bandit.readthedocs.io/) for security-oriented static analysis
- [`gitleaks`](https://github.com/gitleaks/gitleaks) for secret detection

`security_audit.py` exits with a non-zero status only when **High** or **Critical** issues are detected by `pip-audit`, `safety`, or `bandit`. Lower severities are reported but do not fail the job.

The SBOM generator uses [`cyclonedx-bom`](https://github.com/CycloneDX/cyclonedx-python) to produce both JSON and XML CycloneDX manifests in `build/reports/`.

## Handling findings

- For `bandit`, suppress individual findings with `# nosec` or `# noqa: BXXX` (include justification in the code review).
- For `gitleaks`, add safe patterns to `.gitleaks.toml` under the `allowlist` section.
- For dependency advisories, prefer upgrading via `tools/deps_update.sh` to keep the lock files consistent.

## Automation

- GitHub Actions runs the security audit and publishes artifacts on every push/PR.
- Dependabot is configured to open weekly update PRs for pip dependencies and GitHub Actions workflows.
- `tools/deps_compile.sh` rebuilds lock files from `requirements*.in`.
- `tools/deps_update.sh` performs an in-place upgrade and writes a summary to `build/reports/deps_update_summary.md`.

Review Dependabot PRs promptly and ensure that High/Critical issues are resolved before merging.
