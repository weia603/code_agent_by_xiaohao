#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import random
import re
import time
import zipfile
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from megfile import smart_listdir, smart_open

ROOT = Path('/data/openclaw/V0_0423')
DEFAULT_PROMPT_PATH = ROOT / 'prompts' / '00_query_generation_universal_v1.md'
DEFAULT_V0_BASE = 's3://collect-data-text/202511/h5sites_resource/v0'
DEFAULT_OUT_DIR = ROOT / 'outputs' / 'universal_reverse_query_full'


def import_async_chat_completion():
    import sys
    from pathlib import Path as _Path

    import_paths = ['step_align.model.proxy', 'step_align.proxy', 'proxy']
    for module_path in import_paths:
        try:
            module = __import__(module_path, fromlist=['async_chat_completion'])
            return getattr(module, 'async_chat_completion')
        except (ImportError, AttributeError):
            continue

    potential_paths = [
        _Path('/data/step_align'),
        _Path(__file__).resolve().parent / 'step_align',
        _Path(__file__).resolve().parent.parent / 'step_align',
        _Path(__file__).resolve().parent.parent.parent / 'step_align',
    ]
    for p in potential_paths:
        if not p.exists():
            continue
        sys.path.insert(0, str(p.parent if p.name == 'step_align' else p))
        for module_path in import_paths:
            try:
                module = __import__(module_path, fromlist=['async_chat_completion'])
                return getattr(module, 'async_chat_completion')
            except (ImportError, AttributeError):
                continue

    raise ImportError('无法导入 async_chat_completion')


async_chat_completion = import_async_chat_completion()


def ts() -> str:
    now = time.localtime()
    return f'{now.tm_mon:02d}-{now.tm_mday:02d} {now.tm_hour:02d}:{now.tm_min:02d}:{now.tm_sec:02d}'


def log(msg: str) -> None:
    print(f'[{ts()}] {msg}', flush=True)


def normalize_s3_uri(uri: str) -> str:
    u = (uri or '').strip()
    if u.startswith('s3://s3://'):
        u = 's3://' + u[len('s3://s3://') :]
    return u.rstrip('/')


def safe_read_text(path: str, max_chars: int) -> str:
    try:
        with smart_open(path, 'r', encoding='utf-8') as f:
            text = f.read()
        if max_chars > 0 and len(text) > max_chars:
            return text[:max_chars]
        return text
    except Exception:
        return ''


def safe_read_json(path: str) -> Optional[Any]:
    try:
        with smart_open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def html_extract_title(html: str) -> str:
    m = re.search(r'<title[^>]*>([\s\S]*?)</title>', html, flags=re.IGNORECASE)
    return unescape(m.group(1).strip()) if m else ''


def html_extract_meta_description(html: str) -> str:
    m = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]*content=["\']([\s\S]*?)["\']',
        html,
        flags=re.IGNORECASE,
    )
    if not m:
        m = re.search(
            r'<meta[^>]+content=["\']([\s\S]*?)["\'][^>]*name=["\']description["\']',
            html,
            flags=re.IGNORECASE,
        )
    return unescape(m.group(1).strip()) if m else ''


def html_extract_visible_text(html: str, max_chars: int) -> str:
    txt = re.sub(r'<script[\s\S]*?</script>', ' ', html, flags=re.IGNORECASE)
    txt = re.sub(r'<style[\s\S]*?</style>', ' ', txt, flags=re.IGNORECASE)
    txt = re.sub(r'<noscript[\s\S]*?</noscript>', ' ', txt, flags=re.IGNORECASE)
    txt = re.sub(r'<[^>]+>', ' ', txt)
    txt = unescape(txt)
    txt = re.sub(r'\s+', ' ', txt).strip()
    return txt[:max_chars] if max_chars > 0 else txt


def html_dom_summary(html: str) -> Dict[str, Any]:
    lower = html.lower()
    return {
        'contains_canvas': '<canvas' in lower,
        'tag_counts': {
            'canvas': len(re.findall(r'<canvas\b', lower)),
            'button': len(re.findall(r'<button\b', lower)),
            'audio': len(re.findall(r'<audio\b', lower)),
            'video': len(re.findall(r'<video\b', lower)),
            'svg': len(re.findall(r'<svg\b', lower)),
            'img': len(re.findall(r'<img\b', lower)),
        },
    }


def summarize_resource_map(resource_map: Any) -> Dict[str, Any]:
    if not isinstance(resource_map, dict):
        return {'total': 0, 'js': [], 'css': [], 'images': [], 'fonts': [], 'other_count': 0}

    values = [str(v) for v in resource_map.values()]
    js = [v for v in values if v.endswith('.js')]
    css = [v for v in values if v.endswith('.css')]
    images = [v for v in values if re.search(r'\.(png|jpg|jpeg|gif|webp|svg)$', v, flags=re.IGNORECASE)]
    fonts = [v for v in values if re.search(r'\.(woff|woff2|ttf|otf)$', v, flags=re.IGNORECASE)]
    known = set(js + css + images + fonts)
    other_count = len([v for v in values if v not in known])
    return {
        'total': len(values),
        'js': js[:30],
        'css': css[:30],
        'images': images[:50],
        'fonts': fonts[:30],
        'other_count': other_count,
    }


def parse_zip_meta(zip_path: str, v0_base: str) -> Dict[str, str]:
    full = normalize_s3_uri(zip_path)
    base = normalize_s3_uri(v0_base)
    rel = full[len(base) + 1 :] if full.startswith(base + '/') else full
    parts = rel.split('/')
    date = parts[0] if len(parts) > 0 else ''
    source_category = parts[1] if len(parts) > 1 else ''
    slug = re.sub(r'\.zip$', '', parts[-1], flags=re.IGNORECASE) if parts else ''
    return {
        'date': date,
        'source_category': source_category,
        'slug': slug,
    }


def _choose_one(names: List[str], candidates: List[str]) -> str:
    low_to_orig = {n.lower(): n for n in names}
    for c in candidates:
        cl = c.lower()
        if cl in low_to_orig:
            return low_to_orig[cl]
    for c in candidates:
        cl = c.lower()
        matched = [n for n in names if n.lower().endswith('/' + cl) or n.lower().endswith(cl)]
        if matched:
            matched.sort(key=lambda x: (x.count('/'), len(x)))
            return matched[0]
    return ''


def _collect_business_components(names: List[str]) -> List[str]:
    out: List[str] = []
    for n in names:
        ln = n.lower()
        if not ln.endswith(('.tsx', '.ts', '.jsx', '.js')):
            continue
        if '/components/ui/' in ('/' + ln):
            continue
        if (
            '/components/' in ('/' + ln)
            or '/app/components/' in ('/' + ln)
            or '/src/components/' in ('/' + ln)
        ):
            out.append(n)
    out.sort()
    return out


