"""模型适配层：用假的 SDK 客户端验证消息拼装与解析（不联网，不需要安装 SDK）。"""
import json
import unittest
from types import SimpleNamespace as NS

from src.agent import run_agent
from src.llm import AnthropicLLM, LLMError, OpenAICompatLLM
from tests.helpers import TempDirMixin, item


class FakeCreate:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def anthropic_resp(blocks, stop="tool_use"):
    return NS(content=blocks, stop_reason=stop, stop_details=None)


class AnthropicAdapterTest(unittest.TestCase):
    def test_tool_use_round_trip(self):
        blocks = [NS(type="thinking", thinking=""), NS(type="text", text="先读取素材"),
                  NS(type="tool_use", id="tu_1", name="get_material", input={"material_id": "M01", "reason": "r"})]
        beta = FakeCreate([anthropic_resp(blocks)])
        llm = AnthropicLLM(model="claude-opus-5-5", effort="medium", fallbacks="default",
                           client=NS(beta=NS(messages=beta), messages=FakeCreate([])))
        llm.start("sys", "user", [{"name": "get_material", "description": "d", "parameters": {"type": "object"}}])
        turn = llm.next()
        sent = beta.calls[0]
        self.assertEqual(sent["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(sent["fallbacks"], "default")
        self.assertEqual(sent["output_config"], {"effort": "medium"})
        self.assertNotIn("temperature", sent)
        self.assertEqual(sent["tools"][0]["input_schema"], {"type": "object"})
        self.assertEqual((turn.tool_calls[0].id, turn.tool_calls[0].args["material_id"]), ("tu_1", "M01"))
        self.assertIs(llm.messages[-1]["content"], blocks)  # 原样回传（含 thinking 块）
        llm.add_tool_results([("tu_1", '{"ok": true}', False)])
        self.assertEqual(llm.messages[-1]["content"][0],
                         {"type": "tool_result", "tool_use_id": "tu_1", "content": '{"ok": true}', "is_error": False})

    def test_fallbacks_off_uses_plain_messages(self):
        plain = FakeCreate([anthropic_resp([NS(type="text", text="完成")], stop="end_turn")])
        llm = AnthropicLLM(fallbacks="off", client=NS(beta=NS(messages=FakeCreate([])), messages=plain))
        llm.start("sys", "user", [])
        self.assertEqual(llm.next().text, "完成")
        self.assertNotIn("fallbacks", plain.calls[0])

    def test_refusal_raises(self):
        llm = AnthropicLLM(fallbacks="off", client=NS(messages=FakeCreate([anthropic_resp([], stop="refusal")])))
        llm.start("sys", "user", [])
        with self.assertRaises(LLMError):
            llm.next()


def oa_resp(content=None, tool_calls=None, finish="tool_calls"):
    calls = [NS(id=cid, function=NS(name=name, arguments=args)) for cid, name, args in tool_calls or []]
    return NS(choices=[NS(finish_reason=finish, message=NS(content=content, tool_calls=calls or None))])


class OpenAICompatAdapterTest(TempDirMixin, unittest.TestCase):
    def test_parses_multiple_calls_and_bad_json(self):
        fake = FakeCreate([oa_resp(tool_calls=[("c1", "get_material", '{"material_id": "M01", "reason": "r"}'),
                                               ("c2", "check_rules", '{bad json')])])
        llm = OpenAICompatLLM(model="deepseek-chat", client=NS(chat=NS(completions=fake)))
        llm.start("sys", "user", [{"name": "get_material", "description": "d", "parameters": {"type": "object"}}])
        turn = llm.next()
        self.assertEqual(fake.calls[0]["tools"][0]["function"]["name"], "get_material")
        self.assertIsNone(turn.tool_calls[0].arg_error)
        self.assertIsNotNone(turn.tool_calls[1].arg_error)
        self.assertEqual([c["id"] for c in llm.messages[-1]["tool_calls"]], ["c1", "c2"])
        llm.add_tool_results([("c1", "{}", False), ("c2", "{}", True)])
        self.assertEqual([(m["role"], m["tool_call_id"]) for m in llm.messages[-2:]], [("tool", "c1"), ("tool", "c2")])

    def test_full_loop_through_adapter(self):
        save = {"entries": [{"material_id": "M02", "decision": "schedule", "suggested_slot": "2026-11-03 10:00",
                             "risk_reasons": [], "pending_items": []}], "reason": "提交"}
        script = [
            oa_resp(tool_calls=[("1", "get_material", '{"material_id": "M02", "reason": "读取"}'),
                                ("2", "check_rules", '{"material_id": "M02", "reason": "检查"}')]),
            oa_resp(tool_calls=[("3", "query_slots", json.dumps({"material_id": "M02", "channel": "app_home",
                                                                 "publish_time": "2026-11-03 10:00", "reason": "查时段"}))]),
            oa_resp(tool_calls=[("4", "save_draft", json.dumps(save, ensure_ascii=False))]),
            oa_resp(content="M02 已写入草稿，等待确认。", finish="stop"),
        ]
        ctx, _ = self.make_ctx([item("M02")])
        llm = OpenAICompatLLM(model="deepseek-chat", client=NS(chat=NS(completions=FakeCreate(script))))
        report = run_agent(ctx, llm)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["usage"]["tool_calls"], 4)
        self.assertEqual(report["trace"][0]["step"], report["trace"][1]["step"])  # 同一轮的并行调用

    def test_reasoning_content_is_passed_back(self):
        resp = oa_resp(tool_calls=[("c1", "get_material", '{"material_id": "M01", "reason": "r"}')])
        resp.choices[0].message.reasoning_content = "（思考内容）"
        llm = OpenAICompatLLM(client=NS(chat=NS(completions=FakeCreate([resp]))))
        llm.start("sys", "user", [])
        llm.next()
        self.assertEqual(llm.messages[-1]["reasoning_content"], "（思考内容）")

    def test_interrupted_or_malformed_responses_raise(self):
        for resp in (oa_resp(content="...", finish="content_filter"), "<html>502 Bad Gateway</html>", NS(choices=[])):
            llm = OpenAICompatLLM(client=NS(chat=NS(completions=FakeCreate([resp]))))
            llm.start("sys", "user", [])
            with self.assertRaises(LLMError):
                llm.next()

    def test_length_cutoff_raises(self):
        llm = OpenAICompatLLM(client=NS(chat=NS(completions=FakeCreate([oa_resp(content="...", finish="length")]))))
        llm.start("sys", "user", [])
        with self.assertRaises(LLMError):
            llm.next()


if __name__ == "__main__":
    unittest.main()
