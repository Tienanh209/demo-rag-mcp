"""Three-tier memory.

  Short term   - the last N turns verbatim, for immediate coreference.
  Working      - entities and the last topic, so "那個學程呢?" can be resolved
                 without replaying the whole transcript into the prompt.
  Long term    - a rolling summary persisted to disk, so a session survives a
                 restart and long conversations do not grow the prompt without
                 bound.

The split exists because these three have different lifetimes and different
token costs. Keeping them in one blob is the usual mistake: it either forgets
too fast or floods the context window.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.common.config import settings
from src.common.trace import get_logger

log = get_logger("client.memory")


@dataclass
class Turn:
    role: str
    content: str
    # Citations used to live only in the HTTP response, so reopening a session
    # from the sidebar restored the words and silently dropped every source.
    # All three default, so session files written before this still load.
    citations: list[dict[str, Any]] = field(default_factory=list)
    grounded: bool = True
    intent: str = ""


@dataclass
class WorkingMemory:
    entities: list[str] = field(default_factory=list)
    last_topic: str = ""
    last_sources: list[str] = field(default_factory=list)

    def note(self, entities: list[str], topic: str, sources: list[str]) -> None:
        for e in entities:
            if e and e not in self.entities:
                self.entities.append(e)
        self.entities = self.entities[-12:]
        if topic:
            self.last_topic = topic
        if sources:
            self.last_sources = sources[:5]


class ConversationMemory:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.turns: list[Turn] = []
        self.working = WorkingMemory()
        self.summary = ""
        self.title = ""
        self.updated_at = ""
        self._path = settings.memory_dir / f"{session_id}.json"
        self._load()

    # --- tiers -------------------------------------------------------------
    def add(
        self,
        role: str,
        content: str,
        citations: list[dict[str, Any]] | None = None,
        grounded: bool = True,
        intent: str = "",
    ) -> None:
        # The first thing the user asked is the only label a session has; the
        # sidebar has nothing else to show in a list of past conversations.
        if role == "user" and not self.title:
            self.title = " ".join(content.split())[:60]
        self.turns.append(Turn(role, content, citations or [], grounded, intent))

    def recent(self) -> list[Turn]:
        return self.turns[-settings.max_history_turns * 2 :]

    def transcript(self) -> str:
        return "\n".join(f"{t.role}: {t.content}" for t in self.recent())

    def context_block(self) -> str:
        """What every agent sees. Compact by construction."""
        parts = []
        if self.summary:
            parts.append(f"[Conversation summary]\n{self.summary}")
        if self.working.last_topic:
            parts.append(f"[Current topic] {self.working.last_topic}")
        if self.working.entities:
            parts.append(f"[Known entities] {', '.join(self.working.entities)}")
        if self.turns:
            parts.append(f"[Recent turns]\n{self.transcript()}")
        return "\n\n".join(parts)

    def needs_summary(self) -> bool:
        return len(self.turns) >= settings.summarize_after_turns * 2 and (
            len(self.turns) % (settings.summarize_after_turns * 2) == 0
        )

    def set_summary(self, summary: str) -> None:
        self.summary = summary.strip()
        log.info("session %s summary updated (%d chars)", self.session_id, len(self.summary))

    # --- persistence -------------------------------------------------------
    def save(self) -> None:
        self.updated_at = datetime.now(UTC).isoformat(timespec="seconds")
        payload = {
            "session_id": self.session_id,
            "title": self.title,
            "updated_at": self.updated_at,
            "summary": self.summary,
            "working": asdict(self.working),
            # Kept at 200 rather than 40: the sidebar's whole promise is that
            # clicking a conversation brings it back, and a silently truncated
            # restore breaks that. recent() still bounds what reaches a prompt,
            # so this costs disk, not tokens.
            "turns": [asdict(t) for t in self.turns[-200:]],
        }
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data: dict[str, Any] = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("session %s is corrupt — starting it empty", self.session_id)
            return
        self.summary = data.get("summary", "")
        self.title = data.get("title", "")
        self.updated_at = data.get("updated_at", "")
        self.working = WorkingMemory(**data.get("working", {}))
        self.turns = [Turn(**t) for t in data.get("turns", [])]
        log.info("restored session %s (%d turns)", self.session_id, len(self.turns))


_sessions: dict[str, ConversationMemory] = {}

# A session id becomes a filename, so it is validated before it ever touches a
# path. Anything else lets "../../etc/passwd" through.
_VALID_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def valid_session_id(session_id: str) -> bool:
    return bool(_VALID_ID.match(session_id))


def get_memory(session_id: str) -> ConversationMemory:
    if session_id not in _sessions:
        _sessions[session_id] = ConversationMemory(session_id)
    return _sessions[session_id]


def list_sessions() -> list[dict[str, Any]]:
    """Every saved conversation, newest first, for the sidebar."""
    out: list[dict[str, Any]] = []
    for path in settings.memory_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log.warning("skipping unreadable session file %s", path.name)
            continue
        turns = data.get("turns", [])
        out.append(
            {
                "session_id": data.get("session_id", path.stem),
                "title": data.get("title") or _first_user_line(turns) or "New conversation",
                "updated_at": data.get("updated_at", ""),
                "turns": len(turns),
            }
        )
    out.sort(key=lambda s: s["updated_at"], reverse=True)
    return out


def _first_user_line(turns: list[dict[str, Any]]) -> str:
    """Label for sessions saved before titles existed."""
    for t in turns:
        if t.get("role") == "user":
            return " ".join(str(t.get("content", "")).split())[:60]
    return ""


def delete_session(session_id: str) -> bool:
    _sessions.pop(session_id, None)
    path = settings.memory_dir / f"{session_id}.json"
    if not path.exists():
        return False
    path.unlink()
    return True
