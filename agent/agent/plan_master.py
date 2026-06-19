"""Plan Master agent builder.

This module adapts the workflow from `notebooks/4_full_agent.ipynb`:
TODO tracking, virtual files for context offloading, research tools, and
research sub-agent delegation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from deepagents import create_deep_agent
from langchain.agents import create_agent
from langchain_core.tools import BaseTool

from agent.agent.linkedin_master import (
    LINKEDIN_MASTER_AGENT_NAME,
    LinkedInMasterConfig,
    build_linkedin_master_prompt,
    get_linkedin_master_tools,
)
from agent.model_selection import resolve_model_reference
from agent.prompt import render_prompt
from config.env import get_env
from tools.file_tools import ls, read_file, write_file
from tools.research_tools import get_today_str, tavily_search, think_tool
from tools.state import PlanMasterState
from tools.todo_tools import read_todos, write_todos


PLAN_MASTER_AGENT_NAME = "plan-master"
RESEARCH_AGENT_NAME = "research-agent"
DEFAULT_MODEL_ENV = "OFFERGRAPH_PLAN_MASTER_MODEL"
DEFAULT_MODEL = "openai:gpt-4o-mini"

TODO_USAGE_INSTRUCTIONS = """Based upon the user's request:
1. Use write_todos to create a task plan at the start of non-trivial work.
2. Keep only one task in_progress at a time.
3. After completing a task, read the TODO list, reflect, and mark it completed.
4. Continue until all TODOs are completed.
"""

FILE_USAGE_INSTRUCTIONS = """Use the virtual file system to retain context:
1. Use ls to inspect saved files.
2. Use write_file to store user requests and research findings.
3. Use read_file to retrieve source details before answering.
4. Keep large raw research in files instead of active conversation context.
"""

SUBAGENT_USAGE_TEMPLATE = """You can delegate focused research tasks to sub-agents.

Available delegation pattern:
- Use `research-agent` for isolated research on one topic at a time.
- Use `linkedin-master` for LinkedIn post strategy, image+text drafting, auth-aware draft preparation, and publishing handoff.
- For LinkedIn create/open/post/publish requests, the delegated task must explicitly instruct `linkedin-master` to call `linkedin-editor` after drafting.
- If the user asked to post or publish, tell `linkedin-master` to call `linkedin-editor` with `draft_only=false` and `publish=true`; terminal y/n confirmation is still required before posting.
- If the user only asked to create or draft, tell `linkedin-master` to call `linkedin-editor` with `draft_only=true` and `publish=false`.
- Do not accept a LinkedIn delegation as complete unless the returned result includes a LinkedIn editor status.
- Use up to {max_concurrent_research_units} parallel research units when topics are independent.
- Stop after {max_researcher_iterations} delegation rounds if evidence remains insufficient.
- Today's date: {date}
"""


@dataclass(frozen=True)
class PlanMasterConfig:
    """Configuration for Plan Master agent construction."""

    max_concurrent_research_units: int = 3
    max_researcher_iterations: int = 3
    date: str | None = None
    industry: str = "AI Engineer and Software Engineer"
    extra_need: str = "Good performance of https://github.com/siyuansdsd/OfferGraph , if there's some positive effect like stars and prs, can also talk about errors"

    @property
    def resolved_date(self) -> str:
        """Return configured date or today's date."""
        return self.date or get_today_str()


def get_default_model() -> str:
    """Return the default model identifier for Plan Master."""
    return get_env(DEFAULT_MODEL_ENV, DEFAULT_MODEL) or DEFAULT_MODEL


def build_subagent_usage_instructions(config: PlanMasterConfig | None = None) -> str:
    """Render sub-agent delegation instructions."""
    active_config = config or PlanMasterConfig()
    return SUBAGENT_USAGE_TEMPLATE.format(
        max_concurrent_research_units=active_config.max_concurrent_research_units,
        max_researcher_iterations=active_config.max_researcher_iterations,
        date=active_config.resolved_date,
    )


