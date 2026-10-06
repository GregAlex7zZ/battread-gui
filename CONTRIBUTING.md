# Contributing

Use the development setup in README.md. Before submitting changes, run:

```powershell
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m pyright --pythonpath "$((Get-Command python).Source)"
python tools/check_code_docs.py
```

Keep parsing outside the interface thread. Use battread's public API, preserve
scientific behavior and add regressions for non-trivial changes. Document every
function in English, including helpers and tests; public code uses strict types.

Use synthetic or licensed fixtures. Never commit private acquisitions, outputs,
workspaces, environments or executables. Changes are GPL-3.0-or-later.
For packaging changes, verify the frozen worker, main window, cancellation,
resource files, third-party licenses and corresponding source assets.
