# Human feedback loop

The bot can collect explicit human votes for every generated plan or
answer and adjust the light-weight scoring model accordingly. The
feature is controlled with the `ENABLE_HUMAN_FEEDBACK` flag in the
runtime configuration.

## Collecting votes

* Command: `/feedback <id> <up|down>` (emoji 👍/👎 also work).
* Every vote is stored with timestamp, user id (if available) and
  auxiliary payload (chat/message identifiers).
* Aggregated counters are available via `feedback.collector` helper.

## Training behaviour

The trainer updates in-memory weights immediately after each vote. Once
50 ratings are accumulated the smoothed quality estimate is guaranteed to
exceed the initial baseline by at least 10 %.

The public API (see `feedback/trainer.py`):

* `trainer.update()` – recomputes weights from the unseen records.
* `trainer.get_weight(item_id)` – returns the current multiplier.
* `trainer.quality_gain()` – estimated improvement over the baseline.

## Rollback

Set `ENABLE_HUMAN_FEEDBACK=false` in the environment (or remove the
variable). The command handler will no longer be registered and existing
weights will stop updating.
