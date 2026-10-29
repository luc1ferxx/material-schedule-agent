# 运行记录：missing_info

> 离线 Mock：决策由固定规则产生，只验证流程，不代表真实模型的决策效果

- 模式：`offline_mock`；请求范围：`items`；当前时间（as_of）：`2026-10-29 09:00`
- 输入：`examples/inputs/missing_info.json`；已有排期：`data/schedule.json`；草稿库：`examples/drafts/missing_info.drafts.json`
- 结果状态：**completed**
- 草稿：{"saved": true, "result": "created", "draft_id": "D-fe17af77", "version": 1, "message": "草稿已创建", "save_attempts": 1}
- 是否发布：False（本 Agent 只生成排期草稿，没有发布能力；所有条目需用户确认后才生效）
- 用量：{'steps': 5, 'tool_calls': 4, 'max_steps': 40, 'max_tool_calls': 80}

## 每个素材的结论

| 素材 | 审核结论 | 渠道 | 要求时段（规则） | 建议时段 | 风险原因 | 待确认/补充 | 草稿 |
|---|---|---|---|---|---|---|---|
| M03 | 信息缺失，待补充 | app_home | 2026-11-03 15:00（preferred） | — | — | 请补充素材字段：image_url、copyright | 已写入草稿 D-fe17af77 |
| M99 | 信息缺失，待补充 | app_home | 2026-11-03 16:00（preferred） | — | — | 素材库中不存在 M99，请核对素材 ID | 已写入草稿 D-fe17af77 |
| M02 | 信息缺失，待补充 | douyin | — | — | — | 请补充或修正发布要求：publish_time（发布时间要求）缺失 | 已写入草稿 D-fe17af77 |

## 执行轨迹

| 轮次 | # | 工具 | 参数 | 返回摘要 | 决策依据（模型填写的 reason） | 后续动作 |
|---|---|---|---|---|---|---|
| 1 | 1 | `get_material` | {"material_id": "M03"} | 《双十一会场海报》；缺失必填字段 ['image_url', 'copyright']；版权声明状态 无（未核验） | 读取 M03 元数据，确认信息是否完整 | get_material(M99) |
| 2 | 2 | `get_material` | {"material_id": "M99"} | M99 不存在于素材库 | 读取 M99 元数据，确认信息是否完整 | get_material(M02) |
| 3 | 3 | `get_material` | {"material_id": "M02"} | 《周末城市 vlog 合集》；必填字段齐全；版权声明状态 valid（未核验）；发布要求有问题：publish_time（发布时间要求）缺失 | 读取 M02 元数据，确认信息是否完整 | save_draft |
| 4 | 4 | `save_draft` | {"entries": ["M03:needs_info@—", "M99:needs_info@—", "M02:needs_info@—"]} | created：D-fe17af77 v1（草稿已创建） | 全部素材已处理，提交排期草稿 | 结束，输出总结 |

## 模型最终答复

```text
【离线 Mock】处理结果：
- M03：信息缺失，待补充，建议时段 无；待确认/补充：请补充素材字段：image_url、copyright
- M99：信息缺失，待补充，建议时段 无；待确认/补充：素材库中不存在 M99，请核对素材 ID
- M02：信息缺失，待补充，建议时段 无；待确认/补充：请补充或修正发布要求：publish_time（发布时间要求）缺失
草稿保存结果：created（D-fe17af77 v1）。仅为草稿，需你确认，未做任何发布。
```
