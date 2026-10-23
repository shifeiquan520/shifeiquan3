# -*- coding: utf-8 -*-
"""
build.py - 生成订阅文件（clash.yaml / base64.txt / nodes.json）
"""

import argparse
import base64
import datetime
import json
import os

import yaml

TEST_URL = 'http://cp.cloudflare.com/generate_204'

CC_NAMES = {
    'HK': '香港', 'TW': '台湾', 'MO': '澳门', 'JP': '日本', 'SG': '新加坡',
    'US': '美国', 'KR': '韩国', 'GB': '英国', 'DE': '德国', 'FR': '法国',
    'NL': '荷兰', 'CA': '加拿大', 'AU': '澳大利亚', 'RU': '俄罗斯',
    'IN': '印度', 'TR': '土耳其', 'BR': '巴西', 'VN': '越南', 'TH': '泰国',
    'MY': '马来西亚', 'PH': '菲律宾', 'ID': '印度尼西亚', 'AE': '阿联酋',
    'CH': '瑞士', 'SE': '瑞典', 'FI': '芬兰', 'NO': '挪威', 'DK': '丹麦',
    'PL': '波兰', 'IT': '意大利', 'ES': '西班牙', 'IE': '爱尔兰',
    'AT': '奥地利', 'BE': '比利时', 'CZ': '捷克', 'RO': '罗马尼亚',
    'UA': '乌克兰', 'IL': '以色列', 'ZA': '南非', 'MX': '墨西哥',
    'AR': '阿根廷', 'CL': '智利', 'NZ': '新西兰', 'PT': '葡萄牙',
    'HU': '匈牙利', 'BG': '保加利亚', 'LT': '立陶宛', 'LV': '拉脱维亚',
    'EE': '爱沙尼亚', 'MD': '摩尔多瓦', 'KZ': '哈萨克斯坦', 'PK': '巴基斯坦',
    'BD': '孟加拉', 'LK': '斯里兰卡', 'NP': '尼泊尔', 'MM': '缅甸',
    'KH': '柬埔寨', 'LA': '老挝', 'MN': '蒙古', 'CY': '塞浦路斯',
    'GR': '希腊', 'HR': '克罗地亚', 'RS': '塞尔维亚', 'SK': '斯洛伐克',
    'SI': '斯洛文尼亚', 'LU': '卢森堡', 'IS': '冰岛', 'MT': '马耳他',
    'AL': '阿尔巴尼亚', 'AM': '亚美尼亚', 'GE': '格鲁吉亚',
    'AZ': '阿塞拜疆', 'UZ': '乌兹别克斯坦', 'BY': '白俄罗斯',
    'PA': '巴拿马', 'CR': '哥斯达黎加', 'CO': '哥伦比亚', 'PE': '秘鲁',
    'UY': '乌拉圭', 'EC': '厄瓜多尔', 'VE': '委内瑞拉', 'DO': '多米尼加',
    'GT': '危地马拉', 'PR': '波多黎各', 'NG': '尼日利亚', 'KE': '肯尼亚',
    'EG': '埃及', 'MA': '摩洛哥', 'TN': '突尼斯', 'DZ': '阿尔及利亚',
    'GH': '加纳', 'TZ': '坦桑尼亚', 'UG': '乌干达', 'SA': '沙特',
    'QA': '卡塔尔', 'KW': '科威特', 'BH': '巴林', 'OM': '阿曼',
    'JO': '约旦', 'LB': '黎巴嫩', 'IQ': '伊拉克', 'IR': '伊朗',
    'SY': '叙利亚', 'AF': '阿富汗',
}


def flag(cc):
    cc = (cc or '').upper()
    if len(cc) != 2 or not cc.isalpha():
        return ''
    try:
        return ''.join(chr(0x1F1E6 + ord(c) - ord('A')) for c in cc)
    except Exception:
        return ''


def cc_label(cc):
    cc = (cc or 'XX').upper()
    return CC_NAMES.get(cc, cc)


def assign_names(nodes):
    """按国家编号命名，保证唯一"""
    counters = {}
    for node in nodes:
        cc = (node.get('country') or 'XX').upper()
        counters[cc] = counters.get(cc, 0) + 1
        node['name'] = '%s%s-%02d' % (flag(cc), cc, counters[cc])
        node['proxy']['name'] = node['name']
    return nodes


def build_clash(nodes):
    names = [n['name'] for n in nodes]
    proxies = [n['proxy'] for n in nodes]

    groups = [
        {
            'name': '🚀 节点选择',
            'type': 'select',
            'proxies': ['♻️ 自动选择'] + names,
        },
        {
            'name': '♻️ 自动选择',
            'type': 'url-test',
            'url': TEST_URL,
            'interval': 300,
            'tolerance': 50,
            'proxies': names,
        },
    ]

    counts = {}
    for node in nodes:
        cc = (node.get('country') or 'XX').upper()
        counts[cc] = counts.get(cc, 0) + 1

    used = 0
    for cc, count in sorted(counts.items(), key=lambda x: -x[1]):
        if count < 2 or used >= 10:
            continue
        group_names = [n['name'] for n in nodes if (n.get('country') or 'XX').upper() == cc]
        groups.append({
            'name': '%s %s' % (flag(cc), cc_label(cc)),
            'type': 'url-test',
            'url': TEST_URL,
            'interval': 300,
            'tolerance': 50,
            'proxies': group_names,
        })
        used += 1

    config = {
        'mixed-port': 7890,
        'allow-lan': False,
        'mode': 'rule',
        'log-level': 'info',
        'ipv6': False,
        'external-controller': '127.0.0.1:9090',
        'proxies': proxies,
        'proxy-groups': groups,
        'rules': ['MATCH,🚀 节点选择'],
    }
    return config


def write_outputs(outdir, nodes):
    os.makedirs(outdir, exist_ok=True)
    now = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')

    clash = build_clash(nodes)
    clash_path = os.path.join(outdir, 'clash.yaml')
    header = (
        '# free-nodes subscription (auto generated)\n'
        '# updated: %s\n'
        '# nodes: %d (latency tested)\n'
        '# usage: Clash / Clash Meta / Mihomo / Clash Verge / Stash\n'
        '# note: public free nodes, do NOT use for sensitive accounts or payments\n\n'
    ) % (now, len(nodes))
    with open(clash_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(header)
        yaml.safe_dump(clash, f, allow_unicode=True, sort_keys=False, width=1000)

    raw_links = [n['raw'] for n in nodes if n.get('raw')]
    base64_path = os.path.join(outdir, 'base64.txt')
    payload = base64.b64encode('\n'.join(raw_links).encode('utf-8')).decode('ascii')
    with open(base64_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(payload)

    info = []
    for node in nodes:
        info.append({
            'name': node['name'],
            'type': node['proxy'].get('type'),
            'server': node['proxy'].get('server'),
            'port': node['proxy'].get('port'),
            'server_ip': node.get('server_ip'),
            'country': node.get('country'),
            'delay_ms': node.get('delay'),
            'source': node.get('source'),
            'has_raw_link': bool(node.get('raw')),
        })
    json_path = os.path.join(outdir, 'nodes.json')
    with open(json_path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(info, f, ensure_ascii=False, indent=2)

    print('[build] clash.yaml   : %d nodes' % len(nodes))
    print('[build] base64.txt   : %d links' % len(raw_links))
    print('[build] nodes.json   : %d entries' % len(info))
    return {
        'clash': clash_path,
        'base64': base64_path,
        'nodes': json_path,
        'count': len(nodes),
        'links': len(raw_links),
    }
