"""工具与工具层护栏：规则、补查、时段、确认、草稿复核、幂等、保存失败。"""
import json
import unittest

from tests.helpers import TempDirMixin, item


def entry(mid, decision, slot="", risks=None, pending=None):
    return {"material_id": mid, "decision": decision, "suggested_slot": slot,
            "risk_reasons": risks or [], "pending_items": pending or []}


class ReadToolsTest(TempDirMixin, unittest.TestCase):
    def test_missing_fields_and_not_found(self):
        ctx, ex = self.make_ctx([item("M03"), item("M99")])
        m03 = ex.execute("get_material", {"material_id": "M03", "reason": "r"}).data
        self.assertEqual(set(m03["missing_fields"]), {"image_url", "copyright"})
        m99 = ex.execute("get_material", {"material_id": "M99", "reason": "r"}).data
        self.assertFalse(m99["found"])

    def test_request_missing_publish_time_is_reported(self):
        ctx, ex = self.make_ctx([{"material_id": "M02", "channel": "douyin"}])
        data = ex.execute("get_material", {"material_id": "M02", "reason": "r"}).data
        self.assertTrue(any("publish_time" in m for m in data["request_missing"]))

    def test_rule_levels(self):
        ctx, ex = self.make_ctx([item("M01"), item("M04"), item("M05")])
        level = lambda mid: ex.execute("check_rules", {"material_id": mid, "reason": "r"}).data["highest_level"]
        self.assertEqual(level("M01"), "none")
        self.assertEqual(level("M04"), "warn")
        self.assertEqual(level("M05"), "verify")

    def test_duration_over_limit_is_warn(self):
        ctx, ex = self.make_ctx([item("M02")])
        ctx.store.materials["M02"]["duration_sec"] = 150
        hits = ex.execute("check_rules", {"material_id": "M02", "reason": "r"}).data["hits"]
        self.assertIn("R-DUR-01", [h["rule_id"] for h in hits])
        self.assertEqual(next(h["level"] for h in hits if h["rule_id"] == "R-DUR-01"), "warn")

    def test_verify_copyright_valid_vs_expired(self):
        ctx, ex = self.make_ctx([item("M07"), item("M05")])
        self.assertEqual(ex.execute("verify_copyright", {"material_id": "M07", "reason": "r"}).data["status"], "valid")
        self.assertEqual(ex.execute("verify_copyright", {"material_id": "M05", "reason": "r"}).data["status"], "expired")

    def test_slot_conflict_prefers_later_alternative(self):
        ctx, ex = self.make_ctx([item("M01", time="2026-11-03 18:00")])
        data = ex.execute("query_slots", {"material_id": "M01", "channel": "app_home",
                                          "publish_time": "2026-11-03 18:00", "reason": "r"}).data
        self.assertFalse(data["requested_available"])
        self.assertIn("S-1103-02", data["conflict"])
        self.assertEqual(data["alternatives"][0], "2026-11-03 19:00")

    def test_alternatives_exclude_slots_proposed_to_other_material(self):
        ctx, ex = self.make_ctx([item("M01", time="2026-11-03 18:00"), item("M08", time="2026-11-03 20:00", rule="fixed")])
        ex.execute("request_confirmation", {"material_id": "M01", "question": "改到 19:00？",
                                            "proposed_slot": "2026-11-03 19:00", "reason": "r"})
        data = ex.execute("query_slots", {"material_id": "M08", "channel": "app_home",
                                          "publish_time": "2026-11-03 20:00", "reason": "r"}).data
        self.assertNotIn("2026-11-03 19:00", data["alternatives"])

    def test_cannot_propose_occupied_slot(self):
        ctx, ex = self.make_ctx([item("M01", time="2026-11-03 18:00")])
        out = ex.execute("request_confirmation", {"material_id": "M01", "question": "q",
                                                  "proposed_slot": "2026-11-03 20:00", "reason": "r"})
        self.assertFalse(out.ok)
        self.assertEqual(out.data["error_code"], "SLOT_UNAVAILABLE")
        same = ex.execute("request_confirmation", {"material_id": "M01", "question": "q",
                                                   "proposed_slot": "2026-11-03 18:00", "reason": "r"})
        self.assertIsNone(same.data["proposed_slot"])  # 与要求时间相同不算替代时段

    def test_unknown_tool_and_bad_arguments(self):
        ctx, ex = self.make_ctx([item("M01")])
        self.assertEqual(ex.execute("publish_now", {}).data["error_code"], "UNKNOWN_TOOL")
        self.assertEqual(ex.execute("get_material", {"reason": "r"}).data["error_code"], "BAD_ARGUMENTS")
        self.assertTrue(ex.execute("get_material", {"material_id": "M01"}).ok)  # 漏填 reason 不拦截
        self.assertEqual(ex.execute("get_material", {}, arg_error="Expecting value").data["error_code"], "BAD_ARGUMENTS")


