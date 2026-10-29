# 03 评估：测试预期、实际结果、失败与限制

## 验证范围

| 验证项 | 状态 | 证据 |
|---|---|---|
| 工具、护栏、幂等、保存失败、上限 | ✅ 确定性测试 | [test-results.txt](../examples/test-results.txt)：76 项全部通过（Python 3.12.1 与 3.10.0） |
| ReAct 循环机制（错误回传、上限、报告一致性、过期检测） | ✅ 脚本化假模型 | `tests/test_agent_loop.py` |
| 模型适配层消息拼装/解析 | ✅ 假 SDK 客户端（不联网） | `tests/test_providers.py` |
| 全部验收场景端到端（离线 Mock） | ✅ 12 个场景 / 14 次运行 | [examples/README.md](../examples/README.md) |
| **真实模型决策（DeepSeek）** | ✅ `deepseek-v4-pro`、`deepseek-flash` 各跑全部 12 个场景 / 14 次运行 | [v4-pro 索引](../examples/real-deepseek-v4-pro/INDEX.md)、[flash 索引](../examples/real-deepseek-flash/INDEX.md) |
| 已提交运行记录的关键不变量 | ✅ 每次跑测试都会逐个检查全部 42 份记录 | `tests/test_records.py` |
| 真实 Claude API 联调 | ❌ 未验证（没有 Claude Key） | 仅假客户端测试 |
| 真实模型的统计稳定性 | ⚠️ 每个模型只跑了一轮全量 | 见「限制」 |

## 真实模型结果（DeepSeek，最终代码）

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
   `save_draft` 返回“M08 的发布时间 2026-11-03 20:00 是硬性要求，未经用户同意不得改为 19:00……suggested_slot 留空”；
   下一轮模型依据“修正 M08 硬性时间冲突条目：suggested_slot 留空，替代方案仅放入待确认事项”重新提交并保存成功。护栏拦下了一次真实的越界。
2. **同一补查工具、不同结果 → 不同动作**：`verify_copyright` 对 M07 返回 valid → 模型继续 `query_slots` 并排期；对 M05 返回 expired → 模型 `block_material`
   （[v4-pro rule_risk](../examples/real-deepseek-v4-pro/traces/rule_risk.md)、[flash normal](../examples/real-deepseek-flash/traces/normal.md)）。
3. **同一保存失败、不同 retryable → 不同动作**：`retryable=true` → 模型重试一次并成功（[save_fail_once](../examples/real-deepseek-flash/traces/save_fail_once.md)）；
   `retryable=false` → 模型停止并在总结里写明失败原因（[save_fail_always](../examples/real-deepseek-v4-pro/traces/save_fail_always.md)）。
4. **同一请求、不同已有排期 → 不同方案**：schedule_changed 第 2 次时 `query_slots` 返回“更近的时段也不可用：19:00（已被已有排期 S-1103-07 占用）”，
   模型改提 17:00，`save_draft` 返回 `updated` 及 `changes`（[v4-pro run2](../examples/real-deepseek-v4-pro/traces/schedule_changed.run2.md)）。
5. **有依赖的调用分轮**：competing_conflict 中 v4-pro 先为 M08 登记 19:00，看到“已暂留”后重新查询 M01，结果写明“19:00（已提议给本次请求中的 M08）”，再为 M01 选 17:00。

## 自动化测试覆盖（76 项）

