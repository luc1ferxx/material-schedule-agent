# 运行记录：save_fail_once

> 离线 Mock：决策由固定规则产生，只验证流程，不代表真实模型的决策效果

- 模式：`offline_mock`；请求范围：`items`；当前时间（as_of）：`2026-10-29 09:00`
- 输入：`examples/inputs/save_fail_once.json`；已有排期：`data/schedule.json`；草稿库：`examples/drafts/save_fail_once.drafts.json`
- 结果状态：**completed**
- 草稿：{"saved": true, "result": "created", "draft_id": "D-b940d363", "version": 1, "message": "草稿已创建", "save_attempts": 2}
- 是否发布：False（本 Agent 只生成排期草稿，没有发布能力；所有条目需用户确认后才生效）
- 用量：{'steps': 10, 'tool_calls': 9, 'max_steps': 40, 'max_tool_calls': 80}

## 每个素材的结论

| 素材 | 审核结论 | 渠道 | 要求时段（规则） | 建议时段 | 风险原因 | 待确认/补充 | 草稿 |
|---|---|---|---|---|---|---|---|
| M02 | 审核通过，按要求时段排期 | app_home | 2026-11-03 10:00（preferred） | 2026-11-03 10:00 | — | — | 已写入草稿 D-b940d363 |
| M07 | 审核通过，按要求时段排期 | douyin | 2026-11-03 15:00（preferred） | 2026-11-03 15:00 | — | — | 已写入草稿 D-b940d363 |

## 执行轨迹

| 轮次 | # | 工具 | 参数 | 返回摘要 | 决策依据（模型填写的 reason） | 后续动作 |
|---|---|---|---|---|---|---|
| 1 | 1 | `get_material` | {"material_id": "M02"} | 《周末城市 vlog 合集》；必填字段齐全；版权声明状态 valid（未核验） | 读取 M02 元数据，确认信息是否完整 | check_rules(M02) |
| 2 | 2 | `check_rules` | {"material_id": "M02"} | 无规则风险 | M02 信息齐全，按审核规则检查 | query_slots(M02) |
| 3 | 3 | `query_slots` | {"material_id": "M02", "channel": "app_home", "publish_time": "2026-11-03 10:00"} | app_home 2026-11-03 10:00 可用 | M02 审核无阻断风险，查询要求时段 2026-11-03 10:00 是否可用 | get_material(M07) |
| 4 | 4 | `get_material` | {"material_id": "M07"} | 《咖啡拉花教程》；必填字段齐全；版权声明状态 pending（未核验） | 读取 M07 元数据，确认信息是否完整 | check_rules(M07) |
| 5 | 5 | `check_rules` | {"material_id": "M07"} | 命中 R-CP-02(verify) | M07 信息齐全，按审核规则检查 | verify_copyright(M07) |
| 6 | 6 | `verify_copyright` | {"material_id": "M07"} | 版权 valid：授权有效至 2027-06-30，覆盖发布日期 2026-11-03 | M07 版权状态待核验，补查授权 | query_slots(M07) |
| 7 | 7 | `query_slots` | {"material_id": "M07", "channel": "douyin", "publish_time": "2026-11-03 15:00"} | douyin 2026-11-03 15:00 可用 | M07 审核无阻断风险，查询要求时段 2026-11-03 15:00 是否可用 | save_draft |
| 8 | 8 | `save_draft` | {"entries": ["M02:schedule@2026-11-03 10:00", "M07:schedule@2026-11-03 15:00"]} | ❌ 保存失败 STORAGE_TIMEOUT（retryable=True）：草稿库写入超时；本次未写入，可重试 | 全部素材已处理，提交排期草稿 | save_draft |
| 9 | 9 | `save_draft` | {"entries": ["M02:schedule@2026-11-03 10:00", "M07:schedule@2026-11-03 15:00"]} | created：D-b940d363 v1（草稿已创建） | 上次保存失败（STORAGE_TIMEOUT，retryable=true），重试一次 | 结束，输出总结 |

## 模型最终答复

```text
【离线 Mock】处理结果：
- M02：审核通过，按要求时段排期，建议时段 2026-11-03 10:00
- M07：审核通过，按要求时段排期，建议时段 2026-11-03 15:00
草稿保存结果：created（D-b940d363 v1）。仅为草稿，需你确认，未做任何发布。
```
