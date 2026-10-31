# 03 评估：测试预期、实际结果、失败与限制

## 验证范围

| 验证项 | 状态 | 证据 |
|---|---|---|
| 工具、护栏、幂等、保存失败、上限 | ✅ 确定性测试 | [test-results.txt](../examples/test-results.txt)：78 项全部通过（Python 3.12.1 与 3.10.0） |
| ReAct 循环机制（错误回传、上限、报告一致性、过期检测） | ✅ 脚本化假模型 | `tests/test_agent_loop.py` |
| 模型适配层消息拼装/解析 | ✅ 假 SDK 客户端（不联网） | `tests/test_providers.py` |
| 全部验收场景端到端（离线 Mock） | ✅ 12 个场景 / 14 次运行 | [examples/README.md](../examples/README.md) |
| **真实模型决策（DeepSeek）** | ✅ `deepseek-v4-pro`、`deepseek-flash` 各跑全部 12 个场景 / 14 次运行 | [v4-pro 索引](../examples/real-deepseek-v4-pro/INDEX.md)、[flash 索引](../examples/real-deepseek-flash/INDEX.md) |
| 已提交运行记录的关键不变量 | ✅ 每次跑测试都会逐个检查全部 42 份记录 | `tests/test_records.py` |
| 真实 Claude API 联调 | ❌ 未验证（没有 Claude Key） | 仅假客户端测试 |
| 真实模型的统计稳定性 | ⚠️ 修复后的代码上每个模型只跑了一轮全量 | 见「限制」 |

## 真实模型结果（DeepSeek，修复后代码）

每格为：状态 · 草稿结果 · 工具调用次数 / 模型轮数。三列的每个素材结论都一致满足预期，`guard_flags` 全部为空（没有声称发布、没有虚报保存）。

| 场景 | 预期要点 | deepseek-v4-pro | deepseek-flash | 离线 Mock |
|---|---|---|---|---|
| [pending_scope](../examples/inputs/pending_scope.json) | 先 `list_pending_materials`，8 个待审素材各得结论：M01 改期待确认、M02/M07 排期、M03 缺信息、M04 风险待确认、M05/M09 阻断、M08 硬性时间不改 | completed · created · 29/8 | completed · created · 30/9 | completed · created · 29/30 |
| [normal](../examples/inputs/normal.json) | M02 10:00 排期；M07 verify→补查 valid→15:00 排期 | completed · created · 8/6 | completed · created · 8/6 | completed · created · 8/9 |
| [slot_conflict](../examples/inputs/slot_conflict.json) | 参考实例：M01 18:00 被占 → 建议 19:00、待确认 | completed · created · 5/6 | completed · created · 5/6 | completed · created · 5/6 |
| [fixed_conflict](../examples/inputs/fixed_conflict.json) | M08 硬性 20:00 被占 → 建议时段留空，只提方案 | completed · created · 5/6 | completed · created · 5/6 | completed · created · 5/6 |
| [competing_conflict](../examples/inputs/competing_conflict.json) | M01 与 M08 的建议/暂留时段互不冲突，M08 不改 | completed · created · 11/9（**复核拒绝 1 次后修正**） | completed · created · 10/8 | completed · created · 9/10 |
| [missing_info](../examples/inputs/missing_info.json) | M03 缺字段、M99 不存在、M02 缺时间 → 全部 needs_info | completed · created · 4/3 | completed · created · 4/3 | completed · created · 4/5 |
| [rule_risk](../examples/inputs/rule_risk.json) | M04 warn→待确认；M05 verify→expired→阻断；M09 block→阻断 | completed · created · 12/5 | completed · created · 12/6 | completed · created · 12/13 |
| [duplicate_submit](../examples/inputs/duplicate_submit.json) 第 1 / 2 次 | 第 2 次 `duplicate_unchanged`、同一草稿；M06 重复；请求内重复条目合并 | created → **duplicate_unchanged** | created → **duplicate_unchanged** | created → duplicate_unchanged |
| schedule_changed 第 1 / 2 次 | 换成 [schedule_alt.json](../data/schedule_alt.json)（19:00 也被占）后重提 → M01 改建议 17:00，同一草稿 v2 | 19:00 → **17:00，updated v2** | 19:00 → **17:00，updated v2** | 19:00 → 17:00，updated v2 |
| [save_fail_always](../examples/inputs/save_fail_always.json) | 不可重试失败 → 不重试、如实报告 `save_failed` | save_failed · 1 次尝试 | save_failed · 1 次尝试 | save_failed · 1 次尝试 |
| [save_fail_once](../examples/inputs/save_fail_once.json) | 可重试失败 → 重试一次 → 保存成功 | completed · 2 次尝试 | completed · 2 次尝试 | completed · 2 次尝试 |
| tool_limit | 工具调用上限 3 → `incomplete`，超限调用留痕 | incomplete · not_saved | incomplete · not_saved | incomplete · not_saved |

真实模型普遍一轮并行发出多个调用（如 pending_scope 中 flash 单轮最多 8 个），所以模型轮数明显少于 Mock（Mock 每轮只调一个工具）。

