# liveclip-server

## Project Overview
`liveclip-server` is a Douyin live stream recording and AI smart-clipping backend system. The project provides a CLI and a FastAPI-based REST API for managing live rooms, recording tasks, background workers, and AI clipping processes. 

### Key Technologies
*   **Language:** Python 3.11+
*   **Package Manager:** `uv`
*   **Web Framework:** FastAPI, Uvicorn
*   **CLI Framework:** Typer
*   **Database:** SQLAlchemy 2.0, Alembic
*   **Validation & Config:** Pydantic, Pydantic Settings
*   **Audio/Video & AI:** FFmpeg, `funasr`, `modelscope`, PyTorch, `streamlink`, `yt-dlp`
*   **Logging:** `structlog`

### Architecture
The project is split into several main components located in `src/liveclip/`:
*   **`api/`**: FastAPI application, middleware, and route handlers.
*   **`cli/`**: Typer-based command-line interface with subcommands for `api`, `worker`, `room`, `task`, `run`, `clip`, and `db`.
*   **`db/`**: SQLAlchemy models and database session management.
*   **`config/`**: Configuration loading and application settings via Pydantic.
*   **`pipeline/`, `worker/`, `services/`, `domain/`**: Core logic for live stream recording, processing, and AI smart-clipping tasks.

## Building and Running

### Environment Setup
1.  Ensure you have Python 3.11+ installed.
2.  The project uses `uv` for dependency management. Install dependencies:
    ```bash
    uv pip install -e ".[dev]"
    # or follow standard uv virtual environment setup
    ```
3.  Copy `.env.example` to `.env` and `configs/app.example.toml` to `configs/app.toml` and adjust configurations as needed (e.g., database URL, FFmpeg path, Douyin cookies).

### Key Commands

The project provides utility scripts in the `scripts/` directory for common development tasks:

*   **Linting & Formatting:**
    ```bash
    ./scripts/lint.sh
    ```
    This script runs `ruff format`, `ruff check`, and `mypy` for static type checking.

*   **Database Migrations:**
    ```bash
    ./scripts/migrate.sh
    ```
    This script applies Alembic migrations to upgrade the database schema.

*   **Testing:**
    ```bash
    ./scripts/test.sh
    ```
    This script runs the test suite using `pytest`.

### Running the Application
The entry point for the application is the `liveclip` CLI command.
You can run the API server or the background worker using the CLI:

```bash
# To run the API server
liveclip api

# To run the background worker
liveclip worker
```

## Development Conventions
*   **Type Hinting:** Strict type hinting is enforced using `mypy` (with `disallow_untyped_defs = true`).
*   **Linting:** `ruff` is used for both linting and formatting. Line length is set to 100 characters.
*   **Imports:** The project uses absolute imports starting from `liveclip.*`.
*   **Testing:** Tests are located in the `tests/` directory and use `pytest` with `pytest-asyncio` for asynchronous tests. Coverage is measured using `pytest-cov`.
