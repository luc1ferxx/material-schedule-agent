"""运行记录自检：对 examples/ 下提交的全部实际输出（离线 Mock 与真实模型）逐个检查关键不变量。

记录是真实跑出来的结果，这里不重跑模型，只验证记录本身没有越权发布、虚报保存、擅改硬性时间、时段冲突等问题。
"""
import glob
import os
import unittest

from src.common import ROOT, load_json

OUTPUTS = sorted(glob.glob(str(ROOT / "examples" / "**" / "outputs" / "*.json"), recursive=True))


def occupied_slots(report) -> set:
    schedule = (report.get("inputs") or {}).get("schedule") or "data/schedule.json"
    return {(e["channel"], e["slot"]) for e in load_json(ROOT / schedule)["entries"]}


class RecordInvariantTest(unittest.TestCase):
    def test_records_exist(self):
        self.assertTrue(OUTPUTS, "examples/ 下没有运行记录，请先运行 python -m src.run_examples")

    def test_every_record_keeps_invariants(self):
        for path in OUTPUTS:
            with self.subTest(record=os.path.relpath(path, ROOT)):
                report = load_json(path)
                self.assertFalse(report["published"])
                self.assertEqual(report["guard_flags"], [], "模型答复与工具事实不一致")

                saves = [t for t in report["trace"] if t["type"] == "tool_call" and t["tool"] == "save_draft"]
                if report["draft"]["saved"]:  # 草稿状态必须与最后一次 save_draft 的真实结果一致
                    self.assertTrue(saves and saves[-1]["ok"])
                    self.assertIn(report["draft"]["draft_id"], saves[-1]["result_summary"])
                else:
                    self.assertTrue(not saves or not saves[-1]["ok"])
                    self.assertNotEqual(report["status"], "completed")

                occupied, taken = occupied_slots(report), set()
                proposals = {(c["material_id"], c["proposed_slot"]) for c in report["pending_confirmations"]}
                for m in report["materials"]:
                    slot = m.get("suggested_slot")
                    if m.get("time_rule") == "fixed":
                        self.assertIn(slot, (None, m["requested_slot"]), f"{m['material_id']} 硬性时间被改动")
                    if m.get("decision") in ("needs_info", "blocked", "duplicate"):
                        self.assertIsNone(slot, f"{m['material_id']} 不可排期却有建议时段")
                    if not slot:
                        continue
                    key = (m["channel"], slot)
                    self.assertNotIn(key, occupied, f"{m['material_id']} 建议时段已被占用")
                    self.assertNotIn(key, taken, f"{m['material_id']} 与其他素材撞车")
                    taken.add(key)
                    if slot != m["requested_slot"]:
                        self.assertEqual(m["decision"], "pending_confirmation")
                        self.assertIn((m["material_id"], slot), proposals, f"{m['material_id']} 改期未发起确认")

                for t in report["trace"]:
                    if t["type"] == "tool_call":
                        self.assertTrue(t["basis"] and t["result_summary"] and t.get("next_action"))


if __name__ == "__main__":
    unittest.main()
