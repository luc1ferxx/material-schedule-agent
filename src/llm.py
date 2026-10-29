"""模型接入。统一成 start / next / add_tool_results 三个方法，Agent 循环不关心具体厂商。

- AnthropicLLM：官方 anthropic SDK（Claude），默认 claude-opus-5-5。
- OpenAICompatLLM：官方 openai SDK + OpenAI 兼容接口（DeepSeek、通义千问、GLM、Kimi 等），默认 DeepSeek。
SDK 在构造时才导入：离线 Mock 和单元测试不需要安装任何第三方包。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict
    arg_error: str | None = None


@dataclass
class ModelTurn:
    text: str
    tool_calls: list = field(default_factory=list)
    stop_reason: str | None = None


class LLMError(RuntimeError):
    """模型调用失败（鉴权、网络、限流重试后仍失败、拒答、输出被截断等）。"""


def _sdk_errors(module: str, attr: str) -> tuple:
    try:
        return (getattr(__import__(module), attr),)
    except ImportError:
        return ()


class AnthropicLLM:
    def __init__(self, model: str | None = None, max_tokens: int = 16000, effort: str | None = None,
                 fallbacks: str | None = None, client=None):
        self.model = model or os.environ.get("ANTHROPIC_MODEL") or "claude-opus-5-5"
        self.max_tokens = max_tokens
        self.effort = effort if effort is not None else os.environ.get("ANTHROPIC_EFFORT", "medium")
        fallbacks = fallbacks if fallbacks is not None else os.environ.get("ANTHROPIC_FALLBACKS", "default")
        # 拒答时由服务端自动换模型重试；部分代理/中转不支持该 beta，可设 ANTHROPIC_FALLBACKS=off 关闭
        self.fallbacks = None if fallbacks in ("", "off") else fallbacks
        self._errors = _sdk_errors("anthropic", "AnthropicError")
        if client is None:
            try:
                import anthropic
            except ImportError:
                raise LLMError("未安装 anthropic SDK，请先 pip install -r requirements.txt") from None
            try:
                client = anthropic.Anthropic()  # 读取 ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / ant 登录配置 / ANTHROPIC_BASE_URL
            except anthropic.AnthropicError as exc:
                raise LLMError(f"初始化 Claude 客户端失败：{exc}") from None
            if all(getattr(client, attr, None) is None for attr in ("api_key", "auth_token", "credentials")):
                raise LLMError("缺少 Claude 凭据：请在 .env 中设置 ANTHROPIC_API_KEY（参考 .env.example）")
        self.client = client
        self.label = f"anthropic:{self.model}"

    def start(self, system: str, user: str, tools: list) -> None:
        self.system = system
        self.tools = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]
        self.messages = [{"role": "user", "content": user}]

    def next(self) -> ModelTurn:
        kwargs = dict(model=self.model, max_tokens=self.max_tokens, system=self.system,
                      tools=self.tools, messages=self.messages)
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        try:
            if self.fallbacks:
                resp = self.client.beta.messages.create(
                    **kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks=self.fallbacks)
            else:
                resp = self.client.messages.create(**kwargs)
        except self._errors as exc:
            raise LLMError(f"调用 Claude 失败：{type(exc).__name__}: {exc}") from exc
        if resp.stop_reason == "refusal":
            raise LLMError(f"模型拒绝了请求：{getattr(resp, 'stop_details', None)}")
        if resp.stop_reason == "max_tokens":
            raise LLMError("模型输出达到 max_tokens 被截断")
        # 原样追加 content（包括 thinking 块），对话历史只追加不改写
        self.messages.append({"role": "assistant", "content": resp.content})
        text = "".join(b.text for b in resp.content if b.type == "text")
        calls = []
        for block in resp.content:
            if block.type == "tool_use":
                ok = isinstance(block.input, dict)
                calls.append(ToolCall(block.id, block.name, block.input if ok else {}, None if ok else "input 不是对象"))
        return ModelTurn(text, calls, resp.stop_reason)

    def add_tool_results(self, results: list) -> None:
        # 一轮里的多个工具结果放在同一条 user 消息里返回
        self.messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": call_id, "content": content, "is_error": is_error}
            for call_id, content, is_error in results
        ]})


class OpenAICompatLLM:
    def __init__(self, model: str | None = None, base_url: str | None = None, api_key: str | None = None,
                 temperature: float | None = None, client=None):
        self.model = model or os.environ.get("OPENAI_MODEL") or "deepseek-v4-pro"
        self.temperature = temperature if temperature is not None else float(os.environ.get("OPENAI_TEMPERATURE", "0"))
        self._errors = _sdk_errors("openai", "OpenAIError")
        if client is None:
            api_key = api_key or os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise LLMError("缺少 OPENAI_API_KEY，请在 .env 中配置（参考 .env.example）")
            try:
                import openai
            except ImportError:
                raise LLMError("未安装 openai SDK，请先 pip install -r requirements.txt") from None
            base_url = base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.deepseek.com"
            client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=120)
        self.client = client
        self.label = f"openai-compatible:{self.model}"

    def start(self, system: str, user: str, tools: list) -> None:
        self.tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                         "parameters": t["parameters"]}} for t in tools]
        self.messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def next(self) -> ModelTurn:
        try:
            resp = self.client.chat.completions.create(
                model=self.model, messages=self.messages, tools=self.tools,
                tool_choice="auto", temperature=self.temperature)
        except self._errors as exc:
            raise LLMError(f"调用模型失败：{type(exc).__name__}: {exc}") from exc
        choices = getattr(resp, "choices", None)  # 地址配错时中转可能返回 200 + 非 JSON 页面
        if not choices or getattr(choices[0], "message", None) is None:
            raise LLMError(f"模型返回格式异常（请检查 OPENAI_BASE_URL）：{str(resp)[:200]}")
        choice = choices[0]
        msg = choice.message
        if choice.finish_reason == "length":
            raise LLMError("模型输出达到长度上限被截断")
        if choice.finish_reason not in ("stop", "tool_calls", "function_call", None) or getattr(msg, "refusal", None):
            raise LLMError(f"生成被中断或被过滤：finish_reason={choice.finish_reason}，refusal={getattr(msg, 'refusal', None)}")
        calls, raw_calls = [], []
        for tc in msg.tool_calls or []:
            arg_text = tc.function.arguments or "{}"
            try:
                args, err = json.loads(arg_text), None  # arguments 是 JSON 字符串，可能不合法
                if not isinstance(args, dict):
                    args, err = {}, "参数必须是 JSON 对象"
            except json.JSONDecodeError as exc:
                args, err = {}, str(exc)
            calls.append(ToolCall(tc.id, tc.function.name, args, err))
            raw_calls.append({"id": tc.id, "type": "function",
                              "function": {"name": tc.function.name, "arguments": arg_text}})
        assistant = {"role": "assistant", "content": msg.content or ("" if not raw_calls else None)}
        if raw_calls:
            assistant["tool_calls"] = raw_calls
        reasoning = getattr(msg, "reasoning_content", None)
        if reasoning:  # DeepSeek 思考模式：同一轮工具调用过程中需把 reasoning_content 原样带回（只回传，不写入运行记录）
            assistant["reasoning_content"] = reasoning
        self.messages.append(assistant)
        return ModelTurn(msg.content or "", calls, choice.finish_reason)

    def add_tool_results(self, results: list) -> None:
        for call_id, content, _is_error in results:
            self.messages.append({"role": "tool", "tool_call_id": call_id, "content": content})


def make_llm(provider: str):
    if provider == "mock":
        from .mock_llm import MockLLM
        return MockLLM()
    if provider == "anthropic":
        return AnthropicLLM()
    if provider == "openai":
        return OpenAICompatLLM()
    raise LLMError(f"未知 provider：{provider}（可选 mock / anthropic / openai）")
