#!/usr/bin/env python3
"""Weekly Improvement Loop analyzer: reads logs/run_log.jsonl and proposes 1 prompt tweak."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

TEAM_ROOT = Path(__file__).resolve().parent
LOGS_PATH = TEAM_ROOT / "logs" / "run_log.jsonl"


def main() -> None:
    if not LOGS_PATH.exists():
        print("尚无运行日志（logs/run_log.jsonl）。请先至少跑通 1 个真实任务。")
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    runs = []
    for line in LOGS_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        ts = datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00"))
        if ts >= cutoff:
            runs.append(item)

    if not runs:
        print("过去 7 天内没有新的运行记录。")
        return

    total = len(runs)
    first_pass = sum(1 for r in runs if r.get("first_pass_qa"))
    avg_score = sum(r.get("final_score", 0) for r in runs) / total
    avg_rounds = sum(r.get("rounds_used", 0) for r in runs) / total

    blame = Counter()
    issues = []
    for r in runs:
        for qa in r.get("qa_history", []):
            if qa.get("status") == "FAIL":
                target = qa.get("fix_target", "SYNTHESIZER")
                blame[target] += 1
                issues.extend(qa.get("feedback", []))

    weakest = blame.most_common(1)[0][0] if blame else "NONE (全员首轮达标)"
    print("=== 每周改进循环复盘（只读建议，未经同意不改提示词）===")
    print(f"过去 7 天运行次数：{total}")
    print(f"核心指标 · 首轮质检通过率 (First-Pass QA Rate)：{first_pass}/{total} ({first_pass / total * 100:.1f}%)")
    print(f"平均最终质检分：{avg_score:.1f} | 平均返工轮次：{avg_rounds:.2f}")
    print(f"本周最弱智能体：{weakest}")
    if issues:
        print("高频扣分证据：")
        for idx, msg in enumerate(issues[:3], 1):
            print(f"  {idx}. {msg}")
        print("\n建议操作：请审批后由 Lead 向该智能体的 SKILL.md 与 agent.py 应用 1 条针对性提示词修改。")


if __name__ == "__main__":
    main()
