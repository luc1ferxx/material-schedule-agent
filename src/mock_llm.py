"""离线 Mock “模型”。

用固定规则模拟模型的工具选择，只为在没有 API Key 时跑通并验证流程（工具、护栏、幂等、失败处理、上限）。
它本质上是条件分支，不代表、也不证明真实模型的决策效果。真实决策请用 --provider anthropic / openai 运行。
"""
from __future__ import annotations

import json

from .llm import ModelTurn, ToolCall
from .tools import DECISION_LABELS


class MockLLM:
    label = "offline_mock"
    notice = "离线 Mock：决策由固定规则产生，只验证流程，不代表真实模型的决策效果"

    def start(self, system: str, user: str, tools: list) -> None:
        payload = json.loads(user.split("```json", 1)[1].split("```", 1)[0])
        self.scope = payload.get("scope", "items")
        self.items = payload["items"]
        self._policy = self._run()
        self._observation = None
        self._started = False
        self._calls = 0

    def next(self) -> ModelTurn:
        try:
            action = self._policy.send(self._observation) if self._started else next(self._policy)
        except StopIteration:
            return ModelTurn("（Mock 已结束）")
        self._started = True
        if action[0] == "final":
            return ModelTurn(action[1], [], "end_turn")
        self._calls += 1
        return ModelTurn("", [ToolCall(f"mock-{self._calls}", action[1], action[2])], "tool_use")

    def add_tool_results(self, results: list) -> None:
        self._observation = json.loads(results[-1][1])

    # ---- 固定策略 -----------------------------------------------------

    def _run(self):
        if self.scope == "pending":  # 请求没列素材：先找出待审核素材，按其登记的发布要求处理
            listed = yield ("call", "list_pending_materials", {"reason": "请求未列出素材，先找出所有待审核素材"})
            self.items = [dict(m.get("requested_publish") or {}, material_id=m["material_id"])
                          for m in listed.get("materials", [])]
        entries = []
        for item in self.items:
            entry = yield from self._handle(item)
            entries.append(entry)
        result = None
        for _ in range(2):  # 最多重试一次
            reason = ("全部素材已处理，提交排期草稿" if result is None
                      else f"上次保存失败（{result.get('error_code')}，retryable=true），重试一次")
            result = yield ("call", "save_draft", {"entries": entries, "reason": reason})
            if result.get("ok") or not result.get("retryable") or result.get("error_code") == "VALIDATION_FAILED":
                break
        yield ("final", self._summary(entries, result))

    def _handle(self, item: dict):
        mid = item["material_id"]
        entry = {"material_id": mid, "decision": "", "suggested_slot": "", "risk_reasons": [], "pending_items": []}
        mat = yield ("call", "get_material", {"material_id": mid, "reason": f"读取 {mid} 元数据，确认信息是否完整"})
        if not mat.get("found"):
            entry.update(decision="needs_info", pending_items=[f"素材库中不存在 {mid}，请核对素材 ID"])
            return entry
        missing, req_missing = mat.get("missing_fields") or [], mat.get("request_missing") or []
        if missing or req_missing:
            pending = [f"请补充素材字段：{'、'.join(missing)}"] if missing else []
            pending += [f"请补充或修正发布要求：{'、'.join(req_missing)}"] if req_missing else []
            entry.update(decision="needs_info", pending_items=pending)
            return entry
        item = mat.get("request_requirement") or item  # 用工具返回的规范化发布要求
        if mat.get("already_scheduled"):
            s = mat["already_scheduled"][0]
            entry.update(decision="duplicate",
                         risk_reasons=[f"已在排期 {s['schedule_id']}（{s['channel']} {s['slot']}），不重复排期"])
            return entry

        rules = yield ("call", "check_rules", {"material_id": mid, "reason": f"{mid} 信息齐全，按审核规则检查"})
        hits = rules.get("hits", [])
        levels = {h["level"] for h in hits}
        entry["risk_reasons"] = [f"{h['rule_id']}：{h['message']}（{h['evidence']}）" for h in hits if h["level"] != "verify"]
        if "block" in levels:
            summary = "；".join(h["message"] for h in hits if h["level"] == "block")
            yield ("call", "block_material", {"material_id": mid, "risk_summary": summary,
                                              "reason": f"{mid} 命中 block 级规则"})
            entry["decision"] = "blocked"
            return entry
        if "verify" in levels:
            cp = yield ("call", "verify_copyright", {"material_id": mid, "reason": f"{mid} 版权状态待核验，补查授权"})
            if cp.get("status") == "not_found":
                entry.update(decision="needs_info", pending_items=["请补充有效的版权授权信息"])
                return entry
            if cp.get("status") != "valid":
                yield ("call", "block_material", {"material_id": mid, "risk_summary": f"版权失效：{cp.get('message')}",
                                                  "reason": f"补查结果为 {cp.get('status')}，不能发布"})
                entry.update(decision="blocked", risk_reasons=entry["risk_reasons"] + [f"版权失效：{cp.get('message')}"])
                return entry

        slots = yield ("call", "query_slots", {
            "material_id": mid, "channel": item["channel"], "publish_time": item["publish_time"],
            "reason": f"{mid} 审核无阻断风险，查询要求时段 {item['publish_time']} 是否可用"})
        asked = False
        if "warn" in levels:
            warn = "；".join(h["message"] for h in hits if h["level"] == "warn")
            yield ("call", "request_confirmation", {
                "material_id": mid, "question": f"{mid} 命中 warn 级规则：{warn}。是否修改后按计划发布？",
                "proposed_slot": "", "reason": f"{mid} 命中 warn 级规则，需要用户决定"})
            entry["pending_items"].append(f"确认风险处理：{warn}")
            asked = True
        if not slots.get("ok", True):  # 查询本身失败：不猜时段，请用户确认发布时间
            question = f"{mid} 时段查询失败（{slots.get('message')}），请确认发布渠道和时间"
            yield ("call", "request_confirmation", {"material_id": mid, "question": question, "proposed_slot": "",
                                                    "reason": "时段查询失败，无法给出建议时段"})
            entry.update(decision="pending_confirmation", pending_items=entry["pending_items"] + [question])
            return entry
        if slots.get("requested_available"):
            entry["suggested_slot"] = item["publish_time"]
        else:
            alts, conflict = slots.get("alternatives") or [], slots.get("conflict")
            first = alts[0] if alts else ""
            if item.get("time_rule") == "fixed":
                question = (f"{mid} 的硬性发布时间 {item['publish_time']} 不可用（{conflict}）。未经你同意不会改期："
                            f"请决定协调占用方让出该时段，还是改到 {first or '其他日期'}？")
                pending = f"硬性时间 {item['publish_time']} 不可用，需你决定：协调占用方或改到 {first or '其他日期'}"
                reason = "硬性时间被占用，不能擅自改期，需用户决定"
            elif first:
                question = f"{mid} 要求时间 {item['publish_time']} 不可用（{conflict}），建议改到 {first}，是否同意？"
                pending = f"确认改期：{item['publish_time']} → {first}"
                reason = f"要求时段不可用，{first} 可用，改期需用户确认"
                entry["suggested_slot"] = first
            else:
                question = f"{mid} 要求时间 {item['publish_time']} 不可用（{conflict}），当天没有可用时段，请改选日期或放弃"
                pending = question
                reason = "要求时段不可用且当天无替代时段，需用户决定"
            yield ("call", "request_confirmation", {"material_id": mid, "question": question,
                                                    "proposed_slot": first, "reason": reason})
            entry["pending_items"].append(pending)
            asked = True
        entry["decision"] = "pending_confirmation" if asked else "schedule"
        return entry

    @staticmethod
    def _summary(entries: list, result: dict | None) -> str:
        lines = ["【离线 Mock】处理结果："]
        for e in entries:
            line = f"- {e['material_id']}：{DECISION_LABELS[e['decision']]}，建议时段 {e['suggested_slot'] or '无'}"
            if e["pending_items"]:
                line += "；待确认/补充：" + "；".join(e["pending_items"])
            lines.append(line)
        if result and result.get("ok"):
            lines.append(f"草稿保存结果：{result['result']}（{result['draft_id']} v{result['version']}）。仅为草稿，需你确认，未做任何发布。")
        else:
            code = (result or {}).get("error_code")
            lines.append(f"草稿保存失败：{code} {(result or {}).get('message', '')}。草稿未保存，未做任何发布。")
        return "\n".join(lines)
