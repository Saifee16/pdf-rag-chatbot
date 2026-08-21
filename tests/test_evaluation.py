from evaluation.evaluate_retrieval import reciprocal_rank


def test_reciprocal_rank_returns_first_expected_match() -> None:
    assert reciprocal_rank(["a", "b", "c"], {"b", "c"}) == 0.5


def test_reciprocal_rank_returns_zero_for_miss() -> None:
    assert reciprocal_rank(["a", "b"], {"z"}) == 0.0
