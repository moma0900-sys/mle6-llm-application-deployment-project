FROM ghcr.io/astral-sh/uv:0.13.5 AS uv
FROM python:3.13.17-slim

WORKDIR /app

COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY app.py provider.py ./

EXPOSE 8000
CMD ["/app/.venv/bin/python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]