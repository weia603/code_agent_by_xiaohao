# T0046 小样本验证结论

## 类别口径
- prompts/README 定义的类别集合：game / dashboard / productivity-tool / ai-app / presentation / other
- 当前可直接运行且带 preset_category 的现成样本集：category15_input.json，仅覆盖前 5 类；other 类在该样本集中缺失。

## 运行结论
- 本轮实际运行 15 条样本，5 个可运行类别 × 每类 3 条，全部跑通。
- 运行模式为 fallback（heuristic bridge），并未命中真实 provider。
- 5 个预设类别中，ai-app/dashboard/game/productivity-tool 均稳定映射；presentation 出现 2/3 被细分重分类到 作品集/官网，仅 1/3 落到 营销/着陆页。

## 明显问题
- “每个类别”按 prompts 应为 6 类，但现成可运行带 preset 的样本只有 5 类，other 无法按同口径完成 3 条验证。
- 导出 summary 使用 22 类中文细分类，而 prompt README 使用 6 类英文粗分类，口径存在漂移。
- 当前 provider_mode=fallback，说明验证主要是在启发式桥接层，不是严格意义上的真实 prompt/模型效果验证。

## 下一步建议
- 先补齐 other 类的 3 条带 preset_category 样本，再补跑同批验证。
- 明确 6 类分类口径与 22 类重分类口径的上下游关系，单独产出映射规范。
- 如目标是验证 prompts 本身，需要切到 real provider 模式重跑，并把 prompt 路由、原始模型输出、失败样本单独落盘。
