#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from megfile import smart_open


CATEGORY_MAP: Dict[str, List[str]] = {
    "工程级应用": [
        "AI前端应用",
        "中后台管理",
        "电商",
        "社区",
        "内容平台",
        "富文本编辑器应用",
        "图像编辑应用",
        "视频剪辑工具",
        "即时通讯",
        "低代码/流程引擎应用",
        "跨端应用",
        "桌面应用",
        "物联网和嵌入式",
    ],
    "内容站点": ["博客/新闻", "营销/着陆页", "作品集/官网", "文档/维基"],
    "互动娱乐": ["单页工具", "小游戏", "互动媒体/艺术", "可视化", "SVG"],
}

ALL_C1 = set(CATEGORY_MAP.keys())
ALL_C2 = set(x for v in CATEGORY_MAP.values() for x in v)
C2_TO_C1 = {c2: c1 for c1, arr in CATEGORY_MAP.items() for c2 in arr}


def import_async_chat_completion():
    import sys
    from pathlib import Path as _Path

    import_paths = ["step_align.model.proxy", "step_align.proxy", "proxy"]
    for module_path in import_paths:
        try:
            module = __import__(module_path, fromlist=["async_chat_completion"])
            return getattr(module, "async_chat_completion")
        except (ImportError, AttributeError):
            continue

    potential_paths = [
        _Path("/data/step_align"),
        _Path(__file__).resolve().parent / "step_align",
        _Path(__file__).resolve().parent.parent / "step_align",
        _Path(__file__).resolve().parent.parent.parent / "step_align",
    ]
    for p in potential_paths:
        if not p.exists():
            continue
        sys.path.insert(0, str(p.parent if p.name == "step_align" else p))
        for module_path in import_paths:
            try:
                module = __import__(module_path, fromlist=["async_chat_completion"])
                return getattr(module, "async_chat_completion")
            except (ImportError, AttributeError):
                continue

    raise ImportError("无法导入 async_chat_completion")


async_chat_completion = import_async_chat_completion()


def ts() -> str:
    now = time.localtime()
    return f"{now.tm_mon:02d}-{now.tm_mday:02d} {now.tm_hour:02d}:{now.tm_min:02d}:{now.tm_sec:02d}"


def log(msg: str) -> None:
    print(f"[{ts()}] {msg}", flush=True)


class RateLimiter:
    def __init__(self, rpm: int):
        self.min_interval = 60.0 / max(rpm, 1)
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def wait(self):
        async with self._lock:
            now = time.time()
            delta = now - self._last
            if delta < self.min_interval:
                await asyncio.sleep(self.min_interval - delta)
            self._last = time.time()


class KeyPool:
    def __init__(self, keys: List[str]):
        self.keys = keys
        self.idx = 0
        self.lock = asyncio.Lock()

    async def next_key(self) -> str:
        async with self.lock:
            key = self.keys[self.idx % len(self.keys)]
            self.idx += 1
            return key


def resolve_api_keys(cli_keys: Optional[List[str]]) -> List[str]:
    keys = [k for k in (cli_keys or []) if k]
    if keys:
        return keys
    for env_name in ["API_KEY", "OPENAI_API_KEY", "STEP_ALIGN_API_KEY", "MODEL_PROXY_TOKEN", "LLM_API_KEY"]:
        v = os.getenv(env_name)
        if v:
            return [v]
    return []


def extract_choice_text(resp: Any) -> str:
    if not isinstance(resp, dict):
        return ""
    choices = resp.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    msg = first.get("message")
    if isinstance(msg, dict):
        content = msg.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks: List[str] = []
            for part in content:
                if isinstance(part, str):
                    chunks.append(part)
                elif isinstance(part, dict):
                    t = part.get("text")
                    if isinstance(t, str):
                        chunks.append(t)
            return "".join(chunks)
    txt = first.get("text")
    if isinstance(txt, str):
        return txt
    return ""


