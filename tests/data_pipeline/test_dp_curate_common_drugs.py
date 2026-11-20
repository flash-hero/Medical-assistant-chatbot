from data_pipeline.curate_common_drugs import select, signature, wanted_keys


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


def test_salt_and_combination_names_match_but_exact_keys_win() -> None:
    keys = wanted_keys(
        [
            {"inn": "escitalopram"},
            {"inn": "amoxicillin and clavulanate potassium"},
            {"inn": "levodopa and carbidopa"},
            {"inn": "ethinylestradiol and levonorgestrel"},
            {"inn": "calcium carbonate"},
            {"inn": "candesartan"},
        ]
    )
    labels = [
        _label("a", "escitalopram oxalate"),
        _label("b", "amoxicillin + clavulanate"),
        _label("c", "carbidopa + entacapone + levodopa"),  # a different (triple) combination
        _label("d", "carbidopa + levodopa"),
        _label("e", "ethinyl estradiol + levonorgestrel"),
        _label("f", "calcium acetate"),  # a different calcium salt: never matched
        _label("g", "candesartan cilexetil"),
        _label("h", "candesartan"),  # the exact key wins over the salt match seen first
    ]
    result = select(labels, keys)
    assert dict(zip(result.matched, result.doc_ids, strict=True)) == {
        "amoxicillin and clavulanate potassium": "openfda_labels:b",
        "candesartan": "openfda_labels:h",
        "escitalopram": "openfda_labels:a",
        "ethinylestradiol and levonorgestrel": "openfda_labels:e",
        "levodopa and carbidopa": "openfda_labels:d",
    }
    assert result.missing == ("calcium carbonate",)


def test_signature_ignores_order_salts_and_separators() -> None:
    assert signature("Sulfamethoxazole and Trimethoprim") == signature("trimethoprim + sulfamethoxazole")
    assert signature("lithium carbonate") == ("lithium carbonate",)
