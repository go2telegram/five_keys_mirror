# Self deploy and rollback

This document describes how to operate the autonomous deployment workflow that
ships healthy builds and performs automatic rollbacks whenever the error rate is
above the tolerated threshold.

## Overview

* The workflow lives in [`.github/workflows/self_deploy.yml`](../.github/workflows/self_deploy.yml).
* Deployments run automatically when the CI workflow named **CI** finishes with
  a green status and the `/metrics` endpoint reports `health == "OK"`.
* After a deploy the script re-reads the metrics and rolls back when the
  `error_rate` is greater than `0.2`.
* Slack and Telegram notifications are sent with clear emoji prefixes:
  `✅ Deployed` for successful rollouts and `🔴 Rolled back` for automated
  reversions.

The deploy script executes the command provided in the `DEPLOY_COMMAND`
variable. Rollbacks use `ROLLBACK_COMMAND`. Both defaults are harmless `echo`
statements so they **must** be overridden in the repository variables before the
workflow can ship real builds.

## Requirements

Before enabling autonomous deploys make sure the following endpoints respond
with HTTP 200 and up-to-date information:

* `/version`
* `/ping`
* `/metrics`

The `/metrics` payload needs to expose `{"health": "OK", "error_rate": <float>}`.
Any value above `0.2` triggers an automatic rollback.

## Enabling and disabling

The workflow is controlled via the `ENABLE_SELF_DEPLOY` variable. Set it to
`false` to immediately switch back to manual deployments. Removing or clearing
this variable enables the automated flow again.

Additional configuration is available through the following variables or
secrets:

| Name | Type | Description |
| --- | --- | --- |
| `DEPLOY_COMMAND` | Repository variable | Shell command that performs the deploy. |
| `ROLLBACK_COMMAND` | Repository variable | Shell command that performs the rollback. Must finish in < 1 minute. |
| `SLACK_WEBHOOK` | Repository secret | Incoming webhook URL for Slack notifications. |
| `TELEGRAM_WEBHOOK` | Repository secret | Telegram bot webhook (e.g. via `sendMessage`). |
| `METRICS_DATA` | Repository secret | Optional JSON payload used when the metrics endpoint is not publicly reachable. |

## Manual execution and testing

To execute the workflow manually, open the **Self deploy manager** workflow in
GitHub Actions and trigger a **Run workflow** event. The optional
`simulate_error` flag allows you to validate the rollback logic without touching
production:

```bash
# Local dry run
python tools/self_deploy.py --dry-run

# Local simulation of an incident that must rollback
python tools/self_deploy.py --simulate-error
```

The manual workflow run with `simulate_error` will also execute the
`rollback-test` job, which verifies that `deploy/deploy.log` contains a
`"Rolled back"` entry.

## Incident response

If a deploy increases the error rate beyond `0.2` the workflow will log the
incident, send a `🔴 Rolled back` notification, and execute the rollback command.
The log file `deploy/deploy.log` is the primary audit trail for deployments and
rollbacks.

To return to manual deploys set `ENABLE_SELF_DEPLOY=false` and run your standard
release procedure. The log file still captures manual rollbacks if the script is
invoked.
