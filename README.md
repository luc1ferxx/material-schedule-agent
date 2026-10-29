# 素材审核与发布排期 Agent（项目题 1）

帮内容团队找出待处理素材、逐个审核，生成**无冲突、可确认**的发布排期草稿。
Agent 由模型驱动：模型选工具 → 执行 → 看结果 → 决定补查、换时段、请求确认、阻断或结束。
**只保存草稿，没有发布能力。** 草稿是否保存成功、哪些事项待确认，都以工具返回为准，不采信模型的自述。

| 项目 | 内容 |
|---|---|
| 题号 | 1 · 素材审核与发布排期 Agent |
| GitHub URL / commit SHA | TODO(候选人)：推送后填写 |
| 运行方式 | CLI（Python 3.10+；核心、离线 Mock 与全部测试零第三方依赖） |
| 模型 | OpenAI 兼容接口（官方 `openai` SDK，默认 DeepSeek `deepseek-v4-pro`）或 Claude（官方 `anthropic` SDK，默认 `claude-opus-5-5`）；无 Key 时用离线 Mock |
| 真实模型运行记录 | `deepseek-v4-pro` 与 `deepseek-flash` 各跑全部 12 个场景：[examples/real-deepseek-v4-pro](examples/real-deepseek-v4-pro/INDEX.md)、[examples/real-deepseek-flash](examples/real-deepseek-flash/INDEX.md) |
| 实际用时 / 未完成部分 | 约 2 小时（2026-10-29 10:40–12:40，与 Claude Code 协作，分工见 [04 AI 使用](docs/04-ai-usage.md)）。未做：交互式确认闭环、跨请求的时段暂留、并发写草稿加锁（见 [03 评估](docs/03-evaluation.md)「限制」） |

> 边界说明：`examples/outputs`、`examples/traces` 是**离线 Mock**（固定规则模拟模型）的输出，只验证流程与护栏，不证明模型决策效果；
> 真实模型的决策证据在 `examples/real-*` 目录。

## 快速开始（无需安装、无需密钥）

在仓库根目录执行：

```bash
python -m unittest discover -s tests -v
```

```bash
python -m src.run_examples
```

```bash
python -m src.main --input examples/inputs/slot_conflict.json --mock --reset-drafts --brief
```

- 第一条：全部单元/端到端测试（工具护栏、ReAct 循环、模型适配层、验收场景、**对已提交运行记录的不变量自检**）。实际输出见 [examples/test-results.txt](examples/test-results.txt)。
- 第二条：用离线 Mock 跑全部 12 个场景（14 次运行），重新生成 `examples/outputs/`（实际输出 JSON）、`examples/traces/`（可读运行记录）和索引。
- 第三条：单次运行。去掉 `--brief` 可看到完整 trace；`--output x.json`、`--trace-md x.md` 可落盘。

退出码：`0` 完成；`1` 未完成 / 保存失败 / 模型调用失败（结果仍以 JSON 输出）；`2` 输入或配置错误（含 `data/schedule.json` 格式错误、缺少模型凭据）。

## 接入真实模型

```bash
pip install -r requirements.txt
```

复制 `.env.example` 为 `.env` 并填入 Key（`.env` 已被 gitignore，不会提交）。然后：

```bash
python -m src.main --input examples/inputs/slot_conflict.json --provider openai --reset-drafts
```

```bash
python -m src.run_examples --provider openai
```

第二条把全部场景跑一遍，结果写入 `examples/real-<模型名>/`（模型名取自 `.env` 的 `OPENAI_MODEL`），并生成 `INDEX.md`；
加 `--only slot_conflict,rule_risk` 只跑部分场景（索引会合并更新）。Claude 用 `--provider anthropic`。

## 评审入口