def parse_json_object(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty model response")

    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    for m in re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, flags=re.IGNORECASE):
        frag = m.group(1).strip()
        if not frag:
            continue
        try:
            obj = json.loads(frag)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue

    left = raw.find("{")
    right = raw.rfind("}")
    if left != -1 and right != -1 and right > left:
        frag = raw[left : right + 1]
        obj = json.loads(frag)
        if isinstance(obj, dict):
            return obj

    raise ValueError("no valid JSON object found")


def short_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()[:12]


def build_uid(obj: Dict[str, Any], idx_1based: int) -> str:
    prompt = str(obj.get("prompt", ""))
    source_file = str(obj.get("source_file", ""))
    return f"{idx_1based:06d}_{short_hash(source_file + '||' + prompt)}"


def heuristic_category2(prompt: str, old_category: str = "") -> str:
    p = (prompt or "").lower()
    old = (old_category or "").strip().lower()

    kw = [
        ("小游戏", ["游戏", "game", "玩法", "关卡", "boss", "rpg", "platformer", "2048", "unity-like", "phaser"]),
        ("可视化", ["visualize", "visualization", "chart", "dashboard", "kpi", "graph", "plot", "heatmap", "sankey", "地图可视化", "数据可视化"]),
        ("SVG", ["svg", "path", "矢量", "icon set", "icon", "logo animation"]),
        ("互动媒体/艺术", ["3d", "three.js", "webgl", "motion graphics", "generative art", "艺术装置", "沉浸式", "interactive art"]),
        ("电商", ["shop", "store", "ecommerce", "购物车", "下单", "sku", "商品详情", "gmv", "订单"]),
        ("中后台管理", ["admin", "backoffice", "cms", "erp", "crm", "权限", "审批", "管理后台", "报表后台"]),
        ("AI前端应用", ["ai", "llm", "chatbot", "agent", "prompt", "文生图", "大模型", "rag", "copilot"]),
        ("即时通讯", ["chat", "messaging", "im", "群聊", "私聊", "socket", "websocket"]),
        ("图像编辑应用", ["image editor", "photo editor", "抠图", "滤镜", "crop", "retouch", "图像处理"]),
        ("视频剪辑工具", ["video editor", "timeline", "剪辑", "字幕轨", "转场", "关键帧"]),
        ("富文本编辑器应用", ["rich text", "markdown editor", "prosemirror", "slate", "quill", "文档编辑器"]),
        ("低代码/流程引擎应用", ["workflow", "flow builder", "low-code", "drag and drop form builder", "bpmn"]),
        ("跨端应用", ["cross-platform", "pwa", "mobile + desktop", "react native", "tauri"]),
        ("桌面应用", ["desktop app", "electron", "本地客户端", "tray", "窗口管理"]),
        ("物联网和嵌入式", ["iot", "embedded", "firmware", "device", "sensor", "串口", "modbus"]),
        ("社区", ["forum", "community", "帖子", "评论区", "社交", "upvote"]),
        ("内容平台", ["content platform", "creator", "feed", "subscription", "专栏", "内容分发", "媒体库"]),
        ("博客/新闻", ["blog", "news", "article", "作者", "rss", "日报", "新闻站"]),
        ("文档/维基", ["docs", "documentation", "wiki", "knowledge base", "api reference"]),
        ("作品集/官网", ["portfolio", "personal site", "studio", "agency", "showcase", "官网", "案例展示"]),
        ("营销/着陆页", ["landing", "campaign", "cta", "转化", "营销", "获客", "product page"]),
        ("单页工具", ["calculator", "converter", "generator", "todo", "单页", "utility", "tool"]),
    ]

    for c2, words in kw:
        for w in words:
            if w in p:
                return c2

    if old == "data visualization":
        return "可视化"
    if old == "game dev":
        return "小游戏"
    if old == "3d design":
        return "互动媒体/艺术"
    if old == "website":
        return "营销/着陆页"

    return "营销/着陆页"


