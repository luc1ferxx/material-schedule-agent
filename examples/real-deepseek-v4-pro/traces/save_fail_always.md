# 运行记录：save_fail_always

- 模式：`openai-compatible:deepseek-v4-pro`；请求范围：`items`；当前时间（as_of）：`2026-10-29 09:00`
- 输入：`examples/inputs/save_fail_always.json`；已有排期：`data/schedule.json`；草稿库：`examples/real-deepseek-v4-pro/drafts/save_fail_always.drafts.json`
- 结果状态：**save_failed**（草稿库当前只读，写入被拒绝；草稿未保存）
- 草稿：{"saved": false, "result": "save_failed", "error_code": "STORAGE_READ_ONLY", "retryable": false, "message": "草稿库当前只读，写入被拒绝；草稿未保存", "save_attempts": 1}
- 是否发布：False（本 Agent 只生成排期草稿，没有发布能力；所有条目需用户确认后才生效）
- 用量：{'steps': 6, 'tool_calls': 8, 'max_steps': 40, 'max_tool_calls': 80}

## 每个素材的结论

| 素材 | 审核结论 | 渠道 | 要求时段（规则） | 建议时段 | 风险原因 | 待确认/补充 | 草稿 |
|---|---|---|---|---|---|---|---|
| M02 | 审核通过，按要求时段排期 | app_home | 2026-11-03 10:00（preferred） | 2026-11-03 10:00 | — | — | 草稿未保存 |
| M07 | 审核通过，按要求时段排期 | douyin | 2026-11-03 15:00（preferred） | 2026-11-03 15:00 | — | — | 草稿未保存 |

## 执行轨迹

| 轮次 | # | 工具 | 参数 | 返回摘要 | 决策依据（模型填写的 reason） | 后续动作 |
|---|---|---|---|---|---|---|
| 1 | 1 | `get_material` | {"material_id": "M02"} | 《周末城市 vlog 合集》；必填字段齐全；版权声明状态 valid（未核验） | 处理 REQ-1103-SAVEFAIL 中列出的素材 M02，先读取元数据 | check_rules(M02)、check_rules(M07) |
| 1 | 2 | `get_material` | {"material_id": "M07"} | 《咖啡拉花教程》；必填字段齐全；版权声明状态 pending（未核验） | 处理 REQ-1103-SAVEFAIL 中列出的素材 M07，先读取元数据 | check_rules(M02)、check_rules(M07) |
| 2 | 3 | `check_rules` | {"material_id": "M02"} | 无规则风险 | M02 元数据完整、发布要求有效，进行规则检查 | verify_copyright(M07) |
| 2 | 4 | `check_rules` | {"material_id": "M07"} | 命中 R-CP-02(verify) | M07 元数据完整、发布要求有效，进行规则检查 | verify_copyright(M07) |
| 3 | 5 | `verify_copyright` | {"material_id": "M07"} | 版权 valid：授权有效至 2027-06-30，覆盖发布日期 2026-11-03 | M07 规则命中 verify，版权状态 pending，需补查版权登记库 | query_slots(M02)、query_slots(M07) |
| 4 | 6 | `query_slots` | {"material_id": "M02", "channel": "app_home", "publish_time": "2026-11-03 10:00"} | app_home 2026-11-03 10:00 可用 | M02 规则检查无风险，查询 app_home 在 2026-11-03 10:00 是否可用 | save_draft |
| 4 | 7 | `query_slots` | {"material_id": "M07", "channel": "douyin", "publish_time": "2026-11-03 15:00"} | douyin 2026-11-03 15:00 可用 | M07 版权核验有效、无其他规则命中，查询 douyin 在 2026-11-03 15:00 是否可用 | save_draft |
| 5 | 8 | `save_draft` | {"entries": ["M02:schedule@2026-11-03 10:00", "M07:schedule@2026-11-03 15:00"]} | ❌ 保存失败 STORAGE_READ_ONLY（retryable=False）：草稿库当前只读，写入被拒绝；草稿未保存 | M02 与 M07 均无规则风险、要求时段可用，按要求的 preferred 时段排期并保存草稿 | 结束，输出总结 |

## 模型最终答复

```text
处理结果如下：

**素材结论与建议时段**

| 素材 | 结论 | 建议时段 | 说明 |
|------|------|----------|------|
| M02（周末城市 vlog 合集，app_home） | 可直接排期 | 2026-11-03 10:00 | 规则检查无命中；版权有效；要求时段可用 |
| M07（咖啡拉花教程，douyin） | 可直接排期 | 2026-11-03 15:00 | 规则命中 verify，补查版权结果为 valid（授权有效至 2027-06-30，覆盖 2026-11-03）；要求时段可用 |

**待用户确认事项**：无。

**草稿保存结果**：失败，草稿未保存。save_draft 返回 `STORAGE_READ_ONLY`（草稿库当前只读，写入被拒绝），且该错误 `retryable=false`，按规则不重试、停止处理。两个素材的排期未写入任何草稿，需在存储恢复后重新提交。
```
