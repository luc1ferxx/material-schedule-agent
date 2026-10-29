"""ReAct 循环本身：上限、错误回传、报告以工具账本为准（防虚报发布/保存）。"""
import json
import unittest

from src.agent import PUBLISH_CLAIM, SAVE_CLAIM, Limits, affirms, run_agent
from src.llm import LLMError, ModelTurn
from tests.helpers import ScriptedLLM, TempDirMixin, call, item

M02_FLOW = [
    ModelTurn("", [call("get_material", material_id="M02")]),
    ModelTurn("", [call("check_rules", material_id="M02")]),
    ModelTurn("", [call("query_slots", material_id="M02", channel="app_home", publish_time="2026-11-03 10:00")]),
    ModelTurn("", [call("save_draft", entries=[{"material_id": "M02", "decision": "schedule",
                                                "suggested_slot": "2026-11-03 10:00",
                                                "risk_reasons": [], "pending_items": []}])]),
]


class AgentLoopTest(TempDirMixin, unittest.TestCase):
    def run_script(self, turns, fault="none", limits=None, items=None):
        ctx, _ = self.make_ctx(items or [item("M02")], fault=fault)
        llm = ScriptedLLM(turns)
        return run_agent(ctx, llm, limits or Limits()), llm, ctx

    def test_happy_path_completed(self):
        report, _, ctx = self.run_script(M02_FLOW + [ModelTurn("M02 已按 10:00 写入草稿，待确认。")])
        self.assertEqual(report["status"], "completed")
        self.assertTrue(report["draft"]["saved"])
        self.assertFalse(report["published"])
        self.assertEqual(report["guard_flags"], [])
        self.assertEqual(ctx.drafts.count(), 1)

    def test_step_limit_returns_incomplete(self):
        looping = [ModelTurn("", [call("get_material", material_id="M02")]) for _ in range(10)]
        report, _, _ = self.run_script(looping, limits=Limits(max_steps=3))
        self.assertEqual(report["status"], "incomplete")
        self.assertIn("轮数上限 3", report["status_reason"])
        self.assertEqual(report["usage"]["steps"], 3)

    def test_tool_call_limit_returns_incomplete(self):
        burst = [ModelTurn("", [call("get_material", material_id="M02") for _ in range(5)])]
        report, _, _ = self.run_script(burst, limits=Limits(max_tool_calls=2))
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["usage"]["tool_calls"], 2)
        executed = [t for t in report["trace"] if t["type"] == "tool_call"]
        refused = [t for t in report["trace"] if t["type"] == "refused_call"]
        self.assertEqual((len(executed), len(refused)), (2, 3))  # 超限调用不执行但留痕
        self.assertIn("3 个调用未执行", report["status_reason"])
        self.assertIn("停止", executed[-1]["next_action"])

    def test_tool_errors_are_fed_back_and_loop_continues(self):
        turns = [ModelTurn("", [call("publish_material", material_id="M02")])] + M02_FLOW + [ModelTurn("完成")]
        report, llm, _ = self.run_script(turns)
        first_result = llm.tool_results[0][0]
        self.assertTrue(first_result[2])  # is_error
        self.assertEqual(json.loads(first_result[1])["error_code"], "UNKNOWN_TOOL")
        self.assertEqual(report["status"], "completed")

    def test_publish_claim_is_flagged_not_trusted(self):
        report, _, _ = self.run_script(M02_FLOW + [ModelTurn("M02 已发布成功！")])
        self.assertFalse(report["published"])
        self.assertTrue(any("已发布" in f for f in report["guard_flags"]))

    def test_claim_detection_respects_negation(self):
        """真实模型写过“请勿视为已排期或已上线”，不应误报；否定只看同一分句。"""
        self.assertFalse(affirms(PUBLISH_CLAIM, "M01 在草稿中标记为待确认；请勿视为已排期或已上线。"))
        self.assertFalse(affirms(PUBLISH_CLAIM, "仅保存草稿，不代表已发布"))
        self.assertTrue(affirms(PUBLISH_CLAIM, "M02 已发布成功"))
        self.assertTrue(affirms(PUBLISH_CLAIM, "未发现风险，M02 已上线"))
        self.assertFalse(affirms(SAVE_CLAIM, "草稿未能保存成功，请稍后重试"))
        self.assertTrue(affirms(SAVE_CLAIM, "写入超时，但草稿已保存"))
        self.assertTrue(affirms(SAVE_CLAIM, "**草稿保存**：成功，草稿 ID D-1"))  # 真实模型用过的写法
        self.assertTrue(affirms(SAVE_CLAIM, "保存结果：成功"))
        self.assertFalse(affirms(SAVE_CLAIM, "保存结果：失败，未成功写入"))

    def test_more_claim_phrasings(self):
        self.assertTrue(affirms(PUBLISH_CLAIM, "M02 已成功发布"))
        self.assertTrue(affirms(PUBLISH_CLAIM, "核对无误已发布"))
        self.assertFalse(affirms(PUBLISH_CLAIM, "是否已发布：否"))
        self.assertFalse(affirms(PUBLISH_CLAIM, "用户确认后才会发布成功"))
        self.assertTrue(affirms(SAVE_CLAIM, "草稿已写入"))

    def test_saved_draft_survives_later_rejected_revision(self):
        bad = ModelTurn("", [call("save_draft", entries=[{"material_id": "M02", "decision": "needs_info",
                                                          "suggested_slot": "", "risk_reasons": [], "pending_items": ["x"]}])])
        report, _, _ = self.run_script(M02_FLOW + [bad, ModelTurn("草稿已保存")])
        self.assertTrue(report["draft"]["saved"])  # 第一次保存成功的草稿仍在，不能说成“未保存”
        self.assertEqual(report["status"], "incomplete")
        self.assertIn("之后的修订未保存", report["status_reason"])
        self.assertEqual(report["guard_flags"], [])  # 草稿确实存在，不算虚报

    def test_blocking_after_save_marks_draft_stale(self):
        block = ModelTurn("", [call("block_material", material_id="M02", risk_summary="临时下架")])
        report, _, _ = self.run_script(M02_FLOW + [block, ModelTurn("完成")])
        self.assertEqual(report["status"], "incomplete")
        self.assertIn("已过期", report["status_reason"])
        self.assertTrue(report["draft"]["stale"])

    def test_unsaved_plan_is_not_ready_to_confirm(self):
        report, _, _ = self.run_script(M02_FLOW + [ModelTurn("保存失败。")], fault="fail_always")
        self.assertEqual(report["materials"][0]["decision"], "schedule")  # 方案保留供参考
        self.assertEqual(report["materials"][0]["confirm_state"], "not_saved")

    def test_unchecked_facts_are_null_not_clean(self):
        turns = [ModelTurn("", [call("get_material", material_id="M02")]), ModelTurn("先到这里")]
        report, _, _ = self.run_script(turns)
        facts = report["materials"][0]["tool_facts"]
        self.assertIsNone(facts["rule_hits"])  # 没查过 ≠ 查过没问题
        self.assertIsNone(facts["copyright_verified"])
        self.assertEqual(facts["copyright_declared"], "valid")

    def test_false_save_claim_is_flagged(self):
        report, _, ctx = self.run_script(M02_FLOW + [ModelTurn("草稿已保存。")], fault="fail_always")
        self.assertEqual(report["status"], "save_failed")
        self.assertFalse(report["draft"]["saved"])
        self.assertEqual(report["draft"]["error_code"], "STORAGE_READ_ONLY")
        self.assertTrue(any("声称草稿已保存" in f for f in report["guard_flags"]))
        self.assertFalse(ctx.drafts.path.exists())

    def test_finishing_without_save_is_incomplete(self):
        report, _, _ = self.run_script([ModelTurn("看起来都没问题。")])
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["draft"]["result"], "not_saved")

    def test_llm_error_returns_error_status(self):
        report, _, _ = self.run_script([LLMError("401 鉴权失败")])
        self.assertEqual(report["status"], "error")
        self.assertIn("401", report["status_reason"])

    def test_trace_records_args_basis_summary_and_next_action(self):
        report, _, _ = self.run_script(M02_FLOW + [ModelTurn("完成")])
        first = report["trace"][0]
        self.assertEqual(first["args"], {"material_id": "M02"})
        self.assertEqual(first["basis"], "测试")
        self.assertTrue(first["result_summary"])
        self.assertEqual(first["next_action"], "check_rules(M02)")
        self.assertEqual(report["trace"][-1]["next_action"], "结束，输出总结")

    def test_parallel_calls_share_next_round_action(self):
        turns = [ModelTurn("", [call("get_material", material_id="M02"), call("check_rules", material_id="M02")])] \
            + M02_FLOW[2:] + [ModelTurn("完成")]
        report, _, _ = self.run_script(turns)
        first, second = report["trace"][0], report["trace"][1]
        self.assertEqual(first["step"], second["step"])
        self.assertEqual(first["next_action"], "query_slots(M02)")
        self.assertEqual(second["next_action"], "query_slots(M02)")


if __name__ == "__main__":
    unittest.main()
