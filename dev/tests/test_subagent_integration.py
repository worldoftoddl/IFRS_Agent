"""Phase 2 — retrieval-distiller 서브에이전트 통합 테스트.

검증 대상:
- SUBAGENT_RETRIEVAL_PROMPT: 서브에이전트 시스템 프롬프트 내용
- SUBAGENT_CONFIGS: deepagents에 전달되는 서브에이전트 설정
- MAIN_TOOLS: 메인 에이전트의 직접 도구 목록 (search_ifrs 제거 확인)
- SYSTEM_PROMPT: 메인 에이전트 프롬프트에 서브에이전트 위임 지시 포함
"""

from dotenv import load_dotenv

load_dotenv()


class TestSubagentPrompt:
    """서브에이전트 시스템 프롬프트."""

    def test_prompt_is_importable_non_empty_string(self):
        from app.subagent_prompts import SUBAGENT_RETRIEVAL_PROMPT

        assert isinstance(SUBAGENT_RETRIEVAL_PROMPT, str)
        assert len(SUBAGENT_RETRIEVAL_PROMPT) > 200

    def test_prompt_mentions_all_three_tools(self):
        """3개 도구 이름이 모두 프롬프트에 명시되어야 한다."""
        from app.subagent_prompts import SUBAGENT_RETRIEVAL_PROMPT

        assert "retrieve_ifrs" in SUBAGENT_RETRIEVAL_PROMPT
        assert "lookup_paragraph" in SUBAGENT_RETRIEVAL_PROMPT
        assert "search_single_standard" in SUBAGENT_RETRIEVAL_PROMPT

    def test_kifrs_prompt_mentions_dense_reranker_without_bm25(self):
        from app.subagent_prompts import SUBAGENT_RETRIEVAL_PROMPT

        assert "Dense summary 검색" in SUBAGENT_RETRIEVAL_PROMPT
        assert "Dense passage 검색" in SUBAGENT_RETRIEVAL_PROMPT
        assert "Cohere Reranker" in SUBAGENT_RETRIEVAL_PROMPT
        assert "BM25" not in SUBAGENT_RETRIEVAL_PROMPT
        assert "RRF" not in SUBAGENT_RETRIEVAL_PROMPT
        assert "하이브리드" not in SUBAGENT_RETRIEVAL_PROMPT

    def test_audit_prompt_mentions_dense_reranker_without_bm25(self):
        from app.subagent_prompts import AUDIT_SUBAGENT_RETRIEVAL_PROMPT

        assert "retrieve_audit_standards" in AUDIT_SUBAGENT_RETRIEVAL_PROMPT
        assert "lookup_audit_paragraph" in AUDIT_SUBAGENT_RETRIEVAL_PROMPT
        assert "search_single_audit_standard" in AUDIT_SUBAGENT_RETRIEVAL_PROMPT
        assert "Dense" in AUDIT_SUBAGENT_RETRIEVAL_PROMPT
        assert "Reranker" in AUDIT_SUBAGENT_RETRIEVAL_PROMPT
        assert "BM25는 사용하지 않습니다" in AUDIT_SUBAGENT_RETRIEVAL_PROMPT

    def test_prompt_specifies_return_format(self):
        """반환 형식(synthesis + chunks + why_relevant)이 프롬프트에 포함되어야 한다."""
        from app.subagent_prompts import SUBAGENT_RETRIEVAL_PROMPT

        assert "synthesis" in SUBAGENT_RETRIEVAL_PROMPT
        assert "chunks" in SUBAGENT_RETRIEVAL_PROMPT
        assert "why_relevant" in SUBAGENT_RETRIEVAL_PROMPT
        # 원본+요약 반환이 핵심이므로 original_text 명시
        assert "original_text" in SUBAGENT_RETRIEVAL_PROMPT

    def test_prompt_forbids_fabrication(self):
        """문단 번호·기준서 ID 추측을 금지하는 지시가 있어야 한다."""
        from app.subagent_prompts import SUBAGENT_RETRIEVAL_PROMPT

        # "추측 금지" 또는 "보존" 류의 지시
        assert any(
            kw in SUBAGENT_RETRIEVAL_PROMPT
            for kw in ["추측", "보존", "조작", "그대로"]
        ), "원문 보존/추측 금지 지시가 없음"

    def test_prompt_has_no_code_blocks(self):
        """프롬프트에 마크다운 코드 블록(```)이 없어야 한다 — Haiku 모방 방지."""
        from app.subagent_prompts import SUBAGENT_RETRIEVAL_PROMPT

        assert SUBAGENT_RETRIEVAL_PROMPT.count("```") == 0, (
            "프롬프트에 마크다운 코드 블록이 존재 — 서브에이전트가 이를 모방할 위험"
        )

    def test_prompt_specifies_output_starts_with_brace(self):
        """출력이 { 로 시작해야 한다는 규칙이 명시되어야 한다."""
        from app.subagent_prompts import SUBAGENT_RETRIEVAL_PROMPT

        assert "`{`" in SUBAGENT_RETRIEVAL_PROMPT or "첫 글자" in SUBAGENT_RETRIEVAL_PROMPT, (
            "출력 시작 문자 규칙이 프롬프트에 없음"
        )


