"""Image search and generation tools for LinkedIn content workflows."""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Annotated, Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolArg, InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel, Field
from tavily import TavilyClient

from config.env import PROJECT_ROOT, get_env, load_project_env
from tools.research_tools import get_today_str, sanitize_filename, unique_filename
from tools.state import PlanMasterState

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - exercised only when dependency is absent.
    OpenAI = None  # type: ignore[assignment]


TAVILY_API_KEY_ENV = "TAVILY_API_KEY"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
OPENAI_IMAGE_MODEL_ENV = "OFFERGRAPH_OPENAI_IMAGE_MODEL"
DEFAULT_OPENAI_IMAGE_MODEL = "gpt-image-1"
DEFAULT_OPENAI_IMAGE_SIZE = "1024x1024"
DEFAULT_OPENAI_IMAGE_QUALITY = "auto"
DEFAULT_IMAGE_OUTPUT_DIR = PROJECT_ROOT / "generated_assets" / "linkedin_images"
DEFAULT_IMAGE_CANDIDATE_LIMIT = 5


class ImageCandidate(BaseModel):
    """A candidate image found through Tavily search."""

    url: str
    source_url: str | None = None
    title: str | None = None
    description: str | None = None


class OpenAIImageResult(BaseModel):
    """Result from OpenAI image generation."""

    status: str
    message: str
    prompt: str
    model: str
    image_path: str | None = None
    image_url: str | None = None
    revised_prompt: str | None = None


def build_image_search_query(
    post_topic: str,
    *,
    image_brief: str = "",
    post_text: str = "",
) -> str:
    """Build a focused image search query for the LinkedIn post."""
    topic = post_topic.strip()
    brief = image_brief.strip()
    text = " ".join(post_text.strip().split())[:220]
    content_hint = brief or text

    parts = [part for part in (topic, content_hint, "LinkedIn post visual") if part]
    return " ".join(parts)


def run_tavily_image_search(
    query: str,
    max_results: int = DEFAULT_IMAGE_CANDIDATE_LIMIT,
    *,
    client: TavilyClient | None = None,
) -> dict[str, Any]:
    """Search Tavily for image candidates related to a LinkedIn post."""
    if client is None:
        load_project_env()
        tavily_api_key = get_env(TAVILY_API_KEY_ENV, load=False)
        tavily_client = (
            TavilyClient(api_key=tavily_api_key) if tavily_api_key else TavilyClient()
        )
    else:
        tavily_client = client

    return tavily_client.search(
        query,
        max_results=max_results,
        include_images=True,
        include_raw_content=False,
        topic="general",
    )


def extract_image_candidates(
    search_response: dict[str, Any],
    *,
    max_candidates: int = DEFAULT_IMAGE_CANDIDATE_LIMIT,
) -> list[ImageCandidate]:
    """Normalize image URLs from Tavily's top-level and per-result image fields."""
    candidates: list[ImageCandidate] = []
    seen_urls: set[str] = set()

    def append_candidate(candidate: ImageCandidate | None) -> None:
        if candidate is None or candidate.url in seen_urls:
            return
        seen_urls.add(candidate.url)
        candidates.append(candidate)

    for image in search_response.get("images") or []:
        append_candidate(_image_candidate_from_value(image))

    for result in search_response.get("results") or []:
        source_url = str(result.get("url") or "") or None
        title = str(result.get("title") or "") or None
        for image in result.get("images") or []:
            append_candidate(
                _image_candidate_from_value(
                    image,
                    default_source_url=source_url,
                    default_title=title,
                )
            )
        append_candidate(
            _image_candidate_from_value(
                result.get("image"),
                default_source_url=source_url,
                default_title=title,
            )
        )
        if len(candidates) >= max_candidates:
            break

    return candidates[:max_candidates]


