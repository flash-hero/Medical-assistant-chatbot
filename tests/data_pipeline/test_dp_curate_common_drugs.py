from data_pipeline.curate_common_drugs import select, wanted_keys


def _label(doc_id: str, key: str) -> dict[str, object]:
    return {"doc_id": f"openfda_labels:{doc_id}", "metadata": {"ingredient_key": key}}


def test_one_single_ingredient_label_per_medicine_using_usan_or_inn() -> None:
    keys = wanted_keys(
        [
            {"inn": "paracetamol", "usan": "acetaminophen"},
            {"inn": "metformin"},
            {"inn": "salbutamol", "usan": "albuterol"},
            {"inn": "nefopam"},
        ]
    )
    labels = [
        _label("a", "acetaminophen + caffeine"),  # combination: never selected
        _label("b", "acetaminophen"),
        _label("c", "metformin"),
        _label("d", "metformin"),  # a second label for the same medicine is ignored
        _label("e", "albuterol"),
        _label("f", "Sertraline"),  # not in the list
    ]
    result = select(labels, keys)
    assert result.doc_ids == ("openfda_labels:b", "openfda_labels:e", "openfda_labels:c")
    assert result.matched == ("acetaminophen", "albuterol", "metformin")
    assert result.missing == ("nefopam",)
