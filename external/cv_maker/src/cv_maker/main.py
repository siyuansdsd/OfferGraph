
# Copyright 2026 Justin Cook
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Main entry point for the CV Maker CLI.
"""

import argparse
import os
import sys
import logging
from pathlib import Path
import re

from collections import deque

try:
    from rich.logging import RichHandler
except ImportError:
    RichHandler = None

class StatusLogHandler(logging.Handler):
    """
    Custom handler to store the last N logs for a scrolling status display.
    """
    def __init__(self, console, maxlen=5):
        super().__init__()
        self.console = console
        self.maxlen = maxlen
        self.logs = deque(maxlen=maxlen)
        self.live = None

    def emit(self, record):
        try:
            msg = self.format(record)
            self.logs.append(msg)
            if self.live:
                self.live.update(self.get_renderable())
        except Exception:
            self.handleError(record)

    def get_renderable(self):
        from rich.text import Text
        # Join logs with newlines, color them dim grey
        text_content = "\n".join(self.logs)
        return Text(text_content, style="dim grey50")

# Ensure the project root is on sys.path so `cv_maker.*` imports resolve
# regardless of how the script is invoked (python cv_maker/main.py, python -m, etc.)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cv_maker.ingest import read_url, read_docx, ingest_library, read_pdf
from cv_maker.ssl_helpers import get_ca_bundle, set_ca_bundle_override
from cv_maker.llm_client import LLMClient
from cv_maker.generator import CVGenerator
from cv_maker.latex_generator import McDowellLatexGenerator

logger = logging.getLogger(__name__)

def setup_logging(verbosity: int, quiet: bool = False, custom_handler: logging.Handler = None):
    """
    Configures logging:
    - File: logs/cv.log (DEBUG)
    - Console: Default=INFO (dim), -q=ERROR, -v=INFO/DEBUG
    """
    log_dir = Path("user_content/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "cv.log"

    # Root Logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG) # Capture everything at root

    # Formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # File Handler (Always DEBUG)
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    
    # Determine Level
    if verbosity == 0:
        level = logging.ERROR
    elif verbosity == 1:
        level = logging.WARNING
    elif verbosity == 2:
        level = logging.INFO
    elif verbosity >= 3:
        level = logging.DEBUG
    elif quiet:
        level = logging.ERROR
    else:
        level = logging.INFO

    console_handler.setLevel(level)
    
    if custom_handler:
        # If a custom handler is provided (e.g. for rich status), usage it instead of stream
        custom_handler.setLevel(level)
        # Use simple format for status logs too, or let handler decide
        custom_handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(custom_handler)
    else:
        # Simple format for console
        console_formatter = logging.Formatter('%(message)s') 
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
    
    # Silence some noisy libs if not in super debug
    if verbosity < 3:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

def download_template(url: str) -> str:
    """Downloads a template from a URL to a temporary file."""
    try:
        import requests
        import tempfile
        
        logger.info(f"Downloading template from: {url}")
        resp = requests.get(url, timeout=15, verify=get_ca_bundle())
        resp.raise_for_status()
        
        # Create temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
            tmp.write(resp.content)
            return tmp.name
    except Exception as e:
        logger.error(f"Failed to download template: {e}")
        return None

def upload_to_gcs(local_path: str, gcs_path: str):
    """
    Uploads a file to Google Cloud Storage.
    gcs_path should be in format: gs://bucket-name/path/to/object
    """
    try:
        from google.cloud import storage
        
        if not gcs_path.startswith("gs://"):
            logger.error(f"Invalid GCS path: {gcs_path}")
            return

        # Parse bucket and blob
        path_without_scheme = gcs_path[5:]
        bucket_name = path_without_scheme.split("/")[0]
        blob_name = "/".join(path_without_scheme.split("/")[1:])
        
        # If gcs_path ended in a slash or is just a bucket, treat as directory
        if gcs_path.endswith("/") or not blob_name:
             blob_name = os.path.join(blob_name, os.path.basename(local_path))
             # Remove leading slash if any joined
             if blob_name.startswith("/"): blob_name = blob_name[1:]

        logger.info(f"Uploading to GCS: gs://{bucket_name}/{blob_name}")
        
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(local_path)
        
        logger.info(f"    > Upload success: https://storage.cloud.google.com/{bucket_name}/{blob_name}")
        
    except ImportError:
        logger.error("google-cloud-storage not installed. Cannot upload to GCS.")
    except Exception as e:
        logger.error(f"Failed to upload to GCS: {e}")

    except Exception as e:
        logger.error(f"Failed to upload to GCS: {e}")

def _resolve_path(path: str, default_subdir: str | list[str]) -> str:
    """
    Smartly resolves a path.
    1. If it exists as is, return it.
    2. If it is a URL/GCS path, return it.
    3. If it exists in user_content/{subdir}/{path} for any subdir, return that.
    4. Return original path (to let downstream fail/handle it).

    ``default_subdir`` can be a single directory name or a list of directory
    names to search in order (first match wins).
    """
    if not path:
        return path
    
    # 1. Check existence or URL
    if os.path.exists(path) or path.startswith("http") or path.startswith("gs://"):
        return path
    
    # 2. Check in user_content subdirs (in priority order)
    subdirs = [default_subdir] if isinstance(default_subdir, str) else default_subdir
    for subdir in subdirs:
        namespaced_path = os.path.join("user_content", subdir, path)
        if os.path.exists(namespaced_path):
            logger.info(f"Resolved '{path}' to '{namespaced_path}'")
            return namespaced_path
        
    return path

def _cover_letter_output_path(cv_output_path: str) -> str:
    """
    Derives a DOCX cover-letter path from the generated CV path.
    Works for DOCX and LaTeX/PDF CV outputs.
    """
    path = Path(cv_output_path)
    if path.suffix:
        return str(path.with_name(f"{path.stem}_CoverLetter.docx"))
    return f"{cv_output_path}_CoverLetter.docx"

def main():
    try:
        _main_cli()
    except KeyboardInterrupt:
        import sys
        # Use stderr so it captures attention even if stdout is redirected or rich
        sys.stderr.write("\n\033[31m[-] Cancelled by user\033[0m\n")
        sys.exit(130)

def _main_cli():
    """
    Parses arguments, ingests JD and Library, calls LLM to tailor CV, and generates output.
    """
    parser = argparse.ArgumentParser(description="AI Powered CV Maker")
    parser.add_argument("--jd", required=False, help="URL or file path to the Job Description")
    parser.add_argument("--library", default="user_content/library", help="Path to local library or Cloud Folder URL (GDrive/OneDrive)")
    parser.add_argument("--output", default="Tailored_CV.docx", help="Output filename")
    parser.add_argument("--list-models", action="store_true", help="List available auto-discovered models")
    parser.add_argument("--github", help="GitHub username to ingest (e.g., username)")
    parser.add_argument("--template", help="Path or URL to a DOCX template file")
    parser.add_argument("--format", choices=["docx", "latex"], default="docx", help="Output format: docx or latex/McDowell PDF (default: docx)")
    parser.add_argument("--no-compile", action="store_true", help="For --format latex, generate .tex only and skip lualatex PDF compilation")
    parser.add_argument("--suggestions", help="Comma-separated overrides for template (e.g. 'font,header')")
    parser.add_argument("--summarize", type=int, default=10, help="Years of recent experience to detail (default: 10). Older roles are summarized. Set to 0 to disable.")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase output verbosity (-v=WARNING, -vv=INFO, -vvv=DEBUG)")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress status output (ERROR only)")
    parser.add_argument("--ca-bundle", help="Path to a custom CA certificate bundle for HTTPS verification (proxy environments)")
    parser.add_argument("--provider", default="auto", choices=["auto", "gemini", "vertex", "openai", "minimax", "anthropic", "github"], help="LLM provider to use (default: auto)")
    parser.add_argument("--model", default=None, help="Specific model name to use (e.g. gpt-4o, gemini-2.5-pro, MiniMax-M2.7). Overrides automatic model selection for the chosen provider.")
    
    args = parser.parse_args()

    # Configure custom CA bundle if provided via CLI
    if getattr(args, 'ca_bundle', None):
        set_ca_bundle_override(args.ca_bundle)

    # Check for quiet mode
    if getattr(args, 'quiet', False):
        setup_logging(0, quiet=True)
        # We proceed with silent execution (except errors)
    elif args.verbose == 0:
        # Default mode: Use Rich Status Log if available
        try:
            from rich.console import Console
            from rich.live import Live
            from rich.text import Text
            
            console = Console()
            status_handler = StatusLogHandler(console)
            setup_logging(2, custom_handler=status_handler)
            
            # Run everything inside the Live context
            def update_status():
                 return status_handler.get_renderable()

            with Live(update_status(), refresh_per_second=4, console=console) as live:
                status_handler.live = live
                logger.info("--- CV Maker ---")
                _run_main_logic(args, parser)
                
            sys.exit(0)
            
        except ImportError:
             # Fallback if rich is missing despite being in requirements
            setup_logging(args.verbose)
            logger.info("--- CV Maker ---")
            _run_main_logic(args, parser)
            sys.exit(0)
    else:
        # Verbose mode
        setup_logging(args.verbose)
        logger.info("--- CV Maker ---")
        _run_main_logic(args, parser)

def _run_main_logic(args, parser):
    """
    Refactored main logic to allow wrapping in context managers.
    """
    if args.list_models:
        logger.info("[*] discovering models...")
        client = LLMClient(provider=args.provider, model=args.model)
        models = client.discover_models()
        if models:
            # Save to cache explicitly when user runs --list-models
            client._save_cache(models)
            print(f"\nAvailable models for provider '{client.provider}' ({len(models)} found):\n")
            for m in models:
                print(f"  - {m}")
            print()
        else:
            print(f"\n[!] Could not auto-discover models for provider '{client.provider}'. Ensure API key is set.\n")
        sys.exit(0)
    
    # 0. Pre-validate DOCX template (if provided) to fail fast / save tokens
    if args.template and args.format == "docx":
        template_candidate = _resolve_path(args.template, ["templates", "library", "generated_cvs"])

        # Just check existence for local files.
        if not template_candidate.startswith(("http", "gs://")):
            if not os.path.exists(template_candidate):
                 logger.error(f"Template file not found: {template_candidate}. Checked CWD, user_content/templates, user_content/library, and user_content/generated_cvs.")
                 sys.exit(1)

    # 1. Ingest JD
    if not args.jd:
        parser.error("The --jd argument is required unless --list-models is used.")
    
    logger.info(f"Ingesting Job Description from: {args.jd}")
    
    # Resolve JD path — check inputs first, then generated CVs and library
    jd_path = _resolve_path(args.jd, ["inputs", "generated_cvs", "library"])

    if jd_path.startswith("http"):
        jd_text = read_url(jd_path)
    else:
        # Assume text file or docx
        if jd_path.lower().endswith(".docx"):
            jd_text = read_docx(jd_path)
        elif jd_path.lower().endswith(".pdf"):
            jd_text = read_pdf(jd_path)
        else:
            try:
                with open(jd_path, 'r') as f:
                    jd_text = f.read()
            except Exception as e:
                logger.error(f"Failed to read JD file: {e}")
                sys.exit(1)

    if not jd_text:
        logger.error("Could not extract text from JD. Exiting.")
        sys.exit(1)
    
    # 2. Ingest Library
    logger.info(f"Ingesting Master Library from: {args.library}")
    if args.library.startswith("http"):
         logger.info("    > Detected Cloud URL. Attempting download...")
    library = ingest_library(args.library)
    if not library:
        logger.error("Library is empty or not found. Please populate ./library with master CVs.")
        sys.exit(1)
    
    # Combine library content into one "Master Resume" blob for the LLM
    # With Gemini 1.5 Flash (1M+ context), we can just dump everything.
    master_cv_text = "\n\n".join([f"--- SOURCE: {k} ---\n{v}" for k, v in library.items()])

    # 3. LLM Pipeline
    client = LLMClient(provider=args.provider, model=args.model)
    
    logger.info("Analyzing Job Description...")
    jd_data = client.analyze_job_description(jd_text)
    logger.info(f"    > Target Role: {jd_data.summary}")
    logger.info(f"    > Key Skills: {', '.join(jd_data.key_skills)}")

    logger.info("Tailoring CV (this may take a moment)...")
    cv_data = client.tailor_cv(master_cv_text, jd_data, summarize_years=args.summarize)
    if args.github:
        cv_data.github_url = f"github.com/{args.github}"

    logger.info("Drafting Cover Letter...")
    cover_letter_text = client.generate_cover_letter(master_cv_text, jd_data)

    # 6. Generate Output
    output_dir = "user_content/generated_cvs"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        logger.info(f"Created output directory: {output_dir}")
    
    # Handle output path
    gcs_target = None
    output_ext = ".docx" if args.format == "docx" else ".tex"
    if args.output.startswith("gs://"):
        gcs_target = args.output
        # If the GCS path looks like a directory (ends in /) or is just a bucket, 
        # we want to use the dynamic filename logic below.
        # Otherwise, if it's a full path (gs://bucket/file.docx), we use that basename.
        if not gcs_target.endswith(output_ext):
            # Treating as directory/bucket, so we let the dynamic logic below run 
            # by setting args.output to default temporarily or just ensuring final_output is local
            pass 
        else:
            # User specified full GCS path.
            # We'll generate to a temp local file with the same name
            final_output = os.path.join(output_dir, os.path.basename(gcs_target))
            
    # If we haven't set final_output yet (either regular run or GCS directory run)
    if 'final_output' not in locals():
        if os.path.dirname(args.output) and not args.output.startswith("gs://"):
            # User specified a local path, respect it
            final_output = args.output
        else:
            # Check if default filename strictly matches OR we are in GCS directory mode.
            # If so, try to use role_title.
            is_default = (args.output == "Tailored_CV.docx")
            is_gcs_dir = (gcs_target and not gcs_target.endswith(".docx"))

            if (is_default or is_gcs_dir) and jd_data.role_title:
                 # Construct filename: {Company}_{Role} or just {Role}
                 parts = []
                 if jd_data.company_name:
                     parts.append(jd_data.company_name)
                 parts.append(jd_data.role_title)
                 
                 full_title = " ".join(parts)
                 safe_title = re.sub(r'[^\w\s-]', '', full_title)
                 safe_title = re.sub(r'[-\s]+', '_', safe_title).strip('-_')
                 if safe_title:
                     safe_title = safe_title[:80] # Slightly longer for company+role
                     final_output = os.path.join(output_dir, f"{safe_title}{output_ext}")
                 else:
                     final_output = os.path.join(output_dir, f"Tailored_CV{output_ext}")
            else:

                 # Fallback: Use the basename of what was provided if it's not a GS path,
                 # or if we failed to get a role title.
                 # If it was a GCS directory, args.output might be the bucket string, so we default
                 if is_gcs_dir:
                     final_output = os.path.join(output_dir, f"Tailored_CV{output_ext}")
                 else:
                     output_name = os.path.basename(args.output)
                     if args.format == "latex" and output_name.endswith(".docx"):
                         output_name = re.sub(r"\.docx$", ".tex", output_name, flags=re.IGNORECASE)
                     final_output = os.path.join(output_dir, output_name)

    logger.info(f"Generating {args.format.upper()} to: {final_output}")
    try:
        template_path = None
        if args.template:
            # Re-run robust resolution here so cover letters can reuse DOCX template
            # styling even when the CV itself is generated as LaTeX/PDF.
            template_candidate = _resolve_path(args.template, ["templates", "library", "generated_cvs"])

            if template_candidate.startswith("http"):
                template_path = download_template(template_candidate)
            else:
                template_path = template_candidate

        suggestions = args.suggestions.split(",") if args.suggestions else []

        if args.format == "latex":
            generator = McDowellLatexGenerator()
            pdf_path = generator.generate(cv_data, final_output, compile_pdf=not args.no_compile)

            cl_filename = _cover_letter_output_path(final_output)
            cover_generator = CVGenerator(template_path=template_path, suggestions=suggestions)
            cover_generator.generate_cover_letter(cv_data, cover_letter_text, cl_filename)

            if gcs_target:
                upload_to_gcs(final_output, gcs_target)
                if pdf_path:
                    upload_to_gcs(pdf_path, gcs_target)
                upload_to_gcs(cl_filename, gcs_target)

            # Clean up temp file if downloaded
            if template_path and args.template and args.template.startswith("http"):
                try:
                    os.remove(template_path)
                except: pass
            logger.info("Done!")
            return
        
        generator = CVGenerator(template_path=template_path, suggestions=suggestions)
        generator.generate(cv_data, final_output)
        
        # Generate Cover Letter
        cl_filename = _cover_letter_output_path(final_output)
        
        generator.generate_cover_letter(cv_data, cover_letter_text, cl_filename)
        
        # Clean up temp file if downloaded
        if template_path and args.template and args.template.startswith("http"):
            try:
                os.remove(template_path)
            except: pass

        # Handle GCS Upload
        if gcs_target:
            upload_to_gcs(final_output, gcs_target)
            upload_to_gcs(cl_filename, gcs_target)
            
    except Exception as e:
        logger.error(f"Error generating CV: {e}")
        # logging.exception("Detailed generation error:")
        sys.exit(1)
    
    logger.info("Done!")

if __name__ == "__main__":
    main()
