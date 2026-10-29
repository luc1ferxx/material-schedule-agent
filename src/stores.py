"""数据访问：只读业务数据（素材/规则/版权/渠道/已有排期）与草稿库（唯一的写操作）。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .common import DATA_DIR, canonical_hash, canonical_slot, load_json, write_json_atomic

# 判断“是否同一份排期方案”只看结构化字段和工具事实；风险说明、确认问题等措辞每次运行都可能不同，不算方案变化
PLAN_FIELDS = ("material_id", "decision", "channel", "requested_slot", "time_rule", "suggested_slot",
               "confirm_state", "risk_facts")


def plan_signature(entries: list[dict]) -> list[dict]:
    rows = []
    for e in entries:
        row = {k: e.get(k) for k in PLAN_FIELDS}
        row["proposed_slots"] = sorted(c.get("proposed_slot") or "" for c in e.get("confirmations", [])
                                       if c.get("status", "awaiting_user") == "awaiting_user")
        rows.append(row)
    return sorted(rows, key=lambda r: r["material_id"])


def plan_changes(old_entries: list[dict], new_entries: list[dict]) -> list[str]:
    """两版方案的差异，如 “M01 suggested_slot：2026-11-03 19:00 → 2026-11-03 17:00”。"""
    old = {r["material_id"]: r for r in plan_signature(old_entries)}
    changes = []
    for row in plan_signature(new_entries):
        before = old.get(row["material_id"], {})
        for key, value in row.items():
            if key != "material_id" and before.get(key) != value:
                changes.append(f"{row['material_id']} {key}：{before.get(key)} → {value}")
    return changes


class DataStore:
    def __init__(self, data_dir: Path = DATA_DIR, schedule_path: Path | None = None):
        data_dir = Path(data_dir)
        self.materials = {m["material_id"]: m for m in load_json(data_dir / "materials.json")["materials"]}
        self.rules = load_json(data_dir / "rules.json")
        self.channels = load_json(data_dir / "channels.json")["channels"]
        self.licenses = load_json(data_dir / "copyright_registry.json")["licenses"]
        self.schedule_path = Path(schedule_path) if schedule_path else data_dir / "schedule.json"
        self.schedule()  # 启动时就校验一次：文件缺失或格式错误直接报配置错误（退出码 2），而不是跑到一半才出错

    def schedule(self) -> list[dict]:
        """每次现读并规范化：保存前的冲突复核要看到最新排期；手改成 '2026-11-3 19:00' 之类的写法也能识别。"""
        data = load_json(self.schedule_path)
        entries = data.get("entries") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            raise ValueError(f"{self.schedule_path} 格式错误：需要 {{\"entries\": [...]}}")
        normalized = []
        for idx, entry in enumerate(entries, 1):
            try:
                normalized.append(dict(entry, channel=str(entry["channel"]).strip(), slot=canonical_slot(entry["slot"])))
            except (KeyError, TypeError, ValueError):
                raise ValueError(f"{self.schedule_path} 第 {idx} 条排期格式错误（需要 channel 和 'YYYY-MM-DD HH:MM' 格式的 slot）：{entry}") from None
        return normalized


class DraftStore:
    """排期草稿库（JSON 文件）。按 request_key 幂等：同一请求只会有一份草稿。

    fault 用于故障注入测试：fail_once=第一次写入超时（可重试），fail_always=草稿库只读（不可重试）。
    注入的失败发生在写入之前，保证“返回失败 = 确实没写入”。
    """

    def __init__(self, path: Path, fault: str = "none"):
        self.path = Path(path)
        self.fault = fault
        self.write_attempts = 0

    def _load(self) -> dict:
        if not self.path.exists():
            return {"drafts": {}}
        data = load_json(self.path)
        if not isinstance(data, dict) or not isinstance(data.get("drafts"), dict):
            raise ValueError("草稿库文件结构异常，应为 {\"drafts\": {...}}")
        return data

    def get(self, request_key: str) -> dict | None:
        return self._load()["drafts"].get(request_key)

    def count(self) -> int:
        return len(self._load()["drafts"])

    def save(self, request_key: str, request_id: str | None, entries: list[dict]) -> dict:
        self.write_attempts += 1
        if self.fault == "fail_always":
            return {"ok": False, "error_code": "STORAGE_READ_ONLY", "retryable": False,
                    "message": "草稿库当前只读，写入被拒绝；草稿未保存"}
        if self.fault == "fail_once" and self.write_attempts == 1:
            return {"ok": False, "error_code": "STORAGE_TIMEOUT", "retryable": True,
                    "message": "草稿库写入超时；本次未写入，可重试"}
        try:
            data = self._load()
            plan_hash = canonical_hash(plan_signature(entries))
            existing = data["drafts"].get(request_key)
            if existing and existing.get("plan_hash") == plan_hash:
                return {"ok": True, "result": "duplicate_unchanged", "draft_id": existing["draft_id"],
                        "version": existing["version"],
                        "message": "相同请求的草稿已存在且排期方案一致，未重复创建（保留原草稿）"}
            now = datetime.now().isoformat(timespec="seconds")
            changes = plan_changes(existing["entries"], entries) if existing else []
            history = list(existing.get("history", [])) if existing else []
            if existing:  # 旧版本只留方案摘要，便于追溯“为什么改了”
                history.append({"version": existing["version"], "updated_at": existing["updated_at"],
                                "plan": plan_signature(existing["entries"])})
            draft = {
                "draft_id": existing["draft_id"] if existing else f"D-{request_key[:8]}",
                "request_key": request_key,
                "request_id": request_id,
                "status": "draft",
                "version": existing["version"] + 1 if existing else 1,
                "created_at": existing["created_at"] if existing else now,
                "updated_at": now,
                "plan_hash": plan_hash,
                "entries": entries,
                "history": history,
            }
            data["drafts"][request_key] = draft
            write_json_atomic(self.path, data)
        except Exception as exc:  # 存储边界：任何异常都如实作为保存失败返回，绝不当成成功
            return {"ok": False, "error_code": "IO_ERROR", "retryable": False, "message": f"草稿写入失败：{exc}"}
        if existing:
            return {"ok": True, "result": "updated", "draft_id": draft["draft_id"], "version": draft["version"],
                    "changes": changes,
                    "message": "同一请求的排期方案有变化，已更新原草稿（版本 +1），未新建草稿；旧版本的待确认事项作废"}
        return {"ok": True, "result": "created", "draft_id": draft["draft_id"], "version": 1, "message": "草稿已创建"}