class SaveDraftReviewTest(TempDirMixin, unittest.TestCase):
    def _facts(self, ex, mid, channel, time):
        ex.execute("get_material", {"material_id": mid, "reason": "r"})
        ex.execute("check_rules", {"material_id": mid, "reason": "r"})
        return ex.execute("query_slots", {"material_id": mid, "channel": channel, "publish_time": time, "reason": "r"}).data

    def problems(self, out):
        self.assertFalse(out.ok)
        self.assertEqual(out.data["error_code"], "VALIDATION_FAILED")
        return " ".join(out.data["problems"])

    def test_fixed_time_cannot_be_changed_without_consent(self):
        ctx, ex = self.make_ctx([item("M08", time="2026-11-03 20:00", rule="fixed")])
        self._facts(ex, "M08", "app_home", "2026-11-03 20:00")
        ex.execute("request_confirmation", {"material_id": "M08", "question": "q",
                                            "proposed_slot": "2026-11-03 22:00", "reason": "r"})
        out = ex.execute("save_draft", {"entries": [entry("M08", "pending_confirmation", "2026-11-03 22:00")], "reason": "r"})
        self.assertIn("硬性要求", self.problems(out))
        ok = ex.execute("save_draft", {"entries": [entry("M08", "pending_confirmation", "")], "reason": "r"})
        self.assertTrue(ok.ok)

    def test_reschedule_requires_confirmation(self):
        ctx, ex = self.make_ctx([item("M01", time="2026-11-03 18:00")])
        self._facts(ex, "M01", "app_home", "2026-11-03 18:00")
        out = ex.execute("save_draft", {"entries": [entry("M01", "schedule", "2026-11-03 19:00")], "reason": "r"})
        self.assertIn("必须等于要求时间", self.problems(out))
        out = ex.execute("save_draft", {"entries": [entry("M01", "pending_confirmation", "2026-11-03 19:00")], "reason": "r"})
        self.assertIn("request_confirmation", self.problems(out))

    def test_occupied_or_duplicated_slots_rejected(self):
        ctx, ex = self.make_ctx([item("M01", time="2026-11-03 18:00"), item("M02", time="2026-11-03 10:00")])
        self._facts(ex, "M01", "app_home", "2026-11-03 18:00")
        self._facts(ex, "M02", "app_home", "2026-11-03 10:00")
        ex.execute("request_confirmation", {"material_id": "M01", "question": "q", "proposed_slot": "2026-11-03 19:00", "reason": "r"})
        out = ex.execute("save_draft", {"entries": [entry("M01", "pending_confirmation", "2026-11-03 18:00"),
                                                    entry("M02", "schedule", "2026-11-03 10:00")], "reason": "r"})
        self.assertIn("已被已有排期", self.problems(out))

    def test_risky_material_cannot_be_scheduled_directly(self):
        ctx, ex = self.make_ctx([item("M04", time="2026-11-03 14:00"), item("M05", time="2026-11-03 16:00")])
        self._facts(ex, "M04", "app_home", "2026-11-03 14:00")
        ex.execute("get_material", {"material_id": "M05", "reason": "r"})
        ex.execute("check_rules", {"material_id": "M05", "reason": "r"})
        out = ex.execute("save_draft", {"entries": [entry("M04", "schedule", "2026-11-03 14:00"),
                                                    entry("M05", "schedule", "2026-11-03 16:00")], "reason": "r"})
        text = self.problems(out)
        self.assertIn("warn", text)
        self.assertIn("verify_copyright", text)

    def test_every_material_needs_exactly_one_entry(self):
        ctx, ex = self.make_ctx([item("M01"), item("M02", time="2026-11-03 11:00")])
        ex.execute("get_material", {"material_id": "M01", "reason": "r"})
        out = ex.execute("save_draft", {"entries": [entry("M01", "needs_info", pending=["x"]),
                                                    entry("M01", "needs_info", pending=["x"])], "reason": "r"})
        text = self.problems(out)
        self.assertIn("多条记录", text)
        self.assertIn("M02", text)

    def test_needs_info_requires_evidence(self):
        ctx, ex = self.make_ctx([item("M02")])
        ex.execute("get_material", {"material_id": "M02", "reason": "r"})
        out = ex.execute("save_draft", {"entries": [entry("M02", "needs_info", pending=["x"])], "reason": "r"})
        self.assertIn("信息完整", self.problems(out))