| 验收点 | 输入 | 离线 Mock 记录 | 真实模型记录（v4-pro / flash） | 自动化测试 |
|---|---|---|---|---|
| 找出待处理素材（综合） | [pending_scope.json](examples/inputs/pending_scope.json) | [记录](examples/traces/pending_scope.md) | [v4-pro](examples/real-deepseek-v4-pro/traces/pending_scope.md) / [flash](examples/real-deepseek-flash/traces/pending_scope.md) | `test_pending_scope_finds_and_schedules_all_pending` |
| 正常排期 | [normal.json](examples/inputs/normal.json) | [记录](examples/traces/normal.md) | [v4-pro](examples/real-deepseek-v4-pro/traces/normal.md) / [flash](examples/real-deepseek-flash/traces/normal.md) | `test_normal_schedule` |
| 时段冲突（参考实例 M01） | [slot_conflict.json](examples/inputs/slot_conflict.json) | [记录](examples/traces/slot_conflict.md) | [v4-pro](examples/real-deepseek-v4-pro/traces/slot_conflict.md) / [flash](examples/real-deepseek-flash/traces/slot_conflict.md) | `test_slot_conflict_reference_case` |
| 硬性要求不擅改 | [fixed_conflict.json](examples/inputs/fixed_conflict.json) | [记录](examples/traces/fixed_conflict.md) | [v4-pro](examples/real-deepseek-v4-pro/traces/fixed_conflict.md) / [flash](examples/real-deepseek-flash/traces/fixed_conflict.md) | `test_fixed_time_is_not_moved` |
| 多素材争同一替代时段 | [competing_conflict.json](examples/inputs/competing_conflict.json) | [记录](examples/traces/competing_conflict.md) | [v4-pro](examples/real-deepseek-v4-pro/traces/competing_conflict.md) / [flash](examples/real-deepseek-flash/traces/competing_conflict.md) | `test_competing_materials_get_distinct_slots` |
| 素材信息缺失 | [missing_info.json](examples/inputs/missing_info.json) | [记录](examples/traces/missing_info.md) | [v4-pro](examples/real-deepseek-v4-pro/traces/missing_info.md) / [flash](examples/real-deepseek-flash/traces/missing_info.md) | `test_missing_info` |
| 规则风险（warn / verify / block） | [rule_risk.json](examples/inputs/rule_risk.json) | [记录](examples/traces/rule_risk.md) | [v4-pro](examples/real-deepseek-v4-pro/traces/rule_risk.md) / [flash](examples/real-deepseek-flash/traces/rule_risk.md) | `test_rule_risk` |
| 重复提交 | [duplicate_submit.json](examples/inputs/duplicate_submit.json) | [第 1 次](examples/traces/duplicate_submit.run1.md) · [第 2 次](examples/traces/duplicate_submit.run2.md) | [v4-pro](examples/real-deepseek-v4-pro/traces/duplicate_submit.run2.md) / [flash](examples/real-deepseek-flash/traces/duplicate_submit.run2.md) | `test_duplicate_submission_keeps_one_draft` |
| 更换占用时段后重提 | slot_conflict.json + [schedule_alt.json](data/schedule_alt.json) | [第 1 次](examples/traces/schedule_changed.run1.md) · [第 2 次](examples/traces/schedule_changed.run2.md) | [v4-pro](examples/real-deepseek-v4-pro/traces/schedule_changed.run2.md) / [flash](examples/real-deepseek-flash/traces/schedule_changed.run2.md) | `test_changed_schedule_resubmit_updates_same_draft` |
| 保存失败（不可重试） | [save_fail_always.json](examples/inputs/save_fail_always.json) | [记录](examples/traces/save_fail_always.md) | [v4-pro](examples/real-deepseek-v4-pro/traces/save_fail_always.md) / [flash](examples/real-deepseek-flash/traces/save_fail_always.md) | `test_save_failure_is_reported` |
| 保存失败（可重试） | [save_fail_once.json](examples/inputs/save_fail_once.json) | [记录](examples/traces/save_fail_once.md) | [v4-pro](examples/real-deepseek-v4-pro/traces/save_fail_once.md) / [flash](examples/real-deepseek-flash/traces/save_fail_once.md) | `test_retryable_save_failure_then_success` |
| 步数/调用上限 | normal.json + 工具调用上限 3 | [记录](examples/traces/tool_limit.md) | [v4-pro](examples/real-deepseek-v4-pro/traces/tool_limit.md) / [flash](examples/real-deepseek-flash/traces/tool_limit.md) | `test_tool_limit_incomplete` |

完整索引：[Mock](examples/README.md) · [v4-pro](examples/real-deepseek-v4-pro/INDEX.md) · [flash](examples/real-deepseek-flash/INDEX.md)。
`tests/test_records.py` 会逐个检查上述所有已提交记录：未发布、草稿状态与 save_draft 真实结果一致、硬性时间未改、改期都有确认、建议时段无冲突。

> `normal.json`、`save_fail_once.json`、`save_fail_always.json` 的素材与时间相同，是**同一个请求**（`simulate` 不参与幂等键）。
> 手动用 `src.main` 连续运行它们时请加 `--reset-drafts`，否则后跑的会得到 `duplicate_unchanged`——这正是防重复的预期行为。`run_examples` 已为每个场景单独使用草稿库。

### 自己动手改数据复测

