"""K-IFRS 검색 도구 — LangChain @tool 데코레이터."""

import logging
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass

import psycopg
from langchain_core.tools import tool

from app.db import get_connection
from app.embedder import embed_query

logger = logging.getLogger(__name__)

# standard_id 유효성 검증 패턴
_STANDARD_ID_RE = re.compile(r"^K-IFRS\s+\d{4}$")

# ---------------------------------------------------------------------------
# Step 2 결과 캐시 (동일 Agent 턴 내 중복 임베딩 API 호출 방지)
# ---------------------------------------------------------------------------

_STEP2_CACHE_TTL = 60  # 초
_STEP2_CACHE_MAX_SIZE = 50


@dataclass
class _Step2CacheEntry:
    query_emb: list[float]
    main_chunks: list[tuple]
    para_nums: list[str]
    created_at: float


_step2_cache: dict[tuple[str, str], _Step2CacheEntry] = {}
_step2_cache_lock = threading.Lock()


def _get_step2_cached(
    query_emb: list[float], query: str, standard_id: str
) -> tuple[list[tuple], list[str]]:
    """Step 2 결과를 캐시하여 반환. query_emb는 호출자가 미리 계산하여 전달."""
    key = (query, standard_id)
    now = time.monotonic()

    with _step2_cache_lock:
        entry = _step2_cache.get(key)
        if entry and (now - entry.created_at) < _STEP2_CACHE_TTL:
            logger.debug("Step2 캐시 히트: %s", key)
            return entry.main_chunks, entry.para_nums

    # 캐시 미스 — DB 쿼리 (lock 밖에서 실행하여 blocking 최소화)
    with get_connection() as conn:
        main_chunks, para_nums = _step2_search_authoritative(conn, query_emb, standard_id)

    with _step2_cache_lock:
        # re-check: 다른 스레드가 동시에 같은 키를 계산했을 수 있음
        entry = _step2_cache.get(key)
        if entry and (now - entry.created_at) < _STEP2_CACHE_TTL:
            return entry.main_chunks, entry.para_nums

        _step2_cache[key] = _Step2CacheEntry(
            query_emb=query_emb,
            main_chunks=main_chunks,
            para_nums=para_nums,
            created_at=now,
        )
        # 만료 항목 정리 + max size 제한
        expired = [k for k, v in _step2_cache.items() if (now - v.created_at) >= _STEP2_CACHE_TTL]
        for k in expired:
            del _step2_cache[k]
        while len(_step2_cache) > _STEP2_CACHE_MAX_SIZE:
            oldest_key = min(_step2_cache, key=lambda k: _step2_cache[k].created_at)
            del _step2_cache[oldest_key]

    return main_chunks, para_nums


def _validate_standard_id(standard_id: str) -> str | None:
    """standard_id 형식 검증. 유효하면 None, 아니면 에러 메시지 반환."""
    if not _STANDARD_ID_RE.match(standard_id):
        return f"'{standard_id}'는 유효한 기준서 ID 형식이 아닙니다. 예: 'K-IFRS 1115'"
    return None


# 컴포넌트 정렬 순서: 본문 → 정의 → 적용지침 → 경과규정
_COMPONENT_ORDER = {"main": 0, "definitions": 1, "ag": 2, "transition": 3}
_COMPONENT_LABEL = {
    "main": "본문",
    "ag": "적용지침",
    "definitions": "정의",
    "transition": "경과규정",
}

# Step 1 유사도 임계값 — 이 값 미만이면 "관련 기준서 없음" 반환
_SIMILARITY_THRESHOLD = 0.2

# 컨텍스트 포맷팅 시 최대 글자수
_DEFINITIONS_MAX_CHARS = 3000
_CHUNK_CONTENT_MAX_CHARS = 800
_RELATED_CONTENT_MAX_CHARS = 500
_SCOPE_MAX_CHARS = 1000