def collect_zip_jobs(v0_base: str, include_dates: List[str], exclude_date_categories: List[str]) -> Tuple[List[Dict[str, str]], List[str]]:
    jobs: List[Dict[str, str]] = []
    skipped: List[str] = []
    exclude_set = set(x.strip('/') for x in exclude_date_categories if x and x.strip('/'))

    for date in include_dates:
        date_path = f"{normalize_s3_uri(v0_base)}/{date}"
        try:
            categories = sorted(smart_listdir(date_path))
        except Exception as e:
            log(f'[warn] list date failed: {date_path} err={e}')
            continue

        for category in categories:
            key = f'{date}/{category}'
            if key in exclude_set:
                skipped.append(key)
                continue

            cat_path = f'{date_path}/{category}'
            try:
                names = smart_listdir(cat_path)
            except Exception as e:
                log(f'[warn] list category failed: {cat_path} err={e}')
                continue

            for name in names:
                if not str(name).lower().endswith('.zip'):
                    continue
                zip_path = f'{cat_path}/{name}'
                meta = parse_zip_meta(zip_path, v0_base)
                jobs.append(
                    {
                        'source_kind': 'zip',
                        'source_path': zip_path,
                        'zip_path': zip_path,
                        'date': meta['date'],
                        'source_category': meta['source_category'],
                        'slug': meta['slug'],
                    }
                )

    jobs.sort(key=lambda x: x['zip_path'])
    return jobs, sorted(set(skipped))


def collect_flat_zip_jobs(flat_zip_dir: str, source_label: str) -> Tuple[List[Dict[str, str]], List[str]]:
    jobs: List[Dict[str, str]] = []
    base = normalize_s3_uri(flat_zip_dir)
    names = smart_listdir(base)
    for name in names:
        n = str(name)
        if not n.lower().endswith('.zip'):
            continue
        slug = re.sub(r'\.zip$', '', n, flags=re.IGNORECASE)
        jobs.append(
            {
                'source_kind': 'zip',
                'source_path': f'{base}/{n}',
                'zip_path': f'{base}/{n}',
                'date': source_label,
                'source_category': source_label,
                'slug': slug,
            }
        )
    jobs.sort(key=lambda x: x['zip_path'])
    return jobs, []


def collect_framer_jobs(
    framer_base: str,
    include_categories: List[str],
    exclude_categories: List[str],
) -> Tuple[List[Dict[str, str]], List[str]]:
    jobs: List[Dict[str, str]] = []
    skipped: List[str] = []
    base = normalize_s3_uri(framer_base)

    all_categories = sorted(smart_listdir(base))
    include_set = set([c.strip() for c in include_categories if c.strip()])
    exclude_set = set([c.strip() for c in exclude_categories if c.strip()])

    if include_set:
        categories = [c for c in all_categories if c in include_set]
    else:
        categories = all_categories

    for category in categories:
        if category in exclude_set:
            skipped.append(category)
            continue
        cat_path = f'{base}/{category}'
        try:
            sample_ids = sorted(smart_listdir(cat_path))
        except Exception as e:
            log(f'[warn] list framer category failed: {cat_path} err={e}')
            continue

        for sid in sample_ids:
            source_path = f'{cat_path}/{sid}'
            jobs.append(
                {
                    'source_kind': 'framer_dir',
                    'source_path': source_path,
                    'date': 'framer',
                    'source_category': category,
                    'slug': str(sid),
                }
            )

    jobs.sort(key=lambda x: x['source_path'])
    return jobs, sorted(set(skipped))


def collect_site_dir_jobs(
    site_dir_base: str,
    source_label: str,
    include_slugs: List[str],
    exclude_slugs: List[str],
) -> Tuple[List[Dict[str, str]], List[str]]:
    jobs: List[Dict[str, str]] = []
    skipped: List[str] = []
    base = normalize_s3_uri(site_dir_base)

    names = sorted(smart_listdir(base))
    include_set = set([x.strip() for x in include_slugs if x.strip()])
    exclude_set = set([x.strip() for x in exclude_slugs if x.strip()])

    if include_set:
        candidates = [n for n in names if n in include_set]
    else:
        candidates = names

    for slug in candidates:
        if slug in exclude_set:
            skipped.append(slug)
            continue
        source_path = f'{base}/{slug}'
        try:
            _ = smart_listdir(source_path)
        except Exception:
            continue
        jobs.append(
            {
                'source_kind': 'site_dir',
                'source_path': source_path,
                'date': source_label,
                'source_category': source_label,
                'slug': str(slug),
            }
        )

    jobs.sort(key=lambda x: x['source_path'])
    return jobs, sorted(set(skipped))


def collect_nested_site_dir_jobs(
    nested_base: str,
    source_label: str,
    include_categories: List[str],
    exclude_categories: List[str],
) -> Tuple[List[Dict[str, str]], List[str]]:
    jobs: List[Dict[str, str]] = []
    skipped: List[str] = []
    base = normalize_s3_uri(nested_base)
    all_categories = sorted(smart_listdir(base))
    include_set = set([x.strip() for x in include_categories if x.strip()])
    exclude_set = set([x.strip() for x in exclude_categories if x.strip()])
    if include_set:
        categories = [c for c in all_categories if c in include_set]
    else:
        categories = all_categories

    for category in categories:
        if category in exclude_set:
            skipped.append(category)
            continue
        cat_path = f'{base}/{category}'
        try:
            slugs = sorted(smart_listdir(cat_path))
        except Exception as e:
            log(f'[warn] list nested category failed: {cat_path} err={e}')
            continue
        for slug in slugs:
            source_path = f'{cat_path}/{slug}'
            try:
                _ = smart_listdir(source_path)
            except Exception:
                continue
            jobs.append(
                {
                    'source_kind': 'site_dir',
                    'source_path': source_path,
                    'date': source_label,
                    'source_category': category,
                    'slug': str(slug),
                }
            )
    jobs.sort(key=lambda x: x['source_path'])
    return jobs, sorted(set(skipped))


def collect_htmlrev_repo_jobs(
    htmlrev_base: str,
    source_label: str,
    include_repos: List[str],
    exclude_repos: List[str],
) -> Tuple[List[Dict[str, str]], List[str]]:
    jobs: List[Dict[str, str]] = []
    skipped: List[str] = []
    base = normalize_s3_uri(htmlrev_base)
    names = sorted(smart_listdir(base))
    include_set = set([x.strip() for x in include_repos if x.strip()])
    exclude_set = set([x.strip() for x in exclude_repos if x.strip()])

    if include_set:
        candidates = [n for n in names if n in include_set]
    else:
        candidates = names

    for repo in candidates:
        if repo in exclude_set:
            skipped.append(repo)
            continue
        # filter out top-level files
        if str(repo).lower().endswith(('.csv', '.json', '.md', '.txt', '.zip')):
            continue
        source_path = f'{base}/{repo}'
        try:
            entries = set(smart_listdir(source_path))
        except Exception:
            continue
        if '.git' not in entries and 'package.json' not in entries and 'README.md' not in entries and 'readme.md' not in {x.lower() for x in entries}:
            continue
        jobs.append(
            {
                'source_kind': 'htmlrev_repo',
                'source_path': source_path,
                'date': source_label,
                'source_category': source_label,
                'slug': str(repo),
            }
        )
    jobs.sort(key=lambda x: x['source_path'])
    return jobs, sorted(set(skipped))


