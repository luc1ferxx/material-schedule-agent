"""批量运行验收场景，生成 examples/ 下的实际输出、可读运行记录和索引。

    python -m src.run_examples                      # 离线 Mock → examples/outputs、examples/traces
    python -m src.run_examples --provider openai    # 真实模型 → examples/real-<模型名>/
    python -m src.run_examples --provider anthropic --only slot_conflict,rule_risk
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .agent import Limits
from .common import ROOT, load_dotenv
from .llm import make_llm
from .main import run_once
from .render import render_trace_md

SCENARIOS = [
    {"name": "pending_scope", "input": "pending_scope.json",
     "covers": "找出待处理素材：不列素材，Agent 先 list_pending_materials，再对 8 个待审素材逐个审核并形成一份排期草稿（综合场景）"},
    {"name": "normal", "input": "normal.json",
     "covers": "正常排期；版权待核验→补查 valid→正常排期（M07）"},
    {"name": "slot_conflict", "input": "slot_conflict.json",
     "covers": "时段冲突（参考实例）：M01 期望 18:00 被占、19:00 可用→建议 19:00 并标记待确认，不称已发布"},
    {"name": "fixed_conflict", "input": "fixed_conflict.json",
     "covers": "硬性要求边界：M08 硬性 20:00 被占→不擅自改期，只提方案请用户决定（或阻断）"},
    {"name": "competing_conflict", "input": "competing_conflict.json",
     "covers": "多素材争抢替代时段：M01 与 M08 的建议/暂留时段互不冲突，M08 硬性时间不改"},
    {"name": "missing_info", "input": "missing_info.json",
     "covers": "素材信息缺失：必填字段缺失（M03）、素材 ID 不存在（M99）、请求缺发布时间（M02）"},
    {"name": "rule_risk", "input": "rule_risk.json",
     "covers": "规则风险：warn 极限词→请求确认（M04）；verify→补查 expired→阻断（M05）；block 未标广告→阻断（M09）"},
    {"name": "duplicate_submit", "input": "duplicate_submit.json", "runs": [{}, {}],
     "covers": "重复提交：同一请求提交两次只保留一份草稿；请求内重复条目合并；M06 已在排期中"},
    {"name": "schedule_changed", "input": "slot_conflict.json",
     "runs": [{}, {"schedule": "data/schedule_alt.json"}],
     "covers": "更换占用时段后重复提交：19:00 也被占→M01 改建议 17:00，同一草稿更新为 v2（不新建）"},
    {"name": "save_fail_always", "input": "save_fail_always.json",
     "covers": "保存失败（不可重试）：明确返回 save_failed，不虚报成功"},
    {"name": "save_fail_once", "input": "save_fail_once.json",
     "covers": "保存失败（可重试）：根据 retryable=true 重试一次后保存成功"},
    {"name": "tool_limit", "input": "normal.json", "limits": {"max_tool_calls": 3},
     "covers": "工具调用达到上限：返回 incomplete 及原因，超限调用留痕"},
]


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="mock", choices=["mock", "anthropic", "openai"])
    parser.add_argument("--out", help="输出目录（默认 mock→examples，其他→examples/real-<模型名>）")
    parser.add_argument("--only", help="只运行指定场景，逗号分隔（索引会合并更新，不会丢掉其他场景）")
    args = parser.parse_args(argv)
    load_dotenv(ROOT / ".env")

    llm = make_llm(args.provider)
    model, label = getattr(llm, "model", None), getattr(llm, "label", args.provider)
    out = Path(args.out) if args.out else ROOT / "examples" / ("" if args.provider == "mock" else f"real-{model}")
    only = set(args.only.split(",")) if args.only else None
    index_file = out / "index.json"
    index = json.loads(index_file.read_text(encoding="utf-8")) if index_file.exists() else {}
    for sc in SCENARIOS:
        if only and sc["name"] not in only:
            continue
        drafts = out / "drafts" / f"{sc['name']}.drafts.json"
        if drafts.exists():
            drafts.unlink()  # 每个场景从空草稿库开始，结果可复现
        runs = sc.get("runs", [{}])
        input_path = f"examples/inputs/{sc['input']}"
        for i, run in enumerate(runs, 1):
            suffix = f".run{i}" if len(runs) > 1 else ""
            limits = Limits(**sc.get("limits", {}))
            schedule = str(ROOT / run["schedule"]) if run.get("schedule") else None
            report = run_once(str(ROOT / input_path), args.provider, str(drafts), schedule, limits)
            name = sc["name"] + suffix
            (out / "outputs").mkdir(parents=True, exist_ok=True)
            (out / "traces").mkdir(parents=True, exist_ok=True)
            (out / "outputs" / f"{name}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            title = name + (f"（已有排期：{run['schedule']}）" if run.get("schedule") else "")
            (out / "traces" / f"{name}.md").write_text(render_trace_md(report, title, input_path), encoding="utf-8")
            index[name] = {"scenario": sc["name"], "input": sc["input"], "status": report["status"],
                           "draft": report["draft"]["result"], "tool_calls": report["usage"]["tool_calls"]}
            print(f"{name:28s} status={report['status']:12s} draft={report['draft']['result']}")
    index_file.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_index(out, args.provider, label, index)
    return 0


def _write_index(out: Path, provider: str, label: str, index: dict) -> None:
    lines = ["# 运行样例索引", ""]
    if provider == "mock":
        lines += ["> 以下均为**离线 Mock** 的实际输出：决策由固定规则产生，只验证流程（工具、护栏、幂等、失败处理、上限），"
                  "不代表真实模型的决策效果。由 `python -m src.run_examples` 生成。", ""]
    else:
        lines += [f"> 以下为真实模型 `{label}` 的实际输出，由 `python -m src.run_examples --provider {provider}` 生成"
                  "（模型名取自 .env 的模型配置）。", ""]
    lines += ["| 场景 | 覆盖验收点 | 输入 | 实际输出 | 运行记录 | 状态 | 草稿 | 工具调用 |", "|---|---|---|---|---|---|---|---|"]
    covers = {sc["name"]: sc["covers"] for sc in SCENARIOS}
    order = [sc["name"] for sc in SCENARIOS]
    inputs_rel = Path(os.path.relpath(ROOT / "examples" / "inputs", out)).as_posix()
    for name, row in sorted(index.items(), key=lambda kv: (order.index(kv[1]["scenario"]) if kv[1]["scenario"] in order else 99, kv[0])):
        lines.append(f"| {name} | {covers.get(row['scenario'], '')} | [{row['input']}]({inputs_rel}/{row['input']}) "
                     f"| [{name}.json](outputs/{name}.json) | [{name}.md](traces/{name}.md) "
                     f"| {row['status']} | {row['draft']} | {row['tool_calls']} |")
    target = out / ("README.md" if provider == "mock" else "INDEX.md")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