def normalize_result(parsed: Dict[str, Any], prompt: str, old_category: str = "") -> Tuple[str, str, str]:
    c1 = str(parsed.get("category1", "")).strip()
    c2 = str(parsed.get("category2", "")).strip()
    reason = str(parsed.get("reason", "")).strip()

    if c2 in ALL_C2:
        c1 = C2_TO_C1[c2]
    elif c1 in ALL_C1:
        # c1合法但c2非法，使用heuristic挑一个符合该c1的c2
        hc2 = heuristic_category2(prompt, old_category)
        if hc2 in CATEGORY_MAP[c1]:
            c2 = hc2
        else:
            c2 = CATEGORY_MAP[c1][0]
    else:
        c2 = heuristic_category2(prompt, old_category)
        c1 = C2_TO_C1[c2]

    # 兜底确保严格映射
    if c2 not in ALL_C2:
        c2 = "营销/着陆页"
    c1 = C2_TO_C1[c2]

    return c1, c2, reason


def build_classify_prompt(prompt_text: str, old_category: str) -> str:
    taxonomy = {
        "category1": ["工程级应用", "内容站点", "互动娱乐"],
        "category2": [
            "AI前端应用",
            "中后台管理",
            "电商",
            "社区",
            "内容平台",
            "富文本编辑器应用",
            "图像编辑应用",
            "视频剪辑工具",
            "即时通讯",
            "低代码/流程引擎应用",
            "跨端应用",
            "桌面应用",
            "物联网和嵌入式",
            "博客/新闻",
            "营销/着陆页",
            "作品集/官网",
            "文档/维基",
            "单页工具",
            "小游戏",
            "互动媒体/艺术",
            "可视化",
            "SVG",
        ],
        "mapping": CATEGORY_MAP,
    }

    return (
        "你是网页产品分类器。请仅根据输入 prompt 的产品意图分类。\n"
        "必须严格遵守给定映射，禁止输出映射外标签。\n"
        "输出必须是一个 JSON 对象，且只有这3个字段：category1, category2, reason。\n"
        "reason 20字以内。\n\n"
        f"分类体系: {json.dumps(taxonomy, ensure_ascii=False)}\n\n"
        f"旧标签(仅供参考，可能不准): {old_category}\n"
        f"输入prompt:\n{prompt_text}\n"
    )


async def classify_one(
    *,
    model: str,
    prompt_text: str,
    old_category: str,
    key_pool: KeyPool,
    limiter: RateLimiter,
    max_tokens: int,
    temperature: float,
    top_p: float,
    timeout_sec: int,
    response_format_json: bool,
) -> Tuple[str, str, str, str]:
    system_prompt = (
        "你必须只输出一个合法 JSON 对象，不要输出 markdown，不要输出解释，不要输出代码块。"
        "分类必须使用用户给定标签。"
    )
    user_prompt = build_classify_prompt(prompt_text, old_category)
    messages = [
        {"role": "system", "content": [{"type": "text", "text": system_prompt}]},
        {"role": "user", "content": [{"type": "text", "text": user_prompt}]},
    ]

    last_err: Optional[Exception] = None
    for attempt in range(3):
        api_key = await key_pool.next_key()
        try:
            await limiter.wait()
            kwargs: Dict[str, Any] = {
                "message": messages,
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "n": 1,
                "api_key": api_key,
            }
            if response_format_json:
                kwargs["response_format"] = {"type": "json_object"}

            resp = await asyncio.wait_for(async_chat_completion(**kwargs), timeout=timeout_sec)
            raw_text = extract_choice_text(resp)
            parsed = parse_json_object(raw_text)
            c1, c2, reason = normalize_result(parsed, prompt_text, old_category)
            return c1, c2, reason, raw_text
        except Exception as e:
            last_err = e
            await asyncio.sleep((2 ** attempt) + random.random())

    # failed: fall back heuristic
    c2 = heuristic_category2(prompt_text, old_category)
    c1 = C2_TO_C1[c2]
    return c1, c2, f"fallback:{repr(last_err)[:80]}", ""


