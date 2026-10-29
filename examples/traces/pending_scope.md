# 运行记录：pending_scope

> 离线 Mock：决策由固定规则产生，只验证流程，不代表真实模型的决策效果

- 模式：`offline_mock`；请求范围：`pending`；当前时间（as_of）：`2026-10-29 09:00`
- 输入：`examples/inputs/pending_scope.json`；已有排期：`data/schedule.json`；草稿库：`examples/drafts/pending_scope.drafts.json`
- 结果状态：**completed**
- 草稿：{"saved": true, "result": "created", "draft_id": "D-8b5ef4c7", "version": 1, "message": "草稿已创建", "save_attempts": 1}
- 是否发布：False（本 Agent 只生成排期草稿，没有发布能力；所有条目需用户确认后才生效）
- 用量：{'steps': 30, 'tool_calls': 29, 'max_steps': 40, 'max_tool_calls': 80}

## 每个素材的结论

| 素材 | 审核结论 | 渠道 | 要求时段（规则） | 建议时段 | 风险原因 | 待确认/补充 | 草稿 |
|---|---|---|---|---|---|---|---|
| M01 | 待确认 | app_home | 2026-11-03 18:00（preferred） | 2026-11-03 19:00 | — | 确认改期：2026-11-03 18:00 → 2026-11-03 19:00 | 已写入草稿 D-8b5ef4c7 |
| M02 | 审核通过，按要求时段排期 | app_home | 2026-11-03 10:00（preferred） | 2026-11-03 10:00 | — | — | 已写入草稿 D-8b5ef4c7 |
| M03 | 信息缺失，待补充 | app_home | 2026-11-03 15:00（preferred） | — | — | 请补充素材字段：image_url、copyright | 已写入草稿 D-8b5ef4c7 |
| M04 | 待确认 | app_home | 2026-11-03 14:00（preferred） | 2026-11-03 14:00 | R-AD-01：文案含广告法极限词，需修改文案或经法务确认后发布（命中关键词：全网最、最低价） | 确认风险处理：文案含广告法极限词，需修改文案或经法务确认后发布 | 已写入草稿 D-8b5ef4c7 |
| M05 | 阻断 | app_home | 2026-11-03 16:00（preferred） | — | 版权失效：授权有效期至 2026-10-31，不覆盖发布日期 2026-11-03，视为失效 | — | 已写入草稿 D-8b5ef4c7 |
| M07 | 审核通过，按要求时段排期 | douyin | 2026-11-03 15:00（preferred） | 2026-11-03 15:00 | — | — | 已写入草稿 D-8b5ef4c7 |
| M08 | 待确认 | app_home | 2026-11-03 20:00（fixed） | — | — | 硬性时间 2026-11-03 20:00 不可用，需你决定：协调占用方或改到 2026-11-03 22:00 | 已写入草稿 D-8b5ef4c7 |
| M09 | 阻断 | douyin | 2026-11-03 16:00（preferred） | — | R-AD-02：商业推广内容未标注“广告”，不得发布（命中标记：{"is_commercial": true, "ad_label": false}） | — | 已写入草稿 D-8b5ef4c7 |

## 执行轨迹

