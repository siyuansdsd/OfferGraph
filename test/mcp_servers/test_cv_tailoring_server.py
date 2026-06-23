"""Tests for the CV tailoring MCP server wrapper."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from mcp_servers.cv_tailoring import server


class CVTailoringServerTest(TestCase):
    def make_project_root(self, tmp_dir: str) -> Path:
        project_root = Path(tmp_dir) / "cv"
        (project_root / "src" / "cv_maker").mkdir(parents=True)
        (project_root / "run.py").write_text("print('ok')\n", encoding="utf-8")
        return project_root

    def test_resolve_project_root_validates_required_files(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            project_root = self.make_project_root(tmp_dir)

            with patch.dict(
                "os.environ",
                {server.CV_MAKER_PROJECT_ROOT_ENV: str(project_root)},
                clear=True,
            ):
                self.assertEqual(server.resolve_cv_maker_project_root(), project_root.resolve())

    def test_configured_relative_paths_resolve_from_offergraph_root(self) -> None:
        with patch.dict(
            "os.environ",
            {
                server.CV_MAKER_PROJECT_ROOT_ENV: "external/cv_maker",
                server.CV_MAKER_USER_CONTENT_DIR_ENV: "local_data/cv_maker/user_content",
            },
            clear=True,
        ):
            self.assertEqual(
                server.get_configured_project_root(),
                server.PROJECT_ROOT / "external" / "cv_maker",
            )
            self.assertEqual(
                server.get_configured_user_content_dir(),
                server.PROJECT_ROOT / "local_data" / "cv_maker" / "user_content",
            )

    def test_managed_project_root_links_ignored_user_content(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            project_root = self.make_project_root(tmp_dir).resolve()
            user_content_dir = Path(tmp_dir) / "local_data" / "user_content"

            with patch.dict("os.environ", {}, clear=True), patch.object(
                server,
                "DEFAULT_CV_MAKER_PROJECT_ROOT",
                project_root,
            ), patch.object(
                server,
                "DEFAULT_CV_MAKER_USER_CONTENT_DIR",
                user_content_dir,
            ):
                link_path = server.ensure_cv_maker_user_content(project_root)

            self.assertTrue(link_path.is_symlink())
            self.assertEqual(link_path.resolve(), user_content_dir.resolve())
            self.assertTrue(user_content_dir.exists())
            for relative_dir in server.CV_MAKER_USER_CONTENT_DIRS:
                self.assertTrue((user_content_dir / relative_dir).is_dir())

    def test_user_content_structure_creates_required_directories(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            user_content_dir = Path(tmp_dir) / "user_content"

            server.ensure_cv_maker_user_content_structure(user_content_dir)

            for relative_dir in server.CV_MAKER_USER_CONTENT_DIRS:
                self.assertTrue((user_content_dir / relative_dir).is_dir())

    def test_managed_project_root_rejects_private_data_directory_in_source(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            project_root = self.make_project_root(tmp_dir).resolve()
            user_content_dir = Path(tmp_dir) / "local_data" / "user_content"
            (project_root / "user_content").mkdir()

            with patch.dict("os.environ", {}, clear=True), patch.object(
                server,
                "DEFAULT_CV_MAKER_PROJECT_ROOT",
                project_root,
            ), patch.object(
                server,
                "DEFAULT_CV_MAKER_USER_CONTENT_DIR",
                user_content_dir,
            ):
                with self.assertRaisesRegex(RuntimeError, "not a symlink"):
                    server.ensure_cv_maker_user_content(project_root)

    def test_resolve_project_root_reports_missing_run_py(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "cv"
            project_root.mkdir()

            with patch.dict(
                "os.environ",
                {server.CV_MAKER_PROJECT_ROOT_ENV: str(project_root)},
                clear=True,
            ):
                with self.assertRaisesRegex(RuntimeError, "run.py"):
                    server.resolve_cv_maker_project_root()

    def test_prepare_job_description_input_writes_raw_text(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            project_root = self.make_project_root(tmp_dir)

            jd_reference, created_path = server.prepare_job_description_input(
                project_root,
                job_description="We need an AI Engineer.",
                job_description_path="",
                job_url="",
            )

            self.assertIsNotNone(created_path)
            self.assertEqual(jd_reference, str(created_path))
            self.assertIn("We need an AI Engineer.", created_path.read_text())
            self.assertIn("user_content/inputs", str(created_path))

    def test_prepare_job_description_requires_exactly_one_source(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            project_root = self.make_project_root(tmp_dir)

            with self.assertRaisesRegex(ValueError, "exactly one"):
                server.prepare_job_description_input(
                    project_root,
                    job_description="raw",
                    job_description_path="jd.txt",
                    job_url="",
                )

    def test_resolve_python_preserves_project_venv_path(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            project_root = self.make_project_root(tmp_dir)
            project_python = project_root / ".venv" / "bin" / "python"
            project_python.parent.mkdir(parents=True)
            project_python.write_text("#!/usr/bin/env python\n", encoding="utf-8")

            with patch.dict("os.environ", {}, clear=True):
                self.assertEqual(
                    server.resolve_cv_maker_python(project_root),
                    project_python,
                )

    def test_build_tailor_command_uses_cv_maker_cli(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            project_root = self.make_project_root(tmp_dir)

            command = server.build_tailor_command(
                project_root,
                jd_reference="jd.txt",
                library="user_content/library",
                template="template.docx",
                output="Role.docx",
                output_format="docx",
                provider="minimax",
                model="MiniMax-M2.7",
                github="example-org",
                suggestions="font,header",
                summarize_years=5,
                no_compile=True,
            )

        self.assertEqual(command[1], "run.py")
        self.assertIn("--jd", command)
        self.assertIn("jd.txt", command)
        self.assertIn("--template", command)
        self.assertIn("template.docx", command)
        self.assertIn("--provider", command)
        self.assertIn("minimax", command)
        self.assertIn("--model", command)
        self.assertIn("MiniMax-M2.7", command)
        self.assertIn("--github", command)
        self.assertIn("example-org", command)
        self.assertIn("--no-compile", command)
        self.assertIn("--quiet", command)

    def test_changed_generated_files_detects_new_and_modified_files(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            generated_dir = Path(tmp_dir) / "generated"
            generated_dir.mkdir()
            existing = generated_dir / "Existing.docx"
            existing.write_text("old", encoding="utf-8")
            before = server.snapshot_generated_files(generated_dir)

            existing.write_text("new", encoding="utf-8")
            created = generated_dir / "Created.docx"
            created.write_text("created", encoding="utf-8")

            changed = server.changed_generated_files(generated_dir, before)

        self.assertEqual(
            [path.name for path in changed],
            ["Created.docx", "Existing.docx"],
        )

    def test_health_tool_reports_ready_project(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            project_root = self.make_project_root(tmp_dir)

            with patch.dict(
                "os.environ",
                {server.CV_MAKER_PROJECT_ROOT_ENV: str(project_root)},
                clear=True,
            ):
                result = server.cv_tailoring_health()

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["project_root"], str(project_root.resolve()))

    def test_tailor_resume_tool_returns_generated_files(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            project_root = self.make_project_root(tmp_dir)
            generated_dir = project_root / "user_content" / "generated_cvs"
            generated_dir.mkdir(parents=True)
            command_result = server.CommandResult(
                exit_code=0,
                command=["python", "run.py"],
                stdout="done",
                stderr="",
            )

            def fake_run(command, *, project_root, timeout_seconds):
                output = generated_dir / "Tailored_CV.docx"
                output.write_text("cv", encoding="utf-8")
                cover = generated_dir / "Tailored_CV_CoverLetter.docx"
                cover.write_text("cover", encoding="utf-8")
                return command_result.model_copy(update={"command": command})

            with patch.dict(
                "os.environ",
                {server.CV_MAKER_PROJECT_ROOT_ENV: str(project_root)},
                clear=True,
            ), patch(
                "mcp_servers.cv_tailoring.server.run_cv_maker_command",
                side_effect=fake_run,
            ):
                result = server.cv_tailor_resume(
                    job_description="We need an AI Engineer.",
                    provider="minimax",
                    model="MiniMax-M2.7",
                )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(
            [Path(path).name for path in result["generated_files"]],
            ["Tailored_CV.docx", "Tailored_CV_CoverLetter.docx"],
        )
        self.assertTrue(result["jd_input_path"].endswith(".txt"))

    def test_list_models_tool_runs_command(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            project_root = self.make_project_root(tmp_dir)
            command_result = server.CommandResult(
                exit_code=0,
                command=["python", "run.py", "--list-models"],
                stdout="MiniMax-M2.7",
                stderr="",
            )

            with patch.dict(
                "os.environ",
                {server.CV_MAKER_PROJECT_ROOT_ENV: str(project_root)},
                clear=True,
            ), patch(
                "mcp_servers.cv_tailoring.server.run_cv_maker_command",
                Mock(return_value=command_result),
            ):
                result = server.cv_tailoring_list_models(provider="minimax")

        self.assertEqual(result["status"], "ready")
        self.assertIn("MiniMax-M2.7", result["stdout"])

    def test_main_runs_streamable_http_service(self) -> None:
        with patch.object(server.mcp, "run") as run_mock:
            server.main(
                [
                    "--transport",
                    "streamable-http",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8765",
                    "--path",
                    "/mcp",
                ]
            )

        self.assertEqual(server.mcp.settings.host, "127.0.0.1")
        self.assertEqual(server.mcp.settings.port, 8765)
        self.assertEqual(server.mcp.settings.streamable_http_path, "/mcp")
        run_mock.assert_called_once_with(transport="streamable-http")