class TestMainAgentTools:
    """메인 에이전트의 직접 도구 구성."""

    def test_main_tools_exported(self):
        from app.agent import MAIN_TOOLS

        assert isinstance(MAIN_TOOLS, list)
        assert len(MAIN_TOOLS) > 0

    def test_main_tools_does_not_include_search_ifrs(self):
        """옵션 A: search_ifrs는 서브에이전트 경유. 메인에서 제거."""
        from app.agent import MAIN_TOOLS

        tool_names = {t.name for t in MAIN_TOOLS}
        assert "search_ifrs" not in tool_names, (
            f"search_ifrs가 메인 도구에 남아있음: {tool_names}"
        )

    def test_main_tools_keeps_ie_bc_metadata(self):
        """search_ifrs_examples, search_ifrs_rationale, get_standard_info는 유지."""
        from app.agent import MAIN_TOOLS

        tool_names = {t.name for t in MAIN_TOOLS}
        assert "search_ifrs_examples" in tool_names
        assert "search_ifrs_rationale" in tool_names
        assert "get_standard_info" in tool_names

    def test_main_tools_does_not_include_direct_audit_search(self):
        from app.agent import MAIN_TOOLS

        tool_names = {t.name for t in MAIN_TOOLS}
        assert "search_audit_standards_k1" not in tool_names
        assert "search_audit_standards_k3" not in tool_names
        assert "search_audit_standards_k5" not in tool_names


class TestSubagentConfigs:
    """deepagents subagents 파라미터 구성."""

    def test_subagent_configs_exported(self):
        from app.agent import SUBAGENT_CONFIGS

        assert isinstance(SUBAGENT_CONFIGS, list)
        assert len(SUBAGENT_CONFIGS) >= 1

    def test_retrieval_distiller_exists(self):
        from app.agent import SUBAGENT_CONFIGS

        names = [cfg["name"] for cfg in SUBAGENT_CONFIGS]
        assert "retrieval-distiller" in names
        assert "audit-retrieval-distiller" in names

    def test_retrieval_distiller_has_required_fields(self):
        from app.agent import SUBAGENT_CONFIGS

        distiller = next(
            c for c in SUBAGENT_CONFIGS if c["name"] == "retrieval-distiller"
        )
        assert "description" in distiller and distiller["description"]
        assert "system_prompt" in distiller and distiller["system_prompt"]
        assert "tools" in distiller and len(distiller["tools"]) == 3

    def test_retrieval_distiller_has_three_subagent_tools(self):
        """retrieve_ifrs + lookup_paragraph + search_single_standard."""
        from app.agent import SUBAGENT_CONFIGS

        distiller = next(
            c for c in SUBAGENT_CONFIGS if c["name"] == "retrieval-distiller"
        )
        tool_names = {t.name for t in distiller["tools"]}
        assert tool_names == {
            "retrieve_ifrs",
            "lookup_paragraph",
            "search_single_standard",
        }, f"unexpected tools: {tool_names}"

    def test_retrieval_distiller_uses_haiku(self):
        """비용 최소화를 위해 Haiku 모델 사용."""
        from app.agent import SUBAGENT_CONFIGS

        distiller = next(
            c for c in SUBAGENT_CONFIGS if c["name"] == "retrieval-distiller"
        )
        model = distiller.get("model", "")
        model_str = model if isinstance(model, str) else str(model)
        assert "haiku" in model_str.lower(), f"haiku 모델 아님: {model_str}"

    def test_audit_retrieval_distiller_has_three_tools(self):
        from app.agent import SUBAGENT_CONFIGS

        distiller = next(
            c for c in SUBAGENT_CONFIGS if c["name"] == "audit-retrieval-distiller"
        )
        tool_names = {t.name for t in distiller["tools"]}
        assert tool_names == {
            "retrieve_audit_standards",
            "lookup_audit_paragraph",
            "search_single_audit_standard",
        }, f"unexpected tools: {tool_names}"


class TestMainSystemPrompt:
    """메인 에이전트 프롬프트의 서브에이전트 위임 지시."""

    def test_main_prompt_mentions_retrieval_distiller(self):
        from app.prompts import SYSTEM_PROMPT

        assert "retrieval-distiller" in SYSTEM_PROMPT, (
            "메인 프롬프트에 서브에이전트 이름이 없음"
        )
        assert "audit-retrieval-distiller" in SYSTEM_PROMPT

    def test_main_prompt_no_longer_promotes_search_ifrs_directly(self):
        """메인 프롬프트에서 'search_ifrs 도구로 검색' 같은 직접 호출 지시 제거."""
        from app.prompts import SYSTEM_PROMPT

        # search_ifrs를 도구로 쓰라는 직접 지시어가 없어야 함
        # (단, search_ifrs_examples / search_ifrs_rationale는 여전히 언급 가능)
        # 간단 검증: "search_ifrs 도구로" / "`search_ifrs` 도구" 패턴 부재
        forbidden_phrases = [
            "`search_ifrs`로",
            "`search_ifrs` 도구로",
            "search_ifrs를 사용",
            "search_ifrs 도구를 사용",
        ]
        for phrase in forbidden_phrases:
            assert phrase not in SYSTEM_PROMPT, (
                f"메인 프롬프트에 제거되어야 할 지시: {phrase}"
            )


class TestAgentConstruction:
    """agent 객체가 정상 생성되는지."""

    def test_agent_builds_successfully(self):
        from app.agent import agent

        assert agent is not None
        # CompiledStateGraph는 invoke 메서드를 가진다
        assert hasattr(agent, "invoke")
