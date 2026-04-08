"""K-IFRS 질의응답 Agent — DeepAgents + LangGraph.

구조:
- 메인 Agent (Sonnet 4.6): 답변 생성, BC/IE·메타데이터 직접 조회
- retrieval-distiller 서브에이전트 (Haiku 4.5): Level 1 하이브리드 검색 전담
  → 원문 + 요약을 JSON으로 반환하여 메인 컨텍스트 절감

langgraph.json의 "env": ".env"가 환경변수를 로딩하므로,
이 모듈에서 load_dotenv()를 호출하지 않는다.
"""

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from deepagents.middleware.subagents import SubAgent

from app.prompts import SYSTEM_PROMPT
from app.subagent_prompts import SUBAGENT_RETRIEVAL_PROMPT
from app.subagent_tools import (
    lookup_paragraph,
    retrieve_ifrs,
    search_single_standard,
)
from app.accounting_tools import (
    build_amortization_schedule,
    calculate_effective_interest_rate,
    calculate_present_value,
)
from app.tools import (
    get_standard_info,
    search_ifrs_examples,
    search_ifrs_rationale,
)

# 메인 에이전트가 직접 쥐는 도구 — Level 1 검색은 서브에이전트 경유.
MAIN_TOOLS = [
    search_ifrs_examples,
    search_ifrs_rationale,
    get_standard_info,
    calculate_present_value,
    calculate_effective_interest_rate,
    build_amortization_schedule,
]

# retrieval-distiller: Level 1 검색 + 선별·요약 전담 서브에이전트.
SUBAGENT_CONFIGS: list[SubAgent] = [
    {
        "name": "retrieval-distiller",
        "description": (
            "K-IFRS Level 1(기준서 본문·적용지침·정의) 검색 및 선별 전담 서브에이전트. "
            "사용자 질문을 받아 관련 문단을 찾고, 질의 관련 핵심만 원문+요약 JSON으로 반환. "
            "일반적인 회계 질문에는 반드시 이 서브에이전트를 먼저 호출하라."
        ),
        "system_prompt": SUBAGENT_RETRIEVAL_PROMPT,
        "tools": [retrieve_ifrs, lookup_paragraph, search_single_standard],
        "model": "anthropic:claude-haiku-4-5-20251001",
    },
]

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    tools=MAIN_TOOLS,
    system_prompt=SYSTEM_PROMPT,
    subagents=SUBAGENT_CONFIGS,
    backend=FilesystemBackend(root_dir="./"),
    skills=["./app/skills/"],
    name="kifrs-agent",
)