# ---------------------------------------------------------------------------
# 내부 검색 함수
# ---------------------------------------------------------------------------


def _step1_identify_standard(
    conn: psycopg.Connection, query_emb: list[float], top_k: int = 3
) -> list[tuple]:
    """Step 1: 쿼리에 가장 적합한 기준서 식별."""
    return conn.execute(
        """
        SELECT standard_id, title,
               1 - (embedding <=> %s::vector) AS similarity
        FROM standard_summaries
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (query_emb, query_emb, top_k),
    ).fetchall()


def _get_base_authority(conn: psycopg.Connection, standard_id: str) -> int:
    """기준서의 base_authority를 조회. 없으면 1(일반 기준서) 반환."""
    row = conn.execute(
        "SELECT base_authority FROM standards WHERE standard_id = %s",
        (standard_id,),
    ).fetchone()
    return row[0] if row else 1


def _step2_search_authoritative(
    conn: psycopg.Connection, query_emb: list[float], standard_id: str, top_k: int = 10
) -> tuple[list[tuple], list[str]]:
    """Step 2: 기준서 내 권위 문단 벡터 검색.

    authority 필터를 기준서의 base_authority에 따라 동적 적용:
    - 일반 기준서(base_authority=1): authority <= 1 (본문, AG만)
    - 개념체계(base_authority=3): authority <= 3 (개념체계 본문 포함)
    - 실무서(base_authority=4): authority <= 4 (실무서 본문 포함)
    """
    base_auth = _get_base_authority(conn, standard_id)

    rows = conn.execute(
        """
        SELECT chunk_id, para_number, component, section_title,
               content_markdown,
               1 - (embedding <=> %s::vector) AS similarity
        FROM chunks
        WHERE standard_id = %s AND authority <= %s
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (query_emb, standard_id, base_auth, query_emb, top_k),
    ).fetchall()

    rows_sorted = sorted(
        rows, key=lambda r: (_COMPONENT_ORDER.get(r[2], 99), -r[5])
    )
    para_numbers = [r[1] for r in rows if r[1]]
    return rows_sorted, para_numbers


def _step2_search_multi(
    conn: psycopg.Connection,
    query_emb: list[float],
    standard_ids: list[str],
    top_k: int = 10,
) -> tuple[list[tuple], list[str]]:
    """Step 2 복수 기준서 통합 검색.

    여러 기준서의 chunks를 한 번에 벡터 검색하여 유사도 순으로 반환.
    각 기준서의 base_authority에 맞게 authority 필터를 동적 적용.

    반환 튜플 형식: (chunk_id, para_number, component, section_title,
                    content_markdown, similarity, standard_id)
    """
    if not standard_ids:
        return [], []

    # 각 기준서의 base_authority 조회 → (standard_id, max_authority) 쌍 구성
    rows_auth = conn.execute(
        "SELECT standard_id, base_authority FROM standards WHERE standard_id = ANY(%s)",
        (list(standard_ids),),
    ).fetchall()
    auth_pairs = [(r[0], r[1]) for r in rows_auth]

    if not auth_pairs:
        return [], []

    # 단일 쿼리로 복수 기준서 통합 검색 — N+1 방지
    # UNNEST로 (standard_id, max_authority) 쌍을 전달하여 기준서별 authority 동적 필터링
    all_rows = conn.execute(
        """
        SELECT c.chunk_id, c.para_number, c.component, c.section_title,
               c.content_markdown,
               1 - (c.embedding <=> %s::vector) AS similarity,
               c.standard_id
        FROM chunks c
        JOIN UNNEST(%s::text[], %s::int[]) AS auth(sid, max_auth)
          ON c.standard_id = auth.sid AND c.authority <= auth.max_auth
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s
        """,
        (
            query_emb,
            [p[0] for p in auth_pairs],
            [p[1] for p in auth_pairs],
            query_emb,
            top_k,
        ),
    ).fetchall()

    # DB에서 이미 유사도 순 + LIMIT 적용됨
    # component 순서로 재정렬 (본문 → 정의 → AG → 경과규정)
    rows_sorted = sorted(
        all_rows, key=lambda r: (_COMPONENT_ORDER.get(r[2], 99), -r[5])
    )
    para_numbers = [r[1] for r in all_rows if r[1]]
    return rows_sorted, para_numbers


