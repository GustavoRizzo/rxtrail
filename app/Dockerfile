# Python is installed and managed by uv, at the version in .python-version.
FROM debian:trixie-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /bin/

ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python and dependencies first, so the layers are cached across source edits.
# Dev dependencies included: this image is for development and tests.
COPY .python-version pyproject.toml uv.lock ./
RUN uv python install && uv sync --locked --no-install-project

COPY . .

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
