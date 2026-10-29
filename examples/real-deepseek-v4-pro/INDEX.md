# 运行样例索引

> 以下为真实模型 `openai-compatible:deepseek-v4-pro` 的实际输出，由 `python -m src.run_examples --provider openai` 生成（模型名取自 .env 的模型配置）。

| 场景 | 覆盖验收点 | 输入 | 实际输出 | 运行记录 | 状态 | 草稿 | 工具调用 |
|---|---|---|---|---|---|---|---|
| pending_scope | 找出待处理素材：不列素材，Agent 先 list_pending_materials，再对 8 个待审素材逐个审核并形成一份排期草稿（综合场景） | [pending_scope.json](../inputs/pending_scope.json) | [pending_scope.json](outputs/pending_scope.json) | [pending_scope.md](traces/pending_scope.md) | completed | created | 29 |
| normal | 正常排期；版权待核验→补查 valid→正常排期（M07） | [normal.json](../inputs/normal.json) | [normal.json](outputs/normal.json) | [normal.md](traces/normal.md) | completed | created | 8 |
| slot_conflict | 时段冲突（参考实例）：M01 期望 18:00 被占、19:00 可用→建议 19:00 并标记待确认，不称已发布 | [slot_conflict.json](../inputs/slot_conflict.json) | [slot_conflict.json](outputs/slot_conflict.json) | [slot_conflict.md](traces/slot_conflict.md) | completed | created | 5 |
| fixed_conflict | 硬性要求边界：M08 硬性 20:00 被占→不擅自改期，只提方案请用户决定（或阻断） | [fixed_conflict.json](../inputs/fixed_conflict.json) | [fixed_conflict.json](outputs/fixed_conflict.json) | [fixed_conflict.md](traces/fixed_conflict.md) | completed | created | 5 |
| competing_conflict | 多素材争抢替代时段：M01 与 M08 的建议/暂留时段互不冲突，M08 硬性时间不改 | [competing_conflict.json](../inputs/competing_conflict.json) | [competing_conflict.json](outputs/competing_conflict.json) | [competing_conflict.md](traces/competing_conflict.md) | completed | created | 11 |
| missing_info | 素材信息缺失：必填字段缺失（M03）、素材 ID 不存在（M99）、请求缺发布时间（M02） | [missing_info.json](../inputs/missing_info.json) | [missing_info.json](outputs/missing_info.json) | [missing_info.md](traces/missing_info.md) | completed | created | 4 |
| rule_risk | 规则风险：warn 极限词→请求确认（M04）；verify→补查 expired→阻断（M05）；block 未标广告→阻断（M09） | [rule_risk.json](../inputs/rule_risk.json) | [rule_risk.json](outputs/rule_risk.json) | [rule_risk.md](traces/rule_risk.md) | completed | created | 12 |
| duplicate_submit.run1 | 重复提交：同一请求提交两次只保留一份草稿；请求内重复条目合并；M06 已在排期中 | [duplicate_submit.json](../inputs/duplicate_submit.json) | [duplicate_submit.run1.json](outputs/duplicate_submit.run1.json) | [duplicate_submit.run1.md](traces/duplicate_submit.run1.md) | completed | created | 5 |
| duplicate_submit.run2 | 重复提交：同一请求提交两次只保留一份草稿；请求内重复条目合并；M06 已在排期中 | [duplicate_submit.json](../inputs/duplicate_submit.json) | [duplicate_submit.run2.json](outputs/duplicate_submit.run2.json) | [duplicate_submit.run2.md](traces/duplicate_submit.run2.md) | completed | duplicate_unchanged | 5 |
| schedule_changed.run1 | 更换占用时段后重复提交：19:00 也被占→M01 改建议 17:00，同一草稿更新为 v2（不新建） | [slot_conflict.json](../inputs/slot_conflict.json) | [schedule_changed.run1.json](outputs/schedule_changed.run1.json) | [schedule_changed.run1.md](traces/schedule_changed.run1.md) | completed | created | 5 |
| schedule_changed.run2 | 更换占用时段后重复提交：19:00 也被占→M01 改建议 17:00，同一草稿更新为 v2（不新建） | [slot_conflict.json](../inputs/slot_conflict.json) | [schedule_changed.run2.json](outputs/schedule_changed.run2.json) | [schedule_changed.run2.md](traces/schedule_changed.run2.md) | completed | updated | 5 |
| save_fail_always | 保存失败（不可重试）：明确返回 save_failed，不虚报成功 | [save_fail_always.json](../inputs/save_fail_always.json) | [save_fail_always.json](outputs/save_fail_always.json) | [save_fail_always.md](traces/save_fail_always.md) | save_failed | save_failed | 8 |
| save_fail_once | 保存失败（可重试）：根据 retryable=true 重试一次后保存成功 | [save_fail_once.json](../inputs/save_fail_once.json) | [save_fail_once.json](outputs/save_fail_once.json) | [save_fail_once.md](traces/save_fail_once.md) | completed | created | 9 |
| tool_limit | 工具调用达到上限：返回 incomplete 及原因，超限调用留痕 | [normal.json](../inputs/normal.json) | [tool_limit.json](outputs/tool_limit.json) | [tool_limit.md](traces/tool_limit.md) | incomplete | not_saved | 3 |
