# AI CV Maker

An advanced, AI-powered tool for tailoring your CV and generating cover letters for specific job descriptions.

## Features

- **Multi-Provider LLM Support**:
  - **Google Vertex AI**: Enterprise-grade performance (Priority).
  - **Google AI Studio**: Access Gemini 2.5 Pro/Flash models.
  - **OpenAI**: Support for GPT-4o/5 family models.
  - **MiniMax**: Support for MiniMax-M2.7 via the Anthropic-compatible Token Plan API, with optional OpenAI-compatible mode.
  - **Auto-Discovery**: Automatically finds and caches available models per provider.
  - **Model Pinning**: Override automatic model selection with `--model`.
  - **Mock Data**: Fallback mode for testing without API keys.

- **Smart Ingestion**:
  - **Job Descriptions**: URL (with Playwright fallback for JS sites), PDF, DOCX, or Text files.
  - **Master Library**: Local folder or **Google Drive / OneDrive** shared folders.
  - **GitHub**: Fetches your top repositories to populate a "Technical Portfolio" section.

- **Template Engine**:
  - **Style Preservation**: Heuristically detects and applies fonts, headers, and bullet styles from your template.
  - **Format Support**: Generates polished DOCX output.
  - **Cover Letter**: Automatically generates a matching cover letter.

- **Cloud Integration**:
  - **GCS Support**: Directly upload outputs to Google Cloud Storage (`gs://`).

- **Local Web UI**:
  - Pixel-style command deck for submitting JDs to the same local CLI pipeline.
  - Application history, JD summaries, generated file links, status tracking, and token dashboard.

## Installation

1. **Clone the repository**:

    ```bash
    git clone https://github.com/jhcook/cv.git
    cd cv
    ```

2. **Install dependencies**:

    ```bash
    # Create a virtual environment recommended
    python3 -m venv .venv
    source .venv/bin/activate
    
    pip install -r requirements.txt
    
    # Check if Playwright is needed (for JS-heavy JD URLs)
    playwright install chromium
    ```

## Configuration

Set up your API keys in `.env` or your shell environment variables. The CLI
loads `.env` automatically when you run `python run.py`.

```dotenv
# MiniMax
MINIMAX_API_KEY="your-minimax-key"
MINIMAX_API_FORMAT="anthropic"
MINIMAX_BASE_URL="https://api.minimax.io/anthropic"
MINIMAX_MAX_TOKENS="32768"

# For OpenAI
OPENAI_API_KEY="sk-..."

# For Google AI Studio
GEMINI_API_KEY="your-key"

# GitHub ingestion
GITHUB_TOKEN="ghp_..."
```

Shell environment variables still take precedence over values in `.env`.

```bash
# For one-off shell usage you can still export values directly.
export MINIMAX_API_KEY="your-minimax-key"

# For Vertex AI
# Ensure you have run: gcloud auth application-default login
```

## Usage

### Smart Path Resolution

The CLI automatically looks in `user_content/` subdirectories if a file isn't found locally:

- **`--jd`**: Checks `user_content/inputs/`
- **`--template`**: Checks `user_content/templates/`
- **`--library`**: Defaults to `user_content/library/`

### Examples

```bash
# Finds 'SRE_Role.txt' in user_content/inputs/
python run.py --jd SRE_Role.txt

# Uses 'Agency_Template.docx' from user_content/templates/
python run.py --jd SRE_Role.txt --template Agency_Template.docx

# Generate a McDowell-style LaTeX resume
python run.py --jd SRE_Role.txt --format latex
```

For LaTeX output, the CLI writes a `.tex` file plus `mcdowellcv.cls` into
`user_content/generated_cvs/`. If `lualatex` or `tectonic` is installed, it also
attempts to compile a PDF. The cover letter is still generated as a DOCX beside
the LaTeX CV. Use `--no-compile` to generate only the `.tex` source.

### Local Web UI

The web UI is optional and does not replace the CLI. It starts a local-only
server and calls `run.py` underneath, so generated files still land in
`user_content/generated_cvs/`.

```bash
python web.py
# Open http://127.0.0.1:8787
```

The page supports:

- JD URL or raw JD text input.
- Provider/model/format/library/template controls.
- Application history discovered from existing generated CVs.
- Status changes saved to `user_content/applications.json`.
- Token usage dashboard parsed from `user_content/logs/cv.log`.
- Google Drive archive links from `user_content/drive_archive_manifest.json`.

### Google Drive Archive

Generated files can be archived to Google Drive with `rclone`. The command
uploads files whose local modified date matches the selected date, creates a
date folder in Google Drive, saves the returned download links locally, then
deletes the uploaded local files by default.

One-time setup:

```bash
brew install rclone
rclone config
```

Add the configured remote destination to `.env`:

```dotenv
GOOGLE_DRIVE_ARCHIVE_REMOTE="gdrive:CV Maker Archive"
```

Archive yesterday's generated files:

```bash
python3 archive_drive.py
```

Useful variants:

```bash
# Preview without upload or delete
python3 archive_drive.py --date yesterday --dry-run

# Upload but keep local files
python3 archive_drive.py --date 2026-05-21 --keep-local

# Archive every generated file dated two days ago or earlier, grouped by date
python3 archive_drive.py --older-than-days 2

# Override the configured remote
python3 archive_drive.py --remote "gdrive:CV Maker Archive"
```

Archive records are saved to `user_content/drive_archive_manifest.json`. The
web UI reads this manifest so archived Drive links remain downloadable after the
local generated files are removed.

