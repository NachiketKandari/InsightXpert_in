# Few-shot retrieval bank

Per-DB BIRD-train QA pairs + pre-computed question embeddings used by
`services/few_shot_service.py` to thread a "similar example" into the
SQL-generator prompt at chat time.

## Files

| File | What it is |
| ---- | ---------- |
| `few_shot_mini_dev.json` | `{db_id: [{question, gold_sql, columns?}, ...]}` — pairs sampled by `vendored/pipeline_core/few_shot/sampler.py` from BIRD train.json. |
| `few_shot_mini_dev.npz` | Per-DB embedding matrix, key `emb__<db_id>`, dtype `float16`, dim `1536`. Row order matches the JSON pair order. L2-normalized at the stored dim. |

## Coverage

Ten bundled DBs: `california_schools`, `card_games`, `codebase_community`,
`european_football_2`, `financial`, `formula_1`, `student_club`, `superhero`,
`thrombosis_prediction`, `toxicology` — 20 pairs each, 200 total.

## Why these dimensions

`gemini-embedding-001` natively produces 3072-dim float32 vectors; that
matrix would weigh ~2.4 MB at 200 rows. Gemini embeddings are Matryoshka,
so the leading prefix carries the same semantic signal — we slice to 1536
dims and store as float16, dropping the on-disk size to ~600 KB. Retrieval
applies the same slice + L2-renorm to the live query embedding before
cosine-matching, so accuracy is preserved at this prefix length.

## Regenerating

The bank is built once (offline) from BIRD train.json plus per-DB schema
profiles. The vendored builder lives at
`vendored/pipeline_core/few_shot/embedder.py` (`build_index`). Outputs full
3072-dim float32; subset/truncate/cast back to the layout above before
committing. Source-of-truth bank in this slice came from
`Private/InsightXpert-Research/few_shot/`.
