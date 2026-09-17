"""Single source of truth for configuration.

Paths default to a `data/` folder next to the repository root, so the project
runs from a plain `git clone` with no container and no absolute paths.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    # --- paths -------------------------------------------------------------
    data_dir: Path = ROOT / "data"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "index"

    @property
    def memory_dir(self) -> Path:
        return self.data_dir / "memory"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    # --- MCP transport -----------------------------------------------------
    # "stdio" lets a host spawn the server as a subprocess (Claude Desktop, and
    # the default for local development). "http" is for split deployments.
    mcp_transport: str = "stdio"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8100
    mcp_server_url: str = "http://127.0.0.1:8100/mcp"

    # --- retrieval ---------------------------------------------------------
    embedding_model: str = "intfloat/multilingual-e5-small"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    enable_reranker: bool = False
    chunk_size: int = 500
    chunk_overlap: int = 80
    top_k_dense: int = 12
    top_k_lexical: int = 12
    top_k_final: int = 5
    # Calibrated, not guessed: scripts/calibrate.py separates in-scope from
    # out-of-scope questions and reports the midpoint. Re-run it after
    # re-crawling, because the boundary moves with the corpus.
    min_score: float = 0.855

    # --- LLM ---------------------------------------------------------------
    # "auto" uses the API when a usable key is configured; "api" trusts the key
    # as given. A model is required either way — see llm.require().
    llm_mode: str = "auto"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    # The planner call (intent + tool choice + query rewrite) is classification,
    # not prose, so it runs on a smaller model. Empty means "reuse llm_model":
    # llm_base_url may point at Ollama, vLLM or Gemini, where a hardcoded OpenAI
    # model name would 404 on every turn and silently degrade every decision to
    # its rule fallback while the system still looked healthy.
    router_model: str = ""
    llm_temperature: float = 0.1

    # --- client ------------------------------------------------------------
    client_host: str = "127.0.0.1"
    client_port: int = 8000
    max_history_turns: int = 6
    summarize_after_turns: int = 8

    def ensure_dirs(self) -> None:
        for p in (self.raw_dir, self.index_dir, self.memory_dir, self.chroma_dir):
            p.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
