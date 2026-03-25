"""K-IFRS 검색 도구 — LangChain @tool 데코레이터."""

from langchain_core.tools import tool

from app.db import get_connection, release_connection
from app.embedder import embed_query

# 컴포넌트 정렬 순서: 본문 → 정의 → 적용지침 → 경과규정
_COMPONENT_ORDER = {"main": 0, "definitions": 1, "ag": 2, "transition": 3}
_COMPONENT_LABEL = {
    "main": "본문",
    "ag": "적용지침",
    "definitions": "정의",
    "transition": "경과규정",
}


def _step1_identify_standard(
    conn, query_emb: list[float], top_k: int = 3
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


def _step2_search_authoritative(
    conn, query_emb: list[float], standard_id: str, top_k: int = 10
) -> tuple[list[tuple], list[str]]:
    """Step 2: 기준서 내 Level 1 문단 벡터 검색."""
    rows = conn.execute(
        """
        SELECT chunk_id, para_number, component, section_title,
               content_markdown,
               1 - (embedding <=> %s::vector) AS similarity
        FROM chunks
        WHERE standard_id = %s AND authority = 1
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (query_emb, standard_id, query_emb, top_k),
    ).fetchall()

    rows_sorted = sorted(
        rows, key=lambda r: (_COMPONENT_ORDER.get(r[2], 99), -r[5])
    )
    para_numbers = [r[1] for r in rows if r[1]]
    return rows_sorted, para_numbers


def _step3_4_find_related(
    conn, standard_id: str, para_numbers: list[str], component: str, top_k: int = 5
) -> list[tuple]:
    """Step 3/4: paragraph_links를 통해 관련 IE/BC 청크 조회."""
    if not para_numbers:
        return []

    placeholders = ",".join(["%s"] * len(para_numbers))
    return conn.execute(
        f"""
        SELECT DISTINCT c.chunk_id, c.para_number, c.section_title,
               c.content_markdown,
               pl.target_para_start, pl.target_para_end, pl.link_type
        FROM paragraph_links pl
        JOIN chunks c ON c.chunk_id = pl.source_chunk_id
        WHERE pl.standard_id = %s
          AND pl.source_component = %s
          AND pl.target_para_start IN ({placeholders})
        LIMIT %s
        """,
        (standard_id, component, *para_numbers, top_k),
    ).fetchall()


def _build_context(
    conn,
    standard_id: str,
    query: str,
    main_chunks: list[tuple],
    ie_results: list[tuple] | None = None,
    bc_results: list[tuple] | None = None,
) -> str:
    """4단계 결과를 LLM 컨텍스트로 포맷팅."""
    row = conn.execute(
        "SELECT title, definitions_text FROM standard_summaries WHERE standard_id = %s",
        (standard_id,),
    ).fetchone()
    title = row[0] if row else standard_id
    definitions = row[1] if row and row[1] else ""

    ctx: list[str] = []
    ctx.append(f"# {standard_id} {title}")
    ctx.append(f"사용자 질문: {query}\n")

    # 정의
    if definitions:
        ctx.append("## 용어 정의 [참조]")
        ctx.append(definitions[:3000])
        ctx.append("")

    # Step 2: 본문 + AG
    ctx.append("## 적용 문단 [Authoritative, Level 1]")
    for chunk_id, para, comp, section, md, sim in main_chunks:
        label = _COMPONENT_LABEL.get(comp, comp)
        ctx.append(f"\n**문단 {para or 'N/A'}** ({label}, {section or '-'}, 유사도: {sim:.3f})")
        ctx.append(md[:800])
    ctx.append("")

    # Step 3: IE
    if ie_results:
        ctx.append("## 적용사례 [Non-authoritative, Level 4]")
        for chunk_id, para, section, md, ts, te, lt in ie_results:
            target = f"{ts}~{te}" if te else ts
            ctx.append(f"\n**{para or 'IE'}** ({section or '-'}) → 본문 문단 {target}")
            ctx.append(md[:500])
        ctx.append("")

    # Step 4: BC
    if bc_results:
        ctx.append("## 결론도출근거 [Non-authoritative, Level 4]")
        ctx.append(
            "*주의: 결론도출근거는 기준서의 일부를 구성하지 않습니다. "
            "본문과 충돌 시 본문이 우선합니다.*\n"
        )
        for chunk_id, para, section, md, ts, te, lt in bc_results:
            target = f"{ts}~{te}" if te else ts
            ctx.append(f"\n**{para or 'BC'}** ({section or '-'}) → 본문 문단 {target}")
            ctx.append(md[:500])

    return "\n".join(ctx)


@tool
def search_ifrs(query: str) -> str:
    """K-IFRS 기준서를 검색합니다. 사용자의 회계 관련 질문에 대해
    관련 기준서를 식별하고, 적용 문단(본문/적용지침)을 벡터 검색한 뒤,
    관련 적용사례(IE)와 결론도출근거(BC)까지 포함한 종합 컨텍스트를 반환합니다.

    Args:
        query: 검색할 회계 관련 질문 (예: "충당부채 인식 조건", "리스 식별 기준")
    """
    conn = get_connection()
    try:
        query_emb = embed_query(query)

        # Step 1: 기준서 식별
        standards = _step1_identify_standard(conn, query_emb)
        if not standards:
            return "관련 기준서를 찾을 수 없습니다."

        selected_id = standards[0][0]
        selected_title = standards[0][1]
        selected_sim = standards[0][2]

        # 기준서 식별 결과 헤더
        header_lines = ["## 기준서 식별 결과"]
        for sid, stitle, ssim in standards:
            marker = " ← 선택됨" if sid == selected_id else ""
            header_lines.append(f"- {sid} {stitle} (유사도: {ssim:.3f}){marker}")
        header_lines.append("")

        # Step 2: Level 1 문단 검색
        main_chunks, para_nums = _step2_search_authoritative(
            conn, query_emb, selected_id
        )

        # Step 3: IE 적용사례
        ie_results = _step3_4_find_related(conn, selected_id, para_nums, "ie")

        # Step 4: BC 결론도출근거
        bc_results = _step3_4_find_related(conn, selected_id, para_nums, "bc")

        # 컨텍스트 조합
        context = _build_context(
            conn, selected_id, query, main_chunks, ie_results, bc_results
        )

        return "\n".join(header_lines) + "\n" + context

    finally:
        release_connection(conn)


@tool
def get_standard_info(standard_id: str) -> str:
    """특정 K-IFRS 기준서의 메타데이터를 조회합니다.
    기준서 제목, 유형, 구성요소, 청크 수, 한국 고유 추가사항 여부 등을 반환합니다.

    Args:
        standard_id: 기준서 ID (예: "K-IFRS 1115", "K-IFRS 1037")
    """
    conn = get_connection()
    try:
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

        # 요약 정보 추가
        summary = conn.execute(
            "SELECT scope_text FROM standard_summaries WHERE standard_id = %s",
            (standard_id,),
        ).fetchone()
        if summary and summary[0]:
            lines.append(f"\n## 적용범위\n{summary[0][:1000]}")

        return "\n".join(lines)

    finally:
        release_connection(conn)