## 模型根据不同工具结果调整动作（题目要求的运行记录）

以下均来自真实模型记录，“决策依据”是模型自己填写的 reason：

1. **复核拒绝 → 模型修正**（[v4-pro competing_conflict](../examples/real-deepseek-v4-pro/traces/competing_conflict.md)）：模型第一次把硬性素材 M08 的建议时段写成替代时段 19:00，
   `save_draft` 返回“M08 的发布时间 2026-11-03 20:00 是硬性要求，未经用户同意不得改为 2026-11-03 19:00；替代方案只能放在待确认事项里，suggested_slot 留空”；
   下一轮模型依据“修正 M08 硬性时间冲突条目：suggested_slot 留空，替代方案仅放入待确认事项”重新提交并保存成功。护栏拦下了一次真实的越界。
2. **同一补查工具、不同结果 → 不同动作**：`verify_copyright` 对 M07 返回 valid → 模型继续 `query_slots` 并排期；对 M05 返回 expired → 模型 `block_material`
   （[v4-pro rule_risk](../examples/real-deepseek-v4-pro/traces/rule_risk.md)、[flash normal](../examples/real-deepseek-flash/traces/normal.md)）。
3. **同一保存失败、不同 retryable → 不同动作**：`retryable=true` → 模型重试一次并成功（[save_fail_once](../examples/real-deepseek-flash/traces/save_fail_once.md)）；
   `retryable=false` → 模型停止并在总结里写明失败原因（[save_fail_always](../examples/real-deepseek-v4-pro/traces/save_fail_always.md)）。
4. **同一请求、不同已有排期 → 不同方案**：schedule_changed 第 2 次时 `query_slots` 返回“更近的时段也不可用：19:00（已被已有排期 S-1103-07《临时插播：平台活动》占用）”，
   模型改提 17:00，`save_draft` 返回 `updated` 及 `changes`（[v4-pro run2](../examples/real-deepseek-v4-pro/traces/schedule_changed.run2.md)）。
5. **有依赖的调用分轮**：competing_conflict 中 v4-pro 先为 M08 登记 19:00，看到“本次请求内暂留 2026-11-03 19:00（未写入排期）”后重新查询 M01，结果写明“19:00（已提议给本次请求中的 M08）”，再为 M01 选 17:00。

## 自动化测试覆盖（78 项）

| 文件 | 数量 | 覆盖 |
|---|---|---|
| `test_tools.py` | 21 | 字段缺失/不存在/请求缺时间；规则三级；时长上限规则（R-DUR-01）；版权 valid/expired；替代时段排序与排除；不能提议已占用时段；未知工具与坏参数；硬性时间不可改；改期须确认；占用拒绝；有风险不能直接排期；每素材一条；needs_info 需有依据；幂等（措辞不同不算变化、方案变化升版本）；fail_always 不写文件；fail_once 重试成功；保存时现读最新排期 |
| `test_review_fixes.py` | 17 | 代码评审和文档核查确认问题的回归：草稿内撞车拒绝、`run_examples` 缺凭据退出码 2、时间与排期规范化、排期文件写坏报错、未配置渠道与过期时间算缺信息、硬性优先的时段争用、不可排期素材释放时段、新提议替换旧提议、阻断作废确认、不可排期素材不能提议时段、缺信息不能伪装成阻断、授权覆盖日期复核、pending 模式须先列出素材、草稿库损坏如实报失败、新风险触发升版本 |
| `test_agent_loop.py` | 16 | 正常完成；轮数上限；工具调用上限及超限留痕；工具错误回传后继续；声称发布/保存的检测（含否定、疑问、条件、Markdown 写法）；保存失败不算就绪；未查过的事实为 null；保存后修订失败仍报告已保存草稿；保存后阻断判定草稿过期；未保存就结束；模型调用异常；trace 字段；并行调用的后续动作 |
| `test_providers.py` | 8 | Claude：tool_use 解析、tool_result 格式、content 原样回传、fallbacks/effort 参数、拒答；OpenAI 兼容：多工具调用、坏 JSON 参数、reasoning_content 回传、中断/非 JSON 响应、经适配层跑通完整循环、长度截断 |
| `test_scenarios.py` | 14 | 12 个场景端到端（Mock）+ 重复素材未查规则时显示为 null + 评审改占用时段后数据驱动生效 |
| `test_records.py` | 2 | 对 `examples/` 下全部 42 份已提交记录（Mock 14 + 两个真实模型各 14）检查不变量，包括不可排期素材不能有建议时段 |

## 候选人手动复测

2026-10-31 候选人按步骤手动做了一次“更换占用时段并重复提交”（离线 Mock，只验证流程）：先运行 `slot_conflict`，M01 建议 19:00，草稿 v1；
再手动在 `data/schedule.json` 加入占用 `app_home 2026-11-03 19:00` 的排期后重提，M01 建议改为 17:00，同一草稿升为 v2，草稿库里只有一份；数据不变再提交一次，看到 `duplicate_unchanged`（候选人自述，这一步不写文件，没有留痕）；之后还原了排期文件。
当时生成的草稿库文件：[manual-check/drafts.json](../examples/manual-check/drafts.json)（`history` 里能看到 v1 的 19:00）。

