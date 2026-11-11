from app.retrieval.rrf import reciprocal_rank_fusion


def test_single_ranking_preserves_order():
    fused = reciprocal_rank_fusion([["a", "b", "c"]])
    assert [item for item, _ in fused] == ["a", "b", "c"]


def test_agreement_across_rankings_boosts_score():
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "a", "c"]])
    ordered = [item for item, _ in fused]
    # "a" and "b" both appear near the top of both rankings; "c" is last in both.
    assert ordered[-1] == "c"
    assert set(ordered[:2]) == {"a", "b"}


def test_item_only_in_one_ranking_still_included():
    fused = reciprocal_rank_fusion([["a", "b"], ["c"]])
    assert {item for item, _ in fused} == {"a", "b", "c"}


def test_disjoint_rankings_rank_by_best_position():
    fused = reciprocal_rank_fusion([["a", "b"], ["c", "d"]])
    ordered = [item for item, _ in fused]
    # top-of-ranking items (a, c) should outscore bottom-of-ranking items (b, d)
    assert ordered.index("a") < ordered.index("b")
    assert ordered.index("c") < ordered.index("d")


def test_empty_rankings_returns_empty():
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


def test_scores_are_descending():
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["c", "b", "a"]])
    scores = [score for _, score in fused]
    assert scores == sorted(scores, reverse=True)


def test_custom_k_changes_score_but_not_monotonicity():
    ranking = [["a", "b", "c"]]
    fused_default = reciprocal_rank_fusion(ranking)
    fused_small_k = reciprocal_rank_fusion(ranking, k=1)
    assert [item for item, _ in fused_default] == [item for item, _ in fused_small_k] == ["a", "b", "c"]
    # smaller k spreads scores out more
    assert fused_small_k[0][1] > fused_default[0][1]
