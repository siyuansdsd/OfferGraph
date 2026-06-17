"""LinkedIn Master agent builder.

The LinkedIn Master creates image+text LinkedIn post drafts and routes publishing
through the LinkedIn editor tool, which owns auth approval and browser flow gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Sequence

from langchain.agents import create_agent
from langchain_core.tools import BaseTool

from agent.model_selection import resolve_model_reference
from agent.prompt import render_prompt
from config.env import get_env
from tools.file_tools import ls, read_file, write_file
from tools.image_tools import linkedin_image_search, openai_image_generator
from tools.linkedin.content_editor import linkedin_editor
from tools.research_tools import get_today_str, tavily_search, think_tool
from tools.state import PlanMasterState


LINKEDIN_MASTER_AGENT_NAME = "linkedin-master"
DEFAULT_MODEL_ENV = "OFFERGRAPH_LINKEDIN_MASTER_MODEL"
DEFAULT_MODEL = "openai:gpt-4o-mini"
PublishPolicy = Literal["draft_only", "publish_after_confirmation"]


@dataclass(frozen=True)
class LinkedInMasterConfig:
    """Configuration for LinkedIn Master agent construction."""

    industry: str = "AI Engineer and Software Engineer"
    extra_need: str = (
        "Good performance of https://github.com/siyuansdsd/OfferGraph, "
        "and positive project signals such as stars or pull requests when confirmed."
    )
    brand_name: str = "OfferGraph"
    audience: str = "job seekers, AI builders, and software engineers"
    tone: str = "practical, concise, analytical, and founder-style"
    publish_policy: PublishPolicy = "publish_after_confirmation"
    date: str | None = None

    @property
    def resolved_date(self) -> str:
        """Return configured date or today's date."""
        return self.date or get_today_str()


def get_default_model() -> str:
    """Return the default model identifier for LinkedIn Master."""
    return get_env(DEFAULT_MODEL_ENV, DEFAULT_MODEL) or DEFAULT_MODEL


def build_linkedin_master_prompt(config: LinkedInMasterConfig | None = None) -> str:
    """Build the LinkedIn Master structured system prompt."""
    active_config = config or LinkedInMasterConfig()
    return render_prompt(
        "linkedin_master",
        date=active_config.resolved_date,
        industry=active_config.industry,
        extra_need=active_config.extra_need,
        brand_name=active_config.brand_name,
        audience=active_config.audience,
        tone=active_config.tone,
        publish_policy=active_config.publish_policy,
    )


def get_linkedin_master_tools() -> list[BaseTool]:
    """Return tools available to the LinkedIn Master agent."""
    return [
        tavily_search,
        think_tool,
        ls,
        read_file,
        write_file,
        linkedin_image_search,
        openai_image_generator,
        linkedin_editor,
    ]


def create_linkedin_master_agent(
    model: str | Any | None = None,
    *,
    config: LinkedInMasterConfig | None = None,
    extra_tools: Sequence[BaseTool] | None = None,
) -> Any:
    """Create the LinkedIn Master agent graph."""
    active_model = resolve_model_reference(model or get_default_model()) or DEFAULT_MODEL
    active_config = config or LinkedInMasterConfig()
    tools = [*get_linkedin_master_tools(), *(extra_tools or [])]

    return create_agent(
        model=active_model,
        tools=tools,
        system_prompt=build_linkedin_master_prompt(active_config),
        state_schema=PlanMasterState,
        name=LINKEDIN_MASTER_AGENT_NAME,
    )


__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_MODEL_ENV",
    "LINKEDIN_MASTER_AGENT_NAME",
    "LinkedInMasterConfig",
    "PublishPolicy",
    "build_linkedin_master_prompt",
    "create_linkedin_master_agent",
    "get_default_model",
    "get_linkedin_master_tools",
]