def collect_tympanus_json_jobs(
    tympanus_json_path: str,
    source_label: str,
) -> Tuple[List[Dict[str, str]], List[str]]:
    jobs: List[Dict[str, str]] = []
    obj = safe_read_json(tympanus_json_path)
    if not isinstance(obj, list):
        return jobs, []
    for i, rec in enumerate(obj):
        if not isinstance(rec, dict):
            continue
        title = str(rec.get('title') or '')
        slug_base = re.sub(r'[^a-zA-Z0-9]+', '-', title).strip('-').lower()[:60]
        slug = f'{i:05d}-{slug_base or "sample"}'
        jobs.append(
            {
                'source_kind': 'tympanus_json',
                'source_path': f'{normalize_s3_uri(tympanus_json_path)}#{i}',
                'date': source_label,
                'source_category': source_label,
                'slug': slug,
                'record_index': i,
            }
        )
    return jobs, []


def build_input_payload_from_zip(
    job: Dict[str, str],
    html_chars: int,
    visible_text_chars: int,
    js_files_limit: int,
    js_chars_each: int,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    zip_path = job.get('zip_path') or job.get('source_path', '')
    meta = {
        'slug': job.get('slug', ''),
        'date': job.get('date', ''),
        'source_category': job.get('source_category', ''),
    }

    resource_map: Dict[str, str] = {}
    index_json_obj: Optional[Dict[str, Any]] = None
    js_snippets: List[Dict[str, Any]] = []
    html_rel = ''

    with smart_open(zip_path, 'rb') as fp:
        blob = fp.read()
    zf = zipfile.ZipFile(io.BytesIO(blob))
    names = zf.namelist()

    page_entry = _choose_one(
        names,
        ['app/page.tsx', 'app/page.ts', 'app/page.jsx', 'app/page.js', 'src/app/page.tsx', 'src/app/page.ts'],
    )
    layout_entry = _choose_one(
        names,
        ['app/layout.tsx', 'app/layout.ts', 'app/layout.jsx', 'app/layout.js', 'src/app/layout.tsx', 'src/app/layout.ts'],
    )
    globals_entry = _choose_one(names, ['app/globals.css', 'src/app/globals.css'])
    package_entry = _choose_one(names, ['package.json'])

    html_candidates = [n for n in names if n.lower().endswith('index.html')]
    if html_candidates:
        html_rel = sorted(html_candidates, key=lambda x: (x.count('/'), len(x)))[0]

    json_candidates = [n for n in names if n.lower().endswith('index.json')]
    if json_candidates:
        idx_json_rel = sorted(json_candidates, key=lambda x: (x.count('/'), len(x)))[0]
        try:
            obj = json.loads(zf.read(idx_json_rel).decode('utf-8', errors='ignore'))
            if isinstance(obj, dict):
                index_json_obj = obj
        except Exception:
            index_json_obj = None

    for n in names:
        lower = n.lower()
        if lower.endswith(('.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.woff', '.woff2', '.ttf', '.otf')):
            resource_map[n] = n

    resource_summary = summarize_resource_map(resource_map)

    def read_text_from_zip(rel: str, limit: int) -> str:
        if not rel:
            return ''
        try:
            txt = zf.read(rel).decode('utf-8', errors='ignore')
            return txt[: max(limit, 0)] if limit > 0 else txt
        except Exception:
            return ''

    page_text = read_text_from_zip(page_entry, 18000)
    layout_text = read_text_from_zip(layout_entry, 12000)
    globals_text = read_text_from_zip(globals_entry, 8000)
    package_text = read_text_from_zip(package_entry, 12000)
    index_html = read_text_from_zip(html_rel, html_chars)

    business_components = _collect_business_components(names)
    for rel in business_components[: max(js_files_limit, 0)]:
        snippet = read_text_from_zip(rel, js_chars_each)
        js_snippets.append({'path': rel, 'head_snippet': snippet, 'snippet_chars': len(snippet)})

    html_title = html_extract_title(index_html) if index_html else ''
    meta_description = html_extract_meta_description(index_html) if index_html else ''
    source_concat = '\n\n'.join([page_text, layout_text, globals_text, package_text]).strip()
    html_visible = html_extract_visible_text(index_html, visible_text_chars) if index_html else ''
    visible_text = source_concat[:visible_text_chars] if source_concat else html_visible
    dom_summary = html_dom_summary(index_html) if index_html else {
        'contains_canvas': False,
        'tag_counts': {'canvas': 0, 'button': 0, 'audio': 0, 'video': 0, 'svg': 0, 'img': 0},
    }

    title = str((index_json_obj or {}).get('title') or html_title or '')
    summary = str((index_json_obj or {}).get('description') or meta_description or '')
    site_url = str((index_json_obj or {}).get('site_url') or '')
    project_url = str((index_json_obj or {}).get('project_url') or '')

    payload = {
        'id': meta['slug'],
        'title': title,
        'summary': summary,
        'text': visible_text,
        'visible_text': visible_text,
        'dom_summary': dom_summary,
        'ocr_text': '',
        'meta_description': meta_description,
        'image_caption': '',
        'preset_category': meta['source_category'],
        'source_paths': {
            'zip_path': zip_path,
            'index_html': html_rel,
            'resource_map': 'in-zip-derived',
        },
        'code_evidence': {
            'resource_summary': resource_summary,
            'js_snippets': js_snippets,
            'index_json': index_json_obj,
            'source_first': {
                'page_entry': page_entry,
                'layout_entry': layout_entry,
                'globals_entry': globals_entry,
                'package_entry': package_entry,
                'business_components_count': len(business_components),
                'business_components_sample': business_components[:20],
                'page_head': page_text[:3000],
                'layout_head': layout_text[:2000],
                'globals_head': globals_text[:1500],
                'package_head': package_text[:2000],
            },
        },
    }
    sample_meta = {
        'slug': meta['slug'],
        'title': title,
        'source_path': zip_path,
        'zip_path': zip_path,
        'date': meta['date'],
        'source_category': meta['source_category'],
        'site_url': site_url,
        'project_url': project_url,
    }
    return payload, sample_meta


def build_input_payload_from_framer_dir(
    job: Dict[str, str],
    html_chars: int,
    visible_text_chars: int,
    js_files_limit: int,
    js_chars_each: int,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    source_path = job['source_path']
    meta = {
        'slug': job.get('slug', ''),
        'date': job.get('date', 'framer'),
        'source_category': job.get('source_category', ''),
    }

    index_json_path = f'{source_path}/index.json'
    index_html_path = f'{source_path}/index.html'
    resource_map_path = f'{source_path}/resource_map.json'
    failed_urls_path = f'{source_path}/failed_urls.json'

    index_json_obj = safe_read_json(index_json_path)
    resource_map = safe_read_json(resource_map_path)
    failed_urls = safe_read_json(failed_urls_path)
    index_html = safe_read_text(index_html_path, html_chars)

    html_title = html_extract_title(index_html) if index_html else ''
    meta_description = html_extract_meta_description(index_html) if index_html else ''
    visible_text = html_extract_visible_text(index_html, visible_text_chars) if index_html else ''
    dom_summary = html_dom_summary(index_html) if index_html else {
        'contains_canvas': False,
        'tag_counts': {'canvas': 0, 'button': 0, 'audio': 0, 'video': 0, 'svg': 0, 'img': 0},
    }

    resource_summary = summarize_resource_map(resource_map)

    js_snippets: List[Dict[str, Any]] = []
    for rel in resource_summary.get('js', [])[: max(js_files_limit, 0)]:
        rel_norm = str(rel).lstrip('/')
        js_path = f'{source_path}/{rel_norm}'
        snippet = safe_read_text(js_path, js_chars_each)
        js_snippets.append({'path': rel_norm, 'head_snippet': snippet, 'snippet_chars': len(snippet)})

    index_title = ''
    summary = ''
    site_url = ''
    project_url = ''
    creator = ''
    published_url = ''
    price = ''
    category_field = ''

    if isinstance(index_json_obj, dict):
        index_title = str(index_json_obj.get('title') or index_json_obj.get('metaTitle') or '')
        summary = str(index_json_obj.get('description') or '')
        site_url = str(index_json_obj.get('site_url') or '')
        project_url = str(index_json_obj.get('project_url') or '')
        creator = str(index_json_obj.get('creator') or '')
        published_url = str(index_json_obj.get('publishedUrl') or '')
        price = str(index_json_obj.get('price') or '')
        category_field = str(index_json_obj.get('category') or '')

    top_entries = []
    folder_counts: Dict[str, int] = {}
    try:
        names = sorted(smart_listdir(source_path))
        top_entries = names[:50]
        for d in ['images', 'fonts', 'js', 'videos']:
            try:
                folder_counts[d] = len(smart_listdir(f'{source_path}/{d}'))
            except Exception:
                folder_counts[d] = 0
    except Exception:
        names = []

    failed_url_count = len(failed_urls) if isinstance(failed_urls, list) else 0
    failed_url_sample = failed_urls[:10] if isinstance(failed_urls, list) else []

    summary_text = summary or meta_description
    title = index_title or html_title

    payload = {
        'id': meta['slug'],
        'title': title,
        'summary': summary_text,
        'text': visible_text,
        'visible_text': visible_text,
        'dom_summary': dom_summary,
        'ocr_text': '',
        'meta_description': meta_description,
        'image_caption': '',
        'preset_category': meta['source_category'],
        'source_paths': {
            'source_path': source_path,
            'index_json': index_json_path,
            'index_html': index_html_path,
            'resource_map': resource_map_path,
            'failed_urls': failed_urls_path,
        },
        'code_evidence': {
            'resource_summary': resource_summary,
            'js_snippets': js_snippets,
            'index_json': index_json_obj,
            'framer_signals': {
                'dataset_category_dir': meta['source_category'],
                'index_json_category': category_field,
                'creator': creator,
                'price': price,
                'published_url': published_url,
                'site_url': site_url,
                'top_entries': top_entries,
                'folder_counts': folder_counts,
                'failed_url_count': failed_url_count,
                'failed_url_sample': failed_url_sample,
            },
        },
    }
    sample_meta = {
        'slug': meta['slug'],
        'title': title,
        'source_path': source_path,
        'date': meta['date'],
        'source_category': meta['source_category'],
        'site_url': site_url or published_url,
        'project_url': project_url,
    }
    return payload, sample_meta


def _get_desc_text(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        parts = [str(x) for x in obj if str(x).strip()]
        return '\n'.join(parts)
    return ''


def build_input_payload_from_site_dir(
    job: Dict[str, str],
    html_chars: int,
    visible_text_chars: int,
    js_files_limit: int,
    js_chars_each: int,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    source_path = job['source_path']
    meta = {
        'slug': job.get('slug', ''),
        'date': job.get('date', ''),
        'source_category': job.get('source_category', ''),
    }

    index_json_path = f'{source_path}/index.json'
    meta_json_path = f'{source_path}/meta.json'
    index_html_path = f'{source_path}/index.html'
    resource_map_path = f'{source_path}/resource_map.json'
    failed_urls_path = f'{source_path}/failed_urls.json'
    desktop_jpg_path = f'{source_path}/desktop.jpg'
    mobile_jpg_path = f'{source_path}/mobile.jpg'
    index_png_path = f'{source_path}/index.png'

    index_json_obj = safe_read_json(index_json_path)
    meta_json_obj = safe_read_json(meta_json_path)
    resource_map = safe_read_json(resource_map_path)
    failed_urls = safe_read_json(failed_urls_path)
    index_html = safe_read_text(index_html_path, html_chars)

    html_title = html_extract_title(index_html) if index_html else ''
    meta_description = html_extract_meta_description(index_html) if index_html else ''
    html_visible = html_extract_visible_text(index_html, visible_text_chars) if index_html else ''
    dom_summary = html_dom_summary(index_html) if index_html else {
        'contains_canvas': False,
        'tag_counts': {'canvas': 0, 'button': 0, 'audio': 0, 'video': 0, 'svg': 0, 'img': 0},
    }

    resource_summary = summarize_resource_map(resource_map)

    js_snippets: List[Dict[str, Any]] = []
    for rel in resource_summary.get('js', [])[: max(js_files_limit, 0)]:
        rel_norm = str(rel).lstrip('/')
        js_path = f'{source_path}/{rel_norm}'
        snippet = safe_read_text(js_path, js_chars_each)
        js_snippets.append({'path': rel_norm, 'head_snippet': snippet, 'snippet_chars': len(snippet)})

    title = ''
    summary = ''
    site_url = ''
    project_url = ''
    name = ''
    agency = ''

    if isinstance(index_json_obj, dict):
        title = str(index_json_obj.get('title') or index_json_obj.get('metaTitle') or '')
        desc = index_json_obj.get('descriptions')
        summary = _get_desc_text(desc) or str(index_json_obj.get('description') or '')
        site_url = str(index_json_obj.get('site_url') or index_json_obj.get('url') or '')
        project_url = str(index_json_obj.get('project_url') or '')
        name = str(index_json_obj.get('name') or '')
        agency = str(index_json_obj.get('agency') or '')
    if isinstance(meta_json_obj, dict):
        if not title:
            title = str(meta_json_obj.get('title') or '')
        if not summary:
            summary = str(meta_json_obj.get('description') or '')
        if not site_url:
            site_url = str(meta_json_obj.get('site_url') or meta_json_obj.get('url') or '')
        if not name:
            name = str(meta_json_obj.get('name') or '')
        if not agency:
            agency = str(meta_json_obj.get('agency') or '')

    title = title or html_title or name
    summary = summary or meta_description

    visible_text = html_visible
    if not visible_text:
        fallback_parts = [title, summary, name, agency, site_url]
        visible_text = '\n'.join([x for x in fallback_parts if x])[:visible_text_chars]

    failed_url_count = len(failed_urls) if isinstance(failed_urls, list) else 0
    failed_url_sample = failed_urls[:10] if isinstance(failed_urls, list) else []

    file_presence: Dict[str, bool] = {}
    for fn in ['index.html', 'index.json', 'meta.json', 'resource_map.json', 'failed_urls.json', 'desktop.jpg', 'mobile.jpg', 'index.png']:
        file_presence[fn] = bool(safe_read_text(f'{source_path}/{fn}', 1)) if fn.endswith(('.html', '.json')) else False
    # Images are binary; existence via listdir check
    try:
        entries = set(smart_listdir(source_path))
    except Exception:
        entries = set()
    for fn in ['desktop.jpg', 'mobile.jpg', 'index.png']:
        file_presence[fn] = fn in entries

    payload = {
        'id': meta['slug'],
        'title': title,
        'summary': summary,
        'text': visible_text,
        'visible_text': visible_text,
        'dom_summary': dom_summary,
        'ocr_text': '',
        'meta_description': meta_description,
        'image_caption': '',
        'preset_category': meta['source_category'],
        'source_paths': {
            'source_path': source_path,
            'index_json': index_json_path,
            'meta_json': meta_json_path,
            'index_html': index_html_path,
            'resource_map': resource_map_path,
            'failed_urls': failed_urls_path,
            'desktop_jpg': desktop_jpg_path,
            'mobile_jpg': mobile_jpg_path,
            'index_png': index_png_path,
        },
        'code_evidence': {
            'resource_summary': resource_summary,
            'js_snippets': js_snippets,
            'index_json': index_json_obj,
            'meta_json': meta_json_obj,
            'site_signals': {
                'source_label': meta['source_category'],
                'name': name,
                'agency': agency,
                'site_url': site_url,
                'file_presence': file_presence,
                'failed_url_count': failed_url_count,
                'failed_url_sample': failed_url_sample,
            },
        },
    }
    sample_meta = {
        'slug': meta['slug'],
        'title': title,
        'source_path': source_path,
        'date': meta['date'],
        'source_category': meta['source_category'],
        'site_url': site_url,
        'project_url': project_url,
    }
    return payload, sample_meta


def build_input_payload_from_htmlrev_repo(
    job: Dict[str, str],
    html_chars: int,
    visible_text_chars: int,
    js_files_limit: int,
    js_chars_each: int,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    source_path = job['source_path']
    slug = job.get('slug', '')
    readme_text = safe_read_text(f'{source_path}/README.md', 30000) or safe_read_text(f'{source_path}/readme.md', 30000)
    package_json = safe_read_json(f'{source_path}/package.json')
    index_html = safe_read_text(f'{source_path}/index.html', html_chars)

    html_title = html_extract_title(index_html) if index_html else ''
    meta_description = html_extract_meta_description(index_html) if index_html else ''
    html_visible = html_extract_visible_text(index_html, visible_text_chars) if index_html else ''
    dom_summary = html_dom_summary(index_html) if index_html else {
        'contains_canvas': False,
        'tag_counts': {'canvas': 0, 'button': 0, 'audio': 0, 'video': 0, 'svg': 0, 'img': 0},
    }

    try:
        entries = sorted(smart_listdir(source_path))
    except Exception:
        entries = []
    entry_set = set(entries)
    lower = {x.lower() for x in entries}

    framework_signals = {
        'has_next': 'next.config.js' in lower or 'next.config.mjs' in lower,
        'has_astro': 'astro.config.mjs' in lower or 'astro.config.ts' in lower,
        'has_vite': 'vite.config.js' in lower or 'vite.config.ts' in lower,
        'has_nuxt': 'nuxt.config.js' in lower or 'nuxt.config.ts' in lower,
        'has_gatsby': 'gatsby-config.js' in lower or 'gatsby-config.ts' in lower,
        'has_src': 'src' in entry_set,
        'has_public': 'public' in entry_set,
    }

    pkg_name = ''
    pkg_desc = ''
    deps_sample: List[str] = []
    if isinstance(package_json, dict):
        pkg_name = str(package_json.get('name') or '')
        pkg_desc = str(package_json.get('description') or '')
        deps = package_json.get('dependencies') or {}
        if isinstance(deps, dict):
            deps_sample = list(deps.keys())[:30]

    title = html_title or pkg_name or slug
    summary = pkg_desc or ''
    if not summary and readme_text:
        summary = readme_text[:1200]
    summary = summary or meta_description
    visible_text = html_visible or (readme_text[:visible_text_chars] if readme_text else '')

    payload = {
        'id': slug,
        'title': title,
        'summary': summary,
        'text': visible_text,
        'visible_text': visible_text,
        'dom_summary': dom_summary,
        'ocr_text': '',
        'meta_description': meta_description,
        'image_caption': '',
        'preset_category': job.get('source_category', 'htmlrev'),
        'source_paths': {
            'source_path': source_path,
            'readme': f'{source_path}/README.md',
            'package_json': f'{source_path}/package.json',
            'index_html': f'{source_path}/index.html',
        },
        'code_evidence': {
            'index_json': None,
            'meta_json': None,
            'resource_summary': {
                'total': len(entries),
                'js': [],
                'css': [],
                'images': [],
                'fonts': [],
                'other_count': len(entries),
            },
            'js_snippets': [],
            'htmlrev_signals': {
                'framework_signals': framework_signals,
                'root_entries_sample': entries[:60],
                'package_name': pkg_name,
                'dependencies_sample': deps_sample,
                'readme_head': readme_text[:5000],
            },
        },
    }
    sample_meta = {
        'slug': slug,
        'title': title,
        'source_path': source_path,
        'date': job.get('date', 'htmlrev'),
        'source_category': job.get('source_category', 'htmlrev'),
        'site_url': '',
        'project_url': '',
    }
    return payload, sample_meta


def build_input_payload_from_tympanus_json(
    job: Dict[str, str],
    tympanus_json_path: str,
    visible_text_chars: int,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    obj = safe_read_json(tympanus_json_path)
    idx = int(job.get('record_index', 0))
    if not isinstance(obj, list) or idx >= len(obj):
        raise ValueError(f'tympanus record not found index={idx}')
    rec = obj[idx]
    if not isinstance(rec, dict):
        raise ValueError(f'tympanus record invalid index={idx}')

    title = str(rec.get('title') or '')
    desc = str(rec.get('description') or '')
    url = str(rec.get('url') or '')
    keyword = rec.get('keyword')
    html_content = str(rec.get('html_content') or '')
    css_content = str(rec.get('css_content') or '')
    js_content = str(rec.get('js_content') or '')
    code_concat = '\n\n'.join([html_content[:12000], css_content[:12000], js_content[:18000]]).strip()
    visible_text = '\n'.join([title, desc, str(keyword or ''), code_concat[:visible_text_chars]]).strip()[:visible_text_chars]

    payload = {
        'id': job.get('slug', f'tympanus-{idx}'),
        'title': title,
        'summary': desc,
        'text': visible_text,
        'visible_text': visible_text,
        'dom_summary': {
            'contains_canvas': '<canvas' in html_content.lower(),
            'tag_counts': {
                'canvas': html_content.lower().count('<canvas'),
                'button': html_content.lower().count('<button'),
                'audio': html_content.lower().count('<audio'),
                'video': html_content.lower().count('<video'),
                'svg': html_content.lower().count('<svg'),
                'img': html_content.lower().count('<img'),
            },
        },
        'ocr_text': '',
        'meta_description': desc,
        'image_caption': '',
        'preset_category': job.get('source_category', 'tympanus'),
        'source_paths': {
            'source_path': job.get('source_path', ''),
            'tympanus_json': tympanus_json_path,
            'record_index': idx,
        },
        'code_evidence': {
            'resource_summary': {
                'total': 0,
                'js': [],
                'css': [],
                'images': [],
                'fonts': [],
                'other_count': 0,
            },
            'js_snippets': [{'path': 'inline_js', 'head_snippet': js_content[:12000], 'snippet_chars': len(js_content[:12000])}],
            'index_json': {
                'url': url,
                'keyword': keyword,
            },
            'tympanus_signals': {
                'url': url,
                'keyword': keyword,
                'html_head': html_content[:4000],
                'css_head': css_content[:4000],
                'js_head': js_content[:6000],
            },
        },
    }
    sample_meta = {
        'slug': job.get('slug', f'tympanus-{idx}'),
        'title': title,
        'source_path': job.get('source_path', ''),
        'date': job.get('date', 'tympanus'),
        'source_category': job.get('source_category', 'tympanus'),
        'site_url': url,
        'project_url': '',
    }
    return payload, sample_meta


def extract_choice_text(resp: Any) -> str:
    if not isinstance(resp, dict):
        return ''
    choices = resp.get('choices')
    if not isinstance(choices, list) or not choices:
        return ''
    first = choices[0]
    if not isinstance(first, dict):
        return ''
    msg = first.get('message')
    if isinstance(msg, dict):
        content = msg.get('content', '')
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks: List[str] = []
            for part in content:
                if isinstance(part, str):
                    chunks.append(part)
                elif isinstance(part, dict):
                    t = part.get('text')
                    if isinstance(t, str):
                        chunks.append(t)
            return ''.join(chunks)
    txt = first.get('text')
    if isinstance(txt, str):
        return txt
    return ''


def parse_json_object(text: str) -> Dict[str, Any]:
    raw = (text or '').strip()
    if not raw:
        raise ValueError('empty model response')

    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    for m in re.finditer(r'```(?:json)?\s*([\s\S]*?)\s*```', raw, flags=re.IGNORECASE):
        frag = m.group(1).strip()
        if not frag:
            continue
        try:
            obj = json.loads(frag)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue

    left = raw.find('{')
    right = raw.rfind('}')
    if left != -1 and right != -1 and right > left:
        frag = raw[left : right + 1]
        obj = json.loads(frag)
        if isinstance(obj, dict):
            return obj

    raise ValueError('no valid JSON object found')


def normalize_generated(generated: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(generated or {})

    for key in [
        'product_query',
        'feature_query',
        'reason',
        'category1',
        'category2',
        'category_decision_reason',
    ]:
        v = out.get(key, '')
        out[key] = v if isinstance(v, str) else str(v)

    if not out['category1'].strip():
        out['category1'] = '未判定'
    if not out['category2'].strip():
        out['category2'] = '未判定'

    out['is_complete'] = bool(out.get('is_complete', False))

    queries = out.get('queries', [])
    if not isinstance(queries, list):
        queries = []
    queries = [str(x) for x in queries if str(x).strip()]
    if len(queries) > 4:
        queries = queries[:4]
    out['queries'] = queries

    return out


def load_done_map(out_jsonl: Path) -> Dict[str, Dict[str, Any]]:
    done: Dict[str, Dict[str, Any]] = {}
    if not out_jsonl.exists():
        return done
    with out_jsonl.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            sm = obj.get('sample_meta', {})
            source_path = ''
            if isinstance(sm, dict):
                source_path = str(sm.get('source_path') or sm.get('zip_path') or '')
            if source_path:
                done[source_path] = obj
    return done


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


def resolve_api_keys(cli_keys: Optional[List[str]]) -> List[str]:
    keys = [k for k in (cli_keys or []) if k]
    if keys:
        return keys
    for env_name in ['API_KEY', 'OPENAI_API_KEY', 'STEP_ALIGN_API_KEY', 'MODEL_PROXY_TOKEN', 'LLM_API_KEY']:
        v = os.getenv(env_name)
        if v:
            return [v]
    return []


async def generate_one(
    model: str,
    prompt_text: str,
    payload: Dict[str, Any],
    key_pool: KeyPool,
    limiter: RateLimiter,
    max_tokens: int,
    temperature: float,
    top_p: float,
    timeout_sec: int,
    response_format_json: bool,
) -> Tuple[Dict[str, Any], str]:
    system_prompt = (
        '你必须只输出一个合法 JSON 对象，不要输出 markdown，不要输出解释，不要输出代码块。'
        '严格按照用户给定规则填写字段。'
    )
    user_prompt = prompt_text.strip() + '\n\n输入样本：\n' + json.dumps(payload, ensure_ascii=False, indent=2)
    messages = [
        {'role': 'system', 'content': [{'type': 'text', 'text': system_prompt}]},
        {'role': 'user', 'content': [{'type': 'text', 'text': user_prompt}]},
    ]

    last_err: Optional[Exception] = None
    for attempt in range(3):
        api_key = await key_pool.next_key()
        try:
            await limiter.wait()
            kwargs: Dict[str, Any] = {
                'message': messages,
                'model': model,
                'max_tokens': max_tokens,
                'temperature': temperature,
                'top_p': top_p,
                'n': 1,
                'api_key': api_key,
            }
            if response_format_json:
                kwargs['response_format'] = {'type': 'json_object'}

            resp = await asyncio.wait_for(async_chat_completion(**kwargs), timeout=timeout_sec)
            text = extract_choice_text(resp)
            parsed = parse_json_object(text)
            return normalize_generated(parsed), text
        except Exception as e:
            last_err = e
            await asyncio.sleep((2 ** attempt) + random.random())

    raise RuntimeError(f'model call failed after retries: {repr(last_err)}')


async def worker(
    worker_id: int,
    queue: asyncio.Queue,
    prompt_text: str,
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

        source_path = str(job.get('source_path') or job.get('zip_path') or '')
        try:
            source_kind = str(job.get('source_kind', 'zip'))
            if source_kind == 'framer_dir':
                payload, sample_meta = await asyncio.to_thread(
                    build_input_payload_from_framer_dir,
                    job,
                    args.html_chars,
                    args.visible_text_chars,
                    args.js_files_limit,
                    args.js_chars_each,
                )
            elif source_kind == 'site_dir':
                payload, sample_meta = await asyncio.to_thread(
                    build_input_payload_from_site_dir,
                    job,
                    args.html_chars,
                    args.visible_text_chars,
                    args.js_files_limit,
                    args.js_chars_each,
                )
            elif source_kind == 'htmlrev_repo':
                payload, sample_meta = await asyncio.to_thread(
                    build_input_payload_from_htmlrev_repo,
                    job,
                    args.html_chars,
                    args.visible_text_chars,
                    args.js_files_limit,
                    args.js_chars_each,
                )
            elif source_kind == 'tympanus_json':
                payload, sample_meta = await asyncio.to_thread(
                    build_input_payload_from_tympanus_json,
                    job,
                    args.tympanus_json_path,
                    args.visible_text_chars,
                )
            else:
                payload, sample_meta = await asyncio.to_thread(
                    build_input_payload_from_zip,
                    job,
                    args.html_chars,
                    args.visible_text_chars,
                    args.js_files_limit,
                    args.js_chars_each,
                )

            if args.dry_run:
                generated = {
                    'product_query': '',
                    'feature_query': '',
                    'is_complete': False,
                    'reason': 'dry_run mode: skip LLM call',
                    'category1': '未判定',
                    'category2': '未判定',
                    'category_decision_reason': 'dry_run mode',
                    'queries': [],
                }
                raw_text = ''
            else:
                if key_pool is None or limiter is None:
                    raise RuntimeError('key pool / limiter missing while dry_run is False')
                generated, raw_text = await generate_one(
                    model=args.model,
                    prompt_text=prompt_text,
                    payload=payload,
                    key_pool=key_pool,
                    limiter=limiter,
                    max_tokens=args.max_tokens,
                    temperature=args.temperature,
                    top_p=args.top_p,
                    timeout_sec=args.timeout_sec,
                    response_format_json=args.response_format_json,
                )

            out_obj: Dict[str, Any] = {
                'sample_meta': sample_meta,
                'generated_query': generated,
                'category1': generated.get('category1', '未判定'),
                'category2': generated.get('category2', '未判定'),
                'model': args.model,
                'prompt_path': str(args.prompt_path),
            }
            if args.save_raw_output:
                out_obj['raw_response'] = raw_text
            if args.save_input_payload:
                out_obj['input_payload'] = payload
            ok = True
        except Exception as e:
            out_obj = {
                'sample_meta': {
                    'source_path': source_path,
                    'zip_path': source_path if source_path.endswith('.zip') else '',
                    'slug': job.get('slug', ''),
                    'date': job.get('date', ''),
                    'source_category': job.get('source_category', ''),
                },
                'error': str(e),
                'generated_query': {
                    'product_query': '',
                    'feature_query': '',
                    'is_complete': False,
                    'reason': str(e),
                    'category1': '错误',
                    'category2': '错误',
                    'category_decision_reason': 'worker exception',
                    'queries': [],
                },
                'category1': '错误',
                'category2': '错误',
                'model': args.model,
                'prompt_path': str(args.prompt_path),
            }
            ok = False

        async with write_lock:
            with out_jsonl.open('a', encoding='utf-8') as f:
                f.write(json.dumps(out_obj, ensure_ascii=False) + '\n')
                f.flush()
                os.fsync(f.fileno())
            done_map[source_path] = out_obj

            stats['done'] += 1
            if ok:
                stats['success'] += 1
            else:
                stats['failed'] += 1

            elapsed = time.time() - start_time
            pct = (stats['done'] / stats['total'] * 100.0) if stats['total'] else 100.0
            log(
                f'[worker={worker_id}] done={stats["done"]}/{stats["total"]} ({pct:.2f}%) '
                f'success={stats["success"]} failed={stats["failed"]} elapsed={elapsed:.1f}s '
                f'date={job.get("date","")} category={job.get("source_category","")} slug={job.get("slug","")}'
            )

            if args.checkpoint_every > 0 and stats['done'] % args.checkpoint_every == 0:
                ckpt_path = args.out_dir / f'{args.run_name}.checkpoint_{stats["done"]}.json'
                ckpt_path.write_text(
                    json.dumps(list(done_map.values()), ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )
                log(f'[checkpoint] saved={ckpt_path}')

        queue.task_done()


def build_summary(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_source: Dict[str, int] = {}
    by_pred: Dict[str, int] = {}
    errors = 0

    for r in records:
        sm = r.get('sample_meta', {}) if isinstance(r, dict) else {}
        date = str(sm.get('date', ''))
        src = str(sm.get('source_category', ''))
        k = f'{date}/{src}'
        by_source[k] = by_source.get(k, 0) + 1

        c1 = str(r.get('category1', '未判定'))
        c2 = str(r.get('category2', '未判定'))
        p = f'{c1}/{c2}'
        by_pred[p] = by_pred.get(p, 0) + 1

        if 'error' in r:
            errors += 1

    return {
        'records': len(records),
        'error_records': errors,
        'source_breakdown': dict(sorted(by_source.items())),
        'predicted_category_breakdown': dict(sorted(by_pred.items())),
    }


async def amain(args: argparse.Namespace) -> None:
    args.v0_base = normalize_s3_uri(args.v0_base)
    args.flat_zip_dir = normalize_s3_uri(args.flat_zip_dir) if args.flat_zip_dir else ''
    args.framer_base = normalize_s3_uri(args.framer_base) if args.framer_base else ''
    args.site_dir_base = normalize_s3_uri(args.site_dir_base) if args.site_dir_base else ''
    args.nested_site_base = normalize_s3_uri(args.nested_site_base) if args.nested_site_base else ''
    args.htmlrev_base = normalize_s3_uri(args.htmlrev_base) if args.htmlrev_base else ''
    args.tympanus_json_path = normalize_s3_uri(args.tympanus_json_path) if args.tympanus_json_path else ''
    args.prompt_path = Path(args.prompt_path)
    args.out_dir = Path(args.out_dir)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    if not args.prompt_path.exists():
        raise FileNotFoundError(f'prompt file not found: {args.prompt_path}')

    out_jsonl = args.out_dir / f'{args.run_name}.jsonl'
    out_json = args.out_dir / f'{args.run_name}.json'
    out_summary = args.out_dir / f'{args.run_name}.summary.json'

    if args.overwrite:
        for p in [out_jsonl, out_json, out_summary]:
            if p.exists():
                p.unlink()

    done_map = load_done_map(out_jsonl)

    if args.job_source_mode == 'v0_nested':
        jobs, skipped_cats = await asyncio.to_thread(
            collect_zip_jobs,
            args.v0_base,
            args.include_dates,
            args.exclude_date_category,
        )
    elif args.job_source_mode == 'flat_zip_dir':
        if not args.flat_zip_dir:
            raise ValueError('flat_zip_dir mode requires --flat_zip_dir')
        jobs, skipped_cats = await asyncio.to_thread(
            collect_flat_zip_jobs,
            args.flat_zip_dir,
            args.flat_source_label,
        )
    elif args.job_source_mode == 'framer_nested':
        if not args.framer_base:
            raise ValueError('framer_nested mode requires --framer_base')
        jobs, skipped_cats = await asyncio.to_thread(
            collect_framer_jobs,
            args.framer_base,
            args.framer_categories,
            args.framer_exclude_categories,
        )
    elif args.job_source_mode == 'site_dir_flat':
        if not args.site_dir_base:
            raise ValueError('site_dir_flat mode requires --site_dir_base')
        jobs, skipped_cats = await asyncio.to_thread(
            collect_site_dir_jobs,
            args.site_dir_base,
            args.site_source_label,
            args.site_include_slugs,
            args.site_exclude_slugs,
        )
    elif args.job_source_mode == 'nested_site_dir':
        if not args.nested_site_base:
            raise ValueError('nested_site_dir mode requires --nested_site_base')
        jobs, skipped_cats = await asyncio.to_thread(
            collect_nested_site_dir_jobs,
            args.nested_site_base,
            args.nested_source_label,
            args.nested_include_categories,
            args.nested_exclude_categories,
        )
    elif args.job_source_mode == 'htmlrev_repo':
        if not args.htmlrev_base:
            raise ValueError('htmlrev_repo mode requires --htmlrev_base')
        jobs, skipped_cats = await asyncio.to_thread(
            collect_htmlrev_repo_jobs,
            args.htmlrev_base,
            args.htmlrev_source_label,
            args.htmlrev_include_repos,
            args.htmlrev_exclude_repos,
        )
    elif args.job_source_mode == 'tympanus_json':
        if not args.tympanus_json_path:
            raise ValueError('tympanus_json mode requires --tympanus_json_path')
        jobs, skipped_cats = await asyncio.to_thread(
            collect_tympanus_json_jobs,
            args.tympanus_json_path,
            args.tympanus_source_label,
        )
    else:
        raise ValueError(f'unsupported job_source_mode: {args.job_source_mode}')

    if args.offset > 0:
        jobs = jobs[args.offset :]
    if args.limit is not None:
        jobs = jobs[: args.limit]

    pending = [j for j in jobs if str(j.get('source_path') or j.get('zip_path') or '') not in done_map]
    prompt_text = args.prompt_path.read_text(encoding='utf-8')

    key_pool: Optional[KeyPool] = None
    limiter: Optional[RateLimiter] = None
    if not args.dry_run:
        keys = resolve_api_keys(args.api_keys)
        if not keys:
            raise RuntimeError('missing API key: use --api_keys or env API_KEY/OPENAI_API_KEY/STEP_ALIGN_API_KEY')
        key_pool = KeyPool(keys)
        limiter = RateLimiter(args.rpm)

    stats = {
        'total': len(jobs),
        'done': len(done_map),
        'success': len(done_map),
        'failed': 0,
    }
    start_time = time.time()

    log(
        f'[start] total={len(jobs)} done_existing={len(done_map)} pending={len(pending)} '
        f'model={args.model} concurrency={args.concurrency} rpm={args.rpm} '
        f'dry_run={args.dry_run} job_source_mode={args.job_source_mode} '
        f'v0_base={args.v0_base} flat_zip_dir={args.flat_zip_dir} '
        f'framer_base={args.framer_base} site_dir_base={args.site_dir_base} '
        f'nested_site_base={args.nested_site_base} htmlrev_base={args.htmlrev_base} '
        f'tympanus_json_path={args.tympanus_json_path}'
    )
    if skipped_cats:
        log(f'[skip_category] {", ".join(skipped_cats)}')

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
                prompt_text=prompt_text,
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
    out_json.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    out_summary.write_text(json.dumps(build_summary(records), ensure_ascii=False, indent=2), encoding='utf-8')

    log(
        f'[done] records={len(done_map)} success={stats["success"]} failed={stats["failed"]} '
        f'jsonl={out_jsonl} json={out_json} summary={out_summary}'
    )


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Universal reverse-query generation for v0 dates/categories (zip-based).')
    ap.add_argument(
        '--job_source_mode',
        choices=['v0_nested', 'flat_zip_dir', 'framer_nested', 'site_dir_flat', 'nested_site_dir', 'htmlrev_repo', 'tympanus_json'],
        default='v0_nested',
    )
    ap.add_argument('--v0_base', default=DEFAULT_V0_BASE)
    ap.add_argument('--include_dates', nargs='*', default=['20260228', '20260302'])
    ap.add_argument('--exclude_date_category', nargs='*', default=['20260302/apps-and-games'])
    ap.add_argument('--flat_zip_dir', default='')
    ap.add_argument('--flat_source_label', default='flat')
    ap.add_argument('--framer_base', default='s3://collect-data-text/202511/h5sites_resource/framer')
    ap.add_argument('--framer_categories', nargs='*', default=[])
    ap.add_argument('--framer_exclude_categories', nargs='*', default=[])
    ap.add_argument('--site_dir_base', default='')
    ap.add_argument('--site_source_label', default='site')
    ap.add_argument('--site_include_slugs', nargs='*', default=[])
    ap.add_argument('--site_exclude_slugs', nargs='*', default=[])
    ap.add_argument('--nested_site_base', default='')
    ap.add_argument('--nested_source_label', default='nested-site')
    ap.add_argument('--nested_include_categories', nargs='*', default=[])
    ap.add_argument('--nested_exclude_categories', nargs='*', default=[])
    ap.add_argument('--htmlrev_base', default='s3://collect-data-text/202511/h5sites_resource/htmlrev')
    ap.add_argument('--htmlrev_source_label', default='htmlrev')
    ap.add_argument('--htmlrev_include_repos', nargs='*', default=[])
    ap.add_argument('--htmlrev_exclude_repos', nargs='*', default=[])
    ap.add_argument('--tympanus_json_path', default='s3://collect-data-text/202511/h5sites_resource/tympanus/tympanus.json')
    ap.add_argument('--tympanus_source_label', default='tympanus')

    ap.add_argument('--prompt_path', default=str(DEFAULT_PROMPT_PATH))
    ap.add_argument('--out_dir', default=str(DEFAULT_OUT_DIR))
    ap.add_argument('--run_name', default='v0_universal_reverse_query')

    ap.add_argument('--model', default='gemini-3-pro-thinking')
    ap.add_argument('--api_keys', nargs='*', default=None)
    ap.add_argument('--temperature', type=float, default=0.2)
    ap.add_argument('--top_p', type=float, default=1.0)
    ap.add_argument('--max_tokens', type=int, default=3500)
    ap.add_argument('--timeout_sec', type=int, default=180)
    ap.add_argument('--response_format_json', action='store_true')

    ap.add_argument('--concurrency', type=int, default=10)
    ap.add_argument('--rpm', type=int, default=120)
    ap.add_argument('--checkpoint_every', type=int, default=500)

    ap.add_argument('--offset', type=int, default=0)
    ap.add_argument('--limit', type=int, default=None)
    ap.add_argument('--overwrite', action='store_true')
    ap.add_argument('--dry_run', action='store_true')

    ap.add_argument('--html_chars', type=int, default=30000)
    ap.add_argument('--visible_text_chars', type=int, default=5000)
    ap.add_argument('--js_files_limit', type=int, default=2)
    ap.add_argument('--js_chars_each', type=int, default=12000)

    ap.add_argument('--save_raw_output', action='store_true')
    ap.add_argument('--save_input_payload', action='store_true')
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(amain(args))


if __name__ == '__main__':
    main()
