# 2026-04-30 V0 + youware reverse-query 项目整理

本目录从 `/data/openclaw/V0_0423` 与 `/data/openclaw/youware_0423` 中抽取了**可复用脚本**与**关键说明文档**，用于归档到 GitHub。

## 收录原则
- 保留：主运行脚本、验证脚本、prompt、runbook、任务说明、总结文档
- 排除：大体积 outputs、checkpoint、日志、临时测试结果、中间缓存

## 目录结构
- `V0_0423/`
  - `scripts/`：V0 通用 reverse-query 运行脚本及辅助脚本
  - `prompts/`：各数据源 prompt
  - `docs/`：任务说明、运行手册、阶段 memory
- `youware_0423/`
  - `scripts/`：youware query 生成/验证脚本
  - `prompts/`：v2 分类 prompt
  - `docs/`：code signal 框架、5类全量任务 memory、T0046 结论

## 未收录内容
以下内容刻意未上传：
- `outputs/**`
- `logs/**`
- 大型 checkpoint/json/jsonl 结果文件
- 仅用于一次性运行观测的中间产物

## 备注
部分脚本仍包含原始绝对路径（如 `/data/openclaw/...`）和运行环境依赖（如 `step_align`、`megfile`、内部 bridge）。本次上传目标是代码与文档归档，不是立即做成可脱离环境直接运行的开源包。
