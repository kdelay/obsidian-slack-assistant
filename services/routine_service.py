"""루틴 태스크 관리 — Todo/Routines.json 에 저장."""

import json
from datetime import date
from pathlib import Path
from typing import Optional

WEEKDAY_MAP = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
WEEKDAY_NAMES = ["월", "화", "수", "목", "금", "토", "일"]


class RoutineService:
    def __init__(self, vault: str):
        self.path = Path(vault) / "Todo" / "Routines.json"

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save(self, routines: list[dict]):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(routines, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_routine(self, text: str, frequency: str, category: Optional[str] = None,
                    weekday: Optional[str] = None) -> dict:
        """
        frequency: "daily" | "weekly" | "monthly"
        weekday: "월"~"일" (weekly인 경우)
        """
        routines = self._load()
        next_id = max((r["id"] for r in routines), default=0) + 1
        routine = {
            "id": next_id,
            "text": text,
            "frequency": frequency,
            "category": category,
            "weekday": WEEKDAY_MAP.get(weekday) if weekday else None,
        }
        routines.append(routine)
        self._save(routines)
        return routine

    def list_routines(self) -> list[dict]:
        return self._load()

    def delete_routine(self, text_or_id: str) -> bool:
        routines = self._load()
        before = len(routines)
        routines = [r for r in routines
                    if str(r["id"]) != text_or_id and text_or_id.lower() not in r["text"].lower()]
        if len(routines) == before:
            return False
        self._save(routines)
        return True

    def get_due_today(self, d: Optional[date] = None) -> list[dict]:
        """오늘 자동 추가해야 할 루틴 목록."""
        d = d or date.today()
        due = []
        for r in self._load():
            freq = r.get("frequency", "")
            if freq == "daily":
                due.append(r)
            elif freq == "weekly" and r.get("weekday") == d.weekday():
                due.append(r)
            elif freq == "monthly" and d.day == 1:
                due.append(r)
        return due

    def describe(self, r: dict) -> str:
        freq = r.get("frequency", "")
        if freq == "daily":
            freq_str = "매일"
        elif freq == "weekly":
            wd = r.get("weekday")
            day_name = WEEKDAY_NAMES[wd] if wd is not None else "?"
            freq_str = f"매주 {day_name}"
        elif freq == "monthly":
            freq_str = "매달 1일"
        else:
            freq_str = freq
        cat = f"[{r['category']}] " if r.get("category") else ""
        return f"`{r['id']}` {freq_str} — {cat}{r['text']}"
