"""Retrieval-distiller 서브에이전트용 검색 도구.

메인 에이전트가 아닌 서브에이전트가 호출하는 3개 도구:
- retrieve_ifrs: 무거운 파이프라인 (hybrid RRF + reranker), raw list 반환
- lookup_paragraph: (standard_id, para_number) 직접 조회 (검색 없음)
- search_single_standard: 단일 기준서 내 Dense-only 검색 (reranker 없음)

메인 에이전트의 search_ifrs와 달리 마크다운 포맷팅 없이
dict 리스트를 반환하여 서브에이전트가 선별·요약하기 쉽게 한다.
"""

from langchain_core.tools import tool

from app.db import get_connection
from app.embedder import embed_query
from app.tools import (
    _SIMILARITY_THRESHOLD,
    _STANDARD_ID_RE,
    _step1_identify_standard,
    _step2_search_authoritative,
    _step2_search_hybrid,
)


def _row_to_dict(row: tuple, standard_id: str | None = None) -> dict:
    """(chunk_id, para_number, component, section_title, content_markdown, score, [standard_id])
    튜플을 dict로 변환."""
    return {
        "chunk_id": row[0],
        "standard_id": row[6] if len(row) > 6 else standard_id,
        "para_number": row[1],
        "component": row[2],
        "section_title": row[3],
        "content_markdown": row[4],
        "score": float(row[5]),
    }


@tool
def retrieve_ifrs(query: str) -> list[dict]:
    """K-IFRS 기준서에서 관련 문단을 하이브리드 검색합니다 (BM25+Dense RRF+Reranker).

    search_ifrs와 동일한 파이프라인이지만 마크다운 포맷팅 대신
    구조화된 dict 리스트를 반환합니다.

    Args:
        query: 검색할 회계 관련 질문

    Returns:
        검색 결과 리스트. 각 원소는 다음 키를 가집니다:
        - chunk_id, standard_id, para_number, component,
          section_title, content_markdown, score
        관련 기준서가 없으면 빈 리스트.
    """
    query_emb = embed_query(query)

    with get_connection() as conn:
        standards = _step1_identify_standard(conn, query_emb, top_k=5)
        if not standards or standards[0][2] < _SIMILARITY_THRESHOLD:
            return []

        standard_ids = [s[0] for s in standards if s[2] >= _SIMILARITY_THRESHOLD]

        # pool=20 → reranker에 충분한 후보
        main_chunks, _ = _step2_search_hybrid(
            conn, query_emb, query, standard_ids, top_k=20
        )

    if not main_chunks:
        return []

    # Cohere Reranker (graceful degradation)
    from app.reranker import rerank

    docs = [r[4] for r in main_chunks]
    reranked_indices = rerank(query, docs, top_n=10)
    main_chunks = [main_chunks[i] for i in reranked_indices]

    return [_row_to_dict(r) for r in main_chunks]


@tool
def lookup_paragraph(standard_id: str, para_number: str) -> dict | None:
    """특정 기준서의 특정 문단을 직접 조회합니다 (검색 없음, pure SQL).

    이미 확인된 문단 번호의 원문을 정확히 가져올 때 사용합니다.
    임베딩·랭킹 없이 O(1) 인덱스 조회.

    Args:
        standard_id: 기준서 ID (예: "K-IFRS 1037")
        para_number: 문단 번호 (예: "14", "한15")

    Returns:
        문단 정보 dict 또는 None (존재하지 않는 경우).
        dict 키: chunk_id, standard_id, para_number, component,
                 section_title, content_markdown
    """
    if not _STANDARD_ID_RE.match(standard_id):
        return None

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT chunk_id, standard_id, para_number, component,
                   section_title, content_markdown
            FROM chunks
            WHERE standard_id = %s AND para_number = %s
            LIMIT 1
            """,
            (standard_id, para_number),
        ).fetchone()

    if not row:
        return None

    return {
        "chunk_id": row[0],
        "standard_id": row[1],
        "para_number": row[2],
        "component": row[3],
        "section_title": row[4],
        "content_markdown": row[5],
    }


@tool
def search_single_standard(query: str, standard_id: str) -> list[dict]:
    """단일 기준서 내에서 Dense 벡터 검색만 수행합니다 (BM25/Reranker 없음).

    이미 기준서가 확정된 상태에서 추가 관련 문단을 찾을 때 사용합니다.
    retrieve_ifrs보다 훨씬 빠름(임베딩 1회 + SQL 1회).

    Args:
        query: 검색 질문
        standard_id: 대상 기준서 ID (예: "K-IFRS 1115")

    Returns:
        유사도 순 검색 결과 리스트. 각 원소는 다음 키를 가집니다:
        - chunk_id, standard_id, para_number, component,
          section_title, content_markdown, score
    """
    if not _STANDARD_ID_RE.match(standard_id):
        return []

    query_emb = embed_query(query)

    with get_connection() as conn:
        rows, _ = _step2_search_authoritative(
            conn, query_emb, standard_id, top_k=10
        )

    if not rows:
        return []

    # _step2_search_authoritative는 component 순으로 정렬된 6-tuple 반환.
    # 서브에이전트에게는 score 내림차순이 더 유용.
    rows_by_score = sorted(rows, key=lambda r: -r[5])
    return [_row_to_dict(r, standard_id=standard_id) for r in rows_by_score]