def _step3_4_find_related(
    conn: psycopg.Connection,
    standard_id: str,
    para_numbers: list[str],
    component: str,
    top_k: int = 5,
) -> list[tuple]:
    """Step 3/4: paragraph_links를 통해 관련 IE/BC 청크 조회."""
    if not para_numbers:
        return []

    return conn.execute(
        """
        SELECT DISTINCT c.chunk_id, c.para_number, c.section_title,
               c.content_markdown,
               pl.target_para_start, pl.target_para_end, pl.link_type
        FROM paragraph_links pl
        JOIN chunks c ON c.chunk_id = pl.source_chunk_id
        WHERE pl.standard_id = %s
          AND pl.source_component = %s
          AND pl.target_para_start = ANY(%s)
        LIMIT %s
        """,
        (standard_id, component, list(para_numbers), top_k),
    ).fetchall()


# ---------------------------------------------------------------------------
# 컨텍스트 포맷팅
# ---------------------------------------------------------------------------


def _format_standard_header(
    conn: psycopg.Connection, standard_id: str, query: str
) -> list[str]:
    """기준서 제목 + 용어 정의 헤더를 포맷팅."""
    row = conn.execute(
        "SELECT title, definitions_text FROM standard_summaries WHERE standard_id = %s",
        (standard_id,),
    ).fetchone()
    title = row[0] if row else standard_id
    definitions = row[1] if row and row[1] else ""

    ctx: list[str] = []
    ctx.append(f"# {standard_id} {title}")
    ctx.append(f"사용자 질문: {query}\n")

    if definitions:
        ctx.append("## 용어 정의 [참조]")
        ctx.append(definitions[:_DEFINITIONS_MAX_CHARS])
        ctx.append("")

    return ctx


def _format_main_chunks(main_chunks: list[tuple]) -> list[str]:
    """Level 1 문단 검색 결과를 포맷팅."""
    ctx: list[str] = ["## 적용 문단 [Authoritative, Level 1]"]
    for _, para, comp, section, md, sim in main_chunks:
        label = _COMPONENT_LABEL.get(comp, comp)
        ctx.append(f"\n**문단 {para or 'N/A'}** ({label}, {section or '-'}, 유사도: {sim:.3f})")
        ctx.append(md[:_CHUNK_CONTENT_MAX_CHARS])
    ctx.append("")
    return ctx


def _format_main_chunks_multi(main_chunks: list[tuple]) -> list[str]:
    """복수 기준서 통합 검색 결과를 포맷팅. 각 문단에 기준서 ID를 표시."""
    ctx: list[str] = ["## 적용 문단 [Authoritative]"]
    for row in main_chunks:
        _, para, comp, section, md, sim, std_id = row
        label = _COMPONENT_LABEL.get(comp, comp)
        ctx.append(
            f"\n**[{std_id}] 문단 {para or 'N/A'}** ({label}, {section or '-'}, 유사도: {sim:.3f})"
        )
        ctx.append(md[:_CHUNK_CONTENT_MAX_CHARS])
    ctx.append("")
    return ctx


def _format_ie_results(ie_results: list[tuple]) -> list[str]:
    """IE 적용사례 결과를 포맷팅."""
    ctx: list[str] = ["## 적용사례 [Non-authoritative, Level 4]"]
    for _, para, section, md, ts, te, _lt in ie_results:
        target = f"{ts}~{te}" if te else ts
        ctx.append(f"\n**{para or 'IE'}** ({section or '-'}) → 본문 문단 {target}")
        ctx.append(md[:_RELATED_CONTENT_MAX_CHARS])
    ctx.append("")
    return ctx


