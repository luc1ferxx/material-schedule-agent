"""对抗性代码评审确认的问题的回归测试：输入规范化、时段优先级、暂留管理、复核规则、草稿库健壮性。"""
import unittest
from unittest import mock

from src import run_examples
from src.llm import LLMError
from src.request import normalize_request
from src.stores import DraftStore
from tests.helpers import TempDirMixin, item


def entry(mid, decision, slot="", pending=None):
    return {"material_id": mid, "decision": decision, "suggested_slot": slot,
            "risk_reasons": [], "pending_items": pending or []}


def run(ex, tool, **args):
    args.setdefault("reason", "r")
    return ex.execute(tool, args)


def ready(ex, mid, channel="app_home", time=None):
    run(ex, "get_material", material_id=mid)
    run(ex, "check_rules", material_id=mid)
    if time:
        return run(ex, "query_slots", material_id=mid, channel=channel, publish_time=time).data


class NormalizationTest(TempDirMixin, unittest.TestCase):
    def test_non_canonical_request_time_is_normalized(self):
        a = normalize_request({"items": [item("M02", time="2026-11-3 10:00")]})
        b = normalize_request({"items": [item("M02", time="2026-11-03 10:00")]})
        self.assertEqual(a.items[0].publish_time, "2026-11-03 10:00")
        self.assertEqual(a.request_key, b.request_key)  # 同一时刻不同写法 = 同一请求

    def test_non_canonical_schedule_entry_still_occupies_slot(self):
        """评审手改 schedule.json 写成 '2026-11-3 19:00' 也必须被识别为占用。"""
        ctx, ex = self.make_ctx([item("M02", time="2026-11-03 19:00")], schedule_entries=[
            {"schedule_id": "S-X", "channel": " app_home ", "slot": "2026-11-3 19:00", "material_id": "M77", "title": "手改"}])
        data = run(ex, "query_slots", material_id="M02", channel="app_home", publish_time="2026-11-03 19:00").data
        self.assertFalse(data["requested_available"])
        self.assertIn("S-X", data["conflict"])

    def test_unparseable_schedule_is_a_config_error(self):
        with self.assertRaises(ValueError):
            self.make_ctx([item("M02")], schedule_entries=[{"channel": "app_home", "slot": "下午三点"}])

    def test_unknown_channel_and_past_time_are_missing_info(self):
        ctx, ex = self.make_ctx([item("M02", channel="APP_HOME"), item("M01", time="2026-10-01 10:00")])
        missing = {mid: run(ex, "get_material", material_id=mid).data["request_missing"] for mid in ("M02", "M01")}
        self.assertIn("未配置", missing["M02"][0])
        self.assertIn("已过期", missing["M01"][0])
        out = run(ex, "save_draft", entries=[entry("M02", "needs_info", pending=["请改为已配置渠道"]),
                                             entry("M01", "needs_info", pending=["请给出未来的发布时间"])])
        self.assertTrue(out.ok, out.summary)


class SlotPriorityTest(TempDirMixin, unittest.TestCase):
    def test_fixed_item_keeps_contested_slot_even_if_listed_second(self):
        ctx, ex = self.make_ctx([item("M01", time="2026-11-03 19:00"),
                                 item("M08", time="2026-11-03 19:00", rule="fixed")])
        m08 = ready(ex, "M08", time="2026-11-03 19:00")
        m01 = ready(ex, "M01", time="2026-11-03 19:00")
        self.assertTrue(m08["requested_available"])
        self.assertFalse(m01["requested_available"])
        self.assertIn("M08（硬性时间）", m01["conflict"])
        alt = m01["alternatives"][0]
        run(ex, "request_confirmation", material_id="M01", question="改期？", proposed_slot=alt)
        out = run(ex, "save_draft", entries=[entry("M01", "pending_confirmation", alt),
                                             entry("M08", "schedule", "2026-11-03 19:00")])
        self.assertTrue(out.ok, out.summary)

    def test_unschedulable_item_releases_its_requested_slot(self):
        ctx, ex = self.make_ctx([item("M05", time="2026-11-03 19:00"), item("M02", time="2026-11-03 19:00")])
        before = run(ex, "query_slots", material_id="M02", channel="app_home", publish_time="2026-11-03 19:00").data
        self.assertFalse(before["requested_available"])  # M05 靠前且还没查过，先按“可能要排”对待
        ready(ex, "M05")
        run(ex, "verify_copyright", material_id="M05")
        run(ex, "block_material", material_id="M05", risk_summary="版权失效")
        after = run(ex, "query_slots", material_id="M02", channel="app_home", publish_time="2026-11-03 19:00").data
        self.assertTrue(after["requested_available"])


    def test_two_entries_on_same_slot_are_rejected(self):
        """M01 已提议改期，不再占用 11:00，所以两条都能通过单条时段检查，只有草稿内撞车检查能拦下。"""
        ctx, ex = self.make_ctx([item("M01", time="2026-11-03 11:00"), item("M02", time="2026-11-03 11:00")])
        ready(ex, "M01", time="2026-11-03 11:00")
        ready(ex, "M02", time="2026-11-03 11:00")
        run(ex, "request_confirmation", material_id="M01", question="改期？", proposed_slot="2026-11-03 13:00")
        out = run(ex, "save_draft", entries=[entry("M01", "pending_confirmation", "2026-11-03 11:00"),
                                             entry("M02", "schedule", "2026-11-03 11:00")])
        self.assertFalse(out.ok)
        self.assertIn("的建议时段 2026-11-03 11:00 冲突", " ".join(out.data["problems"]))


