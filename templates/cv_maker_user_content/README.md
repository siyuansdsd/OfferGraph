# CV Maker user_content Template

This directory documents the private `user_content` layout that CV Maker expects.
Do not put real personal files here.

Real local data belongs in:

```text
local_data/cv_maker/user_content/
```

That runtime directory is ignored by git and is linked from:

```text
external/cv_maker/user_content
```

Expected layout:

```text
user_content/
  library/        Master resumes, portfolio PDFs, or source career material
  templates/      DOCX templates and template guides
  inputs/         Job descriptions saved from URLs or pasted text
  generated_cvs/  Generated resumes and cover letters
  logs/           CV Maker runtime logs
```

Initialize the ignored local runtime layout with:

```bash
./.venv/bin/python scripts/sync_cv_maker.py --init-only
```

If you have a full CV Maker checkout with private `user_content`, sync it with:

```bash
./.venv/bin/python scripts/sync_cv_maker.py /path/to/jc-cv-matcher/cv
```

The sync command does not overwrite existing local `user_content` files unless
`--overwrite-user-content` is passed.
