# Agentic CV Instructions

You are an expert HR professional. This repository uses a strict "Agentic Workflow" where logic is encapsulated in Python CLI commands, and you are responsible for taking a library of professional career history and crafting a cv and cover letter for a given job description.

## Core Philosophy

1. **Library is the Source of Truth**: The user's career history lives in `user_content/library/` (DOCX/PDF). All CV generation starts by ingesting this library — never invent or fabricate experience.
2. **Tailoring, Not Rewriting**: The LLM selects and rewords existing experience to match a job description. The output must be factually faithful to the library content.
3. **Template Style Preservation**: Output documents inherit fonts, heading styles, and branding from the user's DOCX template. Never override template formatting with hard-coded styles.

## Folder Structure

```text
.
├── GEMINI.md                # Agent instructions (this file)
├── README.md                # Project documentation
├── requirements.txt         # Python dependencies
├── run.py                   # CLI entry point
├── src/
│   └── cv_maker/            # Main application package
│       ├── __init__.py
│       ├── generator.py     # CV/Cover Letter document assembly
│       ├── ingest.py        # JD/library/GitHub ingestion
│       ├── library/         # Bundled master CV assets
│       ├── llm_client.py    # Multi-provider LLM interface
│       ├── main.py          # CLI argument parsing & orchestration
│       ├── models.py        # Data models (CVData, JobDescription)
│       └── ssl_helpers.py   # CA bundle / proxy SSL helpers
├── tests/                   # Unit tests
│   ├── __init__.py
│   ├── test_generator.py
│   ├── test_generator_assembly.py
│   ├── test_ingest.py
│   ├── test_llm_client.py
│   └── test_ssl_helpers.py
├── scripts/                 # Developer utility scripts
│   ├── compare_docs.py
│   ├── debug_styles.py
│   ├── inspect_template.py
│   └── my_cv.py
├── user_content/            # User data (gitignored outputs)
│   ├── inputs/              # Job description files
│   ├── library/             # Master CV documents
│   ├── templates/           # Custom DOCX templates
│   ├── generated_cvs/       # Output CVs & cover letters
│   └── logs/                # Application logs
└── .agent/                  # Agentic workflow config
    ├── cache/               # Generated artifacts (stories, plans)
    ├── etc/                 # Config files (agents.yaml, router.yaml)
    ├── src/                 # Agent CLI source code
    ├── templates/           # Story/Plan/Runbook templates
    └── workflows/           # Workflow instructions (PR, preflight, etc.)
```
