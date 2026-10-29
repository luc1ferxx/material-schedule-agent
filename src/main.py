"""CLI 入口。

    python -m src.main --input examples/inputs/slot_conflict.json --mock
    python -m src.main --input examples/inputs/slot_conflict.json --provider openai

退出码：0=completed；1=incomplete / save_failed / error（结果仍以 JSON 输出）；2=输入或配置错误。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .agent import Limits, run_agent
from .common import ROOT, load_dotenv, load_json
from .llm import LLMError, make_llm
from .render import render_trace_md
from .request import normalize_request
from .stores import DataStore, DraftStore
from .tools import RunContext

DEFAULT_DRAFTS = ".runtime/drafts.json"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="素材审核与发布排期 Agent（只保存草稿，不发布）")
    p.add_argument("--input", required=True, help="请求 JSON 文件")
    p.add_argument("--provider", choices=["mock", "anthropic", "openai"],
                   help="模型来源；默认读取环境变量 LLM_PROVIDER，未设置时为 mock")
    p.add_argument("--mock", action="store_true", help="离线 Mock，等同 --provider mock")
    p.add_argument("--drafts", default=DEFAULT_DRAFTS, help=f"草稿库文件（默认 {DEFAULT_DRAFTS}）")
    p.add_argument("--reset-drafts", action="store_true", help="运行前清空草稿库")
    p.add_argument("--schedule", help="已有排期文件（默认 data/schedule.json）")
    p.add_argument("--max-steps", type=int, default=Limits.max_steps, help="模型轮数上限")
    p.add_argument("--max-tool-calls", type=int, default=Limits.max_tool_calls, help="工具调用次数上限")
    p.add_argument("--output", help="把完整结果（含 trace）写入该 JSON 文件")
    p.add_argument("--trace-md", help="把可读运行记录写入该 Markdown 文件")
    p.add_argument("--brief", action="store_true", help="终端输出不含 trace")
    return p


def run_once(input_path: str, provider: str, drafts: str, schedule: str | None = None,
             limits: Limits | None = None) -> dict:
    """供 CLI 与 run_examples 复用。输入/配置错误抛 ValueError / OSError / LLMError。"""
    request = normalize_request(load_json(Path(input_path)))
    store = DataStore(schedule_path=Path(schedule) if schedule else None)
    llm = make_llm(provider)
    ctx = RunContext(request, store, DraftStore(Path(drafts), request.save_fault))
    report = run_agent(ctx, llm, limits)
    # 记录本次运行实际用到的文件，便于复现（如评审改了已有排期后重提）
    report["inputs"] = {"request": _rel(input_path), "schedule": _rel(store.schedule_path), "drafts": _rel(drafts)}
    return report


def _rel(path) -> str:
    path = Path(path).resolve()
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")  # Windows 终端输出中文
    args = build_parser().parse_args(argv)
    load_dotenv(ROOT / ".env")
    provider = "mock" if args.mock else (args.provider or os.environ.get("LLM_PROVIDER") or "mock")
    if args.reset_drafts and Path(args.drafts).exists():
        Path(args.drafts).unlink()
    try:
        report = run_once(args.input, provider, args.drafts, args.schedule,
                          Limits(args.max_steps, args.max_tool_calls))
    except (OSError, ValueError, LLMError) as exc:
        print(json.dumps({"status": "invalid_input", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.trace_md:
        Path(args.trace_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.trace_md).write_text(render_trace_md(report, Path(args.input).stem, args.input), encoding="utf-8")
    shown = {k: v for k, v in report.items() if k != "trace"} if args.brief else report
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
