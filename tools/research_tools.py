"""Research tools for Plan Master and research sub-agents."""

from __future__ import annotations

import base64
import json
import os
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any, Callable, Literal

import httpx
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import InjectedToolArg, InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from markdownify import markdownify
from pydantic import BaseModel, Field
from tavily import TavilyClient

from agent.model_selection import resolve_model_reference
from agent.prompt import render_prompt
from config.env import get_env, load_project_env
from tools.state import PlanMasterState


SearchTopic = Literal["general", "news", "finance"]
SearchRunner = Callable[[str, int, SearchTopic, bool], dict[str, Any]]
ContentFetcher = Callable[[str], str]
Summarizer = Callable[[str], "SearchSummary"]
TAVILY_API_KEY_ENV = "TAVILY_API_KEY"
SEARCH_SUMMARIZER_MODEL_ENV = "OFFERGRAPH_SEARCH_SUMMARIZER_MODEL"
DEFAULT_SEARCH_SUMMARIZER_MODEL = "openai:gpt-4o-mini"


class SearchSummary(BaseModel):
    """Schema for webpage content summarization."""

    filename: str = Field(description="Name of the file to store.")
    summary: str = Field(description="Key learnings from the webpage.")


def get_today_str(today: date | datetime | None = None) -> str:
    """Get the current date in a prompt-friendly format."""
    value = today or datetime.now()
    return f"{value:%a} {value:%b} {value.day}, {value:%Y}"


def sanitize_filename(filename: str, default: str = "search_result.md") -> str:
    """Return a safe markdown filename for virtual file storage."""
    stripped = filename.strip()
    if not stripped:
        stripped = default

    path_name = Path(stripped).name
    stem, suffix = os.path.splitext(path_name)
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    if not safe_stem:
        safe_stem = Path(default).stem

    safe_suffix = suffix if suffix.lower() == ".md" else ".md"
    return f"{safe_stem}{safe_suffix}"


def unique_filename(filename: str, uid: str | None = None) -> str:
    """Add a short unique suffix to a filename."""
    safe_name = sanitize_filename(filename)
    stem, suffix = os.path.splitext(safe_name)
    unique_id = uid or base64.urlsafe_b64encode(uuid.uuid4().bytes).rstrip(b"=").decode(
        "ascii"
    )[:8]
    return f"{stem}_{unique_id}{suffix}"


def run_tavily_search(
    search_query: str,
    max_results: int = 1,
    topic: SearchTopic = "general",
    include_raw_content: bool = True,
    *,
    client: TavilyClient | None = None,
) -> dict[str, Any]:
    """Perform a Tavily web search for a single query."""
    if client is None:
        load_project_env()
        tavily_api_key = get_env(TAVILY_API_KEY_ENV, load=False)
        tavily_client = (
            TavilyClient(api_key=tavily_api_key) if tavily_api_key else TavilyClient()
        )
    else:
        tavily_client = client

    return tavily_client.search(
        search_query,
        max_results=max_results,
        include_raw_content=include_raw_content,
        topic=topic,
    )


def summarize_webpage_content(
    webpage_content: str,
    *,
    summarizer_model: Any | None = None,
) -> SearchSummary:
    """Summarize webpage content and propose a filename."""
    if not webpage_content:
        return SearchSummary(filename="empty_search_result.md", summary="No content.")

    try:
        model_reference = (
            get_env(SEARCH_SUMMARIZER_MODEL_ENV, DEFAULT_SEARCH_SUMMARIZER_MODEL)
            or DEFAULT_SEARCH_SUMMARIZER_MODEL
        )
        resolved_model = (
            resolve_model_reference(model_reference) or DEFAULT_SEARCH_SUMMARIZER_MODEL
        )
        model = summarizer_model or (
            init_chat_model(model=resolved_model)
            if isinstance(resolved_model, str)
            else resolved_model
        )
        structured_model = model.with_structured_output(SearchSummary)
        prompt = render_prompt(
            "summarize_web_search",
            webpage_content=webpage_content,
            date=get_today_str(),
        )
        summary = structured_model.invoke([HumanMessage(content=prompt)])
        if isinstance(summary, SearchSummary):
            return summary
        if isinstance(summary, dict):
            return SearchSummary(**summary)
    except Exception:
        pass

    return SearchSummary(
        filename="search_result.md",
        summary=webpage_content[:1000] + "..."
        if len(webpage_content) > 1000
        else webpage_content,
    )