| 轮次 | # | 工具 | 参数 | 返回摘要 | 决策依据（模型填写的 reason） | 后续动作 |
|---|---|---|---|---|---|---|
| 1 | 1 | `list_pending_materials` | {} | 待审核素材 8 个：M01、M02、M03、M04、M05、M07、M08、M09；已加入待处理清单 8 个 | 请求未列出素材，先找出所有待审核素材 | get_material(M01) |
| 2 | 2 | `get_material` | {"material_id": "M01"} | 《秋季新品开箱》；必填字段齐全；版权声明状态 valid（未核验） | 读取 M01 元数据，确认信息是否完整 | check_rules(M01) |
| 3 | 3 | `check_rules` | {"material_id": "M01"} | 无规则风险 | M01 信息齐全，按审核规则检查 | query_slots(M01) |
| 4 | 4 | `query_slots` | {"material_id": "M01", "channel": "app_home", "publish_time": "2026-11-03 18:00"} | app_home 2026-11-03 18:00 不可用（已被已有排期 S-1103-02《晚间档推荐》占用）；替代时段 ['2026-11-03 19:00', '2026-11-03 17:00', '2026-11-03 22:00'] | M01 审核无阻断风险，查询要求时段 2026-11-03 18:00 是否可用 | request_confirmation(M01) |
| 5 | 5 | `request_confirmation` | {"material_id": "M01", "question": "M01 要求时间 2026-11-03 18:00 不可用（已被已有排期 S-1103-02《晚间档推荐》占用），建议改到 2026-11-03 19:00，是否同意？", "proposed_slot": "2026-11-03 19:00"} | 已登记待确认 C-M01-671ac9，本次请求内暂留 2026-11-03 19:00（未写入排期）；用户尚未确认 | 要求时段不可用，2026-11-03 19:00 可用，改期需用户确认 | get_material(M02) |
| 6 | 6 | `get_material` | {"material_id": "M02"} | 《周末城市 vlog 合集》；必填字段齐全；版权声明状态 valid（未核验） | 读取 M02 元数据，确认信息是否完整 | check_rules(M02) |
| 7 | 7 | `check_rules` | {"material_id": "M02"} | 无规则风险 | M02 信息齐全，按审核规则检查 | query_slots(M02) |
| 8 | 8 | `query_slots` | {"material_id": "M02", "channel": "app_home", "publish_time": "2026-11-03 10:00"} | app_home 2026-11-03 10:00 可用 | M02 审核无阻断风险，查询要求时段 2026-11-03 10:00 是否可用 | get_material(M03) |
| 9 | 9 | `get_material` | {"material_id": "M03"} | 《双十一会场海报》；缺失必填字段 ['image_url', 'copyright']；版权声明状态 无（未核验） | 读取 M03 元数据，确认信息是否完整 | get_material(M04) |
| 10 | 10 | `get_material` | {"material_id": "M04"} | 《全网最低价！降噪耳机限时抢》；必填字段齐全；版权声明状态 valid（未核验） | 读取 M04 元数据，确认信息是否完整 | check_rules(M04) |
| 11 | 11 | `check_rules` | {"material_id": "M04"} | 命中 R-AD-01(warn) | M04 信息齐全，按审核规则检查 | query_slots(M04) |
| 12 | 12 | `query_slots` | {"material_id": "M04", "channel": "app_home", "publish_time": "2026-11-03 14:00"} | app_home 2026-11-03 14:00 可用 | M04 审核无阻断风险，查询要求时段 2026-11-03 14:00 是否可用 | request_confirmation(M04) |
| 13 | 13 | `request_confirmation` | {"material_id": "M04", "question": "M04 命中 warn 级规则：文案含广告法极限词，需修改文案或经法务确认后发布。是否修改后按计划发布？", "proposed_slot": ""} | 已登记待确认 C-M04-d6395f；用户尚未确认 | M04 命中 warn 级规则，需要用户决定 | get_material(M05) |
| 14 | 14 | `get_material` | {"material_id": "M05"} | 《毕业季混剪》；必填字段齐全；版权声明状态 pending（未核验） | 读取 M05 元数据，确认信息是否完整 | check_rules(M05) |
| 15 | 15 | `check_rules` | {"material_id": "M05"} | 命中 R-CP-02(verify) | M05 信息齐全，按审核规则检查 | verify_copyright(M05) |
| 16 | 16 | `verify_copyright` | {"material_id": "M05"} | 版权 expired：授权有效期至 2026-10-31，不覆盖发布日期 2026-11-03，视为失效 | M05 版权状态待核验，补查授权 | block_material(M05) |
| 17 | 17 | `block_material` | {"material_id": "M05", "risk_summary": "版权失效：授权有效期至 2026-10-31，不覆盖发布日期 2026-11-03，视为失效"} | 已阻断 M05：版权失效：授权有效期至 2026-10-31，不覆盖发布日期 2026-11-03，视为失效 | 补查结果为 expired，不能发布 | get_material(M07) |
| 18 | 18 | `get_material` | {"material_id": "M07"} | 《咖啡拉花教程》；必填字段齐全；版权声明状态 pending（未核验） | 读取 M07 元数据，确认信息是否完整 | check_rules(M07) |
| 19 | 19 | `check_rules` | {"material_id": "M07"} | 命中 R-CP-02(verify) | M07 信息齐全，按审核规则检查 | verify_copyright(M07) |
| 20 | 20 | `verify_copyright` | {"material_id": "M07"} | 版权 valid：授权有效至 2027-06-30，覆盖发布日期 2026-11-03 | M07 版权状态待核验，补查授权 | query_slots(M07) |
| 21 | 21 | `query_slots` | {"material_id": "M07", "channel": "douyin", "publish_time": "2026-11-03 15:00"} | douyin 2026-11-03 15:00 可用 | M07 审核无阻断风险，查询要求时段 2026-11-03 15:00 是否可用 | get_material(M08) |
| 22 | 22 | `get_material` | {"material_id": "M08"} | 《新品发布会直播预热》；必填字段齐全；版权声明状态 valid（未核验） | 读取 M08 元数据，确认信息是否完整 | check_rules(M08) |
| 23 | 23 | `check_rules` | {"material_id": "M08"} | 无规则风险 | M08 信息齐全，按审核规则检查 | query_slots(M08) |
| 24 | 24 | `query_slots` | {"material_id": "M08", "channel": "app_home", "publish_time": "2026-11-03 20:00"} | app_home 2026-11-03 20:00 不可用（已被已有排期 S-1103-03《直播间开播提醒》占用）；更近的时段也不可用：21:00（已被已有排期 S-1103-04《品牌故事》占用），19:00（已提议给本次请求中的 M01）；替代时段 ['2026-11-03 22:00', '2026-11-03 17:00', '2026-11-03 16:00'] | M08 审核无阻断风险，查询要求时段 2026-11-03 20:00 是否可用 | request_confirmation(M08) |
| 25 | 25 | `request_confirmation` | {"material_id": "M08", "question": "M08 的硬性发布时间 2026-11-03 20:00 不可用（已被已有排期 S-1103-03《直播间开播提醒》占用）。未经你同意不会改期：请决定协调占用方让出该时段，还是改到 2026-11-03 22:00？", "proposed_slot": "2026-11-03 22:00"} | 已登记待确认 C-M08-832143，本次请求内暂留 2026-11-03 22:00（未写入排期）；用户尚未确认 | 硬性时间被占用，不能擅自改期，需用户决定 | get_material(M09) |
| 26 | 26 | `get_material` | {"material_id": "M09"} | 《直播间专属优惠券》；必填字段齐全；版权声明状态 valid（未核验） | 读取 M09 元数据，确认信息是否完整 | check_rules(M09) |
| 27 | 27 | `check_rules` | {"material_id": "M09"} | 命中 R-AD-02(block) | M09 信息齐全，按审核规则检查 | block_material(M09) |
| 28 | 28 | `block_material` | {"material_id": "M09", "risk_summary": "商业推广内容未标注“广告”，不得发布"} | 已阻断 M09：商业推广内容未标注“广告”，不得发布 | M09 命中 block 级规则 | save_draft |
| 29 | 29 | `save_draft` | {"entries": ["M01:pending_confirmation@2026-11-03 19:00", "M02:schedule@2026-11-03 10:00", "M03:needs_info@—", "M04:pending_confirmation@2026-11-03 14:00", "M05:blocked@—", "M07:schedule@2026-11-03 15:00", "M08:pending_confirmation@—", "M09:blocked@—"]} | created：D-8b5ef4c7 v1（草稿已创建） | 全部素材已处理，提交排期草稿 | 结束，输出总结 |

