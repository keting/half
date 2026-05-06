FROM python:3.12-slim

RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock .
RUN uv sync --no-dev --frozen

COPY . .

RUN mkdir -p /app/data /app/repos

ENV HALF_DB_PATH=/app/data/half.db
ENV HALF_REPOS_DIR=/app/repos

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
