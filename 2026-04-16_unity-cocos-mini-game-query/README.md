# 2026-04-16 Unity / Cocos 小游戏逆向 query 脚本

## 任务背景
本次任务围绕两类小游戏源码/项目包做“产品需求逆向”：

1. **Cocos 小游戏源码包**
2. **Unity 小游戏项目库 / 项目包**

目标不是分析技术实现，而是从源码包、资源、场景、UI、音频、命名线索中，逆向还原：
- 这个项目最终运行起来像什么产品
- 用户怎么玩
- 有哪些核心玩法、系统、界面和反馈

也就是生成更接近“原始产品需求”的 query。

---

## 本目录包含的脚本

### 1. `inspect_cocos_archives.py`
用途：
- 轻量扫描 Cocos 游戏压缩包
- 不完整解压，只列举归档内的关键条目
- 抽取玩法、UI、引擎、资源等线索
- 输出 JSONL inspection 结果，供后续 reverse query 使用

适用场景：
- Cocos / Creator 类小游戏压缩包
- 想快速判断包里是否包含可逆向的产品信息

---

### 2. `run_game_reverse_query.py`
用途：
- 基于 Cocos inspection 结果，调用 LLM 批量生成 reverse query
- 采用流式、可续跑、增量 JSONL 输出
- 适合完整度较高、信号比较清晰的小游戏包

输出：
- `result_game_reverse_query.jsonl`
- `errors_game_reverse_query.jsonl`

---

### 3. `inspect_unity_archives.py`
用途：
- 轻量扫描 Unity 项目压缩包
- 判断样本更像：
  - `complete_game_project`
  - `starter_kit_or_template`
  - `asset_pack_or_resource_pack`
  - `framework_or_toolkit`
  - `unclear_or_sparse`
- inspection 目标不是看技术细节，而是判断能否还原“最终产品形态”

适用场景：
- Unity 项目库里混杂完整项目、模板、资源包时，先做分层过滤

---

### 4. `run_unity_reverse_query.py`
用途：
- 基于 Unity inspection 输出，逆向生成“最终产品需求”
- 重点关注：
  - 最终运行后的产品长什么样
  - 用户如何操作
  - 核心玩法循环
  - 系统与界面
  - 视听反馈
- 不强调技术实现
- 输出字段中包含：
  - `is_complete_and_good_mini_game_requirement`

该字段含义：
- `true`：这版 query 足够完整、清晰、稳定，像一个完整且好的小游戏产品需求
- `false`：已经有 query，但它不够完整 / 不够好 / 不够稳定 / 太泛 / 不够清晰

注意：
- 当前脚本逻辑要求：**无论 true 还是 false，都必须先生成 query**
- false 不是没有 query，而是“query 质量不足”

---

## 本次任务的关键执行思路

### Cocos 线
- 先用 inspection 脚本提取结构化线索
- 再批量 reverse query
- 已验证适用于样本较干净的 Cocos 小游戏源码包

### Unity 线
- 不能直接把全部 Unity 包混跑
- 必须先 inspection 分层
- 先筛出 `complete_game_project`
- 对 `unclear_or_sparse` 这类弱信号样本，需要单独 runner 逻辑
- 即使样本较弱，也要尽量基于现有线索生成 query，再判断 true/false

---

## 本次目录里没有上传的内容
为了避免把数据带进 git，本目录**只包含脚本和说明文档**，没有上传：
- 任何 `out/` 结果数据
- JSONL 输入/输出文件
- 大体量样本数据
- 临时调试文件

---

## 适合后续继续扩展的方向
1. 对 `unclear_or_sparse` 样本做更深层 inspection
2. 增加对嵌套压缩包的识别
3. 进一步细化小游戏类型分类
4. 在 query 质量评估上增加更明确的 rubric