def build_plan_master_prompt(config: PlanMasterConfig | None = None) -> str:
    """Build the Plan Master system prompt."""
    active_config = config or PlanMasterConfig()
    return render_prompt(
        "plan_master",
        date=active_config.resolved_date,
        industry=active_config.industry,
        extra_need=active_config.extra_need,
        todo_usage_instructions=TODO_USAGE_INSTRUCTIONS,
        file_usage_instructions=FILE_USAGE_INSTRUCTIONS,
        subagent_usage_instructions=build_subagent_usage_instructions(active_config),
    )


def build_researcher_prompt(config: PlanMasterConfig | None = None) -> str:
    """Build the research sub-agent prompt."""
    active_config = config or PlanMasterConfig()
    return render_prompt("researcher", date=active_config.resolved_date)


def get_research_tools() -> list[BaseTool]:
    """Return tools available to research sub-agents."""
    return [tavily_search, think_tool]


def get_plan_master_tools() -> list[BaseTool]:
    """Return tools available to the Plan Master agent."""
    return [
        ls,
        read_file,
        write_file,
        write_todos,
        read_todos,
        tavily_search,
        think_tool,
    ]


def build_research_subagent(config: PlanMasterConfig | None = None) -> dict[str, Any]:
    """Build research sub-agent configuration."""
    return {
        "name": RESEARCH_AGENT_NAME,
        "description": (
            "Delegate focused research to this sub-agent. Give it one topic at a time."
        ),
        "system_prompt": build_researcher_prompt(config),
        "tools": get_research_tools(),
    }


def build_linkedin_subagent(config: PlanMasterConfig | None = None) -> dict[str, Any]:
    """Build LinkedIn content sub-agent configuration."""
    active_config = config or PlanMasterConfig()
    linkedin_config = LinkedInMasterConfig(
        industry=active_config.industry,
        extra_need=active_config.extra_need,
        date=active_config.resolved_date,
    )
    return {
        "name": LINKEDIN_MASTER_AGENT_NAME,
        "description": (
            "Delegate LinkedIn content creation, image brief drafting, auth-aware "
            "LinkedIn editor execution, draft preparation, and publishing handoff "
            "to this sub-agent. Require it to call linkedin-editor before reporting "
            "completion."
        ),
        "system_prompt": build_linkedin_master_prompt(linkedin_config),
        "tools": get_linkedin_master_tools(),
    }


def build_plan_master_subagents(config: PlanMasterConfig | None = None) -> list[dict[str, Any]]:
    """Build all sub-agents available to Plan Master."""
    active_config = config or PlanMasterConfig()
    return [
        build_research_subagent(active_config),
        build_linkedin_subagent(active_config),
    ]


def create_plan_master_agent(
    model: str | Any | None = None,
    *,
    config: PlanMasterConfig | None = None,
    use_deepagents: bool = True,
    extra_tools: Sequence[BaseTool] | None = None,
) -> Any:
    """Create the Plan Master agent graph."""
    active_model = resolve_model_reference(model or get_default_model()) or DEFAULT_MODEL
    active_config = config or PlanMasterConfig()
    tools = [*get_plan_master_tools(), *(extra_tools or [])]
    system_prompt = build_plan_master_prompt(active_config)

    if use_deepagents:
        return create_deep_agent(
            model=active_model,
            tools=[*get_research_tools(), *(extra_tools or [])],
            system_prompt=system_prompt,
            subagents=build_plan_master_subagents(active_config),
            name=PLAN_MASTER_AGENT_NAME,
        )

    return create_agent(
        model=active_model,
        tools=tools,
        system_prompt=system_prompt,
        state_schema=PlanMasterState,
        name=PLAN_MASTER_AGENT_NAME,
    )


__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_MODEL_ENV",
    "FILE_USAGE_INSTRUCTIONS",
    "PLAN_MASTER_AGENT_NAME",
    "PlanMasterConfig",
    "RESEARCH_AGENT_NAME",
    "SUBAGENT_USAGE_TEMPLATE",
    "TODO_USAGE_INSTRUCTIONS",
    "build_linkedin_subagent",
    "build_plan_master_subagents",
    "build_plan_master_prompt",
    "build_research_subagent",
    "build_researcher_prompt",
    "build_subagent_usage_instructions",
    "create_plan_master_agent",
    "get_default_model",
    "get_plan_master_tools",
    "get_research_tools",
]
