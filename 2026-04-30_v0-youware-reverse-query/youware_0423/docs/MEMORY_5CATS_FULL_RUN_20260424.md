# 5类 Query 逆向任务 Memory（可直接接班）

更新时间：2026-04-24 01:54（本地）
目录：`/data/openclaw/youware_0423`

## 一、任务介绍（这件事到底在做什么）
目标：基于 youware 的 S3 全量前端站点，按 5 个类别进行“query 逆向生成”（结构化 JSON 输出），用于后续训练数据构建。

本次 5 类：
1. `ai-app`
2. `education`
3. `landing-page`
4. `presentation`
5. `productivity-tool`

类别总量（来自运行日志统计）：
- ai-app: 939
- education: 297
- landing-page: 466
- presentation: 429
- productivity-tool: 767

## 二、当前会话总结（做了什么、当前到哪一步）
1. 已完成 5 个 prompt 的“强约束版”改造（统一字段、唯一映射、严格类型）。
2. 按用户要求补充并“融合”了 AI前端应用/单页工具的细化规范（不是原样粘贴）。
3. 进一步把 education/landing-page/presentation 也做了同级细化。
4. 最终采用 `generate_query_youware_game_v2.py` 作为统一运行脚本（用户指定参考该脚本）。
5. 已启动 5 类全量任务，3 key 轮询，后台运行中（见下面“运行状态”）。
6. 已清理本轮中间测试脚本/测试数据，仅保留正式任务产物和必要历史目录。

## 三、关键文件（本任务真正依赖哪些）
### 1) 运行脚本
- `/data/openclaw/youware_0423/scripts/generate_query_youware_game_v2.py`

### 2) Prompt 文件
- `/data/openclaw/youware_0423/prompts/23_query_generation_ai_app_v2.md`
- `/data/openclaw/youware_0423/prompts/24_query_generation_education_v2.md`
- `/data/openclaw/youware_0423/prompts/25_query_generation_landing_page_v2.md`
- `/data/openclaw/youware_0423/prompts/26_query_generation_presentation_v2.md`
- `/data/openclaw/youware_0423/prompts/27_query_generation_productivity_tool_v2.md`

## 四、最终稳定运行方案（可快速复用）

### 推荐启动方式（必须）
使用 `setsid + nohup`，避免任务跟随当前会话被回收。

### 单类命令模板
```bash
setsid nohup python /data/openclaw/youware_0423/scripts/generate_query_youware_game_v2.py \
  --s3_base s3://collect-data-text/202511/h5sites_resource/youware/<category> \
  --prompt_path /data/openclaw/youware_0423/prompts/<prompt_file>.md \
  --out_dir /data/openclaw/youware_0423/outputs/<run_root>/<category> \
  --run_name <category>_query_generation_v2_full \
  --model gemini-3-pro-thinking \
  --api_keys <KEY1> <KEY2> <KEY3> \
  --concurrency 2 \
  --rpm 40 \
  --response_format_json \
  </dev/null > /data/openclaw/youware_0423/logs/<run_root>/<category>.nohup.log 2>&1 &
```

### 5类一次性启动参数（本次实际值）
- model: `gemini-3-pro-thinking`
- key 轮询：3 个 key 通过 `--api_keys` 传入
- 并发：`--concurrency 2`
- 节流：`--rpm 40`
- 输出：`--response_format_json`

## 五、当前正式运行（正在执行）
### 1) 运行根目录
- 输出：`/data/openclaw/youware_0423/outputs/query_generation_5cats_full_keys3_detach_20260424_014841`
- 日志：`/data/openclaw/youware_0423/logs/query_generation_5cats_full_keys3_detach_20260424_014841`

### 2) 进程 PID
- ai-app: `1023090`
- education: `1023092`
- landing-page: `1023094`
- presentation: `1023096`
- productivity-tool: `1023098`

