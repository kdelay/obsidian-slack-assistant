#!/usr/bin/env python3
"""
Claude Code Stop 훅 — 세션 종료 시 오늘 작업을 Obsidian에 자동 기록.

설정 방법:
  ~/.claude/settings.json 의 hooks.Stop 에 아래 커맨드 등록:
  /path/to/.venv/bin/python3 /Users/lilly/Documents/slack/personal-assistant/scripts/cc_work_logger.py

프로젝트 매핑:
  PROJECT_MAP에 (작업 디렉토리 prefix → (카테고리, 기본 태스크명)) 추가.
"""

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

# personal-assistant 루트를 Python 경로에 추가
ASSISTANT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ASSISTANT_DIR))

from dotenv import load_dotenv
load_dotenv(ASSISTANT_DIR / ".env")

import anthropic

from config import ANTHROPIC_API_KEY, OBSIDIAN_VAULT
from services.obsidian_service import ObsidianService

# ── 프로젝트 매핑 ──────────────────────────────────────────────
# { "디렉토리 prefix": ("카테고리", "기본 태스크명") }
PROJECT_MAP = {
    "/Users/lilly/IdeaProjects/mobisign":               ("모비사인",  "백엔드 개발"),
    "/Users/lilly/Documents/slack/personal-assistant":  ("개인 업무", "슬랙 비서 봇"),
    "/Users/lilly/onjjan":                              ("처음이라",  "온짠 개발"),
    "/Users/lilly/Documents/Obsidian":                  ("개인 업무", "옵시디언 정리"),
}

# ───────────────────────────────────────────────────────────────


def detect_project(cwd: str):
    for path, info in PROJECT_MAP.items():
        if cwd.startswith(path):
            return info
    return None


def get_git_activity(cwd: str) -> dict:
    """오늘(자정 이후) 커밋 + 미커밋 변경 파일 수집."""
    result = {"commits": [], "changed_files": []}

    # 오늘 커밋만
    try:
        r = subprocess.run(
            ["git", "log", "--oneline", "--no-merges", "--since=midnight"],
            cwd=cwd, capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            result["commits"] = [
                line.split(" ", 1)[-1]
                for line in r.stdout.strip().splitlines()
            ]
    except Exception:
        pass

    # 미커밋 변경 파일
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            result["changed_files"] = r.stdout.strip().splitlines()[:10]
    except Exception:
        pass

    return result


def analyze_work(activity: dict, category: str) -> tuple[str | None, list[str]]:
    """Claude Haiku로 작업 분석 → (주요 태스크명, 서브태스크 목록)."""
    if not activity["commits"] and not activity["changed_files"]:
        return None, []

    lines = []
    if activity["commits"]:
        lines.append("오늘 커밋:")
        lines.extend(f"  {c}" for c in activity["commits"])
    if activity["changed_files"]:
        lines.append("변경 파일:")
        lines.extend(f"  {f}" for f in activity["changed_files"])

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": (
                    f"프로젝트: {category}\n"
                    f"{chr(10).join(lines)}\n\n"
                    "오늘 작업 내용 분석 결과를 JSON으로만 반환하세요:\n"
                    '{"main_task": "핵심 작업 한 줄 (20자 이내, 프로젝트명 제외)", '
                    '"sub_tasks": ["세부작업1", "세부작업2"]}\n'
                    "sub_tasks는 최대 3개, 없으면 빈 배열. JSON만 반환."
                ),
            }],
        )
        data = json.loads(resp.content[0].text.strip())
        return data.get("main_task"), data.get("sub_tasks", [])
    except Exception:
        return None, []


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    cwd = data.get("cwd", os.getcwd())
    project = detect_project(cwd)
    if not project:
        return

    category, default_task = project
    activity = get_git_activity(cwd)
    main_task, sub_tasks = analyze_work(activity, category)
    task_text = main_task or default_task

    obsidian = ObsidianService(OBSIDIAN_VAULT)
    today = date.today()

    # 오늘 이미 같은 내용이 있으면 스킵
    existing = {t.text.lower() for t in obsidian.get_tasks(today)}
    if task_text.lower() not in existing:
        obsidian.add_task(today, task_text, category=category, status="in_progress",
                          sub_tasks=sub_tasks if sub_tasks else None)


if __name__ == "__main__":
    main()
