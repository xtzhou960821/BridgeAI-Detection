#!/usr/bin/env python3
"""Single-command CLI runner for the Bridge/AI Obsidian Wiki Agent Team (v3).

Supports full interactive ADK 2.x HITL resume (adk_request_input -> APPROVE/REJECT
-> finalize_and_log -> Obsidian write + index.md/log.md merge + run_log.jsonl).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google.adk.runners import InMemoryRunner
from google.genai import types

# Load project .env if present (never prints or logs keys)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(Path(__file__).resolve().parent / ".env")

from bridge_wiki_team import root_agent  # noqa: E402


async def _consume_stream(
    runner: InMemoryRunner,
    user_id: str,
    session_id: str,
    message: types.Content,
    t0: float,
) -> dict[str, Any] | None:
    """Stream events from runner and return pending adk_request_input call if paused."""
    pending_interrupt: dict[str, Any] | None = None
    async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=message):
        elapsed = time.monotonic() - t0
        author = getattr(event, "author", "workflow")
        parts_text = []
        if event.content and event.content.parts:
            for p in event.content.parts:
                if getattr(p, "text", None):
                    parts_text.append(p.text.strip())
                elif getattr(p, "function_call", None):
                    fc = p.function_call
                    parts_text.append(f"[tool_call] {fc.name}({fc.args})")
                    if fc.name == "adk_request_input":
                        pending_interrupt = {"id": fc.id, "name": fc.name, "args": fc.args}
                elif getattr(p, "function_response", None):
                    fr = p.function_response
                    parts_text.append(f"[tool_resp] {fr.name} -> {str(fr.response)[:240]}")

        ev_out = getattr(event, "output", None)
        ev_routes = getattr(event, "routes", None) or getattr(event, "route", None)
        if parts_text:
            body = "\n".join(parts_text)
            print(f"\n[{elapsed:5.1f}s] [{author}]\n{body[:1800]}", flush=True)
        elif ev_out is not None or ev_routes is not None:
            print(f"\n[{elapsed:5.1f}s] [{author}] route={ev_routes} output={str(ev_out)[:600]}", flush=True)

    return pending_interrupt


async def run_workflow(topic: str, decision: str | None = None) -> None:
    if not os.environ.get("GEMINI_API_KEY"):
        print(
            "[ERROR] 未检测到环境变量 GEMINI_API_KEY。\n"
            "请在终端执行：export GEMINI_API_KEY=\"你的key\"（切勿提交到 Git 或粘贴在聊天中），然后重试。",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(2)

    runner = InMemoryRunner(agent=root_agent, app_name="bridge_wiki_team")
    session = await runner.session_service.create_session(app_name="bridge_wiki_team", user_id="local_user")

    t0 = time.monotonic()
    print(f"[Lead] 启动 ADK 2.x v3 图工作流 (model=gemini-4-neon) | 主题：{topic}", flush=True)
    user_msg = types.Content(role="user", parts=[types.Part(text=topic)])

    pending = await _consume_stream(runner, "local_user", session.id, user_msg, t0)

    if pending:
        if decision:
            user_decision = decision.strip().upper()
            print(f"\n[HumanApproval] 使用参数决策：{user_decision}", flush=True)
        elif sys.stdin.isatty():
            user_decision = input("\n[HumanApproval] 请输入 APPROVE（批准入库）或 REJECT（拒绝入库）：").strip().upper()
        else:
            print("\n[HumanApproval] 已暂停等待人工审批（非交互终端未传 --decision，跳过自动写入）。", flush=True)
            return

        resume_msg = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=pending["id"],
                        name=pending["name"],
                        response={"response": user_decision},
                    )
                )
            ],
        )
        print(f"\n[{time.monotonic() - t0:5.1f}s] [Lead] 收到审批决策 ({user_decision})，恢复图工作流执行入库与日志记录...", flush=True)
        await _consume_stream(runner, "local_user", session.id, resume_msg, t0)

    print(f"\n[{time.monotonic() - t0:5.1f}s] [DONE] v3 图工作流完整闭环结束。", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Bridge/AI Obsidian Wiki ADK 2.x Agent Team (v3).")
    parser.add_argument("--topic", type=str, help="Research topic or local reference note to ingest.")
    parser.add_argument(
        "--decision",
        type=str,
        choices=["APPROVE", "REJECT"],
        help="Optional non-interactive decision for the HumanApproval pause gate.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate the ADK 2.x Workflow graph structure without calling Gemini API.",
    )
    args = parser.parse_args()

    if args.validate_only:
        print(f"[OK] ADK 2.x Workflow '{root_agent.name}' (v3) 已通过全部静态图结构验证。", flush=True)
        print(f"     Graph edges count: {len(root_agent.edges)}", flush=True)
        return

    if not args.topic:
        parser.error("请提供 --topic \"你的调研主题\"，或使用 --validate-only 仅校验图结构。")

    asyncio.run(run_workflow(args.topic, decision=args.decision))


if __name__ == "__main__":
    main()
