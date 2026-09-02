from __future__ import annotations

import json
from dataclasses import dataclass, field

from .core import LabelDocument


def document_snapshot(document: LabelDocument) -> str:
    """Create a stable, self-contained history snapshot."""
    return json.dumps(document.to_dict(), ensure_ascii=False, sort_keys=True)


def document_from_snapshot(snapshot: str) -> LabelDocument:
    return LabelDocument.from_dict(json.loads(snapshot))


@dataclass
class DocumentHistory:
    limit: int = 100
    undo_stack: list[str] = field(default_factory=list)
    redo_stack: list[str] = field(default_factory=list)

    def reset(self) -> None:
        self.undo_stack.clear()
        self.redo_stack.clear()

    def record(self, before: str, after: str) -> bool:
        """Record one completed edit. Identical states are ignored."""
        if before == after:
            return False
        self.undo_stack.append(before)
        if len(self.undo_stack) > self.limit:
            del self.undo_stack[: len(self.undo_stack) - self.limit]
        self.redo_stack.clear()
        return True

    def undo(self, current: str) -> str | None:
        if not self.undo_stack:
            return None
        self.redo_stack.append(current)
        return self.undo_stack.pop()

    def redo(self, current: str) -> str | None:
        if not self.redo_stack:
            return None
        self.undo_stack.append(current)
        return self.redo_stack.pop()

    @property
    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self.redo_stack)