def _format_bc_results(bc_results: list[tuple]) -> list[str]:
    """BC 결론도출근거 결과를 포맷팅."""
    ctx: list[str] = [
        "## 결론도출근거 [Non-authoritative, Level 4]",
        "*주의: 결론도출근거는 기준서의 일부를 구성하지 않습니다. "
        "본문과 충돌 시 본문이 우선합니다.*\n",
    ]
    for _, para, section, md, ts, te, _lt in bc_results:
        target = f"{ts}~{te}" if te else ts
        ctx.append(f"\n**{para or 'BC'}** ({section or '-'}) → 본문 문단 {target}")
        ctx.append(md[:_RELATED_CONTENT_MAX_CHARS])
    ctx.append("")
    return ctx


def _format_identification_header(standards: list[tuple], selected_id: str) -> list[str]:
    """기준서 식별 결과 헤더를 포맷팅."""
    lines = ["## 기준서 식별 결과"]
    for sid, stitle, ssim in standards:
        marker = " ← 선택됨" if sid == selected_id else ""
        lines.append(f"- {sid} {stitle} (유사도: {ssim:.3f}){marker}")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# 공개 도구 (LangChain @tool)
# ---------------------------------------------------------------------------


@tool
def search_ifrs(query: str) -> str:
    """K-IFRS 기준서에서 Level 1(Authoritative) 문단을 검색합니다.
    일반적인 회계 관련 질문에 사용하세요.
    관련 기준서를 식별한 뒤, 기준서 본문·적용지침·정의 등 권위 있는 문단을 벡터 검색하여 반환합니다.
    적용사례(IE)나 결론도출근거(BC)는 포함되지 않습니다.
    구체적인 처리 사례가 필요하면 search_ifrs_examples를,
    기준 제정 논거가 필요하면 search_ifrs_rationale를 추가로 호출하세요.

    Args:
        query: 검색할 회계 관련 질문 (예: "충당부채 인식 조건", "리스 식별 기준")
    """
    query_emb = embed_query(query)

    with get_connection() as conn:
        # Step 1: 기준서 식별 (top-5 후보 확보)
        standards = _step1_identify_standard(conn, query_emb, top_k=5)
        if not standards:
            return "관련 기준서를 찾을 수 없습니다."

        # 유사도 임계값 필터 — top-1이 임계값 미만이면 관련 기준서 없음
        if standards[0][2] < _SIMILARITY_THRESHOLD:
            return "관련 기준서를 찾을 수 없습니다. 회계 관련 질문을 입력해 주세요."

        # 임계값 이상인 기준서만 통합 검색 대상에 포함
        standard_ids = [s[0] for s in standards if s[2] >= _SIMILARITY_THRESHOLD]

        # Step 2: 임계값 통과 기준서에서 통합 벡터 검색
        main_chunks, _ = _step2_search_multi(conn, query_emb, standard_ids)

        # 결과에서 가장 많이 등장한 기준서를 주 기준서로 판정
        if main_chunks:
            std_counts = Counter(r[6] for r in main_chunks)
            primary_id = std_counts.most_common(1)[0][0]
        else:
            primary_id = standards[0][0]

        # 컨텍스트 조합
        ctx = _format_identification_header(standards, primary_id)
        ctx.extend(_format_standard_header(conn, primary_id, query))
        ctx.extend(_format_main_chunks_multi(main_chunks))

        return "\n".join(ctx)


