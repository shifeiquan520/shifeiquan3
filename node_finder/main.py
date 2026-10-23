# -*- coding: utf-8 -*-
"""
main.py - free-nodes 主入口

流程：拉取上游 -> 解析 -> 去重 -> 采样 -> 地区标注 -> mihomo 测速 -> 输出订阅
"""

import argparse
import os
import sys
import time

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from build import assign_names, write_outputs
from dedupe import dedupe, sample_round_robin
from fetch_sources import fetch_all
from geo import annotate
from parse import extract_links, looks_like_yaml, parse_link, validate_proxy
from test_nodes import test_all

DEFAULT_OUTDIR = os.path.join(HERE, '..', 'output')


def parse_args():
    parser = argparse.ArgumentParser(description='free-nodes subscription builder')
    parser.add_argument('--mihomo', default='', help='mihomo 可执行文件路径')
    parser.add_argument('--top', type=int, default=150, help='最终保留节点数')
    parser.add_argument('--max-test', type=int, default=800, help='参与测速的节点上限')
    parser.add_argument('--concurrency', type=int, default=30, help='测速并发')
    parser.add_argument('--timeout', type=int, default=5000, help='单个节点测速超时(ms)')
    parser.add_argument('--no-test', action='store_true', help='跳过测速（仅调试流程）')
    parser.add_argument('--outdir', default=DEFAULT_OUTDIR, help='输出目录')
    return parser.parse_args()


def find_mihomo(explicit):
    if explicit:
        return os.path.abspath(explicit)
    env = os.environ.get('MIHOMO_BIN', '')
    if env and os.path.exists(env):
        return os.path.abspath(env)
    for name in ('mihomo', 'mihomo.exe'):
        path = os.path.join(HERE, '..', name)
        if os.path.exists(path):
            return os.path.abspath(path)
    return ''


def collect_nodes(fetched):
    nodes = []
    for name, text, _used in fetched:
        if looks_like_yaml(text):
            try:
                data = yaml.safe_load(text) or {}
            except Exception as exc:
                print('[parse] %s yaml error: %s' % (name, str(exc)[:60]))
                continue
            proxies = data.get('proxies') or []
            kept = 0
            for proxy in proxies:
                if not isinstance(proxy, dict):
                    continue
                proxy = dict(proxy)
                if not validate_proxy(proxy):
                    continue
                nodes.append({'proxy': proxy, 'raw': None, 'source': name})
                kept += 1
            print('[parse] %-18s yaml  %5d/%d' % (name, kept, len(proxies)))
        else:
            links = extract_links(text)
            kept = 0
            for link in links:
                proxy = parse_link(link)
                if proxy:
                    nodes.append({'proxy': proxy, 'raw': link, 'source': name})
                    kept += 1
            print('[parse] %-18s links %5d/%d' % (name, kept, len(links)))
    return nodes


def summarize(nodes):
    counts = {}
    for node in nodes:
        cc = (node.get('country') or 'XX').upper()
        counts[cc] = counts.get(cc, 0) + 1
    return sorted(counts.items(), key=lambda x: -x[1])


def main():
    args = parse_args()
    started = time.time()

    print('=' * 54)
    print('  free-nodes - 免费节点聚合 / 测速 / 订阅生成')
    print('=' * 54)

    print('\n[1/6] 拉取上游订阅源')
    fetched = fetch_all()
    if not fetched:
        print('[ERR] 所有上游拉取失败，保留上次输出')
        return 0

    print('\n[2/6] 解析节点')
    nodes = collect_nodes(fetched)
    print('[parse] 合计 %d 个节点' % len(nodes))
    if not nodes:
        print('[ERR] 未解析到任何节点，保留上次输出')
        return 0

    print('\n[3/6] 去重 + 采样')
    nodes = dedupe(nodes)
    nodes = sample_round_robin(nodes, args.max_test)

    print('\n[4/6] 地区标注')
    nodes = annotate(nodes)
    before = len(nodes)
    nodes = [n for n in nodes if (n.get('country') or 'XX').upper() != 'CN']
    if before != len(nodes):
        print('[geo] 剔除境内节点 %d 个' % (before - len(nodes)))
    assign_names(nodes)

    print('\n[5/6] 测速')
    if args.no_test:
        print('[test] 已跳过（--no-test）')
        for node in nodes:
            node['delay'] = 0
        tested = list(nodes)
    else:
        binary = find_mihomo(args.mihomo)
        if not binary or not os.path.exists(binary):
            print('[ERR] 未找到 mihomo 可执行文件，可加 --no-test 或指定 --mihomo')
            return 1
        results = test_all(binary, nodes, timeout_ms=args.timeout, concurrency=args.concurrency)
        tested = []
        for node in nodes:
            delay = results.get(node['name'])
            node['delay'] = delay
            if delay:
                tested.append(node)
        print('[test] 存活 %d/%d' % (len(tested), len(nodes)))

    if not tested:
        print('[ERR] 无可用节点，保留上次输出')
        return 0

    tested.sort(key=lambda x: x.get('delay') or 999999)
    final = tested[:args.top]

    print('\n[6/6] 生成订阅')
    stats = write_outputs(args.outdir, final)

    print('\n地区分布:')
    for cc, count in summarize(final):
        print('  %-3s %d' % (cc, count))

    print('\n延迟区间: %dms ~ %dms' % (final[0].get('delay') or 0, final[-1].get('delay') or 0))
    print('耗时 %.1fs' % (time.time() - started))
    print('=' * 54)
    return 0


if __name__ == '__main__':
    sys.exit(main())