### 3) 结果文件（持续写入）
- `/data/openclaw/youware_0423/outputs/query_generation_5cats_full_keys3_detach_20260424_014841/ai-app/ai-app_query_generation_v2_full.jsonl`
- `/data/openclaw/youware_0423/outputs/query_generation_5cats_full_keys3_detach_20260424_014841/education/education_query_generation_v2_full.jsonl`
- `/data/openclaw/youware_0423/outputs/query_generation_5cats_full_keys3_detach_20260424_014841/landing-page/landing-page_query_generation_v2_full.jsonl`
- `/data/openclaw/youware_0423/outputs/query_generation_5cats_full_keys3_detach_20260424_014841/presentation/presentation_query_generation_v2_full.jsonl`
- `/data/openclaw/youware_0423/outputs/query_generation_5cats_full_keys3_detach_20260424_014841/productivity-tool/productivity-tool_query_generation_v2_full.jsonl`

> 脚本结束时会额外输出对应 `.json`（同目录、同 run_name）。

### 4) 当前进度快照（写本文件时）
- ai-app: 17 / 939
- education: 18 / 297
- landing-page: 19 / 466
- presentation: 16 / 429
- productivity-tool: 20 / 767

## 六、踩坑记录（下次别再踩）
1. **坑：nohup 启动后看似“秒退”**
   - 现象：PID 很快消失，日志空文件。
   - 根因：任务与当前会话进程组耦合，检查窗口又存在错位（检查了旧目录/旧PID），导致误判。
   - 解决：统一用 `setsid + nohup` 脱离会话；启动后先 `ps` 看 PID，再看“当前 run_root”的日志和 jsonl 行数。

2. **坑：误把小样本输入当成全量在跑**
   - 现象：某些类别显示 0/很小条数。
   - 根因：用了 `inputs/category15_input.json` 的流程（那是样本集，不是全量 S3）。
   - 解决：改为 `generate_query_youware_game_v2.py` + `--s3_base s3://.../youware/<category>` 全量目录。

3. **坑：以为是 key 问题**
   - 现象：怀疑 key 未生效。
   - 事实：脚本支持多 key，必须显式 `--api_keys k1 k2 k3` 才会轮询；仅靠环境变量通常只读一个。

4. **坑：日志无内容不代表没跑**
   - 说明：脚本日志刷新取决于写入点；最可靠指标是 `jsonl` 行数增长与 `ps` 中进程存活。

## 六点五、历史已完成结果（本目录内可直接复用）
以下两个文件是此前已跑完的全量结果，需与当前 5 类任务一起保留：
- `/data/openclaw/youware_0423ni'y'O/outputs/query_generation_game_v2/game_query_generation_v2_full.jsonl`
- `/data/openclaw/youware_0423/outputs/query_generation_game_v2/dashboard_query_generation_v2_full.json`

## 七、交互过程摘要（给后续接手者）
1. 用户先要求 5 类 prompt 强约束改造（已完成）。
2. 用户要求“按 game/dashboard 流程跑 5 类、nohup 一次全跑”（已完成）。
3. 用户进一步要求“参考 `generate_query_youware_game_v2.py` 跑 5 类全量”（已切换到该脚本）。
4. 用户提供 3 个 key，要求轮询（已按 `--api_keys` 生效）。
5. 用户要求清理中间测试数据（已清理，保留正式运行目录）。

## 八、快速检查与接管命令
```bash
# 1) 看5个进程是否还在
ps -fp 1023090,1023092,1023094,1023096,1023098

# 2) 看日志尾部
tail -f /data/openclaw/youware_0423/logs/query_generation_5cats_full_keys3_detach_20260424_014841/*.nohup.log

# 3) 看各类进度（jsonl行数）
for f in /data/openclaw/youware_0423/outputs/query_generation_5cats_full_keys3_detach_20260424_014841/*/*.jsonl; do
  echo "$(basename $(dirname $f)) $(wc -l < $f)"
done

# 4) 停止任务（必要时）
kill 1023090 1023092 1023094 1023096 1023098
```

## 九、重启 SOP（简版）
1. 新建 run_root（带时间戳）。
2. 5 类分别执行 `setsid + nohup` 单类模板。
3. 传入三 key：`--api_keys k1 k2 k3`。
4. `ps` + `jsonl` 行数双重确认运行。
5. 定时记录进度快照，避免误判。
