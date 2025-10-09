from __future__ import annotations

from collections import Counter

from app.experiments import ab


def test_select_copy_distribution(tmp_path, monkeypatch):
    experiments_file = tmp_path / "ab.yaml"
    experiments_file.write_text(
        """
experiments:
  demo:
    variants:
      a:
        weight: 1
        text: A
      b:
        weight: 1
        text: B
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(ab, "EXPERIMENTS_FILE", experiments_file)
    ab.load_experiments.cache_clear()  # type: ignore[attr-defined]
    storage = ab.AssignmentStorage()
    counts = Counter()
    for idx in range(200):
        user_id = str(idx)
        copy = ab.select_copy(storage, "demo", user_id, default="A")
        counts[copy] += 1
        # repeat assignment to ensure stability
        copy_again = ab.select_copy(storage, "demo", user_id, default="A")
        assert copy == copy_again
    assert counts["A"] > 0
    assert counts["B"] > 0
    ratio = counts["A"] / counts["B"]
    assert 0.5 <= ratio <= 2


def test_assign_variant_conditions(tmp_path, monkeypatch):
    experiments_file = tmp_path / "ab.yaml"
    experiments_file.write_text(
        """
experiments:
  locale_specific:
    conditions:
      locale: ["ru"]
    variants:
      ru:
        text: RU
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(ab, "EXPERIMENTS_FILE", experiments_file)
    ab.load_experiments.cache_clear()  # type: ignore[attr-defined]
    storage = ab.AssignmentStorage()
    assert ab.select_copy(storage, "locale_specific", "42", context={"locale": "ru"}) == "RU"
    assert ab.select_copy(storage, "locale_specific", "42", context={"locale": "en"}) is None
