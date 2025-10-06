# Growth loop 2.0

## Referral links

Every referral link now follows the schema:

```
https://t.me/<bot_username>?ref=<ref_code>&src=<channel>
```

`<channel>` accepts lowercase letters, numbers, dashes, underscores and dots.
If the parameter is missing we fall back to `organic`. The generator lives in
`growth/referrals.py::generate_referral_link`.

## Anti-fraud bonuses

Referral conversions award up to 25 points while respecting:

- Weekly cap of 250 points per referrer (rolling seven days).
- Duplicate conversions per invited user are ignored.
- Shared device/browser fingerprints immediately flag the account.

Levels are defined in `growth/bonuses.py` and exposed to the UI.

## Viral K metric

The module `growth/referrals.compute_viral_k` recalculates the 30 day rolling
viral coefficient on every event. The number is exposed to Grafana through the
new `/metrics` HTTP endpoint (Prometheus format).

## Growth digest

`jobs/growth_report.py::send_growth_digest` posts a weekly summary to the admin
chat every Monday at `NOTIFY_HOUR_LOCAL:30`.

The digest contains:

- Viral K, clicks, joins and conversions for the last seven days.
- Top channels by traffic and bonus conversions.
- Total amount of awarded bonus points.

## Testing checklist

- Feed 10 valid + 10 fraudulent referrals → only valid conversions produce
  bonus points (fraudulent fingerprints are rejected).
- Check Grafana panel `growth_viral_k` for real time coefficient updates.
- Confirm weekly digest arrives each Monday.
