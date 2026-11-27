"""ADK 2.x Graph Workflow for the Bridge/AI Obsidian Wiki Research Team (v3).

v3 Upgrades:
- WebScout prioritizes primary official sources (mot.gov.cn, arXiv, IEEE, GitHub, Zenodo).
- Full interactive ADK 2.x HITL resume (adk_request_input -> finalize_and_log).
- Approved writes automatically publish the wiki .md AND merge index.md / log.md patches,
  then append structured metrics to logs/run_log.jsonl.
"""

from __future__ import annotations

import json
import re
from typing import Any

from google.adk import Agent, Event, Workflow
from google.adk.events import RequestInput
from google.adk.tools import google_search
from google.adk.workflow import DEFAULT_ROUTE, JoinNode, START
from google.genai import types

from .tools import (
    append_run_log,
    apply_approved_vault_write,
    read_local_pdf,
    read_team_memory,
    run_deterministic_lint,
    save_staging_files,
    scan_obsidian_vault,
)

MODEL_ID = "gemini-4-neon"
FAST_CONFIG = types.GenerateContentConfig(
    thinking_config=types.ThinkingConfig(thinking_level="LOW")
)
MEDIUM_CONFIG = types.GenerateContentConfig(
    thinking_config=types.ThinkingConfig(thinking_level="MEDIUM")
)
MAX_QA_ROUNDS = 2
_RUN_STATE: dict[str, Any] = {"round": 0, "topic": "", "qa_history": [], "lint_summary": {}}


def lead_prepare(node_input: str) -> str:
    """Lead entry node: loads team_memory.md, resets round counter, frames parallel subtasks."""
    memory = read_team_memory()
    _RUN_STATE["round"] = 0
    _RUN_STATE["topic"] = node_input.strip()
    _RUN_STATE["qa_history"] = []
    _RUN_STATE["lint_summary"] = {}
    return json.dumps(
        {
            "topic": node_input.strip(),
            "team_memory": memory,
            "instruction": "Execute external web research and local vault scan in parallel.",
        },
        ensure_ascii=False,
    )


web_scout_agent = Agent(
    name="web_scout",
    model=MODEL_ID,
    mode="single_turn",
    generate_content_config=FAST_CONFIG,
    tools=[google_search],
    instruction="""
JOB: 你是外部权威调研员（WebScout）。针对输入中的桥隧工程或 AI 主题，从多视角（学术论文、工程规范、开源仓库/官方文档）检索外部信息，产出可溯源的结构化证据包。
DONE WELL:
1. 覆盖至少 2 个互补视角（学术方法 vs 工程规范/开源实现）。
2. 每条核心数据、指标与规范条款绑定独立且精确的深层 URL（不要把两篇不同论文合并到同一链接），优先引用交通运输部官网（mot.gov.cn）、arXiv、IEEE/ScienceDirect、GitHub、Zenodo 等一级来源，避免引用第三方转载资讯站。
3. 明确标注来源年份，优先近 2–3 年前沿资料或现行有效规范。
4. 存在结论冲突时如实并列呈现。
NEVER: 绝不编造规范编号、数据或 URL；绝不直接写最终 Wiki 正文。
OUTPUT: 输出结构化 JSON 字符串（sources 列表，每项含 title, url, year, perspective, key_findings）。
""".strip(),
)


vault_miner_agent = Agent(
    name="vault_miner",
    model=MODEL_ID,
    mode="single_turn",
    generate_content_config=FAST_CONFIG,
    tools=[scan_obsidian_vault, read_local_pdf],
    instruction="""
JOB: 你是本地与知识库挖掘员（VaultMiner）。必须调用 scan_obsidian_vault 工具只读扫描 Obsidian Wiki 仓库（若任务提及本地 PDF 路径，调用 read_local_pdf 提取页码要点），完成已有词条查重、真实 [[wikilinks]] 提取以及 index.md/log.md 格式读取。
DONE WELL:
1. 准确列出仓库中已有相关词条与重复风险。
2. 仅返回真实存在于仓库中的 [[wikilinks]]。
3. 完整提取仓库现有的命名、标签及 index.md/log.md 更新格式。
NEVER: 绝不修改或删除仓库中任何文件；绝不虚构不存在的 [[wikilinks]]。
OUTPUT: 输出简洁 JSON 字符串（existing_notes, wikilinks, format_rules, suggested_filename）。
""".strip(),
)


join_research = JoinNode(name="join_research")


def merge_parallel_context(node_input: dict[str, Any]) -> str:
    """Merge WebScout and VaultMiner outputs after JoinNode barrier."""
    return json.dumps(
        {
            "topic": _RUN_STATE.get("topic", ""),
            "round": _RUN_STATE.get("round", 0),
            "evidence_web": node_input.get("web_scout", ""),
            "context_local": node_input.get("vault_miner", ""),
            "team_memory": read_team_memory(),
        },
        ensure_ascii=False,
    )


