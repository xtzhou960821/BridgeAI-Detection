"""Deterministic local tools for VaultMiner, Synthesizer, Linter, and Lead (v3)."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

TEAM_ROOT = Path(__file__).resolve().parent.parent
MEMORY_PATH = TEAM_ROOT / "memory" / "team_memory.md"
STAGING_DIR = TEAM_ROOT / "staging"
LOGS_PATH = TEAM_ROOT / "logs" / "run_log.jsonl"
DEFAULT_VAULT = TEAM_ROOT / "vault_sandbox"

REDIRECT_URL_RE = re.compile(
    r"https://vertexaisearch\.cloud\.google\.com/grounding-api-redirect/[^\s\)\]>\"']+"
)
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")


def get_vault_dir() -> Path:
    """Resolve Obsidian vault path from OBSIDIAN_VAULT_PATH or fallback to local sandbox.

    Cleans accidental shell escape backslashes (e.g. '\\ ' or '\\~') inside quoted paths,
    and raises a clear error if an explicitly configured path does not exist.
    """
    env_path = os.environ.get("OBSIDIAN_VAULT_PATH", "").strip()
    if env_path:
        cleaned = env_path.replace(r"\ ", " ").replace(r"\~", "~").strip()
        p = Path(cleaned).expanduser().resolve()
        if p.exists() and p.is_dir():
            return p
        raise FileNotFoundError(
            f"OBSIDIAN_VAULT_PATH 指向的目录不存在：{cleaned}\n"
            "提示：双引号内不需要用反斜杠转义空格或 ~，例如：\n"
            'export OBSIDIAN_VAULT_PATH="/Users/zhouxiantong/Library/Mobile Documents/iCloud~md~obsidian/Documents/BridgeAI-检测"'
        )
    return DEFAULT_VAULT


def read_team_memory() -> str:
    """Read team_memory.md before every run."""
    if not MEMORY_PATH.exists():
        return "team_memory.md not found."
    return MEMORY_PATH.read_text(encoding="utf-8")


def scan_obsidian_vault(keywords: str) -> dict[str, Any]:
    """Read-only scan of the Obsidian Wiki vault for deduplication, wikilinks, and index/log format."""
    vault = get_vault_dir()
    terms = [t.strip().lower() for t in re.split(r"[\s,，、;；/|]+", keywords) if len(t.strip()) >= 2]
    notes: list[dict[str, Any]] = []
    wikilinks: list[str] = []

    for md_file in sorted(vault.rglob("*.md")):
        if ".obsidian" in md_file.parts or ".trash" in md_file.parts:
            continue
        rel = str(md_file.relative_to(vault))
        stem = md_file.stem
        text = md_file.read_text(encoding="utf-8", errors="ignore")
        if stem not in ("index", "log"):
            wikilinks.append(f"[[{stem}]]")
        haystack = f"{stem}\n{text}".lower()
        matched_terms = [term for term in terms if term in haystack] if terms else ["*"]
        if matched_terms:
            notes.append(
                {
                    "path": rel,
                    "title": stem,
                    "matched_terms": matched_terms[:8],
                    "excerpt": text[:400].strip(),
                }
            )

    index_sample = (vault / "index.md").read_text(encoding="utf-8") if (vault / "index.md").exists() else ""
    log_sample = (vault / "log.md").read_text(encoding="utf-8") if (vault / "log.md").exists() else ""

    return {
        "vault_path": str(vault),
        "existing_related_notes": notes[:10],
        "available_wikilinks": wikilinks[:30],
        "index_format_sample": index_sample[:600],
        "log_format_sample": log_sample[:600],
    }


def read_local_pdf(pdf_path: str, max_pages: int = 10) -> dict[str, Any]:
    """Read-only page-numbered text extractor for local engineering standards or paper PDFs."""
    p = Path(pdf_path).expanduser().resolve()
    if not p.exists() or p.suffix.lower() != ".pdf":
        return {"status": "ERROR", "reason": f"PDF not found or invalid path: {pdf_path}"}
    try:
        import pypdf  # type: ignore

        reader = pypdf.PdfReader(str(p))
        pages = []
        for idx, page in enumerate(reader.pages[:max_pages], 1):
            pages.append({"page": idx, "text": (page.extract_text() or "")[:1200]})
        return {"status": "OK", "path": str(p), "total_pages": len(reader.pages), "pages": pages}
    except ImportError:
        return {
            "status": "MISSING_DEPENDENCY",
            "path": str(p),
            "reason": "Optional package pypdf not installed; install pypdf to extract PDF pages.",
        }


def save_staging_files(draft_markdown: str, index_log_patch: str, filename_slug: str) -> dict[str, str]:
    """Save synthesized draft and index/log patch into staging/ (never directly to live vault)."""
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    draft_path = STAGING_DIR / "draft_wiki.md"
    patch_path = STAGING_DIR / "index_log_patch.md"
    meta_path = STAGING_DIR / "target_meta.json"

    slug = filename_slug[:-3] if filename_slug.endswith(".md") else filename_slug
    draft_path.write_text(draft_markdown, encoding="utf-8")
    patch_path.write_text(index_log_patch, encoding="utf-8")
    meta_path.write_text(
        json.dumps({"target_filename": f"{slug}.md"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "draft_path": str(draft_path),
        "patch_path": str(patch_path),
        "target_filename": f"{slug}.md",
    }


def resolve_redirect_urls_in_text(text: str) -> tuple[str, int]:
    """Resolve vertexaisearch grounding redirect URLs to clean canonical URLs."""
    urls = list(dict.fromkeys(REDIRECT_URL_RE.findall(text)))
    if not urls:
        return text, 0

    resolved_count = 0
    updated = text
    cert_path = "/etc/ssl/cert.pem" if Path("/etc/ssl/cert.pem").exists() else True
    with httpx.Client(follow_redirects=True, timeout=6.0, verify=cert_path) as client:
        for url in urls:
            try:
                resp = client.head(url)
                final_url = str(resp.url)
                if "vertexaisearch.cloud.google.com" in final_url:
                    resp = client.get(url)
                    final_url = str(resp.url)
                if final_url and "vertexaisearch.cloud.google.com" not in final_url:
                    updated = updated.replace(url, final_url)
                    resolved_count += 1
            except Exception:
                continue
    return updated, resolved_count


def run_deterministic_lint() -> dict[str, Any]:
    """Zero-token deterministic linter run between Synthesizer and Checker."""
    draft_path = STAGING_DIR / "draft_wiki.md"
    patch_path = STAGING_DIR / "index_log_patch.md"
    errors: list[str] = []
    warnings: list[str] = []

    if not draft_path.exists():
        return {"ok": False, "errors": ["staging/draft_wiki.md 不存在"], "warnings": []}

    draft_text = draft_path.read_text(encoding="utf-8")
    patch_text = patch_path.read_text(encoding="utf-8") if patch_path.exists() else ""

    cleaned_draft, resolved_urls = resolve_redirect_urls_in_text(draft_text)
    if resolved_urls > 0:
        draft_path.write_text(cleaned_draft, encoding="utf-8")
        draft_text = cleaned_draft

    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", draft_text, re.DOTALL)
    if not fm_match:
        errors.append("缺少顶部 YAML frontmatter 区块（--- ... ---）。")
    else:
        fm_block = fm_match.group(1)
        for field in ("title:", "tags:", "created:", "updated:", "status:"):
            if field not in fm_block:
                errors.append(f"YAML frontmatter 缺少必填字段：{field}")

    vault = get_vault_dir()
    existing_stems = {f.stem for f in vault.rglob("*.md") if ".obsidian" not in f.parts and ".trash" not in f.parts}
    meta_path = STAGING_DIR / "target_meta.json"
    if meta_path.exists():
        target_stem = Path(json.loads(meta_path.read_text(encoding="utf-8")).get("target_filename", "")).stem
        if target_stem:
            existing_stems.add(target_stem)

    referenced_links = sorted(set(WIKILINK_RE.findall(draft_text)))
    broken_links = [lnk for lnk in referenced_links if lnk not in existing_stems]
    if broken_links:
        errors.append(f"正文存在仓库中尚无实体文件的空双链：{broken_links}")

    if not patch_text.strip():
        errors.append("staging/index_log_patch.md 为空，缺少 index.md 与 log.md 增量补丁。")
    else:
        if "index.md" not in patch_text.lower():
            warnings.append("index_log_patch.md 未显式标注 index.md 补丁区块。")
        if "log.md" not in patch_text.lower():
            warnings.append("index_log_patch.md 未显式标注 log.md 补丁区块。")

    leftover_redirects = len(REDIRECT_URL_RE.findall(draft_text))
    if leftover_redirects:
        warnings.append(f"仍有 {leftover_redirects} 条 grounding 重定向链接未能自动解析。")

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "resolved_redirect_urls": resolved_urls,
        "checked_wikilinks": referenced_links,
        "draft_markdown": draft_text,
        "index_log_patch": patch_text,
    }


def _append_unique_bullet(target_file: Path, bullet_line: str, section_hint: str | None = None) -> bool:
    """Append a markdown bullet line to target_file if not already present."""
    if not bullet_line.strip():
        return False
    existing = target_file.read_text(encoding="utf-8") if target_file.exists() else ""
    if bullet_line.strip() in existing:
        return False
    if section_hint and section_hint in existing:
        parts = existing.split(section_hint, 1)
        after_lines = parts[1].splitlines()
        insert_idx = len(after_lines)
        for i, ln in enumerate(after_lines[1:], 1):
            if ln.startswith("## "):
                insert_idx = i
                break
        after_lines.insert(insert_idx, bullet_line.strip())
        updated = parts[0] + section_hint + "\n".join(after_lines) + "\n"
    else:
        sep = "\n" if existing and not existing.endswith("\n") else ""
        updated = f"{existing}{sep}{bullet_line.strip()}\n"
    target_file.write_text(updated, encoding="utf-8")
    return True


def _extract_patch_bullets(patch_text: str) -> tuple[list[str], list[str]]:
    """Parse staging/index_log_patch.md into (index_bullets, log_bullets)."""
    index_bullets: list[str] = []
    log_bullets: list[str] = []
    current = "none"
    for raw in patch_text.splitlines():
        line = raw.strip()
        lower = line.lower()
        if line.startswith("#") or lower.startswith("index.md") or lower.startswith("log.md"):
            if "index.md" in lower:
                current = "index"
                continue
            if "log.md" in lower:
                current = "log"
                continue
        if line.startswith("- "):
            if current == "index":
                index_bullets.append(line)
            elif current == "log":
                log_bullets.append(line)
    return index_bullets, log_bullets


def apply_approved_vault_write(approved: bool) -> dict[str, Any]:
    """Write staged draft AND merge index.md / log.md patches ONLY when explicitly approved."""
    if not approved:
        return {"status": "SKIPPED", "reason": "User did not approve vault write."}

    vault = get_vault_dir()
    draft_path = STAGING_DIR / "draft_wiki.md"
    patch_path = STAGING_DIR / "index_log_patch.md"
    meta_path = STAGING_DIR / "target_meta.json"
    if not draft_path.exists():
        return {"status": "ERROR", "reason": "staging/draft_wiki.md not found."}

    target_name = "new_wiki_entry.md"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        target_name = meta.get("target_filename", target_name)

    dest = vault / target_name
    dest.write_text(draft_path.read_text(encoding="utf-8"), encoding="utf-8")

    index_added = 0
    log_added = 0
    if patch_path.exists():
        idx_bullets, log_bullets = _extract_patch_bullets(patch_path.read_text(encoding="utf-8"))
        for b in idx_bullets:
            if _append_unique_bullet(vault / "index.md", b, section_hint="## 桥梁病害检测与无人机巡检"):
                index_added += 1
        for b in log_bullets:
            if _append_unique_bullet(vault / "log.md", b):
                log_added += 1

    return {
        "status": "WRITTEN",
        "destination": str(dest),
        "index_entries_added": index_added,
        "log_entries_added": log_added,
    }


def append_run_log(record: dict[str, Any]) -> str:
    """Append a structured JSON line to logs/run_log.jsonl for the weekly improvement loop."""
    LOGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **record,
    }
    with LOGS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return str(LOGS_PATH)