已有排期、素材、规则都在 `data/` 下，每次运行现读（时间写成 `2026-11-3 19:00`、`2026-11-03T19:00` 也能识别；无法解析会以退出码 2 报错，不会被静默忽略）。例如“更换占用时段并重复提交”：

1. 先跑一次：`python -m src.main --input examples/inputs/slot_conflict.json --mock --reset-drafts --brief`
2. 编辑 `data/schedule.json`，新增一条占用 `app_home` `2026-11-03 19:00`（或直接用 `--schedule data/schedule_alt.json`）。
3. 不带 `--reset-drafts` 再跑一次：M01 的建议时段改为 17:00，`query_slots` 会说明“19:00 也被占用”，草稿 `result=updated`、`version=2`，
   `draft.changes` 列出差异，草稿库（`.runtime/drafts.json`）里仍只有一份。
4. 数据不变再跑一次：`result=duplicate_unchanged`，不会新增草稿。

## 输入与输出

输入（`examples/inputs/*.json`）两种形式：

```json
{
  "request_id": "REQ-1103-COMPETE",
  "as_of": "2026-10-29 09:00",
  "items": [
    {"material_id": "M01", "channel": "app_home", "publish_time": "2026-11-03 18:00", "time_rule": "preferred"},
    {"material_id": "M08", "channel": "app_home", "publish_time": "2026-11-03 20:00", "time_rule": "fixed"}
  ]
}
```

```json
{"request_id": "REQ-1103-PENDING", "as_of": "2026-10-29 09:00", "scope": "pending"}
```

- `time_rule`：`fixed` 为硬性发布时间（未经用户同意不得改）；`preferred` 为期望时间（可建议替代时段，但必须待确认）。
- `scope: "pending"`：不列素材，由 Agent 调用 `list_pending_materials` 找出待审核素材，按素材登记的 `requested_publish` 排期。
- `as_of`：当前时间，早于它的发布时间视为已过期（样例固定写死，保证任何时候运行结果一致；不填用系统时间）。
- `simulate.save_draft`：测试用故障注入，`fail_once`（可重试）/ `fail_always`（不可重试）。

输出要点：`status`（completed / incomplete / save_failed / error）、`draft`（是否保存、草稿 ID、版本、`changes`、失败原因、过期提示）、
`materials[]`（每个素材的审核结论、风险原因、`risk_facts`、要求与建议时段、待确认项、草稿状态、工具事实）、`pending_confirmations`（仍待用户回复的确认）、
`published`（恒为 false）、`guard_flags`（模型自述与工具事实不一致时的告警）、`inputs`（本次用到的请求/排期/草稿库文件）、
`trace`（每一步的工具、参数、返回摘要、决策依据、后续动作；超限未执行的调用也留痕）。

## 目录

```text
.
├── README.md
├── requirements.txt          # 核心零依赖；真实模型才需要 anthropic / openai
├── .env.example
├── src/
│   ├── main.py               # CLI 入口
│   ├── agent.py              # ReAct 循环、上限、以工具账本生成报告、声称检测
│   ├── tools.py              # 8 个业务工具 + 工具层护栏（时段优先级、暂留、save_draft 复核）
│   ├── stores.py             # 只读业务数据（规范化校验）+ 草稿库（幂等、版本历史、故障注入、原子写）
│   ├── llm.py                # OpenAI 兼容（DeepSeek 等）/ Claude 适配层
│   ├── mock_llm.py           # 离线 Mock（固定规则，仅验证流程）
│   ├── prompts.py            # 系统提示词
│   ├── request.py            # 输入校验、规范化、幂等键
│   ├── render.py             # Markdown 运行记录
│   └── run_examples.py       # 批量跑验收场景
├── tests/                    # unittest：工具、复核规则、循环、适配层、场景、运行记录自检
├── data/                     # 合成素材、规则、版权库、渠道、已有排期（含评审用变体）
├── examples/                 # 输入、Mock 输出、真实模型输出（real-*）、运行记录、测试结果
└── docs/                     # 01 需求 · 02 方案 · 03 评估 · 04 AI 使用 · 05 复盘
```

## 文档

| 文档 | 内容 |
|---|---|
| [01-requirements](docs/01-requirements.md) | 用户、目标、范围、成功标准 |
| [02-solution](docs/02-solution.md) | 调用流程、动态决策、护栏、技术取舍 |
| [03-evaluation](docs/03-evaluation.md) | 测试预期与实际结果（Mock + 两个真实模型）、评审发现、失败与限制 |
| [04-ai-usage](docs/04-ai-usage.md) | AI 辅助范围、个人修改与验证 |
| [05-retrospective](docs/05-retrospective.md) | 最难的问题、收获、下一步 |
