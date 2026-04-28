-- Remove the legacy PostgreSQL keyword-search index artifacts.
-- Run manually against the active DATABASE_URL after confirming the runtime has
-- been migrated to pgvector dense retrieval.

DROP TRIGGER IF EXISTS trg_chunks_tsv ON chunks;
DROP FUNCTION IF EXISTS chunks_tsv_trigger();
DROP INDEX IF EXISTS idx_chunks_content_tsv;
ALTER TABLE IF EXISTS chunks DROP COLUMN IF EXISTS content_tsv;

DO $$
BEGIN
  IF to_regclass('audit.chunks') IS NOT NULL THEN
    EXECUTE 'DROP INDEX IF EXISTS audit.audit_idx_chunks_tsv';
    EXECUTE 'ALTER TABLE audit.chunks DROP COLUMN IF EXISTS content_tsv';
  END IF;
END
$$;
