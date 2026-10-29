"""六个必须验收点的端到端测试（离线 Mock 驱动，验证流程与护栏；不代表真实模型效果）。"""
import json
import unittest

from src.agent import Limits
from src.common import ROOT
from src.main import run_once
from tests.helpers import TempDirMixin

INPUTS = ROOT / "examples" / "inputs"


class ScenarioTest(TempDirMixin, unittest.TestCase):
    def run_input(self, name, schedule=None, limits=None, drafts="drafts.json"):
        return run_once(str(INPUTS / name), "mock", str(self.tmp / drafts), schedule, limits)

    @staticmethod
    def by_id(report):
        return {m["material_id"]: m for m in report["materials"]}

    def test_pending_scope_finds_and_schedules_all_pending(self):
        report = self.run_input("pending_scope.json")
        m = self.by_id(report)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["trace"][0]["tool"], "list_pending_materials")
        self.assertEqual({k: v["decision"] for k, v in m.items()}, {
            "M01": "pending_confirmation", "M02": "schedule", "M03": "needs_info", "M04": "pending_confirmation",
            "M05": "blocked", "M07": "schedule", "M08": "pending_confirmation", "M09": "blocked"})
        self.assertEqual(m["M01"]["suggested_slot"], "2026-11-03 19:00")
        self.assertIsNone(m["M08"]["suggested_slot"])

    def test_normal_schedule(self):
        report = self.run_input("normal.json")
        m = self.by_id(report)
        self.assertEqual(report["status"], "completed")
        self.assertEqual((m["M02"]["decision"], m["M02"]["suggested_slot"]), ("schedule", "2026-11-03 10:00"))
        self.assertEqual(m["M07"]["decision"], "schedule")  # verify → 补查 valid
        self.assertEqual(m["M07"]["tool_facts"]["copyright_verified"], "valid")

    def test_slot_conflict_reference_case(self):
        report = self.run_input("slot_conflict.json")
        m = self.by_id(report)
        self.assertEqual(m["M01"]["decision"], "pending_confirmation")
        self.assertEqual(m["M01"]["suggested_slot"], "2026-11-03 19:00")
        self.assertTrue(m["M01"]["slot_changed"])
        self.assertEqual(m["M01"]["confirm_state"], "awaiting_user_decision")
        self.assertFalse(report["published"])
        self.assertNotIn("已发布", report["model_summary"])
        self.assertEqual(len(report["pending_confirmations"]), 1)

    def test_fixed_time_is_not_moved(self):
        m = self.by_id(self.run_input("fixed_conflict.json"))["M08"]
        self.assertEqual(m["decision"], "pending_confirmation")
        self.assertIsNone(m["suggested_slot"])  # 硬性时间不擅自改
        self.assertFalse(m["slot_changed"])

    def test_competing_materials_get_distinct_slots(self):
        report = self.run_input("competing_conflict.json")
        m = self.by_id(report)
        self.assertIsNone(m["M08"]["suggested_slot"])
        proposed = [c["proposed_slot"] for c in report["pending_confirmations"] if c["proposed_slot"]]
        self.assertEqual(len(proposed), len(set(proposed)))
        self.assertIn(m["M01"]["suggested_slot"], proposed)

    def test_missing_info(self):
        report = self.run_input("missing_info.json")
        decisions = {k: v["decision"] for k, v in self.by_id(report).items()}
        self.assertEqual(decisions, {"M03": "needs_info", "M99": "needs_info", "M02": "needs_info"})
        self.assertTrue(all(v["suggested_slot"] is None for v in report["materials"]))

    def test_rule_risk(self):
        m = self.by_id(self.run_input("rule_risk.json"))
        self.assertEqual(m["M04"]["decision"], "pending_confirmation")
        self.assertIn("R-AD-01", m["M04"]["risk_reasons"][0])
        self.assertEqual(m["M05"]["decision"], "blocked")
        self.assertEqual(m["M05"]["tool_facts"]["copyright_verified"], "expired")
        self.assertEqual(m["M09"]["decision"], "blocked")  # block 级规则：商业推广未标广告
        self.assertIn("R-AD-02(block)", m["M09"]["risk_facts"]["rule_hits"])

    def test_duplicate_submission_keeps_one_draft(self):
        first = self.run_input("duplicate_submit.json")
        second = self.run_input("duplicate_submit.json")
        self.assertEqual(first["draft"]["result"], "created")
        self.assertEqual(second["draft"]["result"], "duplicate_unchanged")
        self.assertEqual(first["draft"]["draft_id"], second["draft"]["draft_id"])
        drafts = json.loads((self.tmp / "drafts.json").read_text(encoding="utf-8"))["drafts"]
        self.assertEqual(len(drafts), 1)
        self.assertTrue(any("合并" in n for n in first["input_notes"]))
        self.assertEqual(self.by_id(first)["M06"]["decision"], "duplicate")

    def test_changed_schedule_resubmit_updates_same_draft(self):
        first = self.run_input("slot_conflict.json")
        second = self.run_input("slot_conflict.json", schedule=str(ROOT / "data" / "schedule_alt.json"))
        self.assertEqual(self.by_id(second)["M01"]["suggested_slot"], "2026-11-03 17:00")
        self.assertEqual((second["draft"]["result"], second["draft"]["version"]), ("updated", 2))
        self.assertEqual(first["draft"]["draft_id"], second["draft"]["draft_id"])
        # 能解释为什么改：更近的 19:00 也被占、方案差异、确认单号随方案变化
        query = next(t for t in second["trace"] if t["tool"] == "query_slots")
        self.assertIn("S-1103-07", query["result_summary"])
        self.assertIn("M01 suggested_slot：2026-11-03 19:00 → 2026-11-03 17:00", second["draft"]["changes"])
        self.assertNotEqual(first["pending_confirmations"][0]["confirmation_id"],
                            second["pending_confirmations"][0]["confirmation_id"])
        self.assertEqual(second["inputs"]["schedule"], "data/schedule_alt.json")
        stored = json.loads((self.tmp / "drafts.json").read_text(encoding="utf-8"))["drafts"]
        self.assertEqual([h["version"] for h in next(iter(stored.values()))["history"]], [1])

    def test_duplicate_material_is_not_reported_as_rule_checked(self):
        m06 = self.by_id(self.run_input("duplicate_submit.json"))["M06"]
        self.assertIsNone(m06["tool_facts"]["rule_hits"])

    def test_save_failure_is_reported(self):
        report = self.run_input("save_fail_always.json")
        self.assertEqual(report["status"], "save_failed")
        self.assertFalse(report["draft"]["saved"])
        self.assertEqual(report["draft"]["save_attempts"], 1)  # 不可重试 → 不重试
        self.assertIn("失败", report["model_summary"])
        self.assertEqual(report["guard_flags"], [])
        self.assertFalse((self.tmp / "drafts.json").exists())
        self.assertTrue(all(m["confirm_state"] == "not_saved" for m in report["materials"]))

    def test_retryable_save_failure_then_success(self):
        report = self.run_input("save_fail_once.json")
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["draft"]["save_attempts"], 2)

    def test_tool_limit_incomplete(self):
        report = self.run_input("normal.json", limits=Limits(max_tool_calls=3))
        self.assertEqual(report["status"], "incomplete")
        self.assertFalse(report["draft"]["saved"])

    def test_edited_schedule_is_respected(self):
        """评审改占用时段：把 app_home 10:00 设为已占用，M02 应改为待确认的替代时段。"""
        schedule = self.tmp / "schedule.json"
        schedule.write_text(json.dumps({"entries": [{"schedule_id": "S-X", "channel": "app_home",
                                                     "slot": "2026-11-03 10:00", "material_id": "M88",
                                                     "title": "临时占用"}]}), encoding="utf-8")
        m = self.by_id(self.run_input("normal.json", schedule=str(schedule)))
        self.assertEqual(m["M02"]["decision"], "pending_confirmation")
        self.assertEqual(m["M02"]["suggested_slot"], "2026-11-03 11:00")


if __name__ == "__main__":
    unittest.main()
