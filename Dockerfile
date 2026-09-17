# Single-process image: the FastAPI web console (src/client/web.py) spawns the
# MCP server itself over stdio (MCP_TRANSPORT=stdio, the project default), so
# one container is enough — no second service to deploy or wire up.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces containers run as a non-root uid by convention.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH
WORKDIR $HOME/app

# Large wheels (torch, onnxruntime) can stall mid-download on a slow link;
# pip's default 15s timeout is too short for that, so give it real patience.
ENV PIP_DEFAULT_TIMEOUT=180

# CPU-only torch first. The plain PyPI wheel pulls CUDA libraries that are
# both useless on a CPU Space and add ~2GB to the image for nothing.
RUN pip install --no-cache-dir --user --retries 5 torch --index-url https://download.pytorch.org/whl/cpu

COPY --chown=user . .
RUN pip install --no-cache-dir --user --retries 5 -e .

# Bake the index and the embedding model into the image at build time, so a
# cold container start never blocks on a network fetch (Spaces have no
# guaranteed persistent disk on the free tier — anything not in the image is
# rebuilt from data/raw on every restart otherwise).
RUN python -m src.server.ingest

ENV CLIENT_HOST=0.0.0.0 \
    CLIENT_PORT=7860 \
    MCP_TRANSPORT=stdio

EXPOSE 7860

CMD ["python", "-m", "src.client.web"]