@tool
def search_ifrs_examples(query: str, standard_id: str) -> str:
    """특정 기준서의 적용사례(IE, Illustrative Examples)를 검색합니다.
    회계처리 방법이나 실무 적용이 필요한데 기준서 본문만으로는 부족할 때 사용하세요.
    먼저 search_ifrs로 관련 기준서를 확인한 후, 해당 기준서의 IE를 조회합니다.

    Args:
        query: 검색할 회계 관련 질문 (예: "수행의무 식별 사례")
        standard_id: 대상 기준서 ID (예: "K-IFRS 1115") — search_ifrs 결과에서 확인
    """
    if err := _validate_standard_id(standard_id):
        return err

    query_emb = embed_query(query)
    _, para_nums = _get_step2_cached(query_emb, query, standard_id)

    with get_connection() as conn:
        ie_results = _step3_4_find_related(conn, standard_id, para_nums, "ie")

        if not ie_results:
            logger.warning("IE 없음: %s, query=%s", standard_id, query)
            return f"{standard_id}에서 '{query}'와 관련된 적용사례(IE)를 찾을 수 없습니다."

        ctx = _format_standard_header(conn, standard_id, query)
        ctx.extend(_format_ie_results(ie_results))

        return "\n".join(ctx)


@tool
def search_ifrs_rationale(query: str, standard_id: str) -> str:
    """특정 기준서의 결론도출근거(BC, Basis for Conclusions)를 검색합니다.
    회계기준이 왜 그렇게 정해졌는지, 기준 제정 과정의 논거를 알고 싶을 때 사용하세요.
    먼저 search_ifrs로 관련 기준서를 확인한 후, 해당 기준서의 BC를 조회합니다.
    주의: BC는 기준서의 일부를 구성하지 않으며, 본문과 충돌 시 본문이 우선합니다.

    Args:
        query: 검색할 질문 (예: "충당부채 인식기준의 제정 배경")
        standard_id: 대상 기준서 ID (예: "K-IFRS 1037") — search_ifrs 결과에서 확인
    """
    if err := _validate_standard_id(standard_id):
        return err

    query_emb = embed_query(query)
    _, para_nums = _get_step2_cached(query_emb, query, standard_id)

    with get_connection() as conn:
        bc_results = _step3_4_find_related(conn, standard_id, para_nums, "bc")

        if not bc_results:
            logger.warning("BC 없음: %s, query=%s", standard_id, query)
            return f"{standard_id}에서 '{query}'와 관련된 결론도출근거(BC)를 찾을 수 없습니다."

        ctx = _format_standard_header(conn, standard_id, query)
        ctx.extend(_format_bc_results(bc_results))

        return "\n".join(ctx)


@tool
def get_standard_info(standard_id: str) -> str:
    """특정 K-IFRS 기준서의 메타데이터를 조회합니다.
    기준서 제목, 유형, 구성요소, 청크 수, 한국 고유 추가사항 여부 등을 반환합니다.

    Args:
        standard_id: 기준서 ID (예: "K-IFRS 1115", "K-IFRS 1037")
    """
    if err := _validate_standard_id(standard_id):
        return err

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT standard_id, title, standard_type, standard_family,
                   components, has_korean_additions, korean_paragraph_count,
                   total_chunks
            FROM standards
            WHERE standard_id = %s
            """,
            (standard_id,),
        ).fetchone()

        if not row:
            return f"기준서 '{standard_id}'를 찾을 수 없습니다."

        sid, title, stype, family, components, has_kr, kr_count, chunks = row
        lines = [
            f"# {sid} {title}",
            f"- 유형: {stype} ({family})",
            f"- 구성요소: {', '.join(components)}",
            f"- 전체 청크 수: {chunks}",
            f"- 한국 고유 추가사항: {'있음' if has_kr else '없음'}"
            + (f" ({kr_count}개 문단)" if has_kr else ""),
        ]

        summary = conn.execute(
            "SELECT scope_text FROM standard_summaries WHERE standard_id = %s",
            (standard_id,),
        ).fetchone()
        if summary and summary[0]:
            lines.append(f"\n## 적용범위\n{summary[0][:_SCOPE_MAX_CHARS]}")

        return "\n".join(lines)
