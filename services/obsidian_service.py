import fcntl
import re
from datetime import date, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from models.task import Task

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

# 패턴
_DATE_HEADER = re.compile(r"^## (\d{2})\.(\d{2}) \(.\)$")
_WEEK_HEADER = re.compile(r"^# (\d+)주차$")
_CATEGORY_HEADER = re.compile(r"^### (.+)$")
_TASK_LINE = re.compile(r"^- \[(.)\] (.+)$")
_DUE_DATE = re.compile(r"📅 (\d{4}-\d{2}-\d{2})")
_SCHEDULED = re.compile(r"🕐 (\d{2}:\d{2}) (.+)")
_URGENCY = re.compile(r"⚠️\s*")


def _week_of_month(d: date) -> int:
    return (d.day - 1) // 7 + 1


def _date_header(d: date) -> str:
    return f"## {d.month:02d}.{d.day:02d} ({WEEKDAYS[d.weekday()]})"


def _parse_task_line(line: str, d: Optional[date] = None, category: Optional[str] = None) -> Optional[Task]:
    m = _TASK_LINE.match(line)
    if not m:
        return None
    status_map = {"x": "complete", "/": "in_progress", "-": "cancelled", " ": "pending"}
    status = status_map.get(m.group(1), "pending")
    content = m.group(2)

    # 마감일 추출
    due_date = None
    dm = _DUE_DATE.search(content)
    if dm:
        due_date = date.fromisoformat(dm.group(1))
        content = content[:dm.start()].strip()

    # ⚠️ 제거 (내부 저장 시 불필요)
    content = _URGENCY.sub("", content).strip()

    # 일정(🕐) 추출
    is_scheduled = False
    scheduled_time = None
    sm = _SCHEDULED.match(content)
    if sm:
        is_scheduled = True
        scheduled_time = sm.group(1)
        content = sm.group(2)

    return Task(
        text=content,
        status=status,
        due_date=due_date,
        category=category,
        is_scheduled=is_scheduled,
        scheduled_time=scheduled_time,
        task_date=d,
    )


