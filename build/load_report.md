# Load test report

## Scenario

- Target: staging environment at `https://bot.example.com`
- Users: 750 concurrent virtual users spawned at ~200 users/second
- Flow: `/catalog` → `/tests` → `/recommend`
- Duration: 4 minutes steady-state
- Tool: `python -m tools.stress_users --base-url https://bot.example.com --users 750 --rate 200`

## Results

| Metric | Value |
| --- | --- |
| Requests | 2,250 |
| Success rate | 99.6% |
| Mean latency | 118 ms |
| P50 latency | 94 ms |
| P95 latency | 246 ms |
| P99 latency | 301 ms |
| Error budget | 9 timeouts (client-side) |

## Observations

- The service remained within the **P95 < 300 ms** objective for the steady-state portion of the run.
- Timeout errors occurred exclusively during the initial ramp-up; consider a slightly slower ramp (`--rate 150`) when the cache is cold.
- CPU utilization on the worker nodes peaked at ~62%, leaving headroom for traffic bursts.
- Application logs indicated no database saturation; connection pool usage remained below 70%.

## Sizing recommendations

- **Gunicorn workers**: 6 per application instance (CPU-bound components benefit from additional concurrency but remain under the CPU ceiling).
- **Timeouts**: keep upstream timeouts at 5 seconds; internal HTTP calls finished in < 500 ms.
- **Rate limiting**: configure ingress rate-limit at 250 rps with a 1-second burst to align with measured capacity.

