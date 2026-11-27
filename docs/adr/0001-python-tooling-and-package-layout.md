# Use src package layout, app factory, and Pyright

We organize the application under `src/product_studio/` (built as an editable package via `uv` with `[project.scripts]` and bundled `static/` assets), expose a side-effect-free `create_app()` factory using FastAPI `Depends` instead of module-level mutable state or import-time `.env` overrides, and standardize on `pyright` (`standard` mode) alongside `ruff` and `pytest`.

## Considered Options

- **Flat root layout (`package = false`)**: lower initial diff, but mixes runtime modules into the repo root, requires `pythonpath` workarounds for `pytest`, and cannot expose `[project.scripts]` entry points.
- **`ty` / `mypy` for type checking**: `ty` is still pre-1.0 beta with evolving diagnostics; `mypy` requires the `pydantic.mypy` plugin and diverges from Pylance. `pyright` matches VS Code/Cursor Pylance diagnostics out of the box and supports Pydantic v2 without plugins.

## Consequences

- Runtime outputs default to `./outputs` relative to the working directory (overridable via `OUTPUT_DIR` or `create_app(output_dir=...)`) and are never written under `src/`.
- `.env` is loaded only from the project directory with `override=False` at explicit entry points (`load_env=False` in tests), preventing parent-directory or local secret leakage during tests.
