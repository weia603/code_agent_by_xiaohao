# V0_0423 任务说明

## 目标
针对 `s3://collect-data-text/202511/h5sites_resource/v0/20260302/apps-and-games/` 下的原始 code 资源，逆向生成高质量小游戏产品需求 query，用于后续与已有 code 组成 QA pair 训练 LLM。

## 本轮约束（已更新）
- 当前这批样本**全部按小游戏处理**。
- **不按类别拆分 prompt**。
- 直接参考 `/data/openclaw/youware_0423` 中的 game prompt 思路，但本任务的输入、脚本、输出都必须新建在 `/data/openclaw/V0_0423`。

## 目标输出字段
- `product_query`
- `feature_query`
- `is_complete`
- `reason`
- `category1`
- `category2`
- `category_is_game`
- `category_decision_reason`
- `queries`

## 任务拆解
1. 分析 S3 原始资源结构，确认可解析字段和适合的逆向证据。
2. 新建小游戏逆向 prompt，包含 code 完整性判断。
3. 新建 S3 抽样与输入构建脚本。
4. 先做小批量验证。
5. 验证通过后再全量批跑。
