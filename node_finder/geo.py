# -*- coding: utf-8 -*-
"""
geo.py - 解析节点出口 IP 并标注国家/地区
"""

import socket
import time
import warnings
from concurrent.futures import ThreadPoolExecutor

import requests

warnings.filterwarnings('ignore')

RESOLVE_WORKERS = 20
BATCH_SIZE = 100
BATCH_INTERVAL = 4.5
GEO_API = 'http://ip-api.com/batch?fields=status,countryCode,query'


def resolve_host(host):
    """域名解析为 IPv4，失败返回 None"""
    host = (host or '').strip()
    if not host:
        return None
    if is_ipv4(host):
        return host
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET)
        if infos:
            return infos[0][4][0]
    except Exception:
        return None
    return None


def is_ipv4(s):
    parts = (s or '').split('.')
    if len(parts) != 4:
        return False
    for part in parts:
        if not part.isdigit():
            return False
        if not 0 <= int(part) <= 255:
            return False
    return True


def resolve_all(servers):
    """批量解析，返回 {server: ip}"""
    result = {}
    unique = list(dict.fromkeys(servers))
    with ThreadPoolExecutor(max_workers=RESOLVE_WORKERS) as pool:
        ips = list(pool.map(resolve_host, unique))
    for server, ip in zip(unique, ips):
        result[server] = ip
    return result


def query_countries(ips):
    """ip-api 批量查询，返回 {ip: countryCode}"""
    result = {}
    unique = [ip for ip in dict.fromkeys(ips) if ip]
    for start in range(0, len(unique), BATCH_SIZE):
        chunk = unique[start:start + BATCH_SIZE]
        try:
            resp = requests.post(
                GEO_API,
                json=[{'query': ip} for ip in chunk],
                timeout=30,
                verify=False,
            )
            if resp.status_code == 200:
                for item in resp.json():
                    ip = item.get('query')
                    cc = item.get('countryCode')
                    if ip and cc:
                        result[ip] = str(cc).upper()
            else:
                print('[geo] batch HTTP %d' % resp.status_code)
        except Exception as exc:
            print('[geo] batch error: %s' % str(exc)[:40])
        if start + BATCH_SIZE < len(unique):
            time.sleep(BATCH_INTERVAL)
    return result


def annotate(nodes):
    """为节点写入 server_ip / country 字段"""
    servers = [node['proxy'].get('server') for node in nodes]
    server_ip = resolve_all(servers)
    countries = query_countries([ip for ip in server_ip.values() if ip])

    ok = 0
    for node in nodes:
        server = node['proxy'].get('server')
        ip = server_ip.get(server)
        node['server_ip'] = ip
        node['country'] = countries.get(ip, 'XX') if ip else 'XX'
        if node['country'] != 'XX':
            ok += 1

    print('[geo] %d/%d nodes tagged' % (ok, len(nodes)))
    return nodes
