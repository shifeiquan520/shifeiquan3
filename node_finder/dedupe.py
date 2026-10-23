# -*- coding: utf-8 -*-
"""
dedupe.py - 节点去重与采样
"""


def proxy_key(p):
    """按 类型+服务器+端口+凭证 生成去重键"""
    cred = p.get('uuid') or p.get('password') or ''
    return (
        str(p.get('type', '')),
        str(p.get('server', '')).lower(),
        int(p.get('port') or 0),
        str(cred),
    )


def dedupe(nodes):
    """nodes: [{'proxy': dict, 'raw': str|None, 'source': str}]"""
    seen = set()
    unique = []
    dropped = 0
    for node in nodes:
        key = proxy_key(node['proxy'])
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        unique.append(node)
    print('[dedupe] %d -> %d (drop %d)' % (len(nodes), len(unique), dropped))
    return unique


def sample_round_robin(nodes, limit):
    """按来源轮询采样，保证各源都有机会进入测速"""
    if limit <= 0 or len(nodes) <= limit:
        return list(nodes)

    buckets = {}
    order = []
    for node in nodes:
        src = node.get('source', '')
        if src not in buckets:
            buckets[src] = []
            order.append(src)
        buckets[src].append(node)

    picked = []
    idx = 0
    while len(picked) < limit:
        progressed = False
        for src in order:
            bucket = buckets[src]
            if idx < len(bucket):
                picked.append(bucket[idx])
                progressed = True
                if len(picked) >= limit:
                    break
        if not progressed:
            break
        idx += 1

    print('[sample] %d -> %d' % (len(nodes), len(picked)))
    return picked