def fetch_markdown_content(url: str, *, http_client: httpx.Client | None = None) -> str:
    """Fetch a URL and convert successful HTML responses to markdown."""
    owns_client = http_client is None
    client = http_client or httpx.Client(timeout=30.0)
    try:
        response = client.get(url)
        response.raise_for_status()
        return markdownify(response.text)
    finally:
        if owns_client:
            client.close()


def process_search_results(
    results: dict[str, Any],
    *,
    fetcher: ContentFetcher | None = None,
    summarizer: Summarizer | None = None,
    uid_factory: Callable[[], str] | None = None,
) -> list[dict[str, str]]:
    """Fetch, summarize, and normalize Tavily search results."""
    processed_results: list[dict[str, str]] = []
    fetch_content = fetcher or fetch_markdown_content
    summarize = summarizer or summarize_webpage_content
    make_uid = uid_factory or (
        lambda: base64.urlsafe_b64encode(uuid.uuid4().bytes).rstrip(b"=").decode(
            "ascii"
        )[:8]
    )

    for result in results.get("results", []):
        url = str(result.get("url", ""))
        title = str(result.get("title", "Untitled result"))
        fallback_content = str(result.get("raw_content") or result.get("content") or "")

        try:
            raw_content = fetch_content(url) if url else fallback_content
        except (httpx.HTTPError, OSError, ValueError):
            raw_content = fallback_content

        summary_obj = summarize(raw_content or fallback_content)
        processed_results.append(
            {
                "url": url,
                "title": title,
                "summary": summary_obj.summary,
                "filename": unique_filename(summary_obj.filename, uid=make_uid()),
                "raw_content": raw_content,
            }
        )

    return processed_results


@tool(parse_docstring=True)
def tavily_search(
    query: str,
    state: Annotated[PlanMasterState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    max_results: Annotated[int, InjectedToolArg] = 1,
    topic: Annotated[SearchTopic, InjectedToolArg] = "general",
) -> Command:
    """Search the web and save detailed results to virtual files.

    Args:
        query: Search query to execute.
        state: Injected agent state for file storage.
        tool_call_id: Injected tool call identifier.
        max_results: Maximum result count.
        topic: Tavily topic filter.
    """
    search_results = run_tavily_search(
        query,
        max_results=max_results,
        topic=topic,
        include_raw_content=True,
    )
    processed_results = process_search_results(search_results)

    files = dict(state.get("files", {}))
    saved_files: list[str] = []
    summaries: list[str] = []
    for result in processed_results:
        filename = result["filename"]
        file_content = (
            f"# Search Result: {result['title']}\n\n"
            f"**URL:** {result['url']}\n"
            f"**Query:** {query}\n"
            f"**Date:** {get_today_str()}\n\n"
            f"## Summary\n{result['summary']}\n\n"
            f"## Raw Content\n{result['raw_content'] or 'No raw content available'}\n"
        )
        files[filename] = file_content
        saved_files.append(filename)
        summaries.append(f"- {filename}: {result['summary']}")

    summary_text = (
        f"Found {len(processed_results)} result(s) for '{query}':\n\n"
        f"{chr(10).join(summaries)}\n\n"
        f"Files: {', '.join(saved_files) if saved_files else 'none'}\n"
        "Use read_file() to access full details when needed."
    )

    return Command(
        update={
            "files": files,
            "messages": [ToolMessage(summary_text, tool_call_id=tool_call_id)],
        }
    )


@tool(parse_docstring=True)
def think_tool(reflection: str) -> str:
    """Record strategic reflection on progress and next steps.

    Args:
        reflection: Analysis of findings, gaps, and next action.
    """
    return f"Reflection recorded: {reflection}"


__all__ = [
    "DEFAULT_SEARCH_SUMMARIZER_MODEL",
    "SearchSummary",
    "SearchTopic",
    "SEARCH_SUMMARIZER_MODEL_ENV",
    "TAVILY_API_KEY_ENV",
    "fetch_markdown_content",
    "get_today_str",
    "process_search_results",
    "run_tavily_search",
    "sanitize_filename",
    "summarize_webpage_content",
    "tavily_search",
    "think_tool",
    "unique_filename",
]
