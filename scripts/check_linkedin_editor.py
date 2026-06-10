"""Smoke test the linkedin-editor tool without publishing anything."""

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
        "--additional-info",
        default=None,
        help="Optional context, audience, facts, or tone instructions.",
    )
    parser.add_argument(
        "--publish-path",
        action="store_true",
        help=(
            "Exercise the publish request path. The current implementation still does "
            "not click Post; it should return needs_confirmation."
        ),
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
            "additional_info": args.additional_info,
            "draft_only": not args.publish_path,
            "publish": args.publish_path,
            "execution_mode": args.mode,
        }
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))

    if result.get("status") == "error":
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
