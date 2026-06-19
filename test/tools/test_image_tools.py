"""Tests for image search and generation tools."""

import base64
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from tools.image_tools import (
    OPENAI_API_KEY_ENV,
    TAVILY_API_KEY_ENV,
    build_image_search_query,
    download_image_url,
    extract_image_candidates,
    generate_openai_image,
    linkedin_image_search,
    openai_image_generator,
    run_tavily_image_search,
    save_base64_image,
)


class ImageToolsTest(TestCase):
    def test_build_image_search_query_prefers_image_brief(self) -> None:
        query = build_image_search_query(
            "MiniMax revenue growth",
            image_brief="clean chart with API nodes",
            post_text="This should be secondary context.",
        )

        self.assertIn("MiniMax revenue growth", query)
        self.assertIn("clean chart with API nodes", query)
        self.assertIn("LinkedIn post visual", query)
        self.assertNotIn("secondary context", query)

    def test_extract_image_candidates_normalizes_and_deduplicates(self) -> None:
        candidates = extract_image_candidates(
            {
                "images": [
                    "https://example.com/hero.png",
                    {"url": "https://example.com/hero.png"},
                    {
                        "image_url": "https://example.com/chart.png",
                        "source_url": "https://example.com/article",
                        "title": "Chart",
                    },
                ],
                "results": [
                    {
                        "url": "https://example.com/page",
                        "title": "Page title",
                        "images": ["https://example.com/page-image.jpg"],
                    }
                ],
            }
        )

        self.assertEqual([candidate.url for candidate in candidates], [
            "https://example.com/hero.png",
            "https://example.com/chart.png",
            "https://example.com/page-image.jpg",
        ])
        self.assertEqual(candidates[1].source_url, "https://example.com/article")
        self.assertEqual(candidates[2].title, "Page title")

    def test_run_tavily_image_search_reads_tavily_api_key_from_env(self) -> None:
        fake_client = Mock()
        fake_client.search.return_value = {"images": []}

        with patch.dict("os.environ", {TAVILY_API_KEY_ENV: "test-key"}), patch(
            "tools.image_tools.load_project_env",
            return_value=True,
        ), patch("tools.image_tools.TavilyClient", return_value=fake_client) as client_cls:
            result = run_tavily_image_search("query", max_results=3)

        self.assertEqual(result, {"images": []})
        client_cls.assert_called_once_with(api_key="test-key")
        fake_client.search.assert_called_once_with(
            "query",
            max_results=3,
            include_images=True,
            include_raw_content=False,
            topic="general",
        )

    def test_linkedin_image_search_saves_candidates_to_state(self) -> None:
        with patch(
            "tools.image_tools.run_tavily_image_search",
            return_value={"images": ["https://example.com/minimax-m3-image.png"]},
        ), patch("tools.image_tools.download_image_url", return_value=Path("/tmp/image.png")), patch(
            "tools.image_tools.unique_filename",
            return_value="images.md",
        ):
            command = linkedin_image_search.func(
                "MiniMax news",
                {"files": {}},
                "call-1",
                image_brief="growth chart",
                post_text="MiniMax is growing.",
                max_results=2,
            )

        self.assertIn("images.md", command.update["files"])
        self.assertIn("https://example.com/minimax-m3-image.png", command.update["files"]["images.md"])
        self.assertIn("/tmp/image.png", command.update["files"]["images.md"])
        self.assertIn("Found 1 image candidate", command.update["messages"][0].content)
        self.assertIn("Downloaded local image path", command.update["messages"][0].content)
        self.assertEqual(command.update["messages"][0].tool_call_id, "call-1")

    def test_linkedin_image_search_reports_download_failure(self) -> None:
        with patch(
            "tools.image_tools.run_tavily_image_search",
            return_value={"images": ["https://example.com/minimax-m3-image.png"]},
        ), patch(
            "tools.image_tools.download_image_url",
            side_effect=RuntimeError("download failed"),
        ), patch("tools.image_tools.unique_filename", return_value="images.md"):
            command = linkedin_image_search.func(
                "MiniMax news",
                {"files": {}},
                "call-1",
            )

        self.assertIn("download failed", command.update["files"]["images.md"])
        self.assertIn("could not download", command.update["messages"][0].content)
        self.assertIn("openai-image-generator", command.update["messages"][0].content)

    def test_linkedin_image_search_skips_irrelevant_candidate_download(self) -> None:
        with patch(
            "tools.image_tools.run_tavily_image_search",
            return_value={"images": ["https://example.com/random-local-news.png"]},
        ), patch("tools.image_tools.download_image_url") as download_mock, patch(
            "tools.image_tools.unique_filename",
            return_value="images.md",
        ):
            command = linkedin_image_search.func(
                "MiniMax M3 news",
                {"files": {}},
                "call-1",
            )

        self.assertIn("No relevant candidate", command.update["messages"][0].content)
        download_mock.assert_not_called()

    def test_linkedin_image_search_reports_generation_fallback_when_empty(self) -> None:
        with patch(
            "tools.image_tools.run_tavily_image_search",
            return_value={"images": []},
        ), patch("tools.image_tools.unique_filename", return_value="images.md"):
            command = linkedin_image_search.func(
                "MiniMax news",
                {"files": {}},
                "call-1",
            )

        self.assertIn("No usable image candidates", command.update["messages"][0].content)
        self.assertIn("openai-image-generator", command.update["messages"][0].content)

    def test_save_base64_image_writes_file(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "image.png"
            saved_path = save_base64_image(
                base64.b64encode(b"image-bytes").decode("ascii"),
                output_path,
            )
            self.assertEqual(saved_path, output_path)
            self.assertEqual(output_path.read_bytes(), b"image-bytes")

    def test_download_image_url_writes_file(self) -> None:
        response = Mock()
        response.headers = {"content-type": "image/png"}
        response.content = b"image-bytes"
        response.raise_for_status = Mock()
        client = Mock()
        client.get.return_value = response

        with TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "downloaded"
            saved_path = download_image_url(
                "https://example.com/image",
                output_path=output_path,
                client=client,
            )

            self.assertEqual(saved_path, output_path.with_suffix(".png"))
            self.assertEqual(saved_path.read_bytes(), b"image-bytes")
        client.get.assert_called_once_with("https://example.com/image")
        response.raise_for_status.assert_called_once()

    def test_generate_openai_image_saves_base64_response(self) -> None:
        generated = base64.b64encode(b"image-bytes").decode("ascii")
        fake_client = SimpleNamespace(
            images=SimpleNamespace(
                generate=Mock(
                    return_value=SimpleNamespace(
                        data=[
                            SimpleNamespace(
                                b64_json=generated,
                                revised_prompt="revised",
                                url=None,
                            )
                        ]
                    )
                )
            )
        )

        with TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "image.png"
            result = generate_openai_image(
                "A clean LinkedIn chart",
                output_path=output_path,
                model="gpt-image-test",
                client=fake_client,
            )
            self.assertEqual(output_path.read_bytes(), b"image-bytes")

        self.assertEqual(result.status, "generated")
        self.assertEqual(result.image_path, str(output_path))
        self.assertEqual(result.revised_prompt, "revised")
        fake_client.images.generate.assert_called_once_with(
            model="gpt-image-test",
            prompt="A clean LinkedIn chart",
            size="1024x1024",
            quality="auto",
            n=1,
        )

    def test_generate_openai_image_downloads_url_response(self) -> None:
        fake_client = SimpleNamespace(
            images=SimpleNamespace(
                generate=Mock(
                    return_value=SimpleNamespace(
                        data=[
                            SimpleNamespace(
                                b64_json=None,
                                revised_prompt="revised",
                                url="https://example.com/generated.png",
                            )
                        ]
                    )
                )
            )
        )

        with TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "image.png"
            with patch(
                "tools.image_tools.download_image_url",
                return_value=output_path,
            ) as download_mock:
                result = generate_openai_image(
                    "A clean LinkedIn chart",
                    output_path=output_path,
                    model="gpt-image-test",
                    client=fake_client,
                )

        self.assertEqual(result.status, "generated")
        self.assertEqual(result.image_path, str(output_path))
        self.assertEqual(result.image_url, "https://example.com/generated.png")
        download_mock.assert_called_once_with(
            "https://example.com/generated.png",
            output_path=output_path,
            filename_hint="A clean LinkedIn chart",
        )

    def test_generate_openai_image_reports_missing_api_key(self) -> None:
        def fake_get_env(name, default=None, load=True):
            if name == OPENAI_API_KEY_ENV:
                return None
            return default

        with patch.dict("os.environ", {}, clear=True), patch(
            "tools.image_tools.load_project_env",
            return_value=False,
        ), patch("tools.image_tools.get_env", side_effect=fake_get_env), patch(
            "tools.image_tools.OpenAI",
        ) as openai_cls:
            result = generate_openai_image("A clean LinkedIn chart")

        self.assertEqual(result.status, "error")
        self.assertIn(OPENAI_API_KEY_ENV, result.message)
        openai_cls.assert_not_called()

    def test_openai_image_generator_tool_returns_dict(self) -> None:
        with patch(
            "tools.image_tools.generate_openai_image",
            return_value=SimpleNamespace(
                model_dump=Mock(
                    return_value={
                        "status": "generated",
                        "message": "Generated image is ready.",
                    }
                )
            ),
        ) as generate_mock:
            result = openai_image_generator.invoke(
                {
                    "image_prompt": "A clean LinkedIn chart",
                    "output_path": "generated_assets/test.png",
                }
            )

        self.assertEqual(result["status"], "generated")
        generate_mock.assert_called_once()
