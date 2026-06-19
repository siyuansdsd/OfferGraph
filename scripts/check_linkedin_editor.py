"""Smoke test the linkedin-editor tool with optional y/n publishing."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from tools.approval import APPROVE_MODE, AUTO_MODE  # noqa: E402
    from tools.linkedin.content_editor import linkedin_editor  # noqa: E402
except ModuleNotFoundError as exc:
    print(
        "Could not import linkedin-editor dependencies.",
        file=sys.stderr,
    )
    print(f"Missing module: {exc.name}", file=sys.stderr)
    print(f"Python executable: {sys.executable}", file=sys.stderr)
    print(f"Expected venv Python: {PROJECT_ROOT / '.venv/bin/python'}", file=sys.stderr)
    print(
        "Fix: source .venv/bin/activate && python -m pip install -r requirements.txt",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manually invoke linkedin-editor and print its structured result."
    )
    parser.add_argument(
        "--task",
        default="Draft a LinkedIn post introducing OfferGraph.",
        help="Brief for the LinkedIn post.",
    )
    parser.add_argument(
        "--post-text",
        dest="post_text",
        required=True,
        help="Exact final LinkedIn post text to insert into the composer.",
    )
    parser.add_argument(
        "--publish",
        "--publish-path",
        dest="publish",
        action="store_true",
        help=(
            "Open the publish request path. After the draft is inserted, the tool asks "
            "for y/n terminal confirmation before clicking Post."
        ),
    )
    parser.add_argument(
        "--image-path",
        dest="image_path",
        default=None,
        help="Local image file path to upload into the LinkedIn composer.",
    )
    parser.add_argument(
        "--image-url",
        dest="image_url",
        default=None,
        help="Remote image URL to download locally and upload into the LinkedIn composer.",
    )
    parser.add_argument(
        "--alt-text",
        dest="alt_text",
        default=None,
        help="Optional alt text for the uploaded image.",
    )
    parser.add_argument(
        "--text-only",
        dest="text_only",
        action="store_true",
        help="Disable automatic image search/generation and allow a text-only draft.",
    )
    parser.add_argument(
        "--hide-cursor",
        dest="show_cursor",
        action="store_false",
        default=True,
        help="Disable the visible Playwright cursor overlay.",
    )
    parser.add_argument(
        "--mode",
        choices=(AUTO_MODE, APPROVE_MODE),
        default=None,
        help=(
            "Approval mode override. Defaults to OFFERGRAPH_TOOL_MODE or approve-mode."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = linkedin_editor.invoke(
        {
            "task": args.task,
            "post_text": args.post_text,
            "draft_only": not args.publish,
            "publish": args.publish,
            "image_path": args.image_path,
            "image_url": args.image_url,
            "alt_text": args.alt_text,
            "auto_image": not args.text_only,
            "require_image": not args.text_only,
            "show_cursor": args.show_cursor,
            "execution_mode": args.mode,
        }
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))

    if result.get("status") == "error":
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
