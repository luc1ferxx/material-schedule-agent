"""请求校验与归一化。格式错误抛 ValueError（CLI 返回退出码 2）；业务层面的缺失交给 Agent 处理。

两种请求：
- scope="items"（默认）：明确列出素材及发布要求；
- scope="pending"：不列素材，由 Agent 调用 list_pending_materials 找出待审核素材，按素材登记的发布要求排期。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .common import canonical_hash, canonical_slot, fmt_slot

TIME_RULES = ("preferred", "fixed")
SAVE_FAULTS = ("none", "fail_once", "fail_always")
SCOPES = ("items", "pending")


@dataclass
class RequestItem:
    material_id: str
    channel: str | None
    publish_time: str | None  # 已规范化为 YYYY-MM-DD HH:MM
    time_rule: str

    def to_dict(self) -> dict:
        return {
            "material_id": self.material_id,
            "channel": self.channel,
            "publish_time": self.publish_time,
            "time_rule": self.time_rule,
        }


@dataclass
class ScheduleRequest:
    request_id: str | None
    items: list[RequestItem]
    request_key: str
    as_of: str  # “当前时间”，早于它的发布时间视为已过期；样例里固定写死以便复现
    scope: str = "items"
    notes: list[str] = field(default_factory=list)
    save_fault: str = "none"

    def item(self, material_id: str) -> RequestItem | None:
        for it in self.items:
            if it.material_id == material_id:
                return it
        return None


def _time(value, where: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"{where} 必须是字符串")
    try:
        return canonical_slot(value)
    except ValueError:
        raise ValueError(f"{where} 格式应为 'YYYY-MM-DD HH:MM'") from None


def parse_item(raw, where: str) -> RequestItem:
    if not isinstance(raw, dict):
        raise ValueError(f"{where} 必须是对象")
    mid = raw.get("material_id")
    if not isinstance(mid, str) or not mid.strip():
        raise ValueError(f"{where}.material_id 必须是非空字符串")
    channel = raw.get("channel")
    if channel is not None and not isinstance(channel, str):
        raise ValueError(f"{where}.channel 必须是字符串")
    time_rule = raw.get("time_rule") or "preferred"
    if time_rule not in TIME_RULES:
        raise ValueError(f"{where}.time_rule 只能是 {TIME_RULES}")
    return RequestItem(mid.strip(), (channel or "").strip() or None, _time(raw.get("publish_time"), f"{where}.publish_time"),
                       time_rule)


def normalize_request(raw) -> ScheduleRequest:
    if not isinstance(raw, dict):
        raise ValueError("输入必须是 JSON 对象")
    scope = raw.get("scope") or "items"
    if scope not in SCOPES:
        raise ValueError(f"scope 只能是 {SCOPES}")
    raw_items = raw.get("items")
    items: list[RequestItem] = []
    notes: list[str] = []
    if scope == "pending":
        if raw_items:
            raise ValueError("scope=pending 表示由 Agent 找出待审核素材，不要再列 items")
    else:
        if not isinstance(raw_items, list) or not raw_items:
            raise ValueError("items 必须是非空数组（或用 scope=\"pending\" 让 Agent 找出待审核素材）")
        seen: dict[str, RequestItem] = {}
        for idx, raw_item in enumerate(raw_items):
            item = parse_item(raw_item, f"items[{idx}]")
            if item.material_id in seen:
                if seen[item.material_id] == item:
                    notes.append(f"请求中 {item.material_id} 重复出现且要求相同，已合并为一条")
                    continue
                raise ValueError(f"同一素材 {item.material_id} 出现多个不同的发布要求，请先明确以哪个为准再提交")
            seen[item.material_id] = item
            items.append(item)

    as_of = _time(raw.get("as_of"), "as_of") or fmt_slot(datetime.now())
    simulate = raw.get("simulate") or {}
    if not isinstance(simulate, dict):
        raise ValueError("simulate 必须是对象")
    save_fault = simulate.get("save_draft", "none")
    if save_fault not in SAVE_FAULTS:
        raise ValueError(f"simulate.save_draft 只能是 {SAVE_FAULTS}")

    # 幂等键只由（规范化后的）请求内容决定，不含 request_id、as_of、模拟开关：相同内容 = 同一份草稿
    key_src = {"scope": scope, "items": sorted((it.to_dict() for it in items), key=lambda d: d["material_id"])}
    request_key = canonical_hash(key_src)[:16]
    return ScheduleRequest(raw.get("request_id"), items, request_key, as_of, scope, notes, save_fault)
