"""Retrieval evaluation (P3B): gold sets, metrics, ablations, confidence calibration, gate records.

gold/            *.jsonl gold queries (status llm_generated_unreviewed until a human reviews them)
gold.py          GoldQuery schema, loading, passage sampling
generate.py      gold generation with the REWRITE-role model in batches (call budget enforced)
metrics.py       recall@k, MRR, nDCG@k, percentiles
calibrate.py     logistic confidence model fitted on answerable vs out-of-corpus queries
evaluate.py      runs the retriever over the gold set for each ablation, aggregates, writes reports
resume_check.py  measures repeat embedding calls after a killed build (gate rag.resume_repeat_embeds)
"""
