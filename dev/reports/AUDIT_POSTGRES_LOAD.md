# Audit Standards PostgreSQL Load

Created: 2026-04-28

## Source

Audit standard data was loaded from:

```bash
/home/shin/Project/_AuditStandard_parsing/output/json/*.json
```

Excluded metadata files:

- `METRICS.json`
- `EMBED_METRICS.json`
- `EMBED_METRICS.idempotency.json`
- `PHASE4E_METRICS.json`

Embeddings were read from:

```bash
/home/shin/Project/_AuditStandard_parsing/.embed_cache.sqlite
```

No Upstage API calls were needed. Chunk vectors and summary vectors were cache hits.

## Target

The load writes to the PostgreSQL `audit` schema in the existing `DATABASE_URL`.
It does not mix audit standards with K-IFRS rows in `public`.

Tables:

- `audit.standards`
- `audit.standard_summaries`
- `audit.chunks`
- `audit.paragraph_links`
- `audit.footnotes`

`standards` and `chunks` include `metadata jsonb` columns to preserve audit-specific
fields such as `kind`, `section`, `heading_trail`, `appendix_index`,
`special_appendix_name`, `table_cells`, `source_idx`, and split metadata.

## Loader

Script:

```bash
python dev/scripts/load_audit_json_to_pg.py --dry-run
python dev/scripts/load_audit_json_to_pg.py --schema audit --rebuild
```

Useful options:

- `--json-dir`: override source JSON directory.
- `--cache-path`: override SQLite embedding cache.
- `--schema`: target PostgreSQL schema, default `audit`.
- `--rebuild`: drop and recreate the target schema. Refuses `public`.
- `--skip-embedding`: load rows with null vectors.
- `--allow-api`: call Upstage for cache misses.
- `--allow-missing-embeddings`: permit null vectors on cache misses.

## Load Result

```text
standards: 39
summaries: 39
chunks: 10348
paragraph_links: 1788
chunk_embedding_hits: 10348
summary_embedding_hits: 39
api_embedding_calls: 0
missing_embeddings: 0
elapsed_seconds: 115.61
```

Database verification:

```text
audit.standards = 39
audit.standard_summaries = 39
audit.chunks = 10348
audit.paragraph_links = 1788
chunks with null embedding = 0
summaries with null embedding = 0
```

Families loaded:

```text
ASSR: 1
FRMK: 1
ISA: 36
ISQM: 1
```

## Notes

The audit JSON stores embeddings as `null`; vectors are reconstructed from the
SQLite cache using the AuditStandard key formula:

```text
sha256("embedding-passage:passage:{text}")[:16]
```

`ISA-200` and `ISA-1200` summary embeddings use the AuditStandard truncation rule
of 3,950 `cl100k_base` tokens. The loader uses this same rule and falls back to
the AuditStandard virtualenv for `tiktoken` if this repository does not have it.