synthesizer_agent = Agent(
    name="synthesizer",
    model=MODEL_ID,
    mode="single_turn",
    generate_content_config=MEDIUM_CONFIG,
    tools=[save_staging_files],
    instruction="""
JOB: 你是结构化撰稿与入库编排员（Synthesizer）。融合 evidence_web 与 context_local（以及返工时的 qa_feedback），撰写适配 Obsidian 与 Typora 的高密度 Markdown 词条，并调用 save_staging_files 写入 staging/draft_wiki.md 与 staging/index_log_patch.md。
DONE WELL:
1. 顶部含规范 YAML frontmatter（title, tags, created, updated, status）。
2. 所有外部断言、数据与规范条款 100% 附带 1 对 1 独立可点击来源链接 [标题](URL)，不合并不同来源到同一 URL。
3. 仅嵌入 VaultMiner 返回的真实 [[wikilinks]]，严禁引用仓库中尚无实体文件的双链。
4. 同步生成含 `## index.md` 与 `## log.md` 两个区块的增量补丁草案，每区块下为 `- ` 开头的标准列表项。
5. 必须明确给出工程落地边界（边缘延迟/算力、像素定性与规范毫米级定量标定、现行规范合规与人工复核要求），无占位符。
NEVER: 绝不引入证据包之外的未核实数据；绝不直接写入正式 Obsidian 目录；调用 save_staging_files 成功后，不要在最终回复中重复粘贴整篇正文（下游确定性节点会直接从磁盘读取）。
OUTPUT: 仅返回简洁 JSON：{"draft_path": "...", "patch_path": "...", "target_filename": "...", "summary": "2句以内摘要"}。
""".strip(),
)


def deterministic_linter(node_input: str) -> str:
    """Zero-token deterministic linter: resolves redirect URLs, validates YAML/wikilinks/patch,
    and passes full draft + patch + lint report inline to Checker."""
    lint_result = run_deterministic_lint()
    _RUN_STATE["lint_summary"] = {
        "ok": lint_result["ok"],
        "errors": lint_result["errors"],
        "warnings": lint_result["warnings"],
        "resolved_redirect_urls": lint_result.get("resolved_redirect_urls", 0),
        "checked_wikilinks": lint_result.get("checked_wikilinks", []),
    }
    return json.dumps(
        {
            "synthesizer_meta": node_input,
            "deterministic_lint": _RUN_STATE["lint_summary"],
            "draft_wiki_markdown": lint_result.get("draft_markdown", ""),
            "index_log_patch_markdown": lint_result.get("index_log_patch", ""),
        },
        ensure_ascii=False,
    )


checker_agent = Agent(
    name="checker",
    model=MODEL_ID,
    mode="single_turn",
    generate_content_config=MEDIUM_CONFIG,
    instruction="""
JOB: 你是独立质检打分智能体（Checker）。结合 deterministic_lint 的代码校验结果，逐项核查 draft_wiki_markdown 与 index_log_patch_markdown 的完整性、溯源准确性与格式规范，给出 0–100 量化评分与 PASS/FAIL 判定。
DONE WELL:
1. 若 deterministic_lint.errors 非空，必须判定 FAIL 并把这些硬错误列入 redlines。
2. 逐项核查外部数据/规范链接是否独立且真实，无合并伪造链接、无空占位符。
3. 同时审计 index_log_patch_markdown 是否完整覆盖 index.md 与 log.md 增量条目且格式合规。
4. 严格执行通过阈值：score >= 85 且 redlines 为空方可判定 PASS。
5. 判定 FAIL 时，明确指定 fix_target（"WEB_SCOUT" 或 "SYNTHESIZER"）与可执行修改清单。
NEVER: 绝不亲自代写或悄悄修改稿件；绝不输出模糊评价。
OUTPUT: 仅输出合法 JSON：{"status": "PASS"|"FAIL", "score": 0-100, "redlines": [], "fix_target": "NONE"|"WEB_SCOUT"|"SYNTHESIZER", "feedback": []}。
""".strip(),
)


