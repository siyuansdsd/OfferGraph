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
from tools.job_application.profile_store import (
    job_profile_read,
    job_profile_resolve_questions,
    job_profile_upsert,
)
from tools.linkedin.jobs import (
    linkedin_job_apply_draft,
    linkedin_job_tailored_apply_draft,
    linkedin_jobs_explorer,
)
from tools.memory_tools import memory_search
from tools.playwright_synthesizer import playwright_tool_synthesizer
from tools.research_tools import get_today_str, tavily_search, think_tool
from tools.state import PlanMasterState
from tools.todo_tools import read_todos, write_todos


PLAN_MASTER_AGENT_NAME = "plan-master"
RESEARCH_AGENT_NAME = "research-agent"
JOB_APPLICATION_AGENT_NAME = "job-application-agent"
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
- Use `job-application-agent` for job search, LinkedIn Jobs exploration, fit scoring, Share -> Copy link JD URL capture, CV/Cover Letter tailoring, and platform-aware application draft preparation.
- Use `linkedin-master` for LinkedIn post strategy, image+text drafting, auth-aware draft preparation, and publishing handoff.
- For job search or job application requests, do not stop after only asking profile questions. First create a concrete search plan, then either delegate to `job-application-agent` or directly call `linkedin-jobs-explorer` with conservative assumptions.
- If user conditions are incomplete, use the request's role title as the query, leave location empty unless provided, keep `easy_apply_only=false`, and list assumptions in the final response.
- `job-application-agent` must call `linkedin-jobs-explorer` before recommending jobs or attempting application drafts.
- For job application requests, `job-application-agent` should call `linkedin-job-tailored-apply-draft` after selecting a role, unless the user already supplied generated files. The tool must obtain the JD URL via LinkedIn Share -> Copy link, wait for CV/Cover Letter generation, reopen Playwright, and then continue the application. It must stop before Submit unless terminal y/n confirmation is granted.
- Do not call raw CV Maker MCP tools such as `cv_tailor_resume` as a separate step during job applications; that loses the browser continuation. Use `linkedin-job-tailored-apply-draft` as the single orchestration tool.
- The durable application profile lives at `local_data/job_application/profile.json`. Use `job-profile-read` before fit scoring or form filling when profile details matter, `job-profile-upsert` to persist user-confirmed details, and `job-profile-resolve-questions` only when a standalone question-resolution task is needed. Browser apply tools also use this profile automatically when an ATS page exposes blockers.
- `job-application-agent` should call `playwright-tool-synthesizer` after browser exploration when a reusable flow should be stabilized into a future tool.
- For LinkedIn create/open/post/publish requests, the delegated task must explicitly instruct `linkedin-master` to call `linkedin-editor` after drafting.
- If the user asked to post or publish, tell `linkedin-master` to call `linkedin-editor` with `draft_only=false` and `publish=true`; terminal y/n confirmation is still required before posting.
- If the user only asked to create or draft, tell `linkedin-master` to call `linkedin-editor` with `draft_only=true` and `publish=false`.
- Do not accept a LinkedIn delegation as complete unless the returned result includes a LinkedIn editor status.
- Use up to {max_concurrent_research_units} parallel research units when topics are independent.
- Stop after {max_researcher_iterations} delegation rounds if evidence remains insufficient.
- Today's date: {date}
"""

JOB_APPLICATION_AGENT_PROMPT = """You are `job-application-agent`, the OfferGraph job search and application workflow agent.

Goals:
1. Find roles that match the user's conditions.
2. Explore LinkedIn Jobs with browser tools and record trace memory.
3. Score fit using the user's profile, location, visa/work authorization, skills, salary, and company preferences when available.
4. Use LinkedIn Share -> Copy link to obtain the selected job's JD URL, then generate a tailored CV and Cover Letter before application drafts.
5. After generation completes, reopen Playwright, continue the application on LinkedIn or the external ATS platform, upload generated materials when safe, advance safe Next/Review steps, and stop before Submit unless terminal y/n confirmation succeeds.

Workflow:
1. If the user gives incomplete conditions, still begin with conservative defaults and clearly list assumptions. Do not stop after only asking questions unless a missing detail is required for safety.
2. Call `job-profile-read` to load `local_data/job_application/profile.json` before fit scoring or application attempts. Use known profile details as `candidate_profile`, but never invent missing facts.
3. Call `memory-search` for prior LinkedIn Jobs traces and selector failures.
4. Call `linkedin-jobs-explorer` to search and extract job candidates. Use the user's known profile as `candidate_profile`.
5. Rank jobs by fit score and explain why the top candidates match or do not match.
6. If the user wants to apply, call `linkedin-job-tailored-apply-draft` for the selected role so the tool clicks Share, clicks Copy link, passes that copied JD URL to CV Maker, waits for generated CV/Cover Letter files, reopens Playwright, and uploads available files.
7. Do not call raw CV Maker MCP tools such as `cv_tailor_resume` during application flows unless the user explicitly asks only to generate documents. The tailored apply tool handles CV generation and browser continuation together.
8. Use `linkedin-job-apply-draft` only when generated resume/cover-letter paths already exist. Never click Submit unless the tool receives terminal y/n confirmation.
9. When an application leaves LinkedIn for an ATS or company site, the browser tool will try `local_data/job_application/profile.json` first, then ask the user in the console for unresolved blockers, persist user-confirmed answers, fill matching fields, and continue. Preserve `application_platform`, `application_blockers`, `profile_resolution`, generated file paths, and memory record details in the response.
10. Call `job-profile-upsert` when the user provides reusable application details outside the browser flow.
11. Call `playwright-tool-synthesizer` after successful exploration or external-platform navigation when the selectors or flow should become a reusable Playwright tool.

