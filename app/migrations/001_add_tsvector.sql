-- 001_add_tsvector.sql
-- chunks 테이블에 tsvector 컬럼 + GIN 인덱스 추가 (BM25 하이브리드 검색용)

-- 1. content_text에 대한 tsvector 컬럼 추가
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS content_tsv tsvector;

-- 2. 기존 데이터 일괄 업데이트 (simple config = 공백 기반 토큰화, 한국어 호환)
UPDATE chunks SET content_tsv = to_tsvector('simple', content_text)
WHERE content_tsv IS NULL;

-- 3. GIN 인덱스 생성 (BM25 검색 성능)
CREATE INDEX IF NOT EXISTS idx_chunks_content_tsv ON chunks USING GIN (content_tsv);

-- 4. 향후 INSERT/UPDATE 시 자동 갱신 트리거
CREATE OR REPLACE FUNCTION chunks_tsv_trigger() RETURNS trigger AS $$
BEGIN
  NEW.content_tsv := to_tsvector('simple', NEW.content_text);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_chunks_tsv ON chunks;
CREATE TRIGGER trg_chunks_tsv
  BEFORE INSERT OR UPDATE OF content_text ON chunks
  FOR EACH ROW EXECUTE FUNCTION chunks_tsv_trigger();