| 文件 | 数量 | 覆盖 |
|---|---|---|
| `test_tools.py` | 21 | 字段缺失/不存在/请求缺时间；规则三级；时长上限规则（R-DUR-01）；版权 valid/expired；替代时段排序与排除；不能提议已占用时段；未知工具与坏参数；硬性时间不可改；改期须确认；占用/撞车拒绝；有风险不能直接排期；每素材一条；needs_info 需有依据；幂等（措辞不同不算变化、方案变化升版本）；fail_always 不写文件；fail_once 重试成功；保存时现读最新排期 |
| `test_review_fixes.py` | 15 | 代码评审确认问题的回归：时间与排期规范化、排期文件写坏报错、未配置渠道与过期时间算缺信息、硬性优先的时段争用、不可排期素材释放时段、新提议替换旧提议、阻断作废确认、不可排期素材不能提议时段、缺信息不能伪装成阻断、授权覆盖日期复核、pending 模式须先列出素材、草稿库损坏如实报失败、新风险触发升版本 |
| `test_agent_loop.py` | 16 | 正常完成；轮数上限；工具调用上限及超限留痕；工具错误回传后继续；声称发布/保存的检测（含否定、疑问、条件、Markdown 写法）；保存失败不算就绪；未查过的事实为 null；保存后修订失败仍报告已保存草稿；保存后阻断判定草稿过期；未保存就结束；模型调用异常；trace 字段；并行调用的后续动作 |
| `test_providers.py` | 8 | Claude：tool_use 解析、tool_result 格式、content 原样回传、fallbacks/effort 参数、拒答；OpenAI 兼容：多工具调用、坏 JSON 参数、reasoning_content 回传、中断/非 JSON 响应、经适配层跑通完整循环、长度截断 |
| `test_scenarios.py` | 14 | 12 个场景端到端（Mock）+ 重复素材未查规则时显示为 null + 评审改占用时段后数据驱动生效 |
| `test_records.py` | 2 | 对 `examples/` 下全部 42 份已提交记录（Mock 14 + 两个真实模型各 14）检查不变量 |

## 对抗性评审：发现与处理

在第一轮真实模型记录和代码上做了两轮多智能体评审（每条发现由独立“质疑者”尝试推翻，多数推不翻才确认），详见 [04 AI 使用](04-ai-usage.md)：

- **运行记录审计**：26 条第一轮记录全部满足验收与安全不变量；确认 21 条次要问题（如“暂留”被模型说成“已预留”、未查过的规则显示为“无风险”、
  保存失败时条目仍显示“可直接确认”、超限调用不留痕），均已修复。
- **代码评审**：确认 41 条，其中“重要”级包括：时段争用只看请求顺序导致硬性素材保不住时间（会拒绝正确方案）；时间写法不规范时已有排期占用被漏判；
  保存成功后又修订失败被误报“未保存”；方案签名忽略新风险；“找出待处理素材”未被演示。均已修复，并在 `test_review_fixes.py` 等补了回归测试。
- 修复后重新生成了全部 Mock 与真实模型记录（本文表格即最终结果）。

## 失败与限制

1. **真实模型只跑了一轮全量**：两个模型各 14 次运行全部符合预期，但没有重复多次统计稳定性；temperature=0 下同一输入的调用数也会有差异（例如是否多调一次 `list_pending_materials`）。
2. **复核偏严的代价**：护栏会拒绝与事实不符的草稿，模型需要多改一轮（v4-pro 在 competing_conflict 中被拒 1 次后修正）；极端情况下可能触发上限返回 `incomplete`——这是有意的：宁可未完成，也不保存错误草稿。
3. **模型措辞不做语义校验**：`risk_reasons` / `pending_items` / 总结是模型写的文字，程序只校验结论与事实一致；工具事实另存于 `risk_facts`、`tool_facts`。
   “已发布/已保存”声称检测是规则级的，能处理否定、疑问、条件和 Markdown 写法，但不保证覆盖所有表达。
4. **跨请求不互相约束**：`request_confirmation` 的暂留只在本次请求内有效；两个不同请求的待确认草稿可能建议同一时段（确认闭环未实现）。
5. **单进程、无锁**：草稿库是 JSON 文件，未处理多进程并发写。
6. **时段模型简化**：只支持整点、按渠道互斥；替代时段只在要求当天内找（当天无空位时请求用户改日）；没有“同渠道最小间隔”“同类素材错峰”等规则。
7. **Claude 适配层未经真实 API 联调**。
