"""LinkedIn Playwright authentication helpers."""

from pathlib import Path
from typing import Callable, Literal, TextIO

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LINKEDIN_AUTH_STATE_PATH = PROJECT_ROOT / ".auth" / "linkedin.json"
LINKEDIN_FEED_URL = "https://www.linkedin.com/feed/"
BrowserName = Literal["chromium", "firefox", "webkit"]


def setup_linkedin_auth_state(
    *,
    state_path: str | Path = DEFAULT_LINKEDIN_AUTH_STATE_PATH,
    browser_name: BrowserName = "chromium",
    wait_for_user: Callable[[str], str] = input,
    stdout: TextIO | None = None,
) -> tuple[Path, str]:
    """Open LinkedIn for manual login and save Playwright storage_state."""
    output = stdout
    resolved_state_path = Path(state_path).expanduser().resolve()
    resolved_state_path.parent.mkdir(parents=True, exist_ok=True)

    if output is not None:
        print(f"Auth state will be saved to: {resolved_state_path}", file=output)
        print("A browser window will open. Log in to LinkedIn manually.", file=output)
        print(
            "After the LinkedIn feed is visible, return here and press Enter.",
            file=output,
        )

    with sync_playwright() as playwright:
        browser_type = getattr(playwright, browser_name)
        browser = browser_type.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(LINKEDIN_FEED_URL, wait_until="domcontentloaded")

            wait_for_user(
                "Press Enter after LinkedIn is logged in and the feed is visible..."
            )

            page.goto(LINKEDIN_FEED_URL, wait_until="domcontentloaded")
            current_url = page.url
            context.storage_state(path=str(resolved_state_path))
        finally:
            browser.close()

    return resolved_state_path, current_url


__all__ = [
    "BrowserName",
    "DEFAULT_LINKEDIN_AUTH_STATE_PATH",
    "LINKEDIN_FEED_URL",
    "PlaywrightError",
    "setup_linkedin_auth_state",
]