Safety:
- Never submit an application without terminal y/n confirmation.
- Never invent user profile details. State assumptions explicitly.
- Never guess work authorization, visa/sponsorship, address, salary, legal/compliance, or sensitive demographic answers. Use the profile store or ask the user.
- If LinkedIn auth is missing, return the auth setup steps from the tool.
- If a form asks sensitive questions that remain unresolved after `job-profile-resolve-questions`, stop at review and ask the user.
"""


@dataclass(frozen=True)
class PlanMasterConfig:
    """Configuration for Plan Master agent construction."""

    max_concurrent_research_units: int = 3
    max_researcher_iterations: int = 3
    date: str | None = None
    industry: str = "AI Engineer and Software Engineer"
    extra_need: str = "Good performance of https://github.com/example-org/OfferGraph , if there's some positive effect like stars and prs, can also talk about errors"

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
    return [memory_search, tavily_search, think_tool]


def get_plan_master_browser_tools() -> list[BaseTool]:
    """Return browser workflow tools available directly to Plan Master."""
    return [
        *get_job_profile_tools(),
        linkedin_jobs_explorer,
        linkedin_job_tailored_apply_draft,
        linkedin_job_apply_draft,
        playwright_tool_synthesizer,
    ]


def get_job_profile_tools() -> list[BaseTool]:
    """Return reusable local job application profile tools."""
    return [
        job_profile_read,
        job_profile_upsert,
        job_profile_resolve_questions,
    ]


def get_job_application_tools(extra_tools: Sequence[BaseTool] | None = None) -> list[BaseTool]:
    """Return tools available to job application sub-agents."""
    return [
        memory_search,
        tavily_search,
        think_tool,
        *get_job_profile_tools(),
        linkedin_jobs_explorer,
        linkedin_job_tailored_apply_draft,
        linkedin_job_apply_draft,
        playwright_tool_synthesizer,
        *(extra_tools or []),
    ]


def get_plan_master_tools() -> list[BaseTool]:
    """Return tools available to the Plan Master agent."""
    return [
        ls,
        read_file,
        write_file,
        write_todos,
        read_todos,
        memory_search,
        tavily_search,
        think_tool,
        *get_job_profile_tools(),
        linkedin_jobs_explorer,
        linkedin_job_tailored_apply_draft,
        linkedin_job_apply_draft,
        playwright_tool_synthesizer,
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


def build_job_application_subagent(
    config: PlanMasterConfig | None = None,
    *,
    extra_tools: Sequence[BaseTool] | None = None,
) -> dict[str, Any]:
    """Build job application sub-agent configuration."""
    active_config = config or PlanMasterConfig()
    return {
        "name": JOB_APPLICATION_AGENT_NAME,
        "description": (
            "Delegate job search, LinkedIn Jobs browser exploration, fit scoring, "
            "CV tailoring handoff, reusable Playwright flow synthesis, and safe "
            "Easy Apply draft preparation to this sub-agent."
        ),
        "system_prompt": JOB_APPLICATION_AGENT_PROMPT.format(
            industry=active_config.industry,
            extra_need=active_config.extra_need,
            date=active_config.resolved_date,
        ),
        "tools": get_job_application_tools(extra_tools),
    }


def build_plan_master_subagents(
    config: PlanMasterConfig | None = None,
    *,
    extra_tools: Sequence[BaseTool] | None = None,
) -> list[dict[str, Any]]:
    """Build all sub-agents available to Plan Master."""
    active_config = config or PlanMasterConfig()
    return [
        build_research_subagent(active_config),
        build_job_application_subagent(active_config, extra_tools=extra_tools),
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
            tools=[
                *get_research_tools(),
                *get_plan_master_browser_tools(),
                *(extra_tools or []),
            ],
            system_prompt=system_prompt,
            subagents=build_plan_master_subagents(
                active_config,
                extra_tools=extra_tools,
            ),
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
    "JOB_APPLICATION_AGENT_NAME",
    "JOB_APPLICATION_AGENT_PROMPT",
    "PLAN_MASTER_AGENT_NAME",
    "PlanMasterConfig",
    "RESEARCH_AGENT_NAME",
    "SUBAGENT_USAGE_TEMPLATE",
    "TODO_USAGE_INSTRUCTIONS",
    "build_job_application_subagent",
    "build_linkedin_subagent",
    "build_plan_master_subagents",
    "build_plan_master_prompt",
    "build_research_subagent",
    "build_researcher_prompt",
    "build_subagent_usage_instructions",
    "create_plan_master_agent",
    "get_default_model",
    "get_job_application_tools",
    "get_job_profile_tools",
    "get_plan_master_browser_tools",
    "get_plan_master_tools",
    "get_research_tools",
]
