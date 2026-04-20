from sizing_rules import decide_from_rules, label_for


def test_large_beats_small_when_both_signals_present():
    yaml = "steps:\n  - run: ruff check .\n  - run: python train.py"
    decision = decide_from_rules(yaml)
    assert decision is not None
    assert decision.size == "large"
    assert decision.source == "rules"


def test_medium_for_pytest():
    yaml = "steps:\n  - run: pytest --cov"
    decision = decide_from_rules(yaml)
    assert decision is not None
    assert decision.size == "medium"
    assert decision.label == "aca-medium"


def test_small_for_pure_lint():
    yaml = "steps:\n  - run: ruff check orchestrator/"
    decision = decide_from_rules(yaml)
    assert decision is not None
    assert decision.size == "small"


def test_no_rule_match_returns_none():
    yaml = "steps:\n  - run: ./some-custom-internal-tool --flag"
    assert decide_from_rules(yaml) is None


def test_label_for_known_sizes():
    assert label_for("small") == "aca-small"
    assert label_for("medium") == "aca-medium"
    assert label_for("large") == "aca-large"


def test_label_for_unknown_raises():
    import pytest

    with pytest.raises(ValueError):
        label_for("xl")