### Full Options

```bash
python run.py \
  --jd "SRE_Role.txt" \
  --output "Tailored_CV.docx" \
  --github "jhcook" \
  --verbose
```

### Model Selection

```bash
# Pin a specific model (bypasses automatic selection)
python run.py --jd SRE_Role.txt --model gpt-4o

# Use a specific provider with model pinning
python run.py --jd SRE_Role.txt --provider openai --model gpt-4o-mini

# Use MiniMax M2.7
python run.py --jd SRE_Role.txt --provider minimax --model MiniMax-M2.7

# List available models for a provider
python run.py --list-models --provider openai
python run.py --list-models --provider minimax
```

### Arguments

| Argument | Description | Default |
| :--- | :--- | :--- |
| `--jd` | **Required**. Job Description file or URL. | `user_content/inputs/` |
| `--library` | Master CVs folder (DOCX/PDF). | `user_content/library/` |
| `--template` | Custom DOCX template file. | `user_content/templates/` |
| `--format` | Output format: `docx` or `latex` (McDowell CV). | `docx` |
| `--no-compile` | With `--format latex`, skip PDF compilation and write only `.tex`. | |
| `--output` | Output filename or path (supports `gs://`). | `user_content/generated_cvs/` |
| `--github` | GitHub username for portfolio section. | |
| `--provider` | LLM provider: `auto`, `gemini`, `vertex`, `openai`, `minimax`, `anthropic`, `github`. | `auto` |
| `--model` | Pin a specific model name (e.g. `gpt-4o`, `gemini-2.5-pro`, `MiniMax-M2.7`). Overrides automatic model selection. | Auto-detected |
| `--suggestions` | Comma-separated template overrides (e.g. `font,header`). | |
| `--summarize` | Years of recent experience to detail. | `10` |
| `--list-models`| Discover and list available models for the selected provider, then exit. | |
| `-v` / `--verbose` | Increase verbosity level. | |
| `-q` / `--quiet` | Suppress status output (ERROR only). | |
| `--ca-bundle` | Path to a custom CA certificate bundle (proxy environments). | |

## Proxy / Custom CA Bundle

If you are behind a corporate proxy that uses a custom CA certificate, set one of these environment variables (in priority order):

```bash
export REQUESTS_CA_BUNDLE=/path/to/ca-bundle.crt
export CURL_CA_BUNDLE=/path/to/ca-bundle.crt
export SSL_CERT_FILE=/path/to/ca-bundle.crt
```

Alternatively, pass it directly via the CLI:

```bash
python run.py --jd SRE_Role.txt --ca-bundle /path/to/ca-bundle.crt
```

The `--ca-bundle` flag takes highest priority and overrides any environment variable.

### Merging Public CAs into a Custom Bundle

If your custom CA bundle only contains corporate/proxy certificates, requests to
public sites (e.g. `seek.com.au`) will fail SSL verification. Fix this by
appending Python's built-in public root CAs to your bundle:

```bash
# Find your certifi CA bundle path
python -c "import certifi; print(certifi.where())"

# Append public CAs to your custom bundle (one-time)
cat "$(python -c 'import certifi; print(certifi.where())')" >> /path/to/custom-ca-bundle.pem
```

Or keep a separate merged file:

```bash
cat /path/to/custom-ca-bundle.pem \
    "$(python -c 'import certifi; print(certifi.where())')" \
    > /path/to/merged-ca-bundle.pem

export REQUESTS_CA_BUNDLE=/path/to/merged-ca-bundle.pem
```

Verify the merged bundle works:

```bash
openssl s_client -connect www.seek.com.au:443 \
    -CAfile /path/to/merged-ca-bundle.pem 2>/dev/null | head -5
# Should show: Verify return code: 0 (ok)
```

## Logging & Observability

All LLM interactions are logged to `user_content/logs/cv.log` with DEBUG-level detail. The log directory is created automatically on first run.

Each LLM call logs:
- **Timing**: Elapsed time for each call and retry attempt.
- **Payload sizes**: Prompt character count and response character count.
- **Token usage**: Prompt, completion, and total tokens (OpenAI).
- **Model context**: Provider, model name, and retry state.
- **Error diagnostics**: Full error messages with elapsed time on failure paths.

To increase console verbosity:

```bash
# Verbose console output
python run.py --jd SRE_Role.txt -v

# Full debug trace in the log file (always enabled)
tail -f user_content/logs/cv.log
```

## Directory Structure

The project isolates user data from source code:

- **`user_content/`**: All your local data (created automatically).
  - `library/`: Place your Master CVs here.
  - `inputs/`: Default folder for Job Descriptions.
  - `templates/`: Default folder for custom templates.
  - `generated_cvs/`: Where tailored CVs are saved.
  - `logs/`: Application logs (`cv.log`) — created automatically.
  - `applications.json`: Web UI application status/history state.
  - `drive_archive_manifest.json`: Google Drive archive links for generated files.
  - `library_cache/`: Cached downloads from Cloud Drives.
  - `.model_cache.json`: Cache of discovered LLM models.
- **`src/`**: Application source code (`cv_maker/` package).
- **`tests/`**: Unit tests for `cv_maker` modules.

## Development

### Running Tests

```bash
python -m pytest tests/
```

### Debug Scripts

- **`inspect_template.py`**: Analyze DOCX styles.
- **`compare_docs.py`**: Verify formatting preservation.
