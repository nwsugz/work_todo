"""업무 한 건을 표현하는 데이터 모델."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

TODO = "TODO"
TBD = "TBD"
COLUMNS = (TODO, TBD)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Task:
    title: str
    note: str = ""
    start: str | None = None          # "YYYY-MM-DD". 새 업무를 만들 당시 날짜가 기본값
    due: str | None = None            # "YYYY-MM-DD" 또는 None
    tags: list[str] = field(default_factory=list)
    column: str = TODO                # 현재 놓여 있는 칸
    category: str | None = None       # 설정에서 지정한 카테고리(우선순위 정렬에 사용)
    pinned: bool = False              # True면 규칙 자동 분류에서 제외
    matched_rule: str | None = None    # 마지막으로 적용된 규칙 이름
    checked: bool = False             # 체크박스 표시(취소선). 목록 위치·숨김에는 영향 없음
    done: bool = False
    done_at: str | None = None        # 완료 처리된 시각(ISO). 완료를 취소하면 다시 None
    archived: bool = False            # TODO/TBD 화면에서 뺐는지. 완료 이력/DONE 화면에는 계속 남음
    order: int = 0
    parent_id: str | None = None      # 상위 업무 id. 있으면 프로젝트의 하위 업무
    collapsed: bool = False           # 하위 업무를 접어뒀는지 (자신이 상위 업무일 때만 의미 있음)
    id: str = field(default_factory=_new_id)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "note": self.note,
            "start": self.start,
            "due": self.due,
            "tags": list(self.tags),
            "column": self.column,
            "category": self.category,
            "pinned": self.pinned,
            "matched_rule": self.matched_rule,
            "checked": self.checked,
            "done": self.done,
            "done_at": self.done_at,
            "archived": self.archived,
            "order": self.order,
            "parent_id": self.parent_id,
            "collapsed": self.collapsed,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        column = data.get("column", TODO)
        if column not in COLUMNS:
            column = TODO
        return cls(
            title=str(data.get("title", "")).strip() or "(제목 없음)",
            note=str(data.get("note", "")),
            start=data.get("start") or None,
            due=data.get("due") or None,
            tags=[str(t) for t in data.get("tags", []) if str(t).strip()],
            column=column,
            category=(str(data["category"]) if data.get("category") else None),
            pinned=bool(data.get("pinned", False)),
            matched_rule=data.get("matched_rule"),
            checked=bool(data.get("checked", False)),
            done=bool(data.get("done", False)),
            done_at=(str(data["done_at"]) if data.get("done_at") else None),
            archived=bool(data.get("archived", False)),
            order=int(data.get("order", 0)),
            parent_id=(str(data["parent_id"]) if data.get("parent_id") else None),
            collapsed=bool(data.get("collapsed", False)),
            id=str(data.get("id") or _new_id()),
            created_at=str(data.get("created_at") or datetime.now().isoformat(timespec="seconds")),
        )