def generate_openai_image(
    image_prompt: str,
    *,
    output_path: str | Path | None = None,
    model: str | None = None,
    size: str = DEFAULT_OPENAI_IMAGE_SIZE,
    quality: str = DEFAULT_OPENAI_IMAGE_QUALITY,
    client: Any | None = None,
) -> OpenAIImageResult:
    """Generate an image with OpenAI and save it when base64 content is returned."""
    prompt = image_prompt.strip()
    active_model = model or (
        get_env(OPENAI_IMAGE_MODEL_ENV, DEFAULT_OPENAI_IMAGE_MODEL)
        or DEFAULT_OPENAI_IMAGE_MODEL
    )
    if not prompt:
        return OpenAIImageResult(
            status="error",
            message="image_prompt is required.",
            prompt=prompt,
            model=active_model,
        )

    active_client = client
    if active_client is None:
        if OpenAI is None:
            return OpenAIImageResult(
                status="error",
                message="OpenAI SDK is not installed.",
                prompt=prompt,
                model=active_model,
            )

        load_project_env()
        api_key = get_env(OPENAI_API_KEY_ENV, load=False)
        if not api_key:
            return OpenAIImageResult(
                status="error",
                message=f"Missing required environment variable: {OPENAI_API_KEY_ENV}",
                prompt=prompt,
                model=active_model,
            )
        active_client = OpenAI(api_key=api_key)

    try:
        response = active_client.images.generate(
            model=active_model,
            prompt=prompt,
            size=size,
            quality=quality,
            n=1,
        )
    except Exception as exc:
        return OpenAIImageResult(
            status="error",
            message=f"OpenAI image generation failed: {exc}",
            prompt=prompt,
            model=active_model,
        )

    data = _first_response_item(response)
    image_b64 = _get_response_field(data, "b64_json")
    image_url = _get_response_field(data, "url")
    revised_prompt = _get_response_field(data, "revised_prompt")
    saved_path = None
    if image_b64:
        saved_path = save_base64_image(
            image_b64,
            output_path or default_image_output_path(prompt),
        )

    if saved_path or image_url:
        return OpenAIImageResult(
            status="generated",
            message="Generated image is ready.",
            prompt=prompt,
            model=active_model,
            image_path=str(saved_path) if saved_path else None,
            image_url=image_url,
            revised_prompt=revised_prompt,
        )

    return OpenAIImageResult(
        status="error",
        message="OpenAI returned no image data.",
        prompt=prompt,
        model=active_model,
        revised_prompt=revised_prompt,
    )


def save_base64_image(image_b64: str, output_path: str | Path) -> Path:
    """Decode and save a base64 image payload."""
    raw_b64 = image_b64.split(",", 1)[1] if "," in image_b64 else image_b64
    image_bytes = base64.b64decode(raw_b64)
    resolved_path = Path(output_path).expanduser()
    if not resolved_path.is_absolute():
        resolved_path = PROJECT_ROOT / resolved_path
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_bytes(image_bytes)
    return resolved_path


def default_image_output_path(prompt: str) -> Path:
    """Return a generated asset path for an OpenAI image prompt."""
    safe_name = sanitize_filename(prompt, default="linkedin_image.md")
    stem = Path(safe_name).stem[:80] or "linkedin_image"
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return DEFAULT_IMAGE_OUTPUT_DIR / f"{timestamp}_{stem}.png"


