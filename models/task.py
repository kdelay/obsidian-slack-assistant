from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class Task:
    text: str
    status: str = "pending"          # pending | complete | in_progress | cancelled
    due_date: Optional[date] = None
    category: Optional[str] = None
    is_scheduled: bool = False       # 🕐 시간이 있는 일정 여부
    scheduled_time: Optional[str] = None  # "HH:MM"
    task_date: Optional[date] = None  # 이 태스크가 속한 날짜 섹션

    @property
    def is_complete(self) -> bool:
        return self.status == "complete"

    @property
    def is_urgent(self) -> bool:
        """마감 3일 이내 미완료 태스크."""
        if self.is_complete or self.due_date is None:
            return False
        delta = (self.due_date - date.today()).days
        return 0 <= delta <= 3

    def to_markdown(self) -> str:
        """옵시디언 마크다운 체크박스 줄로 변환."""
        status_map = {
            "complete": "x",
            "in_progress": "/",
            "cancelled": "-",
            "pending": " ",
        }
        checkbox = status_map.get(self.status, " ")

        if self.is_scheduled and self.scheduled_time:
            content = f"🕐 {self.scheduled_time} {self.text}"
        else:
            content = self.text

        if self.due_date:
            urgency = "⚠️ " if self.is_urgent else ""
            content = f"{urgency}{content} 📅 {self.due_date.strftime('%Y-%m-%d')}"

        return f"- [{checkbox}] {content}"