## 对抗性评审：发现与处理

做了三轮多智能体评审，详见 [04 AI 使用](04-ai-usage.md)。每条发现都由独立“质疑者”尝试推翻：重要级由 3 名质疑者投票，多数推不翻才确认；次要发现只由 1 名质疑者复核，推不翻即确认（前两轮确认的 62 条里有 46 条属于这一类）。

- **运行记录审计**（第一轮真实记录）：26 条记录没有违反发布、保存、硬性时间、改期确认、时段冲突、结论与事实一致这几条不变量（审计判定 16 条 pass、10 条 pass_with_issues、0 条 fail，其中 3 条在依据质量或总结准确性上有问题）；确认 21 条次要问题（如“暂留”被模型说成“已预留”、未查过的规则显示为“无风险”、
  保存失败时条目仍显示“可直接确认”、超限调用不留痕）。
- **代码评审**：确认 41 条（不同角度有重复），其中“重要”级包括：时段争用只看请求顺序导致硬性素材保不住时间（会拒绝正确方案）；时间写法不规范时已有排期占用被漏判；
  保存成功后又修订失败被误报“未保存”；方案签名忽略新风险；“找出待处理素材”未被演示。
- **处理情况**（不是每条都彻底解决）：
  - 代码和报告类问题已改代码，多数补了回归测试（`test_review_fixes.py` 等）；少数只手动验证过，例如缺少 Claude 凭据时的报错。
  - 模型措辞类问题（如总结写错渠道、把暂留说成已预留）只补充了提示词和工具说明，没有程序保证。
  - warn 级风险目前任意一条待确认都能通过复核，不要求确认内容提到这条风险；规则命中事实会写入草稿的 `risk_facts`。
- 修复后重新生成了全部 Mock 与真实模型记录（本文表格即最终结果）。之后真实模型记录没有重跑；代码只追加了时长上限规则 R-DUR-01（现有素材最长 90 秒，不会触发）、`run_examples` 缺凭据的错误处理和几项测试，不影响表格里的结果。
- **文档与最终记录核查**（修复之后）：逐条核对 README、docs 和 28 份最终真实记录，确认 40 条，没有严重级，重要级集中在文档说法过头（如过期检测和 `guard_flags` 的范围）。已按事实改写文档，并补了草稿内撞车、block 级规则的测试和 `run_examples` 缺凭据的处理。28 份记录都没有声称已发布、谎报保存、擅改硬性时间、时段冲突或结论与工具事实不符；发现的是总结文字问题，见「限制」第 3 条。

## 失败与限制

1. **修复后的代码上真实模型只跑了一轮全量**：两个模型各 14 次运行全部符合预期，但没有重复多次统计稳定性。最终记录里同一模型、同一输入的重复运行调用数相同，不同模型之间有差异（pending_scope 29 与 30、competing_conflict 11 与 10）；修复前的第一轮（记录已被替换）里见过 temperature=0 下调用数不同，例如 v4-pro 的 duplicate_submit 第 1 次多调了一次 `list_pending_materials`。
2. **复核偏严的代价**：护栏会拒绝与事实不符的草稿，模型需要多改一轮（v4-pro 在 competing_conflict 中被拒 1 次后修正）；极端情况下可能触发上限返回 `incomplete`——这是有意的：宁可未完成，也不保存错误草稿。
3. **模型措辞不做语义校验**：`risk_reasons` / `pending_items` / 总结是模型写的文字，程序只校验结论与事实一致；工具事实另存于 `risk_facts`、`tool_facts`。
   例如最终记录里 flash 的 pending_scope 总结把 M07 写成“规则无命中”，而实际命中过 verify 规则（已补查为 valid），这类措辞偏差不会被拦下。
   再如 flash 的 pending_scope 总结把 17:00 同时列为 M01 的备选和 M08 的提议，两个模型的 competing_conflict 总结也把已提议给 M01 的 17:00 列为 M08 的替代时段：这些是查询当时的结果，之后的暂留没有反映到文字里；建议时段和暂留本身没有撞车。
   “已发布/已保存”声称检测是规则级的，能处理否定、疑问、条件和 Markdown 写法，但不保证覆盖所有表达。
4. **跨请求不互相约束**：`request_confirmation` 的暂留只在本次请求内有效；两个不同请求的待确认草稿可能建议同一时段（确认闭环未实现）。
5. **单进程、无锁**：草稿库是 JSON 文件，未处理多进程并发写。
6. **时段模型简化**：只支持整点、按渠道互斥；替代时段只在要求当天内找（当天无空位时工具只返回“无”；离线 Mock 会请用户改日，真实模型没有对应的提示词规则，也未实测）；没有“同渠道最小间隔”“同类素材错峰”等规则。
7. **Claude 适配层未经真实 API 联调**。
