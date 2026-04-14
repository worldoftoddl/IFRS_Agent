"""K-IFRS 질의응답 Agent — LangGraph + deepagents 미들웨어.

구조:
- 메인 Agent (Sonnet 4.6): 답변 생성, BC/IE·메타데이터 직접 조회
- retrieval-distiller 서브에이전트 (Haiku 4.5): Level 1 하이브리드 검색 전담
  → 원문 + 요약을 JSON으로 반환하여 메인 컨텍스트 절감

create_deep_agent 대신 create_agent를 직접 사용하여
미들웨어 스택을 자유롭게 조합한다 (EnhancedTodoMiddleware 등).

langgraph.json의 "env": ".env"가 환경변수를 로딩하므로,
이 모듈에서 load_dotenv()를 호출하지 않는다.
"""

from deepagents._models import resolve_model
from deepagents.backends import FilesystemBackend
from deepagents.graph import BASE_AGENT_PROMPT
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.skills import SkillsMiddleware
from deepagents.middleware.subagents import SubAgentMiddleware
from deepagents.middleware.summarization import (
    SummarizationToolMiddleware,
    create_summarization_middleware,
)
from langchain.agents import create_agent
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware

from app.accounting_tools import (
    build_amortization_schedule,
    calculate_effective_interest_rate,
    calculate_present_value,
    verify_arithmetic,
)
from app.compact_middleware import MicroCompactMiddleware
from app.middleware import EnhancedTodoMiddleware
from app.prompts import SYSTEM_PROMPT
from app.subagent_prompts import SUBAGENT_RETRIEVAL_PROMPT
from app.subagent_tools import (
    lookup_paragraph,
    retrieve_ifrs,
    search_single_standard,
)
from app.task_middleware import TaskMiddleware
from app.tools import (
    get_standard_info,
    search_ifrs_examples,
    search_ifrs_rationale,
)

# ── 모델 ──────────────────────────────────────────────
MAIN_MODEL = resolve_model("anthropic:claude-sonnet-4-6")
SUBAGENT_MODEL = resolve_model("anthropic:claude-haiku-4-5-20251001")

# ── 백엔드 ────────────────────────────────────────────
backend = FilesystemBackend(root_dir="./", virtual_mode=False)

# ── 메인 에이전트 도구 ────────────────────────────────
# Level 1 검색은 서브에이전트 경유.
MAIN_TOOLS = [
    search_ifrs_examples,
    search_ifrs_rationale,
    get_standard_info,
    calculate_present_value,
    calculate_effective_interest_rate,
    build_amortization_schedule,
    verify_arithmetic,
]

# ── 서브에이전트 설정 ─────────────────────────────────
# create_deep_agent가 자동으로 채우던 기본값(middleware)을 명시적으로 설정.
SUBAGENT_CONFIGS = [
    {
        "name": "retrieval-distiller",
        "description": (
            "K-IFRS Level 1(기준서 본문·적용지침·정의) 검색 및 선별 전담 서브에이전트. "
            "사용자 질문을 받아 관련 문단을 찾고, 질의 관련 핵심만 원문+요약 JSON으로 반환. "
            "일반적인 회계 질문에는 반드시 이 서브에이전트를 먼저 호출하라."
        ),
        "system_prompt": SUBAGENT_RETRIEVAL_PROMPT,
        "tools": [retrieve_ifrs, lookup_paragraph, search_single_standard],
        "model": SUBAGENT_MODEL,
        "middleware": [
            EnhancedTodoMiddleware(),
            FilesystemMiddleware(backend=backend),
            create_summarization_middleware(SUBAGENT_MODEL, backend),
            AnthropicPromptCachingMiddleware(
                unsupported_model_behavior="ignore"
            ),
            PatchToolCallsMiddleware(),
        ],
        # 서브에이전트에는 SummarizationToolMiddleware/MicroCompact 미적용
        # 단발 검색이라 누적 컨텍스트 없음.
    },
]

# ── 메인 에이전트 미들웨어 스택 ───────────────────────
# create_deep_agent의 하드코딩 순서를 직접 조합.
# 3계층 컨텍스트 압축 (s06 패턴):
#   Layer 1 (tool_result 플레이스홀더, 조건부): MicroCompactMiddleware
#   Layer 2 (threshold auto 요약): _DeepAgentsSummarizationMiddleware
#   Layer 3 (manual tool): SummarizationToolMiddleware → compact_conversation
SUMMARIZATION = create_summarization_middleware(MAIN_MODEL, backend)

# MicroCompactMiddleware는 AnthropicPromptCachingMiddleware 앞에 배치.
# trigger_tokens(50K) 미만일 때 no-op이므로 초반 대화는 캐시 영향 없음.
MIDDLEWARE = [
    EnhancedTodoMiddleware(),
    TaskMiddleware(),
    SkillsMiddleware(backend=backend, sources=["./app/skills/"]),
    FilesystemMiddleware(backend=backend),
    SubAgentMiddleware(backend=backend, subagents=SUBAGENT_CONFIGS),
    SUMMARIZATION,
    SummarizationToolMiddleware(SUMMARIZATION),
    MicroCompactMiddleware(trigger_tokens=50_000, keep_recent=3),
    AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore"),
    PatchToolCallsMiddleware(),
]

# ── 시스템 프롬프트 합성 ──────────────────────────────
# create_deep_agent는 user_prompt + "\n\n" + BASE_AGENT_PROMPT 형태로 합성.
FINAL_SYSTEM_PROMPT = SYSTEM_PROMPT + "\n\n" + BASE_AGENT_PROMPT

# ── 에이전트 생성 ────────────────────────────────────
agent = create_agent(
    model=MAIN_MODEL,
    tools=MAIN_TOOLS,
    system_prompt=FINAL_SYSTEM_PROMPT,
    middleware=MIDDLEWARE,
    name="kifrs-agent",
).with_config({"recursion_limit": 1000})
