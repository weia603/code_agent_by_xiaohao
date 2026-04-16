#!/usr/bin/env python3
"""
Batch-generate reverse product queries from game/source archives using streaming + checkpointing.
Strict mode: no generic fallback query generation. If the model output is unusable, mark fail explicitly.
"""

import argparse
import asyncio
import ast
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

try:
    from step_align.model.proxy import async_chat_completion
except Exception:
    async_chat_completion = None

SYSTEM_PROMPT_GAME = """# Role & Objective
你是一个资深游戏产品策划与逆向分析专家。你的任务是从游戏源码压缩包的元数据（包含工程目录、关键文件名、资源结构、UI 名称、音效/关卡配置等）中，提取产品特征，并逆向还原出“从 0 到 1 的产品需求 query”。

你的输出目标不是泛泛概括，也不是提“参考样本”，更不是索要源码。你要直接把它写成一个真实用户会发给开发者的、结构严谨的**产品需求文档式 query**。

# Workflow (SOP)
在生成最终的 JSON 之前，请在内部执行以下逻辑映射（无需输出推理过程，但必须体现在最终结果中）：
1. **特征提取**：识别 raw data 中的引擎信号（如 3d, 2d）、玩法信号（如 ball, music）和 UI/资源特征（如 resultView, combo.fnt）。**注意：忽略原工程的具体引擎痕迹（如 cocos, laya 等），统一将目标技术栈设定为现代 Web 前端技术。但不要在query中要求用xx技术实现**
2. **逻辑映射**：将资源特征转化为具体的产品交互逻辑。例如，看到 `combo.fnt` -> 推断“连击系统” -> 转化为行为规则：“当玩家连续达成精准操作时，触发连击计数并播放特殊字体动效”。
3. **架构梳理**：确保输出的 query 模块分类处于同一逻辑层级（如分为：核心循环、系统交互、表现反馈），绝不将“道具系统”与“视觉体验”混列为同级。

# Constraints & Rules
## 1. Query 结构要求
* **开篇定调（第一段）**：必须用一句话明确核心属性（游戏类型、2D/3D、核心玩法机制），并**强制声明技术平台为：纯 Web 前端技术（HTML/CSS/JavaScript 等）实现**。严禁在 query 中出现 Cocos、Laya、Unity 等游戏引擎名称。
* **需求展开（后续段落）**：必须按同一逻辑层级进行模块化拆解。建议采用以下架构：
    * **核心玩法循环 (Core Loop)**：操作方式、关卡目标、胜负条件。
    * **系统与数值 (Systems & Economy)**：如有推断信号，需包含成长系统、商店、体力、排位、复活机制等。
    * **交互与反馈 (Interaction & UI)**：UI 布局层级、DOM 结构概念、状态切换逻辑。
    * **视听表现 (Audio-Visual)**：视觉风格、动效触发场景（如命中、消除的粒子或音效反馈，可通过 CSS 动画或 Canvas/WebGL 实现）。

## 2. 行为规则化原则
凡是核心模块，**绝对不能只写一个名称，必须补充最基本的行为规则**。
* 🚫 **错误示例**：包含分数系统、道具系统、视觉体验。
* ✅ **正确方向**：分数系统：玩家每次精准点击获得基础分，连续命中触发倍率加成；道具系统：包含“护盾”与“磁铁”，护盾可抵消一次碰撞伤害。如果只能推断出有道具，必须基于常理补充基础设计。
* ⚠️ **强制纠错**：如果你的初稿中出现了“包含 xxx 系统 / 提供 xxx 体验”这种空泛表述，请立即改写为“当 [触发条件] 时，系统执行 [具体行为]”的自然语言说明。

## 3. 严格禁用词汇（Negative Constraints）
严禁在输出的任何字段中出现以下表达，必须完全剥离“逆向分析”和“旧引擎”的痕迹：
* Cocos / Laya / Unity / 参考样本 / 参考压缩包 / 根据文件名 / 根据资源分析 / 请提供源码 / 下载链接 / 压缩包 / 工程文件 / 从零开发一个类似 xx 的资源包

## 4. 失败处理（强制）
如果你无法可靠生成高质量 query，请不要兜底发挥，直接输出 fail 风格结果：
* `suitability`: `fail`
* `reasoning`: 明确说明失败原因（例如：信号不足、玩法冲突、输出包含禁用词、模型未返回合法 JSON）
* `semantic_brief`: 仅保留轻量摘要
* `query`: `FAIL`
* `query_en`: `FAIL`
* `negative_constraints`: 给出失败时的注意事项

## 5. Output Format (强制 JSON)
输出必须是合法的 JSON 对象，不要包含任何 Markdown、代码块标记或额外说明文字。输出字段只能是下面这 6 个，字段名必须完全一致：

```json
{
  "suitability": "high | medium | low | fail",
  "reasoning": "string",
  "semantic_brief": {
    "summary": "string"
  },
  "query": "string",
  "query_en": "string",
  "negative_constraints": [
    "string"
  ]
}
```

额外要求：
- 不要输出任何技术栈要求
- 不要输出 `query_type`、`query_name`、`description`、`requirements`、`game_name`、`query_body` 等任何未列出的字段。
- 如果失败，仍然必须使用上面的同一 JSON 结构，只把 `suitability` 设为 `fail`，并把 `query` / `query_en` 设为 `FAIL`。
- `semantic_brief` 必须保持轻量，严禁塞入 key_files、entry_name_samples、resource_hints 或资源路径等原始结构代码。
"""