class DraftStoreTest(TempDirMixin, unittest.TestCase):
    def _ready(self, fault="none", schedule_entries=None):
        ctx, ex = self.make_ctx([item("M02")], fault=fault, schedule_entries=schedule_entries)
        for tool in ("get_material", "check_rules"):
            ex.execute(tool, {"material_id": "M02", "reason": "r"})
        ex.execute("query_slots", {"material_id": "M02", "channel": "app_home", "publish_time": "2026-11-03 10:00", "reason": "r"})
        return ctx, ex

    def _save(self, ex, slot="2026-11-03 10:00", risks=None):
        return ex.execute("save_draft", {"entries": [entry("M02", "schedule", slot, risks)], "reason": "r"})

    def test_same_request_saved_twice_keeps_one_draft(self):
        ctx, ex = self._ready()
        first, second = self._save(ex), self._save(ex)
        self.assertEqual(first.data["result"], "created")
        self.assertEqual(second.data["result"], "duplicate_unchanged")
        self.assertEqual(first.data["draft_id"], second.data["draft_id"])
        self.assertEqual(ctx.drafts.count(), 1)

    def test_reworded_same_plan_is_duplicate(self):
        """真实模型每次措辞不同：方案（结论/时段/确认状态）不变就视为重复提交，保留原草稿。"""
        ctx, ex = self._ready()
        self._save(ex, risks=["无风险"])
        again = self._save(ex, risks=["经检查无规则风险"])
        self.assertEqual((again.data["result"], again.data["version"]), ("duplicate_unchanged", 1))
        self.assertEqual(ctx.drafts.get(ctx.request.request_key)["entries"][0]["risk_reasons"], ["无风险"])

    def test_changed_plan_for_same_request_updates_in_place(self):
        ctx, _ = self._ready()
        base = {"material_id": "M02", "decision": "schedule", "channel": "app_home",
                "requested_slot": "2026-11-03 10:00", "time_rule": "preferred",
                "suggested_slot": "2026-11-03 10:00", "confirm_state": "ready_to_confirm", "confirmations": []}
        moved = dict(base, decision="pending_confirmation", suggested_slot="2026-11-03 11:00",
                     confirm_state="awaiting_user_decision",
                     confirmations=[{"proposed_slot": "2026-11-03 11:00"}])
        ctx.drafts.save(ctx.request.request_key, "T", [base])
        updated = ctx.drafts.save(ctx.request.request_key, "T", [moved])
        self.assertEqual((updated["result"], updated["version"]), ("updated", 2))
        self.assertEqual(ctx.drafts.count(), 1)

    def test_fail_always_reports_failure_and_writes_nothing(self):
        ctx, ex = self._ready(fault="fail_always")
        out = self._save(ex)
        self.assertFalse(out.ok)
        self.assertEqual(out.data["error_code"], "STORAGE_READ_ONLY")
        self.assertFalse(out.data["retryable"])
        self.assertFalse(ctx.drafts.path.exists())

    def test_fail_once_then_retry_succeeds(self):
        ctx, ex = self._ready(fault="fail_once")
        first, second = self._save(ex), self._save(ex)
        self.assertEqual((first.ok, first.data["retryable"]), (False, True))
        self.assertTrue(second.ok)
        self.assertEqual(ctx.drafts.count(), 1)

    def test_save_rechecks_latest_schedule(self):
        """排期在查询后被别人占用：保存时现读排期并拒绝，而不是用过期的查询结果。"""
        ctx, ex = self._ready()
        schedule_path = self.tmp / "schedule.json"
        schedule_path.write_text(json.dumps({"entries": [{"schedule_id": "S-NEW", "channel": "app_home",
                                                          "slot": "2026-11-03 10:00", "material_id": "M77",
                                                          "title": "新插入"}]}), encoding="utf-8")
        ctx.store.schedule_path = schedule_path
        out = self._save(ex)
        self.assertFalse(out.ok)
        self.assertIn("S-NEW", " ".join(out.data["problems"]))


if __name__ == "__main__":
    unittest.main()
