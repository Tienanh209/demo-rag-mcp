# Prefer the venv interpreter without needing it activated. `make stdio-config`
# in particular must emit an interpreter that actually has the dependencies —
# the system python produces a config Claude Desktop cannot start.
PY ?= $(shell test -x .venv/bin/python && printf '%s/.venv/bin/python' '$(CURDIR)' || echo python)
.PHONY: help install resolve check-links crawl ingest demo smoke calibrate run stop cli test eval lint clean stdio-config

help:  ## show this help
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | column -t -s "$$(printf '\t')"

install:  ## install everything, then create .env (set LLM_API_KEY before running)
	$(PY) -m pip install -e ".[dev]"
	@test -f .env || cp .env.example .env
	@echo "Set LLM_API_KEY in .env — the client exits at startup without one."

resolve:  ## point every retired document at a real ai.yzu.edu.tw citation (offline)
	$(PY) -m scripts.resolve_sources --apply

crawl:  ## add the current site to data/raw (needs network; never use --clear)
	$(PY) -m scripts.crawl_yzu

ingest:  ## (re)build the index from data/raw
	$(PY) -m src.server.ingest

demo:  ## scripted end-to-end conversation over MCP stdio
	$(PY) -m scripts.demo

smoke:  ## server-side health check (transport, tools, retrieval) — no LLM
	$(PY) -m scripts.smoke_server

check-links:  ## assert every citation URL resolves on ai.yzu.edu.tw (network)
	$(PY) -m scripts.smoke_server --check-links

calibrate:  ## find a defensible MIN_SCORE for the current corpus
	$(PY) -m scripts.calibrate

run:  ## start the web console at http://127.0.0.1:8000
	$(PY) -m src.client.web

stop:  ## kill the web console if it was left running in the background
	@pkill -f 'src\.client\.web' && echo "stopped" || echo "not running"

cli:  ## interactive terminal client
	$(PY) -m src.client.cli

test:  ## unit tests
	$(PY) -m pytest -q

eval:  ## retrieval evaluation
	$(PY) -m scripts.evaluate

lint:
	$(PY) -m ruff check src scripts tests

stdio-config:  ## print the Claude Desktop config block
	@printf '{\n  "mcpServers": {\n    "yzu-ai-center": {\n      "command": "%s",\n      "args": ["-m", "src.server.app"],\n      "cwd": "%s",\n      "env": {"MCP_TRANSPORT": "stdio"}\n    }\n  }\n}\n' "$$(command -v $(PY) || echo $(PY))" "$(PWD)"

clean:  ## drop the index, chroma db, and conversation memory (keeps data/raw)
	rm -rf data/index data/chroma data/memory
	@echo "data/raw kept — every archived document there exists nowhere else, not even on the web."
