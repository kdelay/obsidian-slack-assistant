import json
import re
from datetime import date

import anthropic

_client: anthropic.Anthropic | None = None


def _get_client(api_key: str) -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


SYSTEM_PROMPT = """당신은 개인 할 일 관리 비서입니다. 사용자 메시지를 분석해 아래 JSON 형식으로만 응답하세요.
JSON 외에 어떤 텍스트도 추가하지 마세요.

{{
  "intent": "add_task" | "add_scheduled" | "complete_task" | "cancel_task" | "delete_task" |
            "postpone_task" | "move_from_backlog" | "add_backlog" | "log_day" |
            "query_today" | "query_week" | "query_upcoming" | "query_backlog" |
            "summarize_today" | "weekly_report" | "monthly_summary" | "search_tasks" |
            "query_calendar" | "list_calendars" | "set_calendar_filter" | "query_calendar_filter" |
            "add_routine" | "list_routines" | "delete_routine" | "unknown",
  "task_text": "태스크 내용 | 검색 키워드 | null",
  "scheduled_time": "HH:MM | null",
  "due_date": "YYYY-MM-DD | null",
  "target_date": "YYYY-MM-DD | null",
  "from_date": "YYYY-MM-DD | null",
  "date_range": {{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}} | null,
  "category": "카테고리명 | null",
  "calendar_names": ["캘린더명1"] | null,
  "log_tasks": [{{"task_text": "...", "status": "complete|in_progress|cancelled|pending", "category": "..."}}] | null,
  "backlog_tasks": [{{"task_text": "...", "category": "..."}}] | null,
  "frequency": "daily|weekly|monthly | null",
  "weekday": "월|화|수|목|금|토|일 | null",
  "reply_message": "사용자에게 보낼 자연어 응답 (한국어, 1-2문장)"
}}

intent 선택 기준:
- add_task: 마감일이 있거나 일반적인 할 일 추가
- add_scheduled: 특정 시간이 언급된 일정 추가
- complete_task: 완료했다는 표현 ("완료", "했어", "끝났어")
- cancel_task: 취소 ("취소", "안 해도 돼", "드롭")
- delete_task: 삭제 ("지워줘", "삭제해줘") — cancel_task와 달리 기록 자체를 제거
- postpone_task: 날짜 연기/이동 ("미뤄줘", "내일로 옮겨줘", "다음 주로 연기") — task_text(태스크명), target_date(이동할 날짜), from_date(원래 날짜, 오늘이면 null)
- move_from_backlog: 백로그 항목을 오늘/특정 날로 꺼내기 ("백로그에서 ... 오늘로", "... 꺼내줘") — task_text(항목명), target_date(이동할 날짜, 오늘이면 null)
- add_backlog: 백로그에 새 항목 추가. 여러 개면 backlog_tasks 배열로, 단일이면 task_text
- query_backlog: 백로그 목록 조회 ("백로그", "백로그 보여줘")
- log_day: 오늘 한 일 여러 개 한꺼번에 보고 (log_tasks 배열)
- query_today: 특정 날짜 할 일+일정 통합 조회 (target_date, 오늘이면 null)
- query_week: 이번 주 조회
- query_upcoming: 다가오는 마감 조회
- summarize_today: 오늘 한 일 요약
- weekly_report: 주간 보고서 초안 생성 ("주간 보고서", "주간업무보고 작성해줘")
- monthly_summary: 이번 달 완료 통계 ("이번 달 뭐 했어", "월별 요약") — target_date에 해당 월의 아무 날짜
- search_tasks: 과거 태스크 검색 ("... 언제 했더라", "... 찾아줘") — task_text에 검색 키워드
- query_calendar: 캘린더 일정만 조회 ("캘린더" 키워드 명시한 경우만)
- list_calendars: 캘린더 목록 조회
- set_calendar_filter: 포함할 캘린더 설정
- query_calendar_filter: 현재 캘린더 설정 확인
- add_routine: 루틴 태스크 등록 ("매일", "매주 월요일마다") — task_text, frequency, weekday, category
- list_routines: 루틴 목록 조회 ("루틴 보여줘", "반복 태스크 목록")
- delete_routine: 루틴 삭제 ("루틴 삭제", "... 루틴 없애줘") — task_text에 삭제할 루틴명
- unknown: 위에 해당하지 않음

오늘 날짜: {today}
이번 주 월요일: {monday}
이번 주 일요일: {sunday}
"""

SUMMARIZE_PROMPT = """다음은 오늘 완료한 작업 목록입니다. 자연스럽고 간결하게 요약해주세요 (3-5문장).

{tasks}
"""


def parse_intent(message: str, api_key: str, history: list | None = None) -> dict:
    today = date.today()
    # 이번 주 월/일
    monday = today - __import__("datetime").timedelta(days=today.weekday())
    sunday = monday + __import__("datetime").timedelta(days=6)

    client = _get_client(api_key)
    system = SYSTEM_PROMPT.format(
        today=today.isoformat(),
        monday=monday.isoformat(),
        sunday=sunday.isoformat(),
    )

    messages = list(history) if history else []
    messages.append({"role": "user", "content": message})

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=system,
        messages=messages,
    )

    raw = resp.content[0].text.strip()
    # JSON 블록이 있으면 추출
    code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if code_block:
        raw = code_block.group(1)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "intent": "unknown",
            "task_text": None,
            "scheduled_time": None,
            "due_date": None,
            "target_date": None,
            "date_range": None,
            "category": None,
            "reply_message": "죄송해요, 이해하지 못했어요. 다시 말씀해 주세요.",
        }


def generate_weekly_report(tasks: list, api_key: str) -> str:
    """이번 주 완료 태스크 기반 주간 보고서 초안."""
    if not tasks:
        return "이번 주 완료된 작업이 없어요."
    client = _get_client(api_key)
    lines = []
    for t in tasks:
        cat = f"[{t.category}] " if t.category else ""
        lines.append(f"- {cat}{t.text}")
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        messages=[{"role": "user", "content": (
            f"다음 완료 태스크를 바탕으로 주간업무보고 초안을 작성해주세요.\n\n"
            f"{''.join(f'{l}\n' for l in lines)}\n"
            "형식:\n1. 업무 요약\n2. 주요 완료 사항\n3. 이슈 및 특이사항 (없으면 없음)\n4. 다음 주 계획 (예상)"
        )}],
    )
    return resp.content[0].text.strip()


def generate_monthly_summary(tasks: list, year: int, month: int, api_key: str) -> str:
    """월별 완료 태스크 요약."""
    if not tasks:
        return f"{month}월 완료된 작업이 없어요."
    client = _get_client(api_key)
    by_cat: dict[str, list] = {}
    for t in tasks:
        by_cat.setdefault(t.category or "기타", []).append(t.text)
    lines = [f"{year}년 {month}월 완료 태스크:\n"]
    for cat, texts in by_cat.items():
        lines.append(f"[{cat}] {len(texts)}개")
        for text in texts:
            lines.append(f"  - {text}")
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        messages=[{"role": "user", "content": (
            f"{''.join(f'{l}\n' for l in lines)}\n"
            "위 작업들을 카테고리별로 간결하게 요약해주세요 (3-5문장)."
        )}],
    )
    return resp.content[0].text.strip()


def summarize_tasks(task_lines: list[str], api_key: str) -> str:
    if not task_lines:
        return "오늘 완료된 작업이 없어요."

    client = _get_client(api_key)
    tasks_text = "\n".join(f"- {t}" for t in task_lines)
    prompt = SUMMARIZE_PROMPT.format(tasks=tasks_text)

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()