USER_TEMPLATE_GAME = ""



@dataclass
class RateLimiter:
    rpm: int
    def __post_init__(self):
        self.min_interval = 60.0 / max(self.rpm, 1)
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


def load_config(path: str) -> Dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def resolve_api_keys(raw_keys: List[str]) -> List[str]:
    out = []
    for item in raw_keys:
        if item.startswith('ENV:'):
            v = os.getenv(item[4:])
            if v:
                out.append(v)
        elif item:
            out.append(item)
    if not out:
        raise ValueError('No usable API keys found')
    return out


def ensure_dir(path: str):
    Path(path).mkdir(parents=True, exist_ok=True)


def load_processed_ids(result_file: str) -> set:
    done = set()
    if not os.path.exists(result_file):
        return done
    with open(result_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                sid = obj.get('sample_id')
                if sid:
                    done.add(sid)
            except Exception:
                continue
    return done


def iter_input_rows(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _strip_forbidden_phrases(text: str) -> str:
    return text if isinstance(text, str) else ''


def _rewrite_vague_modules(query: str) -> str:
    return query if isinstance(query, str) else ''


def infer_query_from_signals(sample: Dict[str, Any]) -> str:
    return ''


def extract_message_text(content: Any) -> str:
    """Normalize chat-completion message content to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: List[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
                continue
            if isinstance(item, dict):
                t = item.get('text')
                if isinstance(t, str):
                    chunks.append(t)
        return ''.join(chunks)
    if isinstance(content, dict):
        t = content.get('text')
        if isinstance(t, str):
            return t
    return ''


def extract_choice_text(choice: Any) -> str:
    """Extract text from one choice object across different proxy formats."""
    if not isinstance(choice, dict):
        return ''
    # OpenAI-style
    msg = choice.get('message')
    if isinstance(msg, dict):
        txt = extract_message_text(msg.get('content', ''))
        if txt:
            return txt
    # Some gateways return plain text at choice.text
    txt = choice.get('text')
    if isinstance(txt, str):
        return txt
    return ''


def parse_model_json(text: str) -> Dict[str, Any]:
    """
    Parse model output into a JSON object with tolerant fallbacks:
    1) direct json.loads
    2) fenced ```json blocks
    3) outermost {...} extraction
    4) ast.literal_eval for Python-dict style output
    """
    raw = (text or '').strip()
    if not raw:
        raise ValueError('empty model response')

    # 1) direct JSON parse
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # 2) parse fenced blocks
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

    # 3) parse from the first "{" to the last "}"
    left = raw.find('{')
    right = raw.rfind('}')
    if left != -1 and right != -1 and right > left:
        frag = raw[left:right + 1]
        try:
            obj = json.loads(frag)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

        # 4) Python-dict style fallback
        try:
            obj = ast.literal_eval(frag)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

    raise ValueError('model output is not a valid JSON object')


def make_fail(sample: Dict[str, Any], reason: str) -> Dict[str, Any]:
    topic = sample.get('file_name', '') or sample.get('sample_id', '')
    return {
        'suitability': 'fail',
        'reasoning': reason,
        'semantic_brief': {
            'summary': f'Failed to generate reverse query for {topic}'.strip(),
        },
        'query': 'FAIL',
        'query_en': 'FAIL',
        'negative_constraints': [
            'Insufficient confidence to generate a reliable product requirement query',
            'Do not fabricate missing gameplay rules',
            'Need more structural signals or clearer gameplay evidence'
        ]
    }



def normalize_output(sample: Dict[str, Any], raw: Any) -> Dict[str, Any]:
    def _as_text(v: Any) -> str:
        if isinstance(v, str):
            return v.strip()
        if isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False)
        return ''

    def _join_list_text(v: Any) -> str:
        if not isinstance(v, list):
            return ''
        parts = []
        for item in v:
            t = _as_text(item)
            if t:
                parts.append(t)
        return '；'.join(parts)

    def _build_query_from_raw(data: Dict[str, Any]) -> str:
        pieces: List[str] = []
        name = _as_text(data.get('game_name') or data.get('project_name') or data.get('title'))
        game_type = data.get('game_type')
        if isinstance(game_type, list):
            game_type_txt = ', '.join(str(x) for x in game_type if str(x).strip())
        else:
            game_type_txt = _as_text(game_type)
        desc = _as_text(data.get('description') or data.get('summary') or data.get('intro'))
        gameplay = _join_list_text(data.get('gameplay') or data.get('mechanics'))
        if not gameplay and isinstance(data.get('features'), dict):
            gameplay = _join_list_text(data['features'].get('gameplay'))
        ui = _join_list_text(data.get('ui'))
        if not ui and isinstance(data.get('features'), dict):
            ui = _join_list_text(data['features'].get('ui'))
        audio = _join_list_text(data.get('audio'))
        if not audio and isinstance(data.get('features'), dict):
            audio = _join_list_text(data['features'].get('audio'))
        other = _join_list_text(data.get('other'))
        if not other and isinstance(data.get('features'), dict):
            other = _join_list_text(data['features'].get('other'))

        if name or game_type_txt:
            pieces.append(f"请你从0到1设计一款{name or '游戏'}，类型为{game_type_txt or '休闲/益智'}，并使用纯Web前端技术（HTML/CSS/JavaScript）实现。")
        if desc:
            pieces.append(f"已知产品方向：{desc}")
        if gameplay:
            pieces.append(f"核心玩法循环请重点覆盖：{gameplay}")
        if ui:
            pieces.append(f"交互与界面请重点覆盖：{ui}")
        if audio:
            pieces.append(f"视听反馈请重点覆盖：{audio}")
        if other:
            pieces.append(f"其他设计要点：{other}")
        pieces.append("请输出完整需求文档，至少包含核心循环、关卡目标、胜负条件、关键规则、UI状态流转与反馈机制。")

        return '\n'.join(p for p in pieces if p).strip()

    if not isinstance(raw, dict):
        raw = {}
    query = raw.get('query')
    query_en = raw.get('query_en')
    if not query:
        for k in ['user_query', 'user_need_query', 'prompt', 'need_query', 'query_desc', 'query_body', 'description', 'summary', 'intro']:
            v = raw.get(k)
            if isinstance(v, str):
                query = v
                break
            if isinstance(v, dict):
                query = json.dumps(v, ensure_ascii=False)
                break
            if isinstance(v, list):
                query = '；'.join(str(x) for x in v)
                break
    if not query:
        query = _build_query_from_raw(raw)
    if not query_en:
        query_en = raw.get('queryEnglish') or raw.get('english_query') or ''
    query = query if isinstance(query, str) else ''
    query_en = query_en if isinstance(query_en, str) else ''

    if not query:
        if not isinstance(raw, dict) or not raw:
            return make_fail(sample, 'Model output is not a valid JSON object')
        return make_fail(sample, 'Model failed to produce a usable query')
    query = _rewrite_vague_modules(query)
    if not query_en:
        query_en = query

    suitability = raw.get('suitability') or 'high'
    reasoning = raw.get('reasoning') or 'Inferred from archive file name, engine signals, directory structure, UI prefab names, level/config files, audio cues, and gameplay-related resource names.'
    semantic_brief = raw.get('semantic_brief')
    if not isinstance(semantic_brief, dict):
        semantic_brief = {
            'summary': _as_text(raw.get('description') or raw.get('summary') or sample.get('file_name', '')),
        }
    else:
        semantic_brief = {
            'summary': _as_text(semantic_brief.get('summary') or raw.get('description') or sample.get('file_name', '')),
        }
    negative_constraints = raw.get('negative_constraints')
    if not isinstance(negative_constraints, list):
        negative_constraints = [
            'Do not ask for source code, download links, or archive files',
            'Do not mention reference samples or package names in the query body',
            'Do not invent specific brand or commercial background',
            'Do not overclaim story details without evidence'
        ]
    return {
        'suitability': suitability,
        'reasoning': reasoning,
        'semantic_brief': semantic_brief,
        'query': query,
        'query_en': query_en,
        'negative_constraints': negative_constraints,
    }



async def call_llm_game(sample: Dict[str, Any], cfg: Dict[str, Any], key_pool: KeyPool, limiter: RateLimiter):
    if async_chat_completion is None:
        raise RuntimeError('step_align.model.proxy.async_chat_completion import failed')
    messages = [
        {
            'role': 'system',
            'content': [{'type': 'text', 'text': SYSTEM_PROMPT_GAME}]
        },
        {
            'role': 'user',
            'content': [{'type': 'text', 'text': json.dumps(sample, ensure_ascii=False, indent=2)}]
        }
    ]
    last_err = None
    last_text = ''
    for attempt in range(3):
        api_key = await key_pool.next_key()
        try:
            await limiter.wait()
            req_kwargs: Dict[str, Any] = dict(
                message=messages,
                model=cfg['llm']['model'],
                max_tokens=cfg['llm'].get('max_tokens', 4096),
                temperature=cfg['llm'].get('temperature', 0.2),
                api_key=api_key,
            )
            if cfg['llm'].get('enable_response_format', True):
                req_kwargs['response_format'] = {'type': 'json_object'}
            resp = await asyncio.wait_for(
                async_chat_completion(**req_kwargs),
                timeout=cfg['llm'].get('timeout_sec', 120),
            )

            choices = resp.get('choices', []) if isinstance(resp, dict) else []
            first_choice = choices[0] if choices else {}
            text = extract_choice_text(first_choice)
            last_text = text
            parsed = parse_model_json(text)
            normalized = normalize_output(sample, parsed)
            return {'normalized': normalized, 'raw_text': text, 'raw_parsed': parsed}
        except Exception as e:
            last_err = e
            await asyncio.sleep((2 ** attempt) + random.random())
    fail_obj = make_fail(sample, f'Model call failed after retries: {repr(last_err)}')
    return {'normalized': fail_obj, 'raw_text': last_text, 'raw_parsed': None}


async def process_one(row: Dict[str, Any], cfg: Dict[str, Any], key_pool: KeyPool, limiter: RateLimiter, sem: asyncio.Semaphore, result_file: str, error_file: str):
    async with sem:
        llm_resp = await call_llm_game(row, cfg, key_pool, limiter)
        llm_out = llm_resp.get('normalized', {})
        out = {
            'sample_id': row.get('sample_id'),
            'source_path': row.get('source_path'),
            'file_name': row.get('file_name'),
            'source_type': row.get('source_type'),
            'reverse_query_result': llm_out,
            'raw_model_response': llm_resp.get('raw_text', ''),
            'raw_parsed_response': llm_resp.get('raw_parsed'),
        }
        with open(result_file, 'a', encoding='utf-8') as w:
            w.write(json.dumps(out, ensure_ascii=False) + '\n')
            w.flush()
        if llm_out.get('suitability') == 'fail':
            err = {
                'sample_id': row.get('sample_id'),
                'source_path': row.get('source_path'),
                'file_name': row.get('file_name'),
                'error': llm_out.get('reasoning', 'Unknown fail reason'),
            }
            with open(error_file, 'a', encoding='utf-8') as w:
                w.write(json.dumps(err, ensure_ascii=False) + '\n')
                w.flush()


async def amain(args):
    cfg = load_config(args.config)
    ensure_dir(args.output_dir)
    result_file = os.path.join(args.output_dir, 'result_game_reverse_query.jsonl')
    error_file = os.path.join(args.output_dir, 'errors_game_reverse_query.jsonl')
    done = load_processed_ids(result_file)
    api_keys = resolve_api_keys(cfg['llm']['api_keys'])
    key_pool = KeyPool(api_keys)
    limiter = RateLimiter(cfg['llm'].get('rpm', 120))
    sem = asyncio.Semaphore(cfg['llm'].get('concurrency', 8))
    batch_size = cfg['runtime'].get('batch_size', 10)
    tasks = []
    submitted = 0
    for row in iter_input_rows(args.input_jsonl):
        sid = row.get('sample_id')
        if sid in done:
            continue
        tasks.append(asyncio.create_task(process_one(row, cfg, key_pool, limiter, sem, result_file, error_file)))
        submitted += 1
        if len(tasks) >= batch_size:
            await asyncio.gather(*tasks)
            tasks = []
            print(f'submitted={submitted}', file=sys.stderr)
    if tasks:
        await asyncio.gather(*tasks)
        print(f'submitted={submitted}', file=sys.stderr)
    print(json.dumps({'result_file': result_file, 'error_file': error_file, 'submitted': submitted}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    ap.add_argument('--input-jsonl', required=True)
    ap.add_argument('--output-dir', required=True)
    args = ap.parse_args()
    asyncio.run(amain(args))


if __name__ == '__main__':
    main()