def load_records(input_jsonl: str, limit: Optional[int], offset: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with smart_open(input_jsonl, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            obj["_line_no"] = i
            rows.append(obj)

    if offset > 0:
        rows = rows[offset:]
    if limit is not None:
        rows = rows[:limit]
    return rows


def load_done_map(out_jsonl: Path) -> Dict[str, Dict[str, Any]]:
    done: Dict[str, Dict[str, Any]] = {}
    if not out_jsonl.exists():
        return done
    with out_jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            uid = str(obj.get("uid", ""))
            if uid:
                done[uid] = obj
    return done


async def worker(
    worker_id: int,
    queue: asyncio.Queue,
    args: argparse.Namespace,
    key_pool: Optional[KeyPool],
    limiter: Optional[RateLimiter],
    out_jsonl: Path,
    done_map: Dict[str, Dict[str, Any]],
    write_lock: asyncio.Lock,
    stats: Dict[str, int],
    start_time: float,
) -> None:
    while True:
        job = await queue.get()
        if job is None:
            queue.task_done()
            return

        uid = job["uid"]
        old_category = str(job.get("old_category", ""))
        prompt_text = str(job.get("prompt", ""))

        try:
            if args.dry_run:
                c2 = heuristic_category2(prompt_text, old_category)
                c1 = C2_TO_C1[c2]
                reason = "dry_run heuristic"
                raw = ""
            else:
                if key_pool is None or limiter is None:
                    raise RuntimeError("missing key_pool/limiter")
                c1, c2, reason, raw = await classify_one(
                    model=args.model,
                    prompt_text=prompt_text,
                    old_category=old_category,
                    key_pool=key_pool,
                    limiter=limiter,
                    max_tokens=args.max_tokens,
                    temperature=args.temperature,
                    top_p=args.top_p,
                    timeout_sec=args.timeout_sec,
                    response_format_json=args.response_format_json,
                )

            out = {
                "uid": uid,
                "line_no": job.get("line_no"),
                "source_file": job.get("source_file", ""),
                "prompt": prompt_text,
                "old_category": old_category,
                "category1": c1,
                "category2": c2,
                "reason": reason,
                "model": args.model,
            }
            if args.save_raw_output:
                out["raw_response"] = raw
            ok = True
        except Exception as e:
            c2 = heuristic_category2(prompt_text, old_category)
            c1 = C2_TO_C1[c2]
            out = {
                "uid": uid,
                "line_no": job.get("line_no"),
                "source_file": job.get("source_file", ""),
                "prompt": prompt_text,
                "old_category": old_category,
                "category1": c1,
                "category2": c2,
                "reason": f"worker_exception:{str(e)[:180]}",
                "model": args.model,
                "error": str(e),
            }
            ok = False

        async with write_lock:
            with out_jsonl.open("a", encoding="utf-8") as f:
                f.write(json.dumps(out, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            done_map[uid] = out

            stats["done"] += 1
            if ok:
                stats["success"] += 1
            else:
                stats["failed"] += 1

            elapsed = time.time() - start_time
            pct = (stats["done"] / stats["total"] * 100.0) if stats["total"] else 100.0
            log(
                f"[worker={worker_id}] done={stats['done']}/{stats['total']} ({pct:.2f}%) "
                f"success={stats['success']} failed={stats['failed']} elapsed={elapsed:.1f}s uid={uid}"
            )

            if args.checkpoint_every > 0 and stats["done"] % args.checkpoint_every == 0:
                ckpt_path = args.out_dir / f"{args.run_name}.checkpoint_{stats['done']}.json"
                ckpt_path.write_text(
                    json.dumps(list(done_map.values()), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                log(f"[checkpoint] saved={ckpt_path}")

        queue.task_done()


def build_summary(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_c1 = Counter()
    by_c2 = Counter()
    by_pair = Counter()
    invalid_pair = 0
    error_records = 0

    for r in records:
        c1 = str(r.get("category1", ""))
        c2 = str(r.get("category2", ""))
        by_c1[c1] += 1
        by_c2[c2] += 1
        by_pair[f"{c1}/{c2}"] += 1
        if c1 not in ALL_C1 or c2 not in ALL_C2 or c2 not in CATEGORY_MAP.get(c1, []):
            invalid_pair += 1
        if r.get("error"):
            error_records += 1

    total = len(records)
    by_c1_pct = {k: {"count": v, "pct": round(v * 100.0 / total, 4)} for k, v in by_c1.most_common()}
    by_c2_pct = {k: {"count": v, "pct": round(v * 100.0 / total, 4)} for k, v in by_c2.most_common()}

    return {
        "records": total,
        "error_records": error_records,
        "invalid_mapping_pairs": invalid_pair,
        "category1_distribution": by_c1_pct,
        "category2_distribution": by_c2_pct,
        "pair_distribution": dict(by_pair.most_common()),
    }


async def amain(args: argparse.Namespace) -> None:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_jsonl = args.out_dir / f"{args.run_name}.jsonl"
    out_json = args.out_dir / f"{args.run_name}.json"
    out_summary = args.out_dir / f"{args.run_name}.summary.json"

    if args.overwrite:
        for p in [out_jsonl, out_json, out_summary]:
            if p.exists():
                p.unlink()

    rows = await asyncio.to_thread(load_records, args.input_jsonl, args.limit, args.offset)

    jobs: List[Dict[str, Any]] = []
    for rec in rows:
        uid = build_uid(rec, int(rec.get("_line_no", 0)))
        jobs.append(
            {
                "uid": uid,
                "line_no": rec.get("_line_no"),
                "source_file": rec.get("source_file", ""),
                "prompt": rec.get("prompt", ""),
                "old_category": rec.get("category", ""),
            }
        )

    done_map = load_done_map(out_jsonl)
    pending = [j for j in jobs if j["uid"] not in done_map]

    key_pool: Optional[KeyPool] = None
    limiter: Optional[RateLimiter] = None
    if not args.dry_run:
        keys = resolve_api_keys(args.api_keys)
        if not keys:
            raise RuntimeError("missing API key: use --api_keys or env API_KEY/OPENAI_API_KEY/STEP_ALIGN_API_KEY")
        key_pool = KeyPool(keys)
        limiter = RateLimiter(args.rpm)

    stats = {
        "total": len(jobs),
        "done": len(done_map),
        "success": len(done_map),
        "failed": 0,
    }
    start_time = time.time()

    log(
        f"[start] total={len(jobs)} done_existing={len(done_map)} pending={len(pending)} "
        f"model={args.model} concurrency={args.concurrency} rpm={args.rpm} dry_run={args.dry_run}"
    )

    queue: asyncio.Queue = asyncio.Queue()
    for job in pending:
        await queue.put(job)
    for _ in range(args.concurrency):
        await queue.put(None)

    write_lock = asyncio.Lock()
    workers = [
        asyncio.create_task(
            worker(
                worker_id=i + 1,
                queue=queue,
                args=args,
                key_pool=key_pool,
                limiter=limiter,
                out_jsonl=out_jsonl,
                done_map=done_map,
                write_lock=write_lock,
                stats=stats,
                start_time=start_time,
            )
        )
        for i in range(args.concurrency)
    ]

    await queue.join()
    await asyncio.gather(*workers)

    records = list(done_map.values())
    records.sort(key=lambda x: int(x.get("line_no") or 0))

    out_json.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = build_summary(records)
    out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    log(
        f"[done] records={len(records)} success={stats['success']} failed={stats['failed']} "
        f"jsonl={out_jsonl} json={out_json} summary={out_summary}"
    )


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Classify design_arena prompts into category1/category2 with strict mapping")
    ap.add_argument("--input_jsonl", default="s3://renxiaoxiao/code_agent/design_arena/design_arena_vibecoding_new_1723_20260428.jsonl")
    ap.add_argument("--out_dir", default="/data/openclaw/V0_0423/outputs/design_arena_classification", type=Path)
    ap.add_argument("--run_name", default="design_arena_vibecoding_new_1723_20260428_classified")

    ap.add_argument("--model", default="gemini-2.5-pro-thinking")
    ap.add_argument("--api_keys", nargs="*", default=None)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--top_p", type=float, default=1.0)
    ap.add_argument("--max_tokens", type=int, default=300)
    ap.add_argument("--timeout_sec", type=int, default=120)
    ap.add_argument("--response_format_json", action="store_true")

    ap.add_argument("--concurrency", type=int, default=12)
    ap.add_argument("--rpm", type=int, default=240)
    ap.add_argument("--checkpoint_every", type=int, default=200)

    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--dry_run", action="store_true")
    ap.add_argument("--save_raw_output", action="store_true")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(amain(args))


if __name__ == "__main__":
    main()