## 待用户确认事项（来自 request_confirmation 登记）

- `C-M01-671ac9`（M01）M01 要求时间 2026-11-03 18:00 不可用（已被已有排期 S-1103-02《晚间档推荐》占用），建议改到 2026-11-03 19:00，是否同意？（替代时段：2026-11-03 19:00；状态：awaiting_user）
- `C-M04-d6395f`（M04）M04 命中 warn 级规则：文案含广告法极限词，需修改文案或经法务确认后发布。是否修改后按计划发布？（替代时段：无；状态：awaiting_user）
- `C-M08-832143`（M08）M08 的硬性发布时间 2026-11-03 20:00 不可用（已被已有排期 S-1103-03《直播间开播提醒》占用）。未经你同意不会改期：请决定协调占用方让出该时段，还是改到 2026-11-03 22:00？（替代时段：2026-11-03 22:00；状态：awaiting_user）

## 模型最终答复

```text
【离线 Mock】处理结果：
- M01：待确认，建议时段 2026-11-03 19:00；待确认/补充：确认改期：2026-11-03 18:00 → 2026-11-03 19:00
- M02：审核通过，按要求时段排期，建议时段 2026-11-03 10:00
- M03：信息缺失，待补充，建议时段 无；待确认/补充：请补充素材字段：image_url、copyright
- M04：待确认，建议时段 2026-11-03 14:00；待确认/补充：确认风险处理：文案含广告法极限词，需修改文案或经法务确认后发布
- M05：阻断，建议时段 无
- M07：审核通过，按要求时段排期，建议时段 2026-11-03 15:00
- M08：待确认，建议时段 无；待确认/补充：硬性时间 2026-11-03 20:00 不可用，需你决定：协调占用方或改到 2026-11-03 22:00
- M09：阻断，建议时段 无
草稿保存结果：created（D-8b5ef4c7 v1）。仅为草稿，需你确认，未做任何发布。
```
