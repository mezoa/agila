# The Agila API image (block k). Built and run by `docker compose up -d --build`.
# Python 3.12.15 on Debian 12 (glibc 2.36, V91); digest from Eo's pull on 2026-10-24 (U43).
FROM python:3.12-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70

# The same uv as the laptop; digest from Eo's pull on 2026-10-24. The /uv path is U44.
COPY --from=ghcr.io/astral-sh/uv:0.12.17@sha256:10787c682e4184e4f290de1171fd4703dc63de99221f10fe1c99002ce7fa9acc /uv /bin/uv

WORKDIR /app

# Dependencies first, so a code change does not reinstall them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

# Only named files, never `COPY . .` (V87). The model cache is mounted at run time (compose.yaml).
COPY src/ src/
COPY migrations/ migrations/
COPY scripts/healthcheck.py scripts/healthcheck.py

# Editable install, so CACHE_DIR is /app/.cache/fastembed and MIGRATIONS_DIR /app/migrations (V85).
RUN uv sync --locked --no-dev

ENV PATH=/app/.venv/bin:$PATH
CMD ["python", "-m", "agila.api"]
