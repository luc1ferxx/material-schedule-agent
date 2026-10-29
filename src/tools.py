"""Agent 可调用的业务工具，以及工具层护栏。

设计要点：
- 每次工具调用都把“事实”记进 ledger（RunContext.facts），save_draft 依据这些事实复核模型给出的草稿，
  防止模型漏查、改动硬性时间、未确认就改期、把有风险的素材排进去。
- 没有任何“发布”工具：Agent 只能保存草稿。
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import timedelta

from .common import canonical_hash, canonical_slot, fmt_slot, is_empty, parse_slot
from .request import RequestItem, ScheduleRequest, parse_item
from .stores import DataStore, DraftStore

DECISIONS = ("schedule", "pending_confirmation", "needs_info", "blocked", "duplicate")
DECISION_LABELS = {
    "schedule": "审核通过，按要求时段排期",
    "pending_confirmation": "待确认",
    "needs_info": "信息缺失，待补充",
    "blocked": "阻断",
    "duplicate": "重复提交，已在排期中",
}
CONFIRM_STATES = {
    "schedule": "ready_to_confirm",
    "pending_confirmation": "awaiting_user_decision",
    "needs_info": "not_schedulable",
    "blocked": "not_schedulable",
    "duplicate": "not_schedulable",
}
LEVEL_ORDER = {"none": 0, "verify": 1, "warn": 2, "block": 3}
AWAITING = "awaiting_user"

_REASON = {
    "type": "string",
    "description": "一句话说明本次调用的依据，引用上一步工具结果，例如“M01 规则检查无风险，查询 18:00 是否可用”",
}
_MID = {"type": "string", "description": "素材 ID，如 M01"}

TOOL_SPECS = [
    {
        "name": "list_pending_materials",
        "description": "列出素材库中所有待审核（pending_review）的素材及其登记的发布要求。请求 scope=pending（没有列出素材）时必须先调用，"
                       "返回的素材会加入本次待处理清单；请求已列出素材 ID 时不必调用。",
        "parameters": {"type": "object", "properties": {"reason": _REASON}, "required": ["reason"]},
    },
    {
        "name": "get_material",
        "description": "读取素材元数据。返回素材是否存在、缺失的必填字段、发布要求是否缺失或无效（渠道未配置、时间已过）、是否已在已有排期中（重复提交）。",
        "parameters": {
            "type": "object",
            "properties": {"material_id": _MID, "reason": _REASON},
            "required": ["material_id", "reason"],
        },
    },
    {
        "name": "check_rules",
        "description": "按审核规则检查素材。命中项 level：block=必须阻断；warn=需用户/法务确认；verify=需先调用 verify_copyright 补查再决定。",
        "parameters": {
            "type": "object",
            "properties": {"material_id": _MID, "reason": _REASON},
            "required": ["material_id", "reason"],
        },
    },
    {
        "name": "verify_copyright",
        "description": "补查：到版权登记库核验素材授权是否覆盖本次发布日期。返回 status=valid / expired / not_found。",
        "parameters": {
            "type": "object",
            "properties": {"material_id": _MID, "reason": _REASON},
            "required": ["material_id", "reason"],
        },
    },
    {
        "name": "query_slots",
        "description": "查询渠道在要求时间是否可用；不可用时返回按接近程度排序的替代时段，并说明更近的时段为什么不可用。"
                       "已排除已有排期、本次请求中其他素材仍要求的时段（硬性要求优先）、已提议给其他素材的时段；同等接近时优先晚于要求时间。",
        "parameters": {
            "type": "object",
            "properties": {
                "material_id": _MID,
                "channel": {"type": "string", "description": "渠道，如 app_home / douyin"},
                "publish_time": {"type": "string", "description": "要查询的时间，格式 YYYY-MM-DD HH:MM"},
                "reason": _REASON,
            },
            "required": ["material_id", "channel", "publish_time", "reason"],
        },
    },
    {
        "name": "request_confirmation",
        "description": "登记一条需要用户确认的事项（替代时段、warn 级风险、硬性时间无法满足等）。只登记，不代表用户同意。"
                       "填写 proposed_slot 时，该时段仅在本次请求内为这个素材暂留（同一素材再次提议会替换上一次的提议），"
                       "并未写入正式排期，也不约束其他请求。",
        "parameters": {
            "type": "object",
            "properties": {
                "material_id": _MID,
                "question": {"type": "string", "description": "要用户确认的问题，写清原因和可选方案；只陈述工具返回的事实，推断需注明是推断"},
                "proposed_slot": {"type": "string", "description": "仅当建议改到要求时间以外的时段时填写（YYYY-MM-DD HH:MM）；按要求时间排期、只确认风险时传空字符串"},
                "reason": _REASON,
            },
            "required": ["material_id", "question", "proposed_slot", "reason"],
        },
    },
    {
        "name": "block_material",
        "description": "阻断素材，本次不排期（该素材的待确认事项随之作废）。用于 block 级风险、版权失效，或硬性要求无法满足且不宜改期等情况。",
        "parameters": {
            "type": "object",
            "properties": {
                "material_id": _MID,
                "risk_summary": {"type": "string", "description": "阻断原因"},
                "reason": _REASON,
            },
            "required": ["material_id", "risk_summary", "reason"],
        },
    },
    {
        "name": "save_draft",
        "description": "保存排期草稿（只保存草稿，不会发布）。entries 必须覆盖本次待处理的每个素材且每个素材一条。保存前会复核：时段冲突、"
                       "硬性时间是否被改动、改期是否已发起确认、结论是否与工具事实一致；不通过会返回 problems。同一请求重复保存只保留一份草稿。",
        "parameters": {
            "type": "object",
            "properties": {
                "entries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "material_id": _MID,
                            "decision": {"type": "string", "enum": list(DECISIONS)},
                            "suggested_slot": {"type": "string", "description": "建议时段 YYYY-MM-DD HH:MM；不排期时传空字符串"},
                            "risk_reasons": {"type": "array", "items": {"type": "string"}, "description": "风险或不排期的原因（说明性文字写这里）"},
                            "pending_items": {"type": "array", "items": {"type": "string"}, "description": "只写需要用户确认或补充的事项；duplicate / blocked 通常为空"},
                        },
                        "required": ["material_id", "decision", "suggested_slot", "risk_reasons", "pending_items"],
                    },
                },
                "reason": _REASON,
            },
            "required": ["entries", "reason"],
        },
    },
]
SPEC_BY_NAME = {spec["name"]: spec for spec in TOOL_SPECS}
_JSON_TYPES = {"string": str, "array": list, "object": dict}


@dataclass
class MaterialFacts:
    read: bool = False
    found: bool | None = None
    material: dict | None = None
    missing_fields: list = field(default_factory=list)
    existing_schedule: list = field(default_factory=list)
    rule_hits: list | None = None
    copyright: dict | None = None
    slot_query: dict | None = None
    confirmations: list = field(default_factory=list)
    block: dict | None = None

    def awaiting(self) -> list[dict]:
        return [c for c in self.confirmations if c["status"] == AWAITING]


@dataclass
class ToolOutcome:
    ok: bool
    data: dict
    summary: str

    def content(self) -> str:
        return json.dumps(self.data, ensure_ascii=False)


class RunContext:
    """一次运行的状态：请求、数据源、草稿库，以及工具调用积累的事实账本。"""

    def __init__(self, request: ScheduleRequest, store: DataStore, drafts: DraftStore):
        self.request = request
        self.store = store
        self.drafts = drafts
        self.facts: dict[str, MaterialFacts] = {}
        self.proposed: dict[tuple, str] = {}  # (channel, slot) -> 本次请求内暂留给的素材
        self.save_attempts: list[dict] = []
        self.pending_listed = False

    def fact(self, material_id: str) -> MaterialFacts:
        return self.facts.setdefault(material_id, MaterialFacts())

    def request_problems(self, item: RequestItem) -> list[str]:
        """发布要求本身缺失或无效（缺渠道/时间、渠道未配置、时间已过）。"""
        problems = []
        if not item.channel:
            problems.append("channel（发布渠道）缺失")
        elif item.channel not in self.store.channels:
            problems.append(f"channel（渠道 {item.channel} 未配置，可选：{'、'.join(self.store.channels)}）")
        if not item.publish_time:
            problems.append("publish_time（发布时间要求）缺失")
        elif item.publish_time < self.request.as_of:
            problems.append(f"publish_time（{item.publish_time} 早于当前时间 {self.request.as_of}，已过期）")
        return problems

    def info_missing(self, material_id: str) -> bool:
        fact = self.facts.get(material_id) or MaterialFacts()
        item = self.request.item(material_id)
        return (fact.found is False or bool(fact.missing_fields) or bool(item and self.request_problems(item))
                or (fact.copyright or {}).get("status") == "not_found")

    def unschedulable(self, material_id: str) -> bool:
        """已知不能进排期：阻断、不存在、信息缺失、已在排期中。尚未查过的素材按“可能要排”对待。"""
        fact = self.facts.get(material_id)
        if fact is not None and (fact.block is not None or fact.existing_schedule):
            return True
        return self.info_missing(material_id)

    def holds_requested_slot(self, item: RequestItem) -> bool:
        """另一个素材是否仍占着它自己的要求时段：不能排期的、期望时间已提议改到别处的，不再占用。"""
        if self.unschedulable(item.material_id):
            return False
        if item.time_rule == "preferred":
            fact = self.facts.get(item.material_id)
            if fact and any(c["proposed_slot"] and c["proposed_slot"] != item.publish_time for c in fact.awaiting()):
                return False
        return True

    def slot_conflict(self, channel: str | None, slot: str, material_id: str) -> str | None:
        """slot（已规范化）对该素材不可用时返回原因，可用返回 None。"""
        cfg = self.store.channels.get(channel or "")
        if cfg is None:
            return f"未知渠道 {channel}"
        dt = parse_slot(slot)
        start = parse_slot(f"{slot[:10]} {cfg['start']}")
        end = parse_slot(f"{slot[:10]} {cfg['end']}")
        if dt.minute != 0 or not start <= dt <= end:
            return f"不在 {channel} 可发布时段 {cfg['start']}-{cfg['end']}（整点）内"
        if slot < self.request.as_of:
            return f"早于当前时间 {self.request.as_of}"
        for entry in self.store.schedule():
            if entry["channel"] == channel and entry["slot"] == slot:
                return f"已被已有排期 {entry['schedule_id']}《{entry['title']}》占用"
        items = self.request.items
        own = self.request.item(material_id)
        own_rank = self._rank(own) if own else (2, len(items))
        own_requested = own is not None and own.channel == channel and own.publish_time == slot
        for it in items:
            if it.material_id == material_id or it.channel != channel or it.publish_time != slot:
                continue
            if not self.holds_requested_slot(it):
                continue
            # 别人仍要求的时段不能拿来当替代时段；同一时段被多个素材要求时，硬性要求优先，其次按请求顺序
            if not own_requested or self._rank(it) < own_rank:
                kind = "硬性" if it.time_rule == "fixed" else "期望"
                return f"本次请求中 {it.material_id}（{kind}时间）要求了该时段"
        holder = self.proposed.get((channel, slot))
        if holder and holder != material_id:
            return f"已提议给本次请求中的 {holder}"
        return None

    def _rank(self, item: RequestItem) -> tuple:
        return (0 if item.time_rule == "fixed" else 1, self.request.items.index(item))

    def release_holds(self, material_id: str) -> None:
        for key, holder in list(self.proposed.items()):
            if holder == material_id:
                del self.proposed[key]


def _error(code: str, message: str) -> ToolOutcome:
    return ToolOutcome(False, {"ok": False, "error_code": code, "message": message}, f"失败 {code}：{message}")


def _validate_args(spec: dict, args) -> list[str]:
    if not isinstance(args, dict):
        return ["参数必须是 JSON 对象"]
    props = spec["parameters"]["properties"]
    # reason 只用于运行记录，漏填不拦截（避免真实模型为此白白多一轮），trace 里记为“模型未填写”
    problems = [f"缺少参数 {name}" for name in spec["parameters"]["required"]
                if name not in args and name != "reason"]
    for name, value in args.items():
        expected = _JSON_TYPES.get(props.get(name, {}).get("type"))
        if expected and value is not None and not isinstance(value, expected):
            problems.append(f"参数 {name} 类型应为 {props[name]['type']}")
    return problems


class ToolExecutor:
    def __init__(self, ctx: RunContext):
        self.ctx = ctx
        self.handlers = {
            "list_pending_materials": self.list_pending_materials,
            "get_material": self.get_material,
            "check_rules": self.check_rules,
            "verify_copyright": self.verify_copyright,
            "query_slots": self.query_slots,
            "request_confirmation": self.request_confirmation,
            "block_material": self.block_material,
            "save_draft": self.save_draft,
        }

    def execute(self, name: str, args, arg_error: str | None = None) -> ToolOutcome:
        spec = SPEC_BY_NAME.get(name)
        if spec is None:
            return _error("UNKNOWN_TOOL", f"不存在工具 {name}，可用工具：{', '.join(SPEC_BY_NAME)}")
        if arg_error:
            return _error("BAD_ARGUMENTS", f"参数不是合法 JSON：{arg_error}")
        problems = _validate_args(spec, args)
        if problems:
            return _error("BAD_ARGUMENTS", "；".join(problems))
        kwargs = {k: v for k, v in args.items() if k in spec["parameters"]["properties"] and k != "reason"}
        try:
            return self.handlers[name](**kwargs)
        except Exception as exc:  # 工具内部异常不应打断 Agent 循环，作为失败结果交回模型
            return _error("TOOL_EXCEPTION", f"{type(exc).__name__}: {exc}")

    # ---- 只读工具 -------------------------------------------------------

    def list_pending_materials(self) -> ToolOutcome:
        ctx = self.ctx
        pending, adopted = [], []
        for m in ctx.store.materials.values():
            if m.get("status") != "pending_review":
                continue
            requirement = m.get("requested_publish") or {}
            pending.append({"material_id": m["material_id"], "title": m.get("title"), "owner": m.get("owner"),
                            "requested_publish": requirement or None})
            if ctx.request.scope == "pending" and ctx.request.item(m["material_id"]) is None:
                try:
                    item = parse_item(dict(requirement, material_id=m["material_id"]), m["material_id"])
                except ValueError:  # 登记的发布要求本身不合法：按缺失处理，交给模型标记 needs_info
                    item = RequestItem(m["material_id"], None, None, "preferred")
                ctx.request.items.append(item)
                adopted.append(m["material_id"])
        ctx.pending_listed = True
        data = {"ok": True, "count": len(pending), "materials": pending}
        summary = f"待审核素材 {len(pending)} 个：{'、'.join(p['material_id'] for p in pending)}"
        if ctx.request.scope == "pending":
            data["note"] = "以上素材已加入本次待处理清单，save_draft 需为每个素材给出一条结论"
            summary += f"；已加入待处理清单 {len(adopted)} 个"
        return ToolOutcome(True, data, summary)

    def get_material(self, material_id: str) -> ToolOutcome:
        ctx = self.ctx
        fact = ctx.fact(material_id)
        fact.read = True
        item = ctx.request.item(material_id)
        request_missing = ctx.request_problems(item) if item else []
        material = ctx.store.materials.get(material_id)
        if material is None:
            fact.found = False
            data = {"ok": True, "material_id": material_id, "found": False, "request_missing": request_missing,
                    "message": "素材库中不存在该 ID，无法审核与排期"}
            return ToolOutcome(True, data, f"{material_id} 不存在于素材库")
        required = ctx.store.rules["required_fields"].get(material.get("type"), ctx.store.rules["required_fields"]["default"])
        missing = [k for k in required if is_empty(material.get(k))]
        existing = [e for e in ctx.store.schedule() if e["material_id"] == material_id]
        fact.found, fact.material, fact.missing_fields, fact.existing_schedule = True, material, missing, existing
        data = {
            "ok": True, "material_id": material_id, "found": True, "material": material,
            "missing_fields": missing, "request_requirement": item.to_dict() if item else None,
            "request_missing": request_missing, "already_scheduled": existing,
        }
        parts = [f"《{material.get('title')}》"]
        parts.append(f"缺失必填字段 {missing}" if missing else "必填字段齐全")
        parts.append(f"版权声明状态 {(material.get('copyright') or {}).get('status') or '无'}（未核验）")
        if request_missing:
            parts.append(f"发布要求有问题：{'；'.join(request_missing)}")
        if existing:
            parts.append("已在排期 " + "、".join(f"{e['schedule_id']}({e['channel']} {e['slot']})" for e in existing))
        return ToolOutcome(True, data, "；".join(parts))

    def check_rules(self, material_id: str) -> ToolOutcome:
        material = self.ctx.store.materials.get(material_id)
        if material is None:
            return _error("NOT_FOUND", f"素材 {material_id} 不存在，无法做规则检查")
        hits = []
        for rule in self.ctx.store.rules["rules"]:
            evidence = None
            if rule["type"] == "keyword":
                text = " ".join(str(material.get(f) or "") for f in rule["fields"])
                found = [kw for kw in rule["keywords"] if kw in text]
                if found:
                    evidence = "命中关键词：" + "、".join(found)
            elif rule["type"] == "flag":
                flags = material.get("flags") or {}
                if all(flags.get(k) == v for k, v in rule["when"].items()):
                    evidence = "命中标记：" + json.dumps(rule["when"], ensure_ascii=False)
            elif rule["type"] == "max_value":
                value = material.get(rule["field"])
                if isinstance(value, (int, float)) and value > rule["max"]:
                    evidence = f"{rule['field']}={value}，超过上限 {rule['max']}"
            elif rule["type"] == "copyright_status":
                status = (material.get("copyright") or {}).get("status")
                if status in rule["statuses"]:
                    evidence = f"版权状态为 {status}"
            if evidence:
                hits.append({"rule_id": rule["rule_id"], "level": rule["level"], "message": rule["message"], "evidence": evidence})
        highest = max((h["level"] for h in hits), key=LEVEL_ORDER.get, default="none")
        self.ctx.fact(material_id).rule_hits = hits
        data = {"ok": True, "material_id": material_id, "hits": hits, "highest_level": highest}
        summary = "无规则风险" if not hits else "命中 " + "、".join(f"{h['rule_id']}({h['level']})" for h in hits)
        return ToolOutcome(True, data, summary)

    def license_coverage(self, material: dict, date: str | None) -> dict:
        license_id = (material.get("copyright") or {}).get("license_id")
        record = self.ctx.store.licenses.get(license_id) if license_id else None
        if record is None:
            return {"status": "not_found", "license_id": license_id, "message": "版权登记库中查无该素材授权，需补充授权信息"}
        expired = record["status"] != "valid" or (date is not None and record["valid_until"] < date)
        return {
            "status": "expired" if expired else "valid", "license_id": license_id,
            "valid_until": record["valid_until"], "holder": record["holder"], "publish_date": date,
            "message": (f"授权有效期至 {record['valid_until']}，不覆盖发布日期 {date}，视为失效" if expired
                        else f"授权有效至 {record['valid_until']}，覆盖发布日期 {date}"),
        }

    def verify_copyright(self, material_id: str) -> ToolOutcome:
        material = self.ctx.store.materials.get(material_id)
        if material is None:
            return _error("NOT_FOUND", f"素材 {material_id} 不存在，无法核验版权")
        item = self.ctx.request.item(material_id)
        result = self.license_coverage(material, item.publish_time[:10] if item and item.publish_time else None)
        self.ctx.fact(material_id).copyright = result
        return ToolOutcome(True, {"ok": True, "material_id": material_id, **result}, f"版权 {result['status']}：{result['message']}")

    def query_slots(self, material_id: str, channel: str, publish_time: str) -> ToolOutcome:
        ctx = self.ctx
        channel = (channel or "").strip()
        cfg = ctx.store.channels.get(channel)
        if cfg is None:
            return _error("UNKNOWN_CHANNEL", f"未知渠道 {channel}，可选：{', '.join(ctx.store.channels)}")
        try:
            requested = parse_slot(publish_time)
        except ValueError:
            return _error("BAD_TIME", "publish_time 格式应为 YYYY-MM-DD HH:MM")
        slot = fmt_slot(requested)
        conflict = ctx.slot_conflict(channel, slot, material_id)
        alternatives, skipped = [], []
        if conflict:
            day = slot[:10]
            cursor, end = parse_slot(f"{day} {cfg['start']}"), parse_slot(f"{day} {cfg['end']}")
            candidates = []
            while cursor <= end:
                if fmt_slot(cursor) != slot:
                    candidates.append(cursor)
                cursor += timedelta(hours=1)
            # 越接近要求时间越好；同样接近时优先晚于要求时间（避免早于内容解禁/活动开始时间发布）
            candidates.sort(key=lambda c: (abs((c - requested).total_seconds()), 0 if c > requested else 1))
            for cand in candidates:
                why = ctx.slot_conflict(channel, fmt_slot(cand), material_id)
                if why is None:
                    alternatives.append(fmt_slot(cand))
                    if len(alternatives) == 3:
                        break
                elif not alternatives:  # 比首选替代时段更近却不可用的时段，说明为什么跳过它们
                    skipped.append({"slot": fmt_slot(cand), "reason": why})
        result = {
            "ok": True, "material_id": material_id, "channel": channel, "requested_slot": slot,
            "requested_available": conflict is None, "conflict": conflict, "alternatives": alternatives,
            "skipped_nearer_slots": skipped,
        }
        ctx.fact(material_id).slot_query = result
        if conflict is None:
            summary = f"{channel} {slot} 可用"
        else:
            summary = f"{channel} {slot} 不可用（{conflict}）"
            if skipped:
                summary += "；更近的时段也不可用：" + "，".join(f"{s['slot'][11:]}（{s['reason']}）" for s in skipped)
            summary += f"；替代时段 {alternatives or '无（当天没有可用时段）'}"
        return ToolOutcome(True, result, summary)

    # ---- 记录决策的工具 -------------------------------------------------

    def request_confirmation(self, material_id: str, question: str, proposed_slot: str | None = None) -> ToolOutcome:
        ctx = self.ctx
        item = ctx.request.item(material_id)
        if item is None:
            return _error("NOT_IN_REQUEST", f"{material_id} 不在本次待处理清单中")
        fact = ctx.fact(material_id)
        proposed = (proposed_slot or "").strip()
        if proposed:
            try:
                proposed = canonical_slot(proposed)
            except ValueError:
                return _error("BAD_TIME", "proposed_slot 格式应为 YYYY-MM-DD HH:MM，没有替代时段请传空字符串")
            if proposed == item.publish_time:
                proposed = ""  # 与要求时间相同不算替代时段，统一按“无替代时段”登记
        if proposed:
            if ctx.unschedulable(material_id):
                return _error("NOT_SCHEDULABLE", f"{material_id} 已确定不能排期（阻断/信息缺失/不存在/已在排期），不能为它提议时段")
            why = ctx.slot_conflict(item.channel, proposed, material_id)
            if why:
                return _error("SLOT_UNAVAILABLE", f"提议时段 {proposed} 不可用：{why}；请先用 query_slots 查询可用时段")
            for c in fact.awaiting():  # 同一素材的新提议替换旧提议，旧提议作废并释放暂留
                if c["proposed_slot"]:
                    c["status"] = "superseded"
            ctx.release_holds(material_id)
            ctx.proposed[(item.channel, proposed)] = material_id
        seq = len(fact.confirmations) + 1
        # 编号随方案内容变化：同一请求重跑得到同一方案时编号不变，方案变了（如改提 17:00）编号也变，不会混淆
        digest = canonical_hash([ctx.request.request_key, material_id, proposed, seq])[:6]
        record = {"confirmation_id": f"C-{material_id}-{digest}", "question": question,
                  "proposed_slot": proposed or None, "status": AWAITING}
        fact.confirmations.append(record)
        data = {"ok": True, **record,
                "note": "已登记，等待用户确认；用户尚未同意，草稿中该素材须标记为 pending_confirmation。"
                        "proposed_slot 只在本次请求内暂留，并未写入正式排期，不要向用户表述为已预留/已锁定"}
        held = f"，本次请求内暂留 {proposed}（未写入排期）" if proposed else ""
        return ToolOutcome(True, data, f"已登记待确认 {record['confirmation_id']}{held}；用户尚未确认")

    def block_material(self, material_id: str, risk_summary: str) -> ToolOutcome:
        ctx = self.ctx
        if ctx.request.item(material_id) is None:
            return _error("NOT_IN_REQUEST", f"{material_id} 不在本次待处理清单中")
        fact = ctx.fact(material_id)
        fact.block = {"risk_summary": risk_summary}
        cancelled = [c["confirmation_id"] for c in fact.awaiting()]
        for c in fact.awaiting():
            c["status"] = "cancelled"
        ctx.release_holds(material_id)
        data = {"ok": True, "material_id": material_id, "blocked": True, "cancelled_confirmations": cancelled,
                "note": "该素材本次不排期；草稿中 decision 须为 blocked，suggested_slot 留空"}
        extra = f"；作废待确认 {cancelled}" if cancelled else ""
        return ToolOutcome(True, data, f"已阻断 {material_id}：{risk_summary}{extra}")

    def save_draft(self, entries: list) -> ToolOutcome:
        ctx = self.ctx
        problems = self.review_entries(entries)
        if problems:
            result = {"ok": False, "error_code": "VALIDATION_FAILED", "retryable": True, "problems": problems,
                      "message": "草稿未保存：复核未通过，请按 problems 修正后重新提交"}
            ctx.save_attempts.append({"validated": False, "raw": entries, "entries": None, "result": result})
            return ToolOutcome(False, result, f"复核未通过，未保存：{'；'.join(problems)}")
        attempt = {"validated": True, "raw": copy.deepcopy(entries), "entries": [self._enrich(e) for e in entries]}
        ctx.save_attempts.append(attempt)  # 先登记再写：写入过程出任何异常，报告也能如实显示“保存失败”
        try:
            result = ctx.drafts.save(ctx.request.request_key, ctx.request.request_id, attempt["entries"])
        except Exception as exc:
            result = {"ok": False, "error_code": "IO_ERROR", "retryable": False, "message": f"草稿写入失败：{exc}"}
        attempt["result"] = result
        if result["ok"]:
            summary = f"{result['result']}：{result['draft_id']} v{result['version']}（{result['message']}）"
            if result.get("changes"):
                summary += "；变化：" + "；".join(result["changes"])
        else:
            summary = f"保存失败 {result['error_code']}（retryable={result['retryable']}）：{result['message']}"
        return ToolOutcome(result["ok"], result, summary)

    # ---- save_draft 复核 ------------------------------------------------

    def review_entries(self, entries) -> list[str]:
        """按工具事实复核草稿条目；返回问题列表（空列表表示通过）。保存时调用，生成报告时也用它判断草稿是否已过期。"""
        ctx = self.ctx
        if ctx.request.scope == "pending" and not ctx.pending_listed:
            return ["本次请求要求处理全部待审核素材：请先调用 list_pending_materials 找出待处理素材"]
        if not isinstance(entries, list) or not entries:
            return ["entries 不能为空，需覆盖本次待处理的每个素材"]
        problems: list[str] = []
        request_ids = [it.material_id for it in ctx.request.items]
        seen: set = set()
        taken: dict = {}
        for idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                problems.append(f"entries[{idx}] 必须是对象")
                continue
            mid, decision = entry.get("material_id"), entry.get("decision")
            slot = (entry.get("suggested_slot") or "").strip()
            if mid not in request_ids:
                problems.append(f"{mid} 不在本次待处理清单中")
                continue
            if mid in seen:
                problems.append(f"{mid} 出现多条记录，每个素材只能一条")
                continue
            seen.add(mid)
            if decision not in DECISIONS:
                problems.append(f"{mid} 的 decision 非法：{decision}")
                continue
            for key in ("risk_reasons", "pending_items"):
                value = entry.get(key, [])
                if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                    problems.append(f"{mid} 的 {key} 必须是字符串数组")
            problems.extend(self._review_one(mid, decision, slot, entry, taken))
        missing = [m for m in request_ids if m not in seen]
        if missing:
            problems.append(f"缺少以下素材的条目：{'、'.join(missing)}")
        return problems

    def _review_one(self, mid: str, decision: str, slot: str, entry: dict, taken: dict) -> list[str]:
        ctx = self.ctx
        item = ctx.request.item(mid)
        fact = ctx.facts.get(mid) or MaterialFacts()
        if not fact.read:
            return [f"{mid} 未调用 get_material 读取素材，不能下结论"]
        if slot:
            try:
                slot = canonical_slot(slot)
            except ValueError:
                return [f"{mid} 的 suggested_slot 格式应为 YYYY-MM-DD HH:MM"]
        hits = fact.rule_hits or []
        copyright_status = (fact.copyright or {}).get("status")
        info_missing = ctx.info_missing(mid)
        block_fact = copyright_status == "expired" or any(h["level"] == "block" for h in hits)
        awaiting = fact.awaiting()
        problems: list[str] = []

        if decision in ("needs_info", "blocked", "duplicate"):
            if slot:
                problems.append(f"{mid} 为 {decision} 时 suggested_slot 必须为空")
            if decision == "needs_info":
                if not info_missing:
                    problems.append(f"{mid} 工具结果显示信息完整，不能标记 needs_info")
                if not entry.get("pending_items"):
                    problems.append(f"{mid} 标记 needs_info 须在 pending_items 列出需补充的信息")
            elif decision == "blocked":
                if fact.block is None:
                    problems.append(f"{mid} 标记 blocked 前须调用 block_material 登记阻断原因")
                elif info_missing and not block_fact:
                    problems.append(f"{mid} 是信息缺失，应标记 needs_info 并列出需补充项，而不是阻断")
            elif decision == "duplicate" and not fact.existing_schedule:
                problems.append(f"{mid} 不在已有排期中，不能标记 duplicate")
            return problems

        # 以下是要进入排期的结论：schedule / pending_confirmation
        if info_missing:
            return [f"{mid} 信息缺失或发布要求无效，只能标记 needs_info 并列出需补充项"]
        if fact.existing_schedule:
            return [f"{mid} 已在已有排期 {[e['schedule_id'] for e in fact.existing_schedule]} 中，应标记 duplicate"]
        if fact.block is not None or block_fact:
            return [f"{mid} 存在阻断级风险或版权失效，须调用 block_material 并标记 blocked"]
        if fact.rule_hits is None:
            return [f"{mid} 未调用 check_rules，不能排期"]
        if any(h["level"] == "verify" for h in hits) and copyright_status != "valid":
            return [f"{mid} 有待核验项（verify），须先调用 verify_copyright 补查"]
        coverage = self.license_coverage(fact.material, (slot or item.publish_time)[:10])
        if coverage["status"] == "expired":
            return [f"{mid} 的授权 {coverage['license_id']} 不覆盖发布日期（{coverage['message']}），须先 verify_copyright 核验并阻断"]

        if decision == "schedule":
            if any(h["level"] == "warn" for h in hits):
                problems.append(f"{mid} 命中 warn 级规则，须 request_confirmation 并标记 pending_confirmation")
            if awaiting:
                problems.append(f"{mid} 有待确认事项，decision 应为 pending_confirmation")
            if fact.slot_query is None:
                problems.append(f"{mid} 未调用 query_slots 确认时段可用")
            if slot != item.publish_time:
                problems.append(f"{mid} 直接排期时 suggested_slot 必须等于要求时间 {item.publish_time}；"
                                f"改期须先 request_confirmation 并标记 pending_confirmation")
        else:
            if not awaiting:
                problems.append(f"{mid} 标记 pending_confirmation 前须调用 request_confirmation 登记待确认事项")
            if slot and slot != item.publish_time:
                if item.time_rule == "fixed":
                    problems.append(f"{mid} 的发布时间 {item.publish_time} 是硬性要求，未经用户同意不得改为 {slot}；"
                                    f"替代方案只能放在待确认事项里，suggested_slot 留空")
                elif not any(c["proposed_slot"] == slot for c in awaiting):
                    problems.append(f"{mid} 改到 {slot} 未向用户发起确认（request_confirmation 的 proposed_slot 应为该时段）")
        if slot:
            why = ctx.slot_conflict(item.channel, slot, mid)
            if why:
                problems.append(f"{mid} 的建议时段 {slot} 不可用：{why}")
            key = (item.channel, slot)
            if key in taken:
                problems.append(f"{mid} 与 {taken[key]} 的建议时段 {slot} 冲突")
            taken[key] = mid
        return problems

    def _enrich(self, entry: dict) -> dict:
        """草稿条目以请求和工具事实为准补全，模型只贡献结论、风险说明和待确认文字。"""
        ctx = self.ctx
        mid = entry["material_id"]
        item = ctx.request.item(mid)
        fact = ctx.facts.get(mid) or MaterialFacts()
        slot = (entry.get("suggested_slot") or "").strip()
        slot = canonical_slot(slot) if slot else None
        return {
            "material_id": mid,
            "title": (fact.material or {}).get("title"),
            "decision": entry["decision"],
            "review_status": DECISION_LABELS[entry["decision"]],
            "channel": item.channel,
            "requested_slot": item.publish_time,
            "time_rule": item.time_rule,
            "suggested_slot": slot,
            "slot_changed": bool(slot and slot != item.publish_time),
            "risk_reasons": list(entry.get("risk_reasons", [])),
            "pending_items": list(entry.get("pending_items", [])),
            # 风险事实取自工具账本，不依赖模型措辞：即使模型漏写，草稿里也保留规则命中等事实
            "risk_facts": {
                "rule_hits": None if fact.rule_hits is None else [f"{h['rule_id']}({h['level']})" for h in fact.rule_hits],
                "copyright_verified": (fact.copyright or {}).get("status"),
                "missing_fields": list(fact.missing_fields),
                "request_problems": ctx.request_problems(item),
                "already_scheduled": [e["schedule_id"] for e in fact.existing_schedule],
                "blocked": fact.block is not None,
            },
            "confirmations": copy.deepcopy(fact.confirmations),
            "confirm_state": CONFIRM_STATES[entry["decision"]],
        }
