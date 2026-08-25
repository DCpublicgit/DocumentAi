# ARM64-friendly (Oracle A1): both the uv and python:3.12-slim base images
# publish linux/arm64 manifests, and BGE-M3's deps (torch, transformers) ship
# manylinux aarch64 wheels, so this builds natively on ARM without emulation.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Dependencies in their own layer so app-code edits don't invalidate the
# (slow — torch et al.) install step.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

COPY app ./app
RUN uv sync --locked --no-dev

EXPOSE 8000

CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
