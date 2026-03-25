"""K-IFRS 질의응답 Agent — DeepAgents + LangGraph."""

from dotenv import load_dotenv

load_dotenv()

from deepagents import create_deep_agent  # noqa: E402

from app.prompts import SYSTEM_PROMPT  # noqa: E402
from app.tools import get_standard_info, search_ifrs  # noqa: E402

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    tools=[search_ifrs, get_standard_info],
    system_prompt=SYSTEM_PROMPT,
    name="kifrs-agent",
)
