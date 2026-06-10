"""Create a reusable Playwright LinkedIn auth state.

This script opens a visible Playwright browser. Log in to LinkedIn manually,
then return to the terminal and press Enter to save cookies/session state.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.linkedin.auth import (  # noqa: E402
    DEFAULT_LINKEDIN_AUTH_STATE_PATH,
    PlaywrightError,
    setup_linkedin_auth_state,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open LinkedIn and save a Playwright storage_state file."
    )
    parser.add_argument(
        "--state-path",
        default=str(DEFAULT_LINKEDIN_AUTH_STATE_PATH),
        help="Where to save the LinkedIn Playwright storage_state JSON.",
    )
    parser.add_argument(
        "--browser",
        default="chromium",
        choices=("chromium", "firefox", "webkit"),
        help="Playwright browser engine to launch.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        state_path, current_url = setup_linkedin_auth_state(
            state_path=Path(args.state_path),
            browser_name=args.browser,
            stdout=sys.stdout,
        )
    except PlaywrightError as exc:
        print(f"Playwright failed: {exc}", file=sys.stderr)
        print(
            "If the browser is not installed yet, run: "
            ".venv/bin/python -m playwright install chromium",
            file=sys.stderr,
        )
        return 1

    print(f"Saved LinkedIn auth state to: {state_path}")
    if "linkedin.com/feed" not in current_url:
        print(
            f"Warning: final URL was {current_url!r}. "
            "If you were not logged in, rerun this script and save after the feed loads.",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
