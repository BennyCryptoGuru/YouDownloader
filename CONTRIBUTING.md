# Contributing

Thanks for your interest in improving YouDownloader.

## Development setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

## Quality checks

Before opening a pull request, run:

```powershell
python -m pytest -q
python -m ruff check .
node --check frontend/js/app.js
```

## Pull request guidelines

- Keep changes focused and easy to review.
- Do not commit local databases, caches, downloaded media, virtual environments or FFmpeg binaries.
- Update `README.md` when behavior, setup steps or requirements change.
- Respect YouTube's terms and applicable law when testing downloads.