class RunExamplesCliTest(unittest.TestCase):
    def test_missing_credentials_exit_2_without_traceback(self):
        with mock.patch("src.run_examples.load_dotenv"), \
                mock.patch("src.run_examples.make_llm", side_effect=LLMError("缺少 Key")):
            self.assertEqual(run_examples.main(["--provider", "openai"]), 2)


class HoldsTest(TempDirMixin, unittest.TestCase):
    def test_new_proposal_supersedes_old_one_and_releases_slot(self):
        ctx, ex = self.make_ctx([item("M01", time="2026-11-03 18:00"), item("M02", time="2026-11-03 11:00")])
        run(ex, "request_confirmation", material_id="M01", question="19 点？", proposed_slot="2026-11-03 19:00")
        run(ex, "request_confirmation", material_id="M01", question="17 点？", proposed_slot="2026-11-03 17:00")
        self.assertEqual([c["status"] for c in ctx.facts["M01"].confirmations], ["superseded", "awaiting_user"])
        self.assertIsNone(ctx.slot_conflict("app_home", "2026-11-03 19:00", "M02"))  # 19:00 已释放

    def test_superseded_proposal_cannot_justify_reschedule(self):
        ctx, ex = self.make_ctx([item("M01", time="2026-11-03 18:00")])
        ready(ex, "M01", time="2026-11-03 18:00")
        run(ex, "request_confirmation", material_id="M01", question="19 点？", proposed_slot="2026-11-03 19:00")
        run(ex, "request_confirmation", material_id="M01", question="17 点？", proposed_slot="2026-11-03 17:00")
        self.assertFalse(run(ex, "save_draft", entries=[entry("M01", "pending_confirmation", "2026-11-03 19:00")]).ok)
        self.assertTrue(run(ex, "save_draft", entries=[entry("M01", "pending_confirmation", "2026-11-03 17:00")]).ok)

    def test_block_cancels_open_confirmations(self):
        ctx, ex = self.make_ctx([item("M04", time="2026-11-03 14:00")])
        run(ex, "request_confirmation", material_id="M04", question="改文案？", proposed_slot="")
        run(ex, "block_material", material_id="M04", risk_summary="法务不同意")
        self.assertEqual([c["status"] for c in ctx.facts["M04"].confirmations], ["cancelled"])

    def test_cannot_propose_slot_for_unschedulable_material(self):
        ctx, ex = self.make_ctx([item("M03", time="2026-11-03 15:00")])
        run(ex, "get_material", material_id="M03")
        out = run(ex, "request_confirmation", material_id="M03", question="改期？", proposed_slot="2026-11-03 16:00")
        self.assertEqual(out.data["error_code"], "NOT_SCHEDULABLE")


class ReviewRuleTest(TempDirMixin, unittest.TestCase):
    def test_missing_info_cannot_be_disguised_as_blocked(self):
        ctx, ex = self.make_ctx([item("M03", time="2026-11-03 15:00")])
        run(ex, "get_material", material_id="M03")
        run(ex, "block_material", material_id="M03", risk_summary="缺图")
        out = run(ex, "save_draft", entries=[entry("M03", "blocked")])
        self.assertIn("needs_info", " ".join(out.data["problems"]))

    def test_license_not_covering_date_is_caught_without_verify_rule(self):
        ctx, ex = self.make_ctx([item("M02", time="2026-11-03 10:00")])
        ctx.store.licenses["LIC-002"] = {"status": "valid", "valid_until": "2026-10-31", "holder": "x"}
        ready(ex, "M02", time="2026-11-03 10:00")
        out = run(ex, "save_draft", entries=[entry("M02", "schedule", "2026-11-03 10:00")])
        self.assertIn("不覆盖发布日期", " ".join(out.data["problems"]))

    def test_pending_scope_lists_materials_before_saving(self):
        ctx, ex = self.make_ctx(None, scope="pending")
        early = run(ex, "save_draft", entries=[entry("M02", "schedule", "2026-11-03 10:00")])
        self.assertIn("list_pending_materials", early.data["problems"][0])
        listed = run(ex, "list_pending_materials").data
        self.assertEqual((listed["count"], len(ctx.request.items)), (8, 8))
        self.assertEqual(ctx.request.item("M08").time_rule, "fixed")
        self.assertEqual(ctx.request.item("M08").publish_time, "2026-11-03 20:00")


class DraftStoreRobustnessTest(TempDirMixin, unittest.TestCase):
    def test_corrupt_drafts_file_is_a_reported_save_failure(self):
        ctx, ex = self.make_ctx([item("M02")])
        ctx.drafts.path.write_text('{"drafts": []}', encoding="utf-8")
        ready(ex, "M02", time="2026-11-03 10:00")
        out = run(ex, "save_draft", entries=[entry("M02", "schedule", "2026-11-03 10:00")])
        self.assertEqual(out.data["error_code"], "IO_ERROR")
        self.assertTrue(ctx.save_attempts[-1]["validated"])  # 记为一次真实的保存失败，而不是“没调用 save_draft”

    def test_new_risk_fact_with_same_slot_updates_draft(self):
        store = DraftStore(self.tmp / "d.json")
        base = {"material_id": "M02", "decision": "pending_confirmation", "suggested_slot": "2026-11-03 10:00",
                "risk_facts": {"rule_hits": []}, "confirmations": []}
        store.save("k", "T", [base])
        out = store.save("k", "T", [dict(base, risk_facts={"rule_hits": ["R-MINOR-01(warn)"]})])
        self.assertEqual((out["result"], out["version"]), ("updated", 2))


if __name__ == "__main__":
    unittest.main()
