# Reverse Query Pipeline Runbook (2026-04-24)

目录：`/data/openclaw/V0_0423`
主脚本：`/data/openclaw/V0_0423/scripts/run_v0_universal_reverse_query.py`

## 1. 这套 Pipeline 能处理哪些数据源结构
统一脚本支持 4 种源模式（`--job_source_mode`）：

1. `v0_nested`
- 结构：`<base>/<date>/<category>/*.zip`
- 典型：`s3://collect-data-text/202511/h5sites_resource/v0`

2. `flat_zip_dir`
- 结构：`<base>/*.zip`
- 典型：`templatemo`

3. `framer_nested`
- 结构：`<base>/<category>/<id>/[index.json,index.html,resource_map.json,...]`
- 典型：`framer`

4. `site_dir_flat`
- 结构：`<base>/<slug>/[index.json/index.html/meta.json/resource_map.json/... ]`
- 典型：`killerportfolio`, `commercecream`

## 2. 当前 prompt 配置
- 通用：`/data/openclaw/V0_0423/prompts/00_query_generation_universal_v1.md`
- Framer 专用：`/data/openclaw/V0_0423/prompts/01_query_generation_framer_universal_v1.md`
- Killerportfolio 专用：`/data/openclaw/V0_0423/prompts/02_query_generation_killerportfolio_v1.md`
- Commercecream 专用：`/data/openclaw/V0_0423/prompts/03_query_generation_commercecream_v1.md`

## 3. 输出目录规范（必须按数据源分开）
统一根目录：`/data/openclaw/V0_0423/outputs/universal_reverse_query_full`

- v0: `.../v0/`
- templatemo: `.../templatemo/`
- framer: `.../framer/`
- killerportfolio: `.../killerportfolio/`
- commercecream: `.../commercecream/`

每个 run 的产物：
- `<run_name>.jsonl`（主结果，断点续跑读取此文件）
- `<run_name>.json`
- `<run_name>.summary.json`

## 4. 稳定启动方式（避免进程秒退）
统一用：`setsid + nohup + </dev/null`。

模板：
```bash
setsid nohup python /data/openclaw/V0_0423/scripts/run_v0_universal_reverse_query.py \
  --job_source_mode <mode> \
  ...source args... \
  --prompt_path <prompt> \
  --out_dir <out_dir> \
  --run_name <run_name> \
  --concurrency 2 \
  --rpm 40 \
  --response_format_json \
  </dev/null > /data/openclaw/V0_0423/logs/<run_name>.nohup.log 2>&1 &
```

## 5. 每种模式最小可用命令
### 5.1 v0_nested
```bash
python /data/openclaw/V0_0423/scripts/run_v0_universal_reverse_query.py \
  --job_source_mode v0_nested \
  --v0_base s3://collect-data-text/202511/h5sites_resource/v0 \
  --include_dates 20260228 20260302 \
  --exclude_date_category 20260302/apps-and-games \
  --prompt_path /data/openclaw/V0_0423/prompts/00_query_generation_universal_v1.md \
  --out_dir /data/openclaw/V0_0423/outputs/universal_reverse_query_full/v0 \
  --run_name v0_universal_reverse_query_full_<timestamp> \
  --concurrency 2 --rpm 40 --response_format_json
```

### 5.2 flat_zip_dir (templatemo)
```bash
python /data/openclaw/V0_0423/scripts/run_v0_universal_reverse_query.py \
  --job_source_mode flat_zip_dir \
  --flat_zip_dir s3://collect-data-text/202511/h5sites_resource/templatemo \
  --flat_source_label templatemo \
  --prompt_path /data/openclaw/V0_0423/prompts/00_query_generation_universal_v1.md \
  --out_dir /data/openclaw/V0_0423/outputs/universal_reverse_query_full/templatemo \
  --run_name templatemo_universal_reverse_query_full_<timestamp> \
  --concurrency 2 --rpm 40 --response_format_json
```

### 5.3 framer_nested
```bash
python /data/openclaw/V0_0423/scripts/run_v0_universal_reverse_query.py \
  --job_source_mode framer_nested \
  --framer_base s3://collect-data-text/202511/h5sites_resource/framer \
  --prompt_path /data/openclaw/V0_0423/prompts/01_query_generation_framer_universal_v1.md \
  --out_dir /data/openclaw/V0_0423/outputs/universal_reverse_query_full/framer \
  --run_name framer_universal_reverse_query_full_<timestamp> \
  --concurrency 2 --rpm 40 --response_format_json
```

### 5.4 site_dir_flat (killerportfolio / commercecream)
```bash
# killerportfolio
python /data/openclaw/V0_0423/scripts/run_v0_universal_reverse_query.py \
  --job_source_mode site_dir_flat \
  --site_dir_base s3://collect-data-text/202511/h5sites_resource/killerportfolio \
  --site_source_label killerportfolio \
  --prompt_path /data/openclaw/V0_0423/prompts/02_query_generation_killerportfolio_v1.md \
  --out_dir /data/openclaw/V0_0423/outputs/universal_reverse_query_full/killerportfolio \
  --run_name killerportfolio_reverse_query_full_<timestamp> \
  --concurrency 2 --rpm 40 --response_format_json

# commercecream
python /data/openclaw/V0_0423/scripts/run_v0_universal_reverse_query.py \
  --job_source_mode site_dir_flat \
  --site_dir_base s3://collect-data-text/202511/h5sites_resource/commercecream \
  --site_source_label commercecream \
  --prompt_path /data/openclaw/V0_0423/prompts/03_query_generation_commercecream_v1.md \
  --out_dir /data/openclaw/V0_0423/outputs/universal_reverse_query_full/commercecream \
  --run_name commercecream_reverse_query_full_<timestamp> \
  --concurrency 2 --rpm 40 --response_format_json
```

## 6. 断点续跑规则
- 断点判断基于 `<run_name>.jsonl`。
- 要续跑：保持同一 `run_name` + 同一 `out_dir`。
- 不要随意 `--overwrite`，否则会清空进度。

## 7. 进度检查（最可靠）
```bash
# 1) 看进程
ps -ef | grep run_v0_universal_reverse_query.py | grep -v grep

# 2) 看日志尾
tail -f /data/openclaw/V0_0423/logs/<run_name>.nohup.log

# 3) 看 jsonl 行数增长
wc -l <out_dir>/<run_name>.jsonl
```

## 8. 已知坑
1. 日志短时无新增不等于挂掉，优先看 jsonl 行数是否增长。
2. 不同数据源必须不同 `out_dir` 和 `run_name`，避免混写。
3. 新数据源先 dry-run（`--dry_run --limit 3`）再全量。
4. 数据结构不匹配时要先探目录，再选 mode/改 prompt，不要硬套 zip 流程。
