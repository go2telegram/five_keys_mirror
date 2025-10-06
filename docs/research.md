# Autonomous research engine

## Overview

The autonomous research loop generates light-weight product hypotheses every day
and runs synthetic AutoAB experiments to evaluate them. The engine keeps track
of active hypotheses in memory and stores a short history of completed tests
with recommendations on the winning variant.

## Daily cadence

* The APScheduler job `autonomous_research` runs every day at 04:00 server time.
* On each run the engine ensures there is at least one active hypothesis,
  launches a new one if needed and simulates traffic for all running tests.
* Once a variant shows a statistically meaningful uplift or the maximum number
  of iterations is reached, the engine produces a recommendation. Notifications
  are sent to the admin chat.

## Admin commands

The bot exposes `/research_status` (admin-only) which renders:

* all active hypotheses with their key metrics (sample size and conversion);
* the latest recommendations for recently finished experiments.

## Configuration

The feature can be disabled by setting the environment variable
`ENABLE_AUTONOMOUS_RESEARCH=false`. When disabled, the scheduler job is not
registered and the engine remains idle.

## Rollback

To rollback the feature without touching the codebase, redeploy with
`ENABLE_AUTONOMOUS_RESEARCH=false`. This prevents the engine from running while
keeping other bot functionality intact.
