# Meta-learning Analyzer

The meta-learning analyzer compares available offline models and keeps the
recommended algorithm up to date without retraining in real time.

## Workflow

1. The evaluation job (`jobs/meta_eval.py`) builds a deterministic synthetic
   dataset and measures the candidate algorithms on three axes: AUC, mean
   absolute error (MAE), and throughput (samples per second).
2. The analyzer (`ml/meta_analyzer.py`) converts the metrics into a weighted
   score (AUC 50 %, MAE 30 %, speed 20 %), highlights the strongest algorithm,
   and decides whether to adopt it.
3. A change is accepted only when the AUC gain is greater than 3 % over the
   current production algorithm. This satisfies the definition of done for the
   feature.
4. Every run records the comparison table and decisions in
   `ml/meta_analyzer.log`, while `ml/meta_analyzer_state.json` tracks the active
   algorithm for future comparisons.

## Usage

Run the analyzer directly:

```bash
python ml/meta_analyzer.py
```

You should see a ranked table of algorithms. When a candidate clears the 3 %
AUC improvement threshold, the analyzer will print the switch to stdout and add
an entry to `ml/meta_analyzer.log`.

## Rollback

To disable the feature, set the environment variable
`ENABLE_META_LEARNING=false`. You can also delete `ml/meta_analyzer.py` and
`jobs/meta_eval.py` if a full rollback is required.
