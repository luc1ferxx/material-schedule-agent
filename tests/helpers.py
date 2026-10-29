"""测试辅助：构造运行上下文、脚本化的假模型。"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from src.common import DATA_DIR, load_json
from src.llm import ModelTurn, ToolCall
from src.request import normalize_request
from src.stores import DataStore, DraftStore
from src.tools import RunContext, ToolExecutor

AS_OF = "2026-10-29 09:00"


class TempDirMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def make_ctx(self, items, fault="none", schedule_entries=None, drafts_name="drafts.json", scope="items"):
        # as_of 固定：测试用的 2026-11-03 时段不会因为“今天”过了这一天而变成过期
        raw = {"request_id": "T", "as_of": AS_OF, "scope": scope, "items": items, "simulate": {"save_draft": fault}}
        schedule_path = None
        if schedule_entries is not None:
            schedule_path = self.tmp / "schedule.json"
            schedule_path.write_text(json.dumps({"entries": schedule_entries}, ensure_ascii=False), encoding="utf-8")
        request = normalize_request(raw)
        ctx = RunContext(request, DataStore(schedule_path=schedule_path), DraftStore(self.tmp / drafts_name, fault))
        return ctx, ToolExecutor(ctx)


def default_schedule() -> list:
    return load_json(DATA_DIR / "schedule.json")["entries"]


def item(mid, channel="app_home", time="2026-11-03 10:00", rule="preferred"):
    return {"material_id": mid, "channel": channel, "publish_time": time, "time_rule": rule}


def call(name, **args):
    args.setdefault("reason", "测试")
    return ToolCall(f"id-{name}-{args.get('material_id', '')}", name, args)


class ScriptedLLM:
    """按预设剧本返回模型回合，用于测试循环本身（上限、错误处理、报告一致性）。"""
    label = "scripted"

    def __init__(self, turns):
        self.turns = list(turns)
        self.tool_results = []

    def start(self, system, user, tools):
        self.system, self.user, self.tools = system, user, tools

    def next(self):
        if not self.turns:
            return ModelTurn("剧本结束")
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return turn

    def add_tool_results(self, results):
        self.tool_results.append(results)
