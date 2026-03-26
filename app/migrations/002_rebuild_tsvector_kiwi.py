"""002: kiwipiepy 형태소 분석으로 content_tsv 재빌드.

simple(공백분리) → kiwipiepy(형태소분석) 토큰화로 전환.
기존 트리거는 제거 (Python 형태소 분석을 SQL 트리거에서 호출 불가).
"""

import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv

load_dotenv()

import psycopg
from psycopg.rows import dict_row

from app.tokenizer import tokenize_for_index

BATCH_SIZE = 500


def main():
    conninfo = __import__("os").environ.get("DATABASE_URL", "dbname=kifrs")
    conn = psycopg.connect(conninfo, autocommit=True, row_factory=dict_row)

    # 1. 기존 트리거 제거 (kiwipiepy는 SQL 트리거에서 호출 불가)
    conn.execute("DROP TRIGGER IF EXISTS trg_chunks_tsv ON chunks")
    conn.execute("DROP FUNCTION IF EXISTS chunks_tsv_trigger()")
    print("[1/4] 기존 트리거 제거 완료")

    # 2. 전체 행 수 확인
    total = conn.execute("SELECT count(*) AS cnt FROM chunks").fetchone()["cnt"]
    print(f"[2/4] 전체 {total}행 토큰화 시작 (배치 {BATCH_SIZE})")

    # 3. 배치 처리: content_text → kiwipiepy → content_tsv 업데이트
    offset = 0
    updated = 0
    while offset < total:
        rows = conn.execute(
            "SELECT chunk_id, content_text FROM chunks ORDER BY chunk_id LIMIT %s OFFSET %s",
            (BATCH_SIZE, offset),
        ).fetchall()

        if not rows:
            break

        for row in rows:
            tokenized = tokenize_for_index(row["content_text"])
            conn.execute(
                "UPDATE chunks SET content_tsv = to_tsvector('simple', %s) WHERE chunk_id = %s",
                (tokenized, row["chunk_id"]),
            )
            updated += 1

        offset += BATCH_SIZE
        print(f"  진행: {min(offset, total)}/{total} ({offset * 100 // total}%)")

    print(f"[3/4] {updated}행 토큰화 완료")

    # 4. GIN 인덱스 리빌드
    conn.execute("REINDEX INDEX idx_chunks_content_tsv")
    print("[4/4] GIN 인덱스 리빌드 완료")

    conn.close()
    print(f"\n마이그레이션 완료: {updated}행 kiwipiepy 토큰화 적용")


if __name__ == "__main__":
    main()
