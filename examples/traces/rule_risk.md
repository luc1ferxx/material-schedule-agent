# 运行记录：rule_risk

> 离线 Mock：决策由固定规则产生，只验证流程，不代表真实模型的决策效果

- 模式：`offline_mock`；请求范围：`items`；当前时间（as_of）：`2026-10-29 09:00`
- 输入：`examples/inputs/rule_risk.json`；已有排期：`data/schedule.json`；草稿库：`examples/drafts/rule_risk.drafts.json`
- 结果状态：**completed**
- 草稿：{"saved": true, "result": "created", "draft_id": "D-bfc249d5", "version": 1, "message": "草稿已创建", "save_attempts": 1}
- 是否发布：False（本 Agent 只生成排期草稿，没有发布能力；所有条目需用户确认后才生效）
- 用量：{'steps': 13, 'tool_calls': 12, 'max_steps': 40, 'max_tool_calls': 80}

## 每个素材的结论

| 素材 | 审核结论 | 渠道 | 要求时段（规则） | 建议时段 | 风险原因 | 待确认/补充 | 草稿 |
|---|---|---|---|---|---|---|---|
| M04 | 待确认 | app_home | 2026-11-03 14:00（preferred） | 2026-11-03 14:00 | R-AD-01：文案含广告法极限词，需修改文案或经法务确认后发布（命中关键词：全网最、最低价） | 确认风险处理：文案含广告法极限词，需修改文案或经法务确认后发布 | 已写入草稿 D-bfc249d5 |
| M05 | 阻断 | app_home | 2026-11-03 16:00（preferred） | — | 版权失效：授权有效期至 2026-10-31，不覆盖发布日期 2026-11-03，视为失效 | — | 已写入草稿 D-bfc249d5 |
| M09 | 阻断 | douyin | 2026-11-03 16:00（preferred） | — | R-AD-02：商业推广内容未标注“广告”，不得发布（命中标记：{"is_commercial": true, "ad_label": false}） | — | 已写入草稿 D-bfc249d5 |

## 执行轨迹

| 轮次 | # | 工具 | 参数 | 返回摘要 | 决策依据（模型填写的 reason） | 后续动作 |
|---|---|---|---|---|---|---|
| 1 | 1 | `get_material` | {"material_id": "M04"} | 《全网最低价！降噪耳机限时抢》；必填字段齐全；版权声明状态 valid（未核验） | 读取 M04 元数据，确认信息是否完整 | check_rules(M04) |
| 2 | 2 | `check_rules` | {"material_id": "M04"} | 命中 R-AD-01(warn) | M04 信息齐全，按审核规则检查 | query_slots(M04) |
| 3 | 3 | `query_slots` | {"material_id": "M04", "channel": "app_home", "publish_time": "2026-11-03 14:00"} | app_home 2026-11-03 14:00 可用 | M04 审核无阻断风险，查询要求时段 2026-11-03 14:00 是否可用 | request_confirmation(M04) |
| 4 | 4 | `request_confirmation` | {"material_id": "M04", "question": "M04 命中 warn 级规则：文案含广告法极限词，需修改文案或经法务确认后发布。是否修改后按计划发布？", "proposed_slot": ""} | 已登记待确认 C-M04-80e03a；用户尚未确认 | M04 命中 warn 级规则，需要用户决定 | get_material(M05) |
| 5 | 5 | `get_material` | {"material_id": "M05"} | 《毕业季混剪》；必填字段齐全；版权声明状态 pending（未核验） | 读取 M05 元数据，确认信息是否完整 | check_rules(M05) |
| 6 | 6 | `check_rules` | {"material_id": "M05"} | 命中 R-CP-02(verify) | M05 信息齐全，按审核规则检查 | verify_copyright(M05) |
| 7 | 7 | `verify_copyright` | {"material_id": "M05"} | 版权 expired：授权有效期至 2026-10-31，不覆盖发布日期 2026-11-03，视为失效 | M05 版权状态待核验，补查授权 | block_material(M05) |
| 8 | 8 | `block_material` | {"material_id": "M05", "risk_summary": "版权失效：授权有效期至 2026-10-31，不覆盖发布日期 2026-11-03，视为失效"} | 已阻断 M05：版权失效：授权有效期至 2026-10-31，不覆盖发布日期 2026-11-03，视为失效 | 补查结果为 expired，不能发布 | get_material(M09) |
| 9 | 9 | `get_material` | {"material_id": "M09"} | 《直播间专属优惠券》；必填字段齐全；版权声明状态 valid（未核验） | 读取 M09 元数据，确认信息是否完整 | check_rules(M09) |
| 10 | 10 | `check_rules` | {"material_id": "M09"} | 命中 R-AD-02(block) | M09 信息齐全，按审核规则检查 | block_material(M09) |
| 11 | 11 | `block_material` | {"material_id": "M09", "risk_summary": "商业推广内容未标注“广告”，不得发布"} | 已阻断 M09：商业推广内容未标注“广告”，不得发布 | M09 命中 block 级规则 | save_draft |
| 12 | 12 | `save_draft` | {"entries": ["M04:pending_confirmation@2026-11-03 14:00", "M05:blocked@—", "M09:blocked@—"]} | created：D-bfc249d5 v1（草稿已创建） | 全部素材已处理，提交排期草稿 | 结束，输出总结 |

## 待用户确认事项（来自 request_confirmation 登记）

- `C-M04-80e03a`（M04）M04 命中 warn 级规则：文案含广告法极限词，需修改文案或经法务确认后发布。是否修改后按计划发布？（替代时段：无；状态：awaiting_user）

## 模型最终答复

```text
【离线 Mock】处理结果：
- M04：待确认，建议时段 2026-11-03 14:00；待确认/补充：确认风险处理：文案含广告法极限词，需修改文案或经法务确认后发布
- M05：阻断，建议时段 无
- M09：阻断，建议时段 无
草稿保存结果：created（D-bfc249d5 v1）。仅为草稿，需你确认，未做任何发布。
```
