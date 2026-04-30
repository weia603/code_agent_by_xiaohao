# Memory: Multi-Source Reverse Query Pipeline (2026-04-24)

目录：`/data/openclaw/V0_0423`
主脚本：`/data/openclaw/V0_0423/scripts/run_v0_universal_reverse_query.py`

## 1. 本次会话目标
用户要求：
1. 将多个 S3 数据源用同一 pipeline 做逆向 query 生成。
2. 输出必须按数据源分目录存放，避免混写。
3. 对每个新增数据源先看原始结构，再决定 schema + prompt 是否匹配；不匹配就改脚本和 prompt。
4. prompt 必须包含 category1/category2 的完整映射关系。
5. `feature_query` 不能写成笼统小标题，必须非常详细且体现当前数据特征（字段驱动）。
6. 已在运行生成的任务尽量不改对应 prompt；新增源用新增 prompt。

## 2. 统一输出目录规范
根目录：`/data/openclaw/V0_0423/outputs/universal_reverse_query_full`
按数据源子目录：
- `v0/`
- `templatemo/`
- `framer/`
- `killerportfolio/`
- `commercecream/`
- `siteinspire/`
- `designrush/`
- `nicepage/`
- `landingfolio/`
- `freehtml5/`
- `htmlrev/`
- `tympanus/`

## 3. 脚本改造总结
文件：`/data/openclaw/V0_0423/scripts/run_v0_universal_reverse_query.py`

### 3.1 已支持的 job_source_mode
- `v0_nested`: `<base>/<date>/<category>/*.zip`
- `flat_zip_dir`: `<base>/*.zip`
- `framer_nested`: `<base>/<category>/<id>/...`
- `site_dir_flat`: `<base>/<slug>/...`
- `nested_site_dir`: `<base>/<category>/<slug>/...`
- `htmlrev_repo`: `<base>/<repo>/...`（仓库目录）
- `tympanus_json`: JSON 列表记录（`tympanus.json`）

### 3.2 新增/增强的数据采集函数
- `collect_nested_site_dir_jobs`
- `collect_htmlrev_repo_jobs`
- `collect_tympanus_json_jobs`
- `build_input_payload_from_htmlrev_repo`
- `build_input_payload_from_tympanus_json`

### 3.3 done-map 主键统一
- 使用 `sample_meta.source_path`（兼容 zip 和目录源）作为断点续跑主键。

### 3.4 兼容特性
- 统一支持 `source_kind` 分发 payload 组装。
- 保持 `dry_run`、`overwrite`、`checkpoint`、`response_format_json` 行为一致。

## 4. Prompt 变更总结
本次新增/改写 prompt（均在 `/data/openclaw/V0_0423/prompts/`）：
- `00_query_generation_universal_v1.md`
- `01_query_generation_framer_universal_v1.md`
- `02_query_generation_killerportfolio_v1.md`
- `03_query_generation_commercecream_v1.md`
- `04_query_generation_siteinspire_v1.md`
- `05_query_generation_designrush_v1.md`
- `06_query_generation_nicepage_v1.md`
- `07_query_generation_landingfolio_v1.md`
- `08_query_generation_freehtml5_v1.md`
- `09_query_generation_htmlrev_v1.md`
- `10_query_generation_tympanus_v1.md`

说明：
- 新增 prompt 已包含 category1/category2 允许集合 + 完整一级二级映射。
- 新增 prompt 对 `feature_query` 增加了固定条数和字段驱动细则。
- 对“正在跑任务”的 prompt尽量保持不再反复改动，新增源走新增 prompt。

## 5. 数据源结构结论（本次已探查）

### 已完成/在跑组
- `v0`: 日期/类别/zip（`v0_nested`）
- `templatemo`: 扁平 zip（`flat_zip_dir`）
- `framer`: category/id 目录（`framer_nested`）
- `killerportfolio`: slug 目录（`site_dir_flat`）
- `commercecream`: slug 目录，含 meta/desktop/mobile（`site_dir_flat`）
- `siteinspire`: slug 目录（`site_dir_flat`）

### 本轮新增 6 源
- `designrush`: category/slug 目录（`nested_site_dir`）
- `nicepage`: category/id 目录（`nested_site_dir`）
- `landingfolio`: slug 目录（`site_dir_flat`）
- `freehtml5`: 扁平 zip（`flat_zip_dir`）
- `htmlrev`: 仓库目录（`htmlrev_repo`）
- `tympanus`: `tympanus.json` + `tympanus.zip`，当前按 json 记录跑（`tympanus_json`）

## 6. 运行状态快照（最终总数）

### V0 多源最终结果总数
- v0: `1073`
- templatemo: `626`
- framer: `6614`
- killerportfolio: `183`
- commercecream: `107`
- siteinspire: `6796`
- designrush: `2391`
- nicepage: `21009`
- landingfolio: `635`
- freehtml5: `120`
- htmlrev: `88`
- tympanus: `220`

> 以上以各数据源最终 `.json` 主结果文件中的记录总数为准，而不是中途 checkpoint 或当时的 jsonl 行数快照。

## 7. 关键运行命令模式
统一后台启动（稳定）：`setsid + nohup + </dev/null`

通用模板：
```bash
setsid nohup python /data/openclaw/V0_0423/scripts/run_v0_universal_reverse_query.py \
  --job_source_mode <mode> \
  ...source args... \
  --prompt_path <prompt_path> \
  --out_dir <source_out_dir> \
  --run_name <run_name> \
  --concurrency 2 \
  --rpm 40 \
  --response_format_json \
  </dev/null > /data/openclaw/V0_0423/logs/<run_name>.nohup.log 2>&1 &
```

## 8. 踩坑与处理
1. `nohup` 后日志短时为空，不代表失败；可能在全量收集任务列表阶段。
2. 大目录源（例如 `nicepage`）启动慢，`--limit` 也可能先遍历后截断。
3. 多任务批量 shell 启动偶发“秒退”；改为逐条启动更稳。
4. 进度判断必须三重确认：`ps` + `tail log` + `jsonl行数`。
5. 避免不同源共享同一 `run_name/out_dir`，否则会混写或断点错位。

## 9. 快速检查命令
```bash
# 所有运行中的进程
ps -ef | grep run_v0_universal_reverse_query.py | grep -v grep

# 所有源当前行数
for f in /data/openclaw/V0_0423/outputs/universal_reverse_query_full/*/*.jsonl; do
  echo "$(basename $(dirname "$f")) $(basename "$f") $(wc -l < "$f")"
done | sort

# 单源跟日志
# 示例: designrush
tail -f /data/openclaw/V0_0423/logs/designrush_reverse_query_full_*.nohup.log
```

## 10. 后续接手建议
1. 优先跟进 `nicepage` 与 `designrush` 的启动后稳定写入（大目录源）。
2. 当 `framer/siteinspire` 结束后统一汇总 success/failed 和 category 分布。
3. 如需调整 prompt，先复制新版本文件，不要直接覆盖正在运行 run 使用的 prompt。
