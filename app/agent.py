"""K-IFRS 질의응답 Agent — DeepAgents + LangGraph.

langgraph.json의 "env": ".env"가 환경변수를 로딩하므로,
이 모듈에서 load_dotenv()를 호출하지 않는다.
"""

from deepagents import create_deep_agent

from app.prompts import SYSTEM_PROMPT
from app.tools import (
    get_standard_info,
    search_ifrs,
    search_ifrs_examples,
    search_ifrs_rationale,
)

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    tools=[search_ifrs, search_ifrs_examples, search_ifrs_rationale, get_standard_info],
    system_prompt=SYSTEM_PROMPT,
    name="kifrs-agent",
)
