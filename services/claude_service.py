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
  "intent": "add_task" | "add_scheduled" | "complete_task" | "add_backlog" | "log_day" | "query_today" | "query_week" | "query_upcoming" | "query_backlog" | "summarize_today" | "query_calendar" | "list_calendars" | "set_calendar_filter" | "query_calendar_filter" | "unknown",
  "task_text": "태스크 내용 (add_task/add_scheduled/complete_task/add_backlog 시 필수)",
  "scheduled_time": "HH:MM 형식 | null",
  "due_date": "YYYY-MM-DD 형식 | null",
  "target_date": "YYYY-MM-DD 형식 (특정 날짜 조회 시) | null",
  "date_range": {{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}} | null,
  "category": "카테고리명 (언급된 경우) | null",
  "calendar_names": ["캘린더명1", "캘린더명2"] | null,
  "log_tasks": [{{"task_text": "...", "status": "complete|in_progress|cancelled|pending", "category": "..."|null}}] | null,
  "backlog_tasks": [{{"task_text": "...", "category": "..."|null}}] | null,
  "reply_message": "사용자에게 보낼 자연어 응답 (한국어, 1-2문장)"
}}

intent 선택 기준:
- add_task: 마감일이 있거나 일반적인 할 일 추가
- add_scheduled: 특정 시간이 언급된 일정 추가 ("13시", "오후 3시" 등)
- complete_task: 완료했다는 표현 ("완료", "했어", "끝났어", "처리했어")
- add_backlog: 백로그에 새 항목 추가. 여러 항목이면 backlog_tasks 배열로, 단일이면 task_text로 반환
- query_backlog: 백로그 목록 조회 ("백로그", "백로그 보여줘", "백로그 조회" 등 — 추가할 내용 없이 백로그를 언급하면 무조건 이것)
- query_today: 특정 날짜의 할 일+일정 통합 조회 ("오늘 뭐해?", "내일 할 일", "모레 일정", "3/25 할 일" 등 — "캘린더" 키워드 없이 날짜+할 일/일정을 묻는 경우. target_date에 해당 날짜 입력, 오늘이면 null)
- query_week: 이번 주 일정 조회
- query_upcoming: 다가오는 일정/마감 조회
- log_day: 오늘 한 일/진행중인 일을 여러 개 한꺼번에 보고할 때 (log_tasks 배열로 반환, status는 complete/in_progress/pending)
- summarize_today: 오늘 한 일 요약 요청
- query_calendar: 캘린더 일정만 조회 ("캘린더" 키워드를 명시한 경우만. 예: "캘린더 일정 보여줘", "캘린더에 뭐 있어")
- list_calendars: 사용 가능한 캘린더 목록 조회 ("캘린더 목록", "어떤 캘린더" 등)
- set_calendar_filter: 포함할 캘린더 설정 ("캘린더 설정:", "캘린더 필터" 등, calendar_names에 쉼표 구분 목록)
- query_calendar_filter: 현재 캘린더 설정 확인 ("캘린더 설정 확인", "어떤 캘린더 보고 있어" 등)
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
