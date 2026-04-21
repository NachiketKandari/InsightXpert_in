"""Few-shot retrieval over BIRD train QA pairs.

Pre-build (one-time, offline):
- ``sampler.sample_pairs`` — pick N pairs per DB from BIRD train, dedupe vs. the
  benchmark we evaluate against, and pre-parse the gold SQL into (table, col)
  pairs so retrieval is O(lookup).
- ``embedder.build`` — embed the sampled questions and persist them next to
  ``qa_pairs.json``.

Runtime:
- ``retriever.FewShotRetriever`` — load the cached pairs+embeddings, embed an
  incoming question, and return the most similar pair within the same db_id.
"""
