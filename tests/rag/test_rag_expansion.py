import pytest

from rag.expansion import Sibling, expand_window, merge_overlapping


def test_merge_drops_the_duplicated_sentence_overlap():
    a = "First sentence here. Second sentence is shared."
    b = "Second sentence is shared. Third sentence follows."
    assert (
        merge_overlapping([a, b]) == "First sentence here. Second sentence is shared. Third sentence follows."
    )
    assert merge_overlapping([]) == ""


def test_merge_without_overlap_joins_with_a_newline_and_ignores_tiny_accidental_matches():
    assert merge_overlapping(["Alpha beta.", "Gamma delta."]) == "Alpha beta.\nGamma delta."
    # "a." also starts the next text, but a 2-char seam is below the minimum and is not trusted
    assert merge_overlapping(["Take vitamin a.", "a. Then rest."]) == "Take vitamin a.\na. Then rest."


def test_window_grows_both_ways_within_budget_and_always_keeps_the_hit():
    sibs = [Sibling(i, f"Chunk {i} text.", 100) for i in range(5)]
    win = expand_window(sibs, 2, 300)
    assert win.ordinals == (1, 2, 3)
    assert win.tokens == 300
    assert win.text.startswith("Chunk 1 text.")
    assert expand_window(sibs, 0, 250).ordinals == (0, 1)
    assert expand_window(sibs, 4, 50).ordinals == (4,)  # hit alone exceeds the budget: still returned
    with pytest.raises(ValueError, match="not among siblings"):
        expand_window(sibs, 9, 300)
