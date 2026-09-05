"""규칙 엔진.

규칙은 위에서 아래로 평가하고, 처음 걸린 규칙이 이깁니다.
한 규칙 안의 조건들은 모두 만족해야 합니다(AND).

지원하는 조건
  title_contains   : 제목에 이 단어들 중 하나가 있으면 참
  has_due          : true/false — 마감일 유무
  due_within_days  : 정수 — 마감일이 오늘부터 N일 이내면 참(지난 것도 포함)
  overdue          : true/false — 마감일이 오늘보다 지났는지
조건을 비워 두면 항상 참이므로 마지막 기본 규칙으로 씁니다.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .models import TBD, TODO, Task

DEFAULT_RULES: dict[str, Any] = {
    "version": 1,
    "rules": [
        {
            "name": "보류 단어가 있으면 TBD",
            "when": {"title_contains": ["보류", "대기", "미정", "확인 필요", "검토 후", "TBD", "hold"]},
            "then": TBD,
        },
        {
            "name": "마감일이 14일 이내면 TODO",
            "when": {"due_within_days": 14},
            "then": TODO,
        },
        {
            "name": "그 밖에는 TODO",
            "when": {},
            "then": TODO,
        },
    ],
}


def _haystack(task: Task) -> str:
    return task.title.lower()


def _parse_due(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _condition_holds(key: str, expected: Any, task: Task, today: date) -> bool:
    due = _parse_due(task.due)

    if key == "title_contains":
        text = _haystack(task)
        return any(str(word).lower() in text for word in expected or [])

    if key == "has_due":
        return (due is not None) == bool(expected)

    if key == "due_within_days":
        if due is None:
            return False
        try:
            limit = int(expected)
        except (TypeError, ValueError):
            return False
        return (due - today).days <= limit

    if key == "overdue":
        if due is None:
            return False
        return ((due - today).days < 0) == bool(expected)

    # 모르는 조건은 무시하지 않고 불일치로 처리해 오타가 조용히 넘어가지 않게 합니다.
    return False


def classify(task: Task, rules: dict[str, Any], today: date | None = None) -> tuple[str, str | None]:
    """(칸 이름, 적용된 규칙 이름)을 돌려줍니다."""
    today = today or date.today()
    for rule in rules.get("rules", []):
        conditions = rule.get("when") or {}
        if all(_condition_holds(k, v, task, today) for k, v in conditions.items()):
            target = rule.get("then", TODO)
            return (target if target in (TODO, TBD) else TODO), rule.get("name")
    return TODO, None


def apply_rules(tasks: list[Task], rules: dict[str, Any], today: date | None = None) -> int:
    """고정되지 않은 업무에만 규칙을 적용합니다. 칸이 바뀐 건수를 돌려줍니다."""
    today = today or date.today()
    moved = 0
    for task in tasks:
        if task.pinned or task.done:
            continue
        column, rule_name = classify(task, rules, today)
        if column != task.column:
            moved += 1
        task.column = column
        task.matched_rule = rule_name
    return moved


def validate(rules: Any) -> str | None:
    """규칙 파일이 쓸 만한지 확인하고, 문제가 있으면 사람이 읽을 메시지를 돌려줍니다."""
    if not isinstance(rules, dict) or not isinstance(rules.get("rules"), list):
        return "규칙 파일의 최상위는 rules 목록을 가진 객체여야 합니다."
    for index, rule in enumerate(rules["rules"], start=1):
        if not isinstance(rule, dict):
            return f"{index}번째 규칙이 객체가 아닙니다."
        if rule.get("then") not in (TODO, TBD):
            return f"{index}번째 규칙의 then 값은 TODO 또는 TBD여야 합니다."
        if rule.get("when") is not None and not isinstance(rule["when"], dict):
            return f"{index}번째 규칙의 when 값은 객체여야 합니다."
    return None