class ObsidianService:
    def __init__(self, vault: str):
        self.vault = Path(vault)
        self.todo_root = self.vault / "Todo"
        self.backlog_path = self.todo_root / "Backlog.md"

    # ── 파일 경로 ────────────────────────────────────────────────

    def get_monthly_file(self, d: date) -> Path:
        return self.todo_root / f"{d.year}년" / f"{d.month}월.md"

    # ── 파싱 ────────────────────────────────────────────────────

    def _read_lines(self, path: Path) -> list[str]:
        if not path.exists():
            return []
        return path.read_text(encoding="utf-8").splitlines(keepends=True)

    def _find_date_section(self, lines: list[str], d: date) -> tuple[int, int]:
        """날짜 섹션의 시작/끝 인덱스 반환. 없으면 (-1, -1)."""
        header = _date_header(d)
        start = -1
        for i, line in enumerate(lines):
            if line.rstrip() == header:
                start = i
                break
        if start == -1:
            return -1, -1

        end = len(lines)
        for i in range(start + 1, len(lines)):
            ln = lines[i].rstrip()
            if ln.startswith("## ") or ln.startswith("# "):
                end = i
                break
        return start, end

    def get_tasks(self, d: date) -> list[Task]:
        path = self.get_monthly_file(d)
        lines = self._read_lines(path)
        start, end = self._find_date_section(lines, d)
        if start == -1:
            return []
        return self._parse_section_tasks(lines[start:end], d)

    def _parse_section_tasks(self, lines: list[str], d: date) -> list[Task]:
        tasks = []
        current_category = None
        for line in lines:
            ln = line.rstrip()
            cm = _CATEGORY_HEADER.match(ln)
            if cm:
                current_category = cm.group(1)
                continue
            if ln.startswith("- [") and not ln.startswith("\t") and not ln.startswith("    "):
                task = _parse_task_line(ln, d=d, category=current_category)
                if task:
                    tasks.append(task)
        return tasks

    def get_tasks_range(self, start_date: date, end_date: date) -> dict[date, list[Task]]:
        result: dict[date, list[Task]] = {}
        d = start_date
        while d <= end_date:
            tasks = self.get_tasks(d)
            if tasks:
                result[d] = tasks
            d += timedelta(days=1)
        return result

    def get_upcoming_tasks(self, days: int = 7) -> list[Task]:
        """오늘~N일 후 마감인 미완료 태스크 수집 (모든 월별 파일 스캔)."""
        today = date.today()
        end = today + timedelta(days=days)
        upcoming = []

        # 필요한 파일들 (이번 달 + 다음 달 정도)
        months = set()
        d = today
        while d <= end:
            months.add((d.year, d.month))
            d += timedelta(days=32)
            d = d.replace(day=1)

        for (year, month) in months:
            path = self.todo_root / f"{year}년" / f"{month}월.md"
            if not path.exists():
                continue
            lines = self._read_lines(path)
            # 전체 파일 스캔해서 📅 마감일이 today~end 범위인 미완료 태스크
            current_date_in_file = None
            current_category = None
            for line in lines:
                ln = line.rstrip()
                dm = _DATE_HEADER.match(ln)
                if dm:
                    m_val, day_val = int(dm.group(1)), int(dm.group(2))
                    current_date_in_file = date(year, m_val, day_val)
                    current_category = None
                    continue
                cm = _CATEGORY_HEADER.match(ln)
                if cm:
                    current_category = cm.group(1)
                    continue
                if ln.startswith("- [") and not ln.startswith("\t"):
                    task = _parse_task_line(ln, d=current_date_in_file, category=current_category)
                    if task and task.due_date and today <= task.due_date <= end and not task.is_complete:
                        upcoming.append(task)

        upcoming.sort(key=lambda t: t.due_date)
        return upcoming

    # ── 쓰기 ────────────────────────────────────────────────────

    def _write_lines(self, path: Path, lines: list[str]):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "r+" if path.exists() else "w", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                f.writelines(lines)
                f.truncate()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def _ensure_date_section(self, lines: list[str], d: date) -> list[str]:
        """날짜 섹션이 없으면 생성하여 반환."""
        header = _date_header(d)
        if any(line.rstrip() == header for line in lines):
            return lines

        new_lines = lines[:]
        week_num = _week_of_month(d)
        week_header = f"# {week_num}주차\n"

        # 삽입 위치: 날짜순으로 적절한 위치 찾기
        insert_pos = len(new_lines)
        for i, line in enumerate(new_lines):
            dm = _DATE_HEADER.match(line.rstrip())
            if dm:
                file_d = date(d.year, int(dm.group(1)), int(dm.group(2)))
                if file_d > d:
                    insert_pos = i
                    break

        # 주차 헤더가 앞에 있는지 확인
        need_week_header = True
        for i in range(insert_pos - 1, -1, -1):
            ln = new_lines[i].rstrip()
            if _WEEK_HEADER.match(ln):
                existing_week = int(_WEEK_HEADER.match(ln).group(1))
                if existing_week == week_num:
                    need_week_header = False
                break
            if ln.startswith("## "):
                break

        section: list[str] = []
        if need_week_header:
            # 앞 내용이 있으면 빈 줄 추가
            if new_lines and insert_pos > 0:
                section.append("\n")
            section.append(week_header)
        section.append(f"{header}\n")
        section.append("---\n")

        new_lines[insert_pos:insert_pos] = section
        return new_lines

    def carry_over_inprogress(self, from_date: date, to_date: date) -> list[str]:
        """from_date의 진행중 태스크를 to_date로 이월. 이미 to_date에 있으면 건너뜀. 추가된 태스크 텍스트 반환."""
        yesterday_tasks = self.get_tasks(from_date)
        today_tasks = self.get_tasks(to_date)
        today_texts = {t.text.lower() for t in today_tasks}

        carried = []
        for t in yesterday_tasks:
            if t.status == "in_progress" and t.text.lower() not in today_texts:
                self.add_task(to_date, t.text, category=t.category, status="in_progress")
                carried.append(t.text)
        return carried

    def add_task(
        self,
        d: date,
        text: str,
        due_date: Optional[date] = None,
        category: Optional[str] = None,
        scheduled_time: Optional[str] = None,
        status: str = "pending",
    ) -> str:
        path = self.get_monthly_file(d)
        lines = self._read_lines(path)

        # frontmatter 없는 기존 파일도 그대로 유지
        if not lines:
            # 새 파일: frontmatter + 주차 헤더 생성
            lines = [f"---\nmonth: {d.year}-{d.month:02d}\n---\n\n"]

        lines = self._ensure_date_section(lines, d)

        # 태스크 줄 생성
        task = Task(
            text=text,
            status=status,
            due_date=due_date,
            category=category,
            is_scheduled=bool(scheduled_time),
            scheduled_time=scheduled_time,
        )
        task_line = task.to_markdown() + "\n"

        # 날짜 섹션 내 삽입 위치
        header = _date_header(d)
        start = next(i for i, l in enumerate(lines) if l.rstrip() == header)

        if category:
            cat_header = f"### {category}\n"
            cat_pos = -1
            for i in range(start + 1, len(lines)):
                ln = lines[i].rstrip()
                if ln == f"### {category}":
                    cat_pos = i
                    break
                if ln.startswith("## ") or ln.startswith("# ") or ln == "---":
                    break

            if cat_pos == -1:
                # 카테고리 섹션 없음 → `---` 앞에 삽입
                insert_pos = start + 1
                for i in range(start + 1, len(lines)):
                    ln = lines[i].rstrip()
                    if ln == "---" or ln.startswith("## ") or ln.startswith("# "):
                        insert_pos = i
                        break
                lines[insert_pos:insert_pos] = [cat_header, task_line]
            else:
                # 카테고리 마지막 태스크 뒤에 삽입
                insert_pos = cat_pos + 1
                for i in range(cat_pos + 1, len(lines)):
                    ln = lines[i].rstrip()
                    if not ln.startswith("- [") and not (lines[i].startswith("\t") or lines[i].startswith("    ")):
                        if not (lines[i].startswith("\t") or lines[i].startswith("    ")):
                            insert_pos = i
                            break
                else:
                    insert_pos = len(lines)
                lines.insert(insert_pos, task_line)
        else:
            # 카테고리 없음 → 날짜 섹션 내 마지막 태스크 뒤에 삽입
            insert_pos = start + 1
            for i in range(start + 1, len(lines)):
                ln = lines[i].rstrip()
                if ln == "---" or (ln.startswith("## ") and i != start) or ln.startswith("# "):
                    insert_pos = i
                    break
                if ln.startswith("- [") and not lines[i].startswith("\t"):
                    insert_pos = i + 1
            lines.insert(insert_pos, task_line)

        self._write_lines(path, lines)
        return task_line.strip()

    def mark_complete(self, d: date, task_text: str) -> bool:
        """task_text와 가장 유사한 미완료 태스크를 완료 처리."""
        path = self.get_monthly_file(d)
        lines = self._read_lines(path)
        start, end = self._find_date_section(lines, d)
        if start == -1:
            return False

        best_ratio = 0.0
        best_idx = -1
        for i in range(start, end):
            ln = lines[i].rstrip()
            m = _TASK_LINE.match(ln)
            if not m or m.group(1) == "x":
                continue
            content = _URGENCY.sub("", m.group(2)).strip()
            content = _DUE_DATE.sub("", content).strip()
            sm = _SCHEDULED.match(content)
            if sm:
                content = sm.group(2)
            ratio = SequenceMatcher(None, task_text, content).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_idx = i

        if best_idx == -1 or best_ratio < 0.5:
            return False

        lines[best_idx] = _TASK_LINE.sub(lambda m: f"- [x] {m.group(2)}", lines[best_idx])
        self._write_lines(path, lines)
        return True

    def update_urgency_tags(self):
        """이번 달 + 다음 달 파일에서 ⚠️ 태그를 마감 임박 여부에 맞게 갱신."""
        today = date.today()
        months = [(today.year, today.month)]
        if today.month == 12:
            months.append((today.year + 1, 1))
        else:
            months.append((today.year, today.month + 1))

        for (year, month) in months:
            path = self.todo_root / f"{year}년" / f"{month}월.md"
            if not path.exists():
                continue
            lines = self._read_lines(path)
            changed = False
            for i, line in enumerate(lines):
                ln = line.rstrip()
                m = _TASK_LINE.match(ln)
                if not m or m.group(1) == "x":
                    continue
                content = m.group(2)
                dm = _DUE_DATE.search(content)
                if not dm:
                    continue
                due = date.fromisoformat(dm.group(1))
                delta = (due - today).days
                has_urgency = "⚠️" in content
                should_be_urgent = 0 <= delta <= 3

                if should_be_urgent and not has_urgency:
                    new_content = _URGENCY.sub("", content).strip()
                    pre = content[: dm.start() - len(new_content) + len(_URGENCY.sub("", content[:dm.start()]).strip())]
                    # 간단하게: content에서 📅 앞 텍스트에 ⚠️ 추가
                    text_part = content[: dm.start()].strip()
                    date_part = content[dm.start() :]
                    lines[i] = f"- [{m.group(1)}] ⚠️ {text_part} {date_part}\n"
                    changed = True
                elif not should_be_urgent and has_urgency:
                    lines[i] = line.replace("⚠️ ", "").replace("⚠️", "")
                    changed = True

            if changed:
                self._write_lines(path, lines)

    # ── 백로그 ──────────────────────────────────────────────────

    def add_backlog(self, text: str, category: Optional[str] = None) -> str:
        lines = self._read_lines(self.backlog_path)

        if not lines:
            lines = [
                f"---\nupdated: {date.today().isoformat()}\n---\n\n# 백로그\n\n"
            ]

        task_line = f"- [ ] {text}\n"
        cat_header = f"## {category}\n" if category else None

        if category:
            cat_pos = -1
            for i, line in enumerate(lines):
                if line.rstrip() == f"## {category}":
                    cat_pos = i
                    break

            if cat_pos == -1:
                # 카테고리 없음 → 파일 끝에 추가
                if lines and not lines[-1].endswith("\n"):
                    lines.append("\n")
                lines.append(f"\n{cat_header}{task_line}")
            else:
                # 카테고리 마지막 항목 뒤에 삽입
                insert_pos = cat_pos + 1
                for i in range(cat_pos + 1, len(lines)):
                    ln = lines[i].rstrip()
                    if ln.startswith("## ") or ln.startswith("# "):
                        insert_pos = i
                        break
                    if ln.startswith("- ["):
                        insert_pos = i + 1
                lines.insert(insert_pos, task_line)
        else:
            # 카테고리 없음 → # 백로그 헤더 바로 아래에 추가
            insert_pos = len(lines)
            for i, line in enumerate(lines):
                if line.rstrip() == "# 백로그":
                    insert_pos = i + 1
                    break
            lines.insert(insert_pos, task_line)

        # updated 날짜 갱신
        for i, line in enumerate(lines):
            if line.startswith("updated:"):
                lines[i] = f"updated: {date.today().isoformat()}\n"
                break

        self._write_lines(self.backlog_path, lines)
        return task_line.strip()

    def get_backlog(self) -> dict[str, list[Task]]:
        lines = self._read_lines(self.backlog_path)
        result: dict[str, list[Task]] = {}
        current_category = "기타"
        for line in lines:
            ln = line.rstrip()
            m = re.match(r"^## (.+)$", ln)
            if m:
                current_category = m.group(1)
                continue
            if ln.startswith("- ["):
                task = _parse_task_line(ln, category=current_category)
                if task and not task.is_complete:
                    result.setdefault(current_category, []).append(task)
        return result