@tool("linkedin-image-search", parse_docstring=True)
def linkedin_image_search(
    post_topic: str,
    state: Annotated[PlanMasterState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    image_brief: str = "",
    post_text: str = "",
    max_results: Annotated[int, InjectedToolArg] = DEFAULT_IMAGE_CANDIDATE_LIMIT,
) -> Command:
    """Search for image candidates that match the LinkedIn post.

    Args:
        post_topic: Topic or news angle for the LinkedIn post.
        state: Injected agent state for virtual file storage.
        tool_call_id: Injected tool call identifier.
        image_brief: Optional visual direction for the post image.
        post_text: Optional final or draft post body to align the image search.
        max_results: Maximum number of Tavily web results to inspect.
    """
    query = build_image_search_query(
        post_topic,
        image_brief=image_brief,
        post_text=post_text,
    )
    files = dict(state.get("files", {}))

    try:
        search_response = run_tavily_image_search(query, max_results=max_results)
        candidates = extract_image_candidates(search_response, max_candidates=max_results)
    except Exception as exc:
        message = (
            f"Image search failed for '{query}': {exc}. "
            "Next: call openai-image-generator with a specific visual prompt."
        )
        return Command(
            update={
                "files": files,
                "messages": [ToolMessage(message, tool_call_id=tool_call_id)],
            }
        )

    filename = unique_filename("linkedin_image_candidates.md")
    files[filename] = _format_image_candidates_file(query, candidates)

    if candidates:
        message = (
            f"Found {len(candidates)} image candidate(s) for '{query}'. "
            f"Recommended first candidate: {candidates[0].url}. "
            f"Saved candidates to {filename}. Prefer a searched image before "
            "calling openai-image-generator."
        )
    else:
        message = (
            f"No usable image candidates found for '{query}'. "
            f"Saved search notes to {filename}. "
            "Next: call openai-image-generator with the image brief."
        )

    return Command(
        update={
            "files": files,
            "messages": [ToolMessage(message, tool_call_id=tool_call_id)],
        }
    )


@tool("openai-image-generator", parse_docstring=True)
def openai_image_generator(
    image_prompt: str,
    output_path: str = "",
    model: Annotated[str, InjectedToolArg] = "",
    size: Annotated[str, InjectedToolArg] = DEFAULT_OPENAI_IMAGE_SIZE,
    quality: Annotated[str, InjectedToolArg] = DEFAULT_OPENAI_IMAGE_QUALITY,
) -> dict[str, Any]:
    """Generate a LinkedIn post image using OpenAI.

    Args:
        image_prompt: Specific prompt for the image to generate.
        output_path: Optional local file path for saving base64 image output.
        model: OpenAI image model override.
        size: Output image size.
        quality: Output image quality.
    """
    result = generate_openai_image(
        image_prompt,
        output_path=output_path or None,
        model=model or None,
        size=size,
        quality=quality,
    )
    return result.model_dump(exclude_none=True)


def _image_candidate_from_value(
    value: Any,
    *,
    default_source_url: str | None = None,
    default_title: str | None = None,
) -> ImageCandidate | None:
    if value is None:
        return None
    if isinstance(value, str):
        return (
            ImageCandidate(
                url=value,
                source_url=default_source_url,
                title=default_title,
            )
            if _is_http_image_candidate(value)
            else None
        )
    if not isinstance(value, dict):
        return None

    url = str(
        value.get("url")
        or value.get("image_url")
        or value.get("src")
        or value.get("thumbnail_url")
        or value.get("thumbnail")
        or ""
    )
    if not _is_http_image_candidate(url):
        return None

    source_url = str(
        value.get("source_url")
        or value.get("origin_url")
        or value.get("page_url")
        or default_source_url
        or ""
    )
    title = str(value.get("title") or value.get("alt") or default_title or "")
    description = str(value.get("description") or value.get("content") or "")

    return ImageCandidate(
        url=url,
        source_url=source_url or None,
        title=title or None,
        description=description or None,
    )


def _is_http_image_candidate(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


def _first_response_item(response: Any) -> Any | None:
    data = _get_response_field(response, "data")
    if isinstance(data, list) and data:
        return data[0]
    return None


def _get_response_field(value: Any, field_name: str) -> Any:
    if isinstance(value, dict):
        return value.get(field_name)
    return getattr(value, field_name, None)


def _format_image_candidates_file(
    query: str,
    candidates: list[ImageCandidate],
) -> str:
    lines = [
        "# LinkedIn Image Candidates",
        "",
        f"**Query:** {query}",
        f"**Date:** {get_today_str()}",
        "",
    ]

    if not candidates:
        lines.append("No usable image candidates were found.")
        return "\n".join(lines)

    for index, candidate in enumerate(candidates, start=1):
        lines.extend(
            [
                f"## Candidate {index}",
                f"- Image URL: {candidate.url}",
                f"- Source URL: {candidate.source_url or 'Unknown'}",
                f"- Title: {candidate.title or 'Untitled'}",
                f"- Description: {candidate.description or 'None'}",
                "",
            ]
        )

    return "\n".join(lines)


__all__ = [
    "DEFAULT_IMAGE_CANDIDATE_LIMIT",
    "DEFAULT_IMAGE_OUTPUT_DIR",
    "DEFAULT_OPENAI_IMAGE_MODEL",
    "DEFAULT_OPENAI_IMAGE_QUALITY",
    "DEFAULT_OPENAI_IMAGE_SIZE",
    "ImageCandidate",
    "OPENAI_API_KEY_ENV",
    "OPENAI_IMAGE_MODEL_ENV",
    "OpenAIImageResult",
    "TAVILY_API_KEY_ENV",
    "build_image_search_query",
    "default_image_output_path",
    "extract_image_candidates",
    "generate_openai_image",
    "linkedin_image_search",
    "openai_image_generator",
    "run_tavily_image_search",
    "save_base64_image",
]
