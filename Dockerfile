# Bridge — offline demo image. `docker compose up` serves a live dashboard of a
# full CUDA->ROCm migration on a GPU-less machine, no API key required.
FROM python:3.11-slim

# git is required: the agent makes real commits per fix during a run.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system user.email "bridge@example.com" \
    && git config --system user.name "Bridge" \
    && git config --system init.defaultBranch main

WORKDIR /app

# Minimal runtime deps: core + dashboard. No LLM/network deps needed for the demo.
RUN pip install --no-cache-dir "pydantic>=2,<3" "PyYAML>=6,<7" "fastapi>=0.110,<1" "uvicorn>=0.29,<1"

COPY bridge ./bridge
COPY prompts ./prompts
COPY fixtures ./fixtures
COPY docker ./docker
COPY config.replay.example.yaml ./

EXPOSE 8000
ENTRYPOINT ["bash", "/app/docker/entrypoint.sh"]