def lead_qa_router(node_input: str) -> Event:
    """Deterministic Lead router: enforces max-2-round quality loop and routes to HITL gate."""
    parsed: dict[str, Any] = {"status": "PASS", "score": 85, "redlines": [], "fix_target": "NONE", "feedback": []}
    try:
        match = re.search(r"\{.*\}", str(node_input), re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        parsed["feedback"] = ["Checker output was not valid JSON; escalating to human review."]
        parsed["status"] = "FAIL"

    current_round = int(_RUN_STATE.get("round", 0))
    _RUN_STATE.setdefault("qa_history", []).append({"round": current_round, **parsed})

    status = str(parsed.get("status", "FAIL")).upper()
    score = int(parsed.get("score", 0))
    redlines = parsed.get("redlines", [])
    fix_target = str(parsed.get("fix_target", "SYNTHESIZER")).upper()

    if status == "PASS" and score >= 85 and not redlines:
        return Event(
            route="HUMAN_APPROVAL",
            output=json.dumps(
                {
                    "decision": "PASS",
                    "round": current_round,
                    "lint_summary": _RUN_STATE.get("lint_summary", {}),
                    "qa_report": parsed,
                },
                ensure_ascii=False,
            ),
        )

    if current_round < MAX_QA_ROUNDS:
        _RUN_STATE["round"] = current_round + 1
        route = "FIX_EVIDENCE" if fix_target == "WEB_SCOUT" else "FIX_DRAFT"
        return Event(
            route=route,
            output=json.dumps(
                {
                    "topic": _RUN_STATE.get("topic", ""),
                    "round": _RUN_STATE["round"],
                    "qa_feedback": parsed.get("feedback", []),
                    "redlines": redlines,
                },
                ensure_ascii=False,
            ),
        )

    return Event(
        route="HUMAN_APPROVAL",
        output=json.dumps(
            {
                "decision": "ESCALATED_MAX_ROUNDS",
                "round": current_round,
                "lint_summary": _RUN_STATE.get("lint_summary", {}),
                "qa_report": parsed,
                "note": "已达 2 轮质检返工上限，请人工审阅未解决项后决定是否入库。",
            },
            ensure_ascii=False,
        ),
    )


def human_approval_gate(node_input: str):
    """Human-in-the-loop pause node: requires explicit approval before writing to live vault."""
    yield RequestInput(
        message=(
            "【人工审批节点】暂存稿已生成在 agent_team/staging/draft_wiki.md。\n"
            f"质检摘要：{node_input}\n"
            "请回复 APPROVE（批准写入 Obsidian）或 REJECT（暂不入库）。"
        ),
        payload={"approval_packet": node_input},
    )


def finalize_and_log(node_input: Any) -> Event:
    """Apply approved vault write (md + index.md + log.md) and append run metrics to logs/run_log.jsonl."""
    if isinstance(node_input, dict):
        raw_reply = node_input.get("response") or node_input.get("result") or str(node_input)
    else:
        raw_reply = str(node_input)
    reply = str(raw_reply).strip().upper()
    approved = reply in ("APPROVE", "YES", "Y", "通过", "批准")
    write_result = apply_approved_vault_write(approved=approved)

    qa_history = _RUN_STATE.get("qa_history", [])
    first_pass = bool(qa_history and qa_history[0].get("status") == "PASS" and qa_history[0].get("score", 0) >= 85)
    final_score = qa_history[-1].get("score", 0) if qa_history else 0

    log_path = append_run_log(
        {
            "version": "v3",
            "topic": _RUN_STATE.get("topic", ""),
            "rounds_used": _RUN_STATE.get("round", 0),
            "first_pass_qa": first_pass,
            "final_score": final_score,
            "lint_summary": _RUN_STATE.get("lint_summary", {}),
            "human_approved": approved,
            "write_result": write_result,
            "qa_history": qa_history,
        }
    )
    return Event(
        message=json.dumps(
            {
                "approved": approved,
                "write_result": write_result,
                "log_path": log_path,
                "rounds_used": _RUN_STATE.get("round", 0),
                "final_score": final_score,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


root_agent = Workflow(
    name="bridge_wiki_team",
    description="v3 5-agent ADK 2.x graph workflow with deterministic linter, URL resolver, 2-round QA loop, and full HITL resume.",
    edges=[
        # Entry -> Lead prepare -> Parallel Fan-Out -> Join -> Synthesize -> Deterministic Linter -> Check -> QA Router
        (
            START,
            lead_prepare,
            (web_scout_agent, vault_miner_agent),
            join_research,
            merge_parallel_context,
            synthesizer_agent,
            deterministic_linter,
            checker_agent,
            lead_qa_router,
        ),
        # Conditional Quality Loop (max 2 rounds) & Human Approval Gate
        (
            lead_qa_router,
            {
                "FIX_EVIDENCE": (web_scout_agent, vault_miner_agent),
                "FIX_DRAFT": synthesizer_agent,
                "HUMAN_APPROVAL": human_approval_gate,
                DEFAULT_ROUTE: human_approval_gate,
            },
        ),
        # Post-approval write & logging
        (human_approval_gate, finalize_and_log),
    ],
)
