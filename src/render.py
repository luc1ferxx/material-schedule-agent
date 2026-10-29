"""把运行结果渲染成便于评审阅读的 Markdown 运行记录。"""
from __future__ import annotations

import json


def _cell(value) -> str:
    if value is None or value == "" or value == []:
        return "—"
    if isinstance(value, list):
        value = "；".join(str(v) for v in value)
    elif isinstance(value, dict):
        value = json.dumps(value, ensure_ascii=False)
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def render_trace_md(report: dict, title: str, input_path: str | None = None) -> str:
    lines = [f"# 运行记录：{title}", ""]
    if report.get("mode_notice"):
        lines += [f"> {report['mode_notice']}", ""]
    inputs = report.get("inputs") or {}
    lines += [
        f"- 模式：`{report['mode']}`；请求范围：`{report.get('scope', 'items')}`；当前时间（as_of）：`{report.get('as_of', '—')}`",
        f"- 输入：`{inputs.get('request') or input_path or '—'}`；已有排期：`{inputs.get('schedule', '—')}`；"
        f"草稿库：`{inputs.get('drafts', '—')}`",
        f"- 结果状态：**{report['status']}**" + (f"（{report['status_reason']}）" if report.get("status_reason") else ""),
        f"- 草稿：{_cell(report['draft'])}",
        f"- 是否发布：{report['published']}（{report['publish_notice']}）",
        f"- 用量：{report['usage']}",
    ]
    if report.get("input_notes"):
        lines.append(f"- 输入说明：{_cell(report['input_notes'])}")
    lines += ["", "## 每个素材的结论", "",
              "| 素材 | 审核结论 | 渠道 | 要求时段（规则） | 建议时段 | 风险原因 | 待确认/补充 | 草稿 |",
              "|---|---|---|---|---|---|---|---|"]
    for m in report["materials"]:
        lines.append("| " + " | ".join([
            _cell(m["material_id"]), _cell(m["review_status"]), _cell(m["channel"]),
            _cell(f"{m['requested_slot']}（{m['time_rule']}）" if m.get("requested_slot") else None),
            _cell(m["suggested_slot"]), _cell(m["risk_reasons"]), _cell(m["pending_items"]),
            _cell(m.get("draft_status")),
        ]) + " |")
    lines += ["", "## 执行轨迹", "",
              "| 轮次 | # | 工具 | 参数 | 返回摘要 | 决策依据（模型填写的 reason） | 后续动作 |",
              "|---|---|---|---|---|---|---|"]
    for t in report["trace"]:
        if t["type"] == "model_note":
            lines.append(f"| {t['step']} | — | （模型说明） | — | {_cell(t['text'])} | — | — |")
            continue
        if t["type"] == "refused_call":
            lines.append(f"| {t['step']} | — | `{t['tool']}` | {_cell(t['args'])} | ⛔ 未执行：已达工具调用上限 "
                         f"| {_cell(t['basis'])} | — |")
            continue
        args = dict(t["args"])
        if t["tool"] == "save_draft" and isinstance(args.get("entries"), list):
            args["entries"] = [f"{e.get('material_id')}:{e.get('decision')}@{e.get('suggested_slot') or '—'}"
                               for e in args["entries"] if isinstance(e, dict)]
        lines.append("| " + " | ".join([
            str(t["step"]), str(t["call"]), f"`{t['tool']}`", _cell(args),
            ("" if t["ok"] else "❌ ") + _cell(t["result_summary"]), _cell(t["basis"]), _cell(t.get("next_action")),
        ]) + " |")
    if report.get("pending_confirmations"):
        lines += ["", "## 待用户确认事项（来自 request_confirmation 登记）", ""]
        for c in report["pending_confirmations"]:
            lines.append(f"- `{c['confirmation_id']}`（{c['material_id']}）{c['question']}"
                         f"（替代时段：{c['proposed_slot'] or '无'}；状态：{c['status']}）")
    lines += ["", "## 模型最终答复", "", "```text", report.get("model_summary") or "（无）", "```"]
    if report.get("guard_flags"):
        lines += ["", "## 一致性检查告警", ""] + [f"- {f}" for f in report["guard_flags"]]
    return "\n".join(lines) + "\n"
