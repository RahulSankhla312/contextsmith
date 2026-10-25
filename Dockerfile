# ContextSmith MCP server in a container.
#   docker build -t contextsmith .
#   docker run -i --rm -v "$PWD:/repo" contextsmith      # serves the mounted repository over stdio
# Build with --build-arg EXTRAS="[semantic]" for local embeddings (a larger image).
FROM python:3.12-slim

ARG EXTRAS=""
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory '*'

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY contextsmith ./contextsmith
RUN pip install --no-cache-dir ".${EXTRAS}"

WORKDIR /repo
ENV CTXSMITH_ROOT=/repo
ENTRYPOINT ["contextsmith"]
