# -*- coding: utf-8 -*-
"""
fetch_sources.py - 拉取上游订阅源（直连失败时自动走镜像）
"""

import json
import os
import time
import warnings

import requests

warnings.filterwarnings('ignore')

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES_FILE = os.path.join(HERE, 'sources.json')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
}

RAW_HOST = 'raw.githubusercontent.com/'
MIRROR_PREFIXES = ('https://gh-proxy.com/', 'https://ghfast.top/')


def load_sources():
    with open(SOURCES_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def mirror_candidates(url):
    """生成镜像候选列表，直连优先"""
    candidates = [url]
    if RAW_HOST in url:
        rest = url.split(RAW_HOST, 1)[1]
        parts = rest.split('/')
        if len(parts) >= 4:
            user, repo = parts[0], parts[1]
            if parts[2] == 'refs' and len(parts) >= 6 and parts[3] == 'heads':
                ref = parts[4]
                path = '/'.join(parts[5:])
            else:
                ref = parts[2]
                path = '/'.join(parts[3:])
            candidates.append('https://cdn.jsdelivr.net/gh/%s/%s@%s/%s' % (user, repo, ref, path))
        for prefix in MIRROR_PREFIXES:
            candidates.append(prefix + url)
    return candidates


def fetch_text(url, timeout=40):
    """按候选顺序尝试拉取，返回 (text, used_url) 或 (None, None)"""
    for candidate in mirror_candidates(url):
        for attempt in range(2):
            try:
                resp = requests.get(candidate, headers=HEADERS, timeout=timeout, verify=False)
                if resp.status_code == 200 and len(resp.text.strip()) > 20:
                    return resp.text, candidate
                if resp.status_code == 404:
                    break
            except Exception:
                pass
            time.sleep(1)
    return None, None


def fetch_all():
    """拉取所有源，返回 [(source_name, text, used_url)]"""
    results = []
    for source in load_sources():
        name = source.get('name', 'unknown')
        url = source.get('url', '')
        if not url or not source.get('enabled', True):
            continue
        print('[fetch] %s ...' % name, end=' ', flush=True)
        text, used = fetch_text(url)
        if text:
            print('OK (%d bytes)' % len(text))
            results.append((name, text, used))
        else:
            print('FAIL')
    return results
