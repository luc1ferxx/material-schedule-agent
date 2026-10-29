"""ReAct 循环：模型选择工具 → 执行 → 把结果交回模型 → 模型决定下一步或结束。

最终报告由工具账本（RunContext）生成，而不是采信模型的自然语言：
保存是否成功、待确认项、是否发布都以工具结果为准，模型的总结只作参考并做一致性检查。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .llm import LLMError
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .tools import AWAITING, TOOL_SPECS, MaterialFacts, RunContext, ToolExecutor

# 模型答复里“声称已发布 / 已保存”的说法（匹配前先去掉 Markdown 标记）
PUBLISH_CLAIM = re.compile(r"已(?:经)?(?:成功|正式|顺利)?(?:发布|上线)|(?:成功|正式)(?:发布|上线)"
                           r"|(?:发布|上线)(?:结果|状态)?[\s:：为]*(?:成功|完成)")
SAVE_CLAIM = re.compile(r"已(?:经)?(?:成功)?(?:保存|写入|存入)|成功(?:保存|写入)"
                        r"|(?:保存|写入)(?:结果|状态)?[\s:：为]*(?:成功|完成)|草稿已(?:创建|更新)")
_CLAUSE_BREAK = re.compile(r"[，。；！？,.;!?\n]")
_NEGATORS = ("未", "不", "没", "勿", "别", "禁止", "避免", "无法", "并非")  # 只看命中前 8 个字以内
_NON_ASSERTIVE = ("是否", "如果", "若", "一旦", "才能", "才会", "即可", "后才")  # 同一分句里出现则视为疑问/条件
_NEGATIVE_VALUE = re.compile(r"\s*[:：]\s*(?:否|无|0|false|未)", re.I)


def affirms(pattern: re.Pattern, text: str) -> bool:
    """文本中存在“陈述性的、未被否定的”命中才算声称：“请勿视为已上线”“是否已发布：否”“确认后才会发布成功”都不算。"""
    text = re.sub(r"[*`_#>|]", " ", text or "")
    for match in pattern.finditer(text):
        clause_start = max((b.end() for b in _CLAUSE_BREAK.finditer(text, 0, match.start())), default=0)
        clause_prefix = text[clause_start:match.start()]
        window = text[max(clause_start, match.start() - 8):match.start()]
        if any(n in window for n in _NEGATORS) or any(k in clause_prefix for k in _NON_ASSERTIVE):
            continue
        if _NEGATIVE_VALUE.match(text, match.end()):
            continue
        return True
    return False


@dataclass
class Limits:
    max_steps: int = 40        # 模型轮数上限
    max_tool_calls: int = 80   # 工具调用次数上限


def run_agent(ctx: RunContext, llm, limits: Limits | None = None) -> dict:
    limits = limits or Limits()
    executor = ToolExecutor(ctx)
    llm.start(SYSTEM_PROMPT, build_user_prompt(ctx.request), TOOL_SPECS)
    trace: list[dict] = []
    steps = calls = 0
    final_text, loop_status, stop_reason = "", None, None

    while loop_status is None:
        if steps >= limits.max_steps:
            loop_status, stop_reason = "incomplete", f"达到模型轮数上限 {limits.max_steps}"
            break
        steps += 1
        try:
            turn = llm.next()
        except LLMError as exc:
            loop_status, stop_reason = "error", str(exc)
            break
        if not turn.tool_calls:
            final_text, loop_status = turn.text, "finished"
            break
        if turn.text:
            trace.append({"step": steps, "type": "model_note", "text": turn.text})
        results = []
        for idx, call in enumerate(turn.tool_calls):
            if calls >= limits.max_tool_calls:
                refused = turn.tool_calls[idx:]
                for r in refused:  # 超限的调用不执行，但要留痕
                    r_args = r.args if isinstance(r.args, dict) else {}
                    trace.append({"step": steps, "type": "refused_call", "tool": r.name,
                                  "args": {k: v for k, v in r_args.items() if k != "reason"},
                                  "basis": r_args.get("reason") or "（模型未填写）"})
                loop_status = "incomplete"
                stop_reason = (f"达到工具调用次数上限 {limits.max_tool_calls}，本轮另有 {len(refused)} 个调用未执行："
                               + "、".join(r.name for r in refused))
                break
            calls += 1
            outcome = executor.execute(call.name, call.args, call.arg_error)
            args = call.args if isinstance(call.args, dict) else {}
            trace.append({
                "step": steps, "call": calls, "type": "tool_call", "tool": call.name,
                "args": {k: v for k, v in args.items() if k != "reason"},
                "basis": args.get("reason") or "（模型未填写）", "ok": outcome.ok, "result_summary": outcome.summary,
            })
            results.append((call.id, outcome.content(), not outcome.ok))
        if loop_status is None:
            llm.add_tool_results(results)

    _link_next_actions(trace, loop_status, stop_reason)
    return build_report(ctx, llm, trace, loop_status, stop_reason, final_text,
                        {"steps": steps, "tool_calls": calls,
                         "max_steps": limits.max_steps, "max_tool_calls": limits.max_tool_calls})


def _link_next_actions(trace: list, loop_status: str, stop_reason: str | None) -> None:
    """后续动作 = 模型看到本轮结果后在下一轮选择的动作；同一轮的并行调用共享同一个后续动作。"""
    calls = [t for t in trace if t["type"] == "tool_call"]
    steps = sorted({t["step"] for t in calls})
    end = {"finished": "结束，输出总结"}.get(loop_status, f"停止：{stop_reason}")
    for i, step in enumerate(steps):
        if i + 1 < len(steps):
            label = "、".join(t["tool"] + (f"({t['args']['material_id']})" if t["args"].get("material_id") else "")
                             for t in calls if t["step"] == steps[i + 1])
        else:
            label = end
        for t in calls:
            if t["step"] == step:
                t["next_action"] = label


def build_report(ctx: RunContext, llm, trace: list, loop_status: str, stop_reason: str | None,
                 final_text: str, usage: dict) -> dict:
    attempts = ctx.save_attempts
    last = attempts[-1] if attempts else None
    persisted = next((a for a in reversed(attempts) if a["validated"] and a.get("result", {}).get("ok")), None)
    # 草稿保存之后若又阻断了素材、改了确认事项或已有排期被改，草稿已过期：用最终账本重新复核一遍
    stale = ToolExecutor(ctx).review_entries(persisted["raw"]) if persisted else []

    if loop_status in ("error", "incomplete"):
        status = loop_status
    elif last is None:
        status, stop_reason = "incomplete", "模型结束时没有调用 save_draft，草稿未保存"
    elif persisted is None:
        if last["validated"]:
            status, stop_reason = "save_failed", last["result"]["message"]
        else:
            status, stop_reason = "incomplete", "草稿复核未通过，模型未修正就结束了"
    elif stale:
        status, stop_reason = "incomplete", "草稿保存后审核事实又有变化，已保存的草稿已过期：" + "；".join(stale)
    elif last is not persisted:
        status = "incomplete"
        stop_reason = f"草稿 {persisted['result']['draft_id']} v{persisted['result']['version']} 已保存，但之后的修订未保存：" \
                      + (last["result"].get("message") or "")
    else:
        status = "completed"

    if persisted:
        r = persisted["result"]
        draft = {"saved": True, "result": r["result"], "draft_id": r["draft_id"], "version": r["version"],
                 "message": r["message"]}
        if r.get("changes"):
            draft["changes"] = r["changes"]
        if last is not persisted:
            draft["latest_attempt"] = {k: last["result"].get(k) for k in ("error_code", "message", "problems") if k in last["result"]}
        if stale:
            draft["stale"] = stale
    elif last is not None and last["validated"]:
        r = last["result"]
        draft = {"saved": False, "result": "save_failed", "error_code": r.get("error_code"),
                 "retryable": r.get("retryable"), "message": r.get("message")}
    else:
        draft = {"saved": False, "result": "not_saved", "message": "没有通过复核并写入的草稿"}
    draft["save_attempts"] = len(attempts)

    # 每个素材的结论：已保存的以草稿为准；没保存成功的给出最后一次通过复核的方案（标注 not_saved），再没有就列出已查到的事实
    plan = persisted or next((a for a in reversed(attempts) if a["validated"]), None)
    if plan:
        state = f"已写入草稿 {draft['draft_id']}" if persisted else "草稿未保存"
        materials = [dict(e, draft_status=state, tool_facts=_facts_view(ctx.facts.get(e["material_id"])))
                     for e in plan["entries"]]
        if not persisted:
            for m in materials:
                m["confirm_state"] = "not_saved"
    else:
        materials = [_unfinished_entry(ctx, it) for it in ctx.request.items]
    decisions = {m["material_id"]: m["decision"] for m in materials}

    flags = []
    if affirms(PUBLISH_CLAIM, final_text):
        flags.append("模型答复出现“已发布/已上线”类表述，与事实不符（本系统没有发布能力），以结构化结果为准")
    if not persisted and affirms(SAVE_CLAIM, final_text):
        flags.append("模型答复声称草稿已保存，但 save_draft 实际没有成功写入，以工具结果为准")

    return {
        "status": status,
        "status_reason": stop_reason,
        "mode": getattr(llm, "label", type(llm).__name__),
        "mode_notice": getattr(llm, "notice", None),
        "request_id": ctx.request.request_id,
        "request_key": ctx.request.request_key,
        "scope": ctx.request.scope,
        "as_of": ctx.request.as_of,
        "input_notes": ctx.request.notes,
        "published": False,
        "publish_notice": "本 Agent 只生成排期草稿，没有发布能力；所有条目需用户确认后才生效",
        "draft": draft,
        "materials": materials,
        # 只列仍在等用户回复的确认；已阻断/信息缺失/重复的素材不再请用户确认排期
        "pending_confirmations": [
            {"material_id": mid, **c} for mid, f in ctx.facts.items() for c in f.confirmations
            if c["status"] == AWAITING and decisions.get(mid) in ("pending_confirmation", None)
        ],
        "guard_flags": flags,
        "model_summary": final_text,
        "usage": usage,
        "trace": trace,
    }


def _facts_view(fact: MaterialFacts | None) -> dict:
    """工具事实摘要；对应工具没调用过的项为 null（区别于“查过且没问题”）。"""
    fact = fact or MaterialFacts()
    return {
        "found": fact.found,
        "missing_fields": fact.missing_fields,
        "already_scheduled": [e["schedule_id"] for e in fact.existing_schedule],
        "rule_hits": None if fact.rule_hits is None else [f"{h['rule_id']}({h['level']})" for h in fact.rule_hits],
        "copyright_declared": ((fact.material or {}).get("copyright") or {}).get("status") if fact.found else None,
        "copyright_verified": (fact.copyright or {}).get("status"),
        "slot_available": (fact.slot_query or {}).get("requested_available"),
        "slot_conflict": (fact.slot_query or {}).get("conflict"),
        "blocked": fact.block is not None,
    }


def _unfinished_entry(ctx: RunContext, item) -> dict:
    fact = ctx.facts.get(item.material_id)
    return {
        "material_id": item.material_id, "decision": None, "review_status": "未完成（没有通过复核的草稿条目）",
        "channel": item.channel, "requested_slot": item.publish_time, "time_rule": item.time_rule,
        "suggested_slot": None, "risk_reasons": [h["message"] for h in (fact.rule_hits or [])] if fact else [],
        "pending_items": [], "confirmations": fact.confirmations if fact else [],
        "confirm_state": "unknown", "draft_status": "草稿未保存", "tool_facts": _facts_view(fact),
    }
