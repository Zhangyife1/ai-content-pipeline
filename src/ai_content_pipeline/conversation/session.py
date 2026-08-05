"""会话存储：多轮上下文记忆（最近 N 轮 + 事实记忆）。"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field

from ai_content_pipeline.models import ChatMessage


@dataclass
class ConversationSession:
    session_id: str
    history: list[ChatMessage] = field(default_factory=list)
    facts: set[str] = field(default_factory=set)
    last_intent: str = ""

    def add_message(self, role: str, content: str) -> None:
        self.history.append(ChatMessage(role=role, content=content))
        if len(self.history) > 50:  # 防止无限增长
            self.history = self.history[-50:]

    def recent(self, n: int = 6) -> list[str]:
        return [f"{m.role}: {m.content}" for m in self.history[-n:]]

    def remember_fact(self, fact: str) -> None:
        if fact and len(fact) <= 100:
            self.facts.add(fact)


class SessionStore:
    """进程内会话存储。生产环境可替换为 Redis（key: session:{id}，TTL 24h）。"""

    def __init__(self) -> None:
        self._sessions: dict[str, ConversationSession] = {}
        self._lock = threading.RLock()

    def get_or_create(self, session_id: str | None = None) -> ConversationSession:
        session_id = session_id or f"session_{uuid.uuid4().hex[:12]}"
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                session = ConversationSession(session_id=session_id)
                self._sessions[session_id] = session
            return session

    def get(self, session_id: str) -> ConversationSession | None:
        with self._lock:
            return self._sessions.get(session_id)

