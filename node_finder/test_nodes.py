# -*- coding: utf-8 -*-
"""
test_nodes.py - 两阶段真实测速

阶段 A：经 mihomo external-controller 并发测 YouTube 可达性与延迟
阶段 B：对可达节点用 listeners（每节点独立本地端口）并发下载 1MB 测带宽
        若 listeners 启动失败则降级为只测延迟（speed=0）
"""

import os
import socket
import subprocess
import tempfile
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

import requests
import yaml

warnings.filterwarnings('ignore')

LATENCY_URL = 'https://www.youtube.com/generate_204'
SPEED_URLS = (
    'https://speed.cloudflare.com/__down?bytes=1048576',
    'https://speedtest.tele2.net/1MB.zip',
)
SPEED_BYTES = 1048576
SPEED_SECONDS = 8
CHUNK_SIZE = 120
SPEED_CHUNK_SIZE = 100


def local_session():
    sess = requests.Session()
    sess.trust_env = False
    return sess


def free_port():
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def stop_process(proc):
    if proc is None:
        return
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    except Exception:
        pass


def wait_ready(ctrl_port, proc, timeout=25):
    deadline = time.time() + timeout
    url = 'http://127.0.0.1:%d/version' % ctrl_port
    sess = local_session()
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            resp = sess.get(url, timeout=2)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def start_core(binary, config, workdir, log_name):
    config_path = os.path.join(workdir, log_name + '.yaml')
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)
    log_path = os.path.join(workdir, log_name + '.log')
    log_file = open(log_path, 'wb')
    proc = subprocess.Popen(
        [binary, '-d', workdir, '-f', config_path],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        cwd=workdir,
    )
    return proc, log_file, log_path


def tail_log(log_path, size=400):
    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()[-size:].replace('\n', ' ')
    except Exception:
        return ''


def get_delay(ctrl_port, name, timeout_ms, url):
    target = 'http://127.0.0.1:%d/proxies/%s/delay' % (ctrl_port, quote(name, safe=''))
    sess = local_session()
    try:
        resp = sess.get(
            target,
            params={'timeout': timeout_ms, 'url': url},
            timeout=timeout_ms / 1000.0 + 5,
        )
        if resp.status_code == 200:
            delay = resp.json().get('delay')
            if isinstance(delay, int) and delay > 0:
                return delay
    except Exception:
        pass
    return None


def latency_chunk(binary, proxies, timeout_ms, concurrency, tag):
    """阶段 A：一批节点的 YouTube 延迟，返回 {name: delay}"""
    if not proxies:
        return {}

    workdir = tempfile.mkdtemp(prefix='mihomo_lat_%s_' % tag)
    ctrl_port = free_port()
    config = {
        'mixed-port': free_port(),
        'allow-lan': False,
        'mode': 'rule',
        'log-level': 'silent',
        'ipv6': False,
        'external-controller': '127.0.0.1:%d' % ctrl_port,
        'proxies': proxies,
        'rules': ['MATCH,DIRECT'],
    }
    log_file = None
    proc = None
    results = {}
    try:
        proc, log_file, log_path = start_core(binary, config, workdir, 'lat')
        if not wait_ready(ctrl_port, proc, 25):
            print('[test] 延迟阶段启动失败: %s' % tail_log(log_path)[:160])
            return {}
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {
                pool.submit(get_delay, ctrl_port, p['name'], timeout_ms, LATENCY_URL): p['name']
                for p in proxies
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    results[name] = future.result()
                except Exception:
                    results[name] = None
    finally:
        stop_process(proc)
        if log_file:
            try:
                log_file.close()
            except Exception:
                pass

    return results


def download_speed(port, timeout_s):
    """经指定本地端口下载，返回 KB/s（0 表示失败）"""
    proxies = {
        'http': 'http://127.0.0.1:%d' % port,
        'https': 'http://127.0.0.1:%d' % port,
    }
    for url in SPEED_URLS:
        sess = requests.Session()
        sess.trust_env = False
        sess.proxies = proxies
        started = time.time()
        total = 0
        try:
            resp = sess.get(url, stream=True, timeout=(6, timeout_s + 2), verify=False)
            if resp.status_code not in (200, 206):
                resp.close()
                continue
            deadline = started + timeout_s
            for block in resp.iter_content(65536):
                if not block:
                    continue
                total += len(block)
                if total >= SPEED_BYTES or time.time() >= deadline:
                    break
            resp.close()
        except Exception:
            pass
        finally:
            sess.close()

        elapsed = time.time() - started
        if total > 65536 and elapsed > 0.2:
            return int(total / elapsed / 1024.0)
    return 0


def speed_chunk(binary, proxies, timeout_s, concurrency, tag):
    """阶段 B：一批节点的下载带宽，返回 {name: kbps}"""
    if not proxies:
        return {}

    workdir = tempfile.mkdtemp(prefix='mihomo_spd_%s_' % tag)
    ctrl_port = free_port()
    listeners = []
    port_map = {}
    for index, proxy in enumerate(proxies):
        port = free_port()
        port_map[proxy['name']] = port
        listeners.append({
            'name': 'ln%d' % index,
            'type': 'http',
            'port': port,
            'proxy': proxy['name'],
        })

    config = {
        'mixed-port': free_port(),
        'allow-lan': False,
        'mode': 'rule',
        'log-level': 'silent',
        'ipv6': False,
        'external-controller': '127.0.0.1:%d' % ctrl_port,
        'proxies': proxies,
        'listeners': listeners,
        'rules': ['MATCH,DIRECT'],
    }
    log_file = None
    proc = None
    results = {}
    try:
        proc, log_file, log_path = start_core(binary, config, workdir, 'spd')
        if not wait_ready(ctrl_port, proc, 25):
            print('[test] 带宽阶段启动失败(降级为只测延迟): %s' % tail_log(log_path)[:160])
            return {}
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {
                pool.submit(download_speed, port_map[p['name']], timeout_s): p['name']
                for p in proxies
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    results[name] = future.result()
                except Exception:
                    results[name] = 0
    finally:
        stop_process(proc)
        if log_file:
            try:
                log_file.close()
            except Exception:
                pass

    return results


def test_all(binary, nodes, timeout_ms=3000, concurrency=60, speed_concurrency=8):
    """返回 {name: {'delay': int|None, 'speed_kbps': int}}"""
    proxies = [node['proxy'] for node in nodes if node.get('proxy', {}).get('name')]
    if not proxies:
        return {}

    print('[test] 阶段A YouTube 可达性: %d 节点, 超时 %dms, 并发 %d'
          % (len(proxies), timeout_ms, concurrency))

    delays = {}
    total = len(proxies)
    for start in range(0, total, CHUNK_SIZE):
        chunk = proxies[start:start + CHUNK_SIZE]
        tag = '%d_%d' % (start, start + len(chunk))
        print('[test] A %d-%d ...' % (start + 1, start + len(chunk)), end=' ', flush=True)
        chunk_delays = latency_chunk(binary, chunk, timeout_ms, concurrency, tag)
        if not chunk_delays:
            chunk_delays = latency_chunk(binary, chunk, timeout_ms, concurrency, tag + 'r')
        alive = sum(1 for value in chunk_delays.values() if value)
        delays.update(chunk_delays)
        print('OK %d/%d' % (alive, len(chunk)))

    alive_proxies = [p for p in proxies if delays.get(p['name'])]
    print('[test] 阶段A 可达 %d/%d' % (len(alive_proxies), total))
    if not alive_proxies:
        return {}

    print('[test] 阶段B 下载带宽: %d 节点, 限时 %ds, 并发 %d'
          % (len(alive_proxies), SPEED_SECONDS, speed_concurrency))

    speeds = {}
    total2 = len(alive_proxies)
    for start in range(0, total2, SPEED_CHUNK_SIZE):
        chunk = alive_proxies[start:start + SPEED_CHUNK_SIZE]
        tag = '%d_%d' % (start, start + len(chunk))
        print('[test] B %d-%d ...' % (start + 1, start + len(chunk)), end=' ', flush=True)
        chunk_speeds = speed_chunk(binary, chunk, SPEED_SECONDS, speed_concurrency, tag)
        if not chunk_speeds:
            chunk_speeds = speed_chunk(binary, chunk, SPEED_SECONDS, speed_concurrency, tag + 'r')
        measured = sum(1 for value in chunk_speeds.values() if value)
        speeds.update(chunk_speeds)
        print('有速度 %d/%d' % (measured, len(chunk)))

    results = {}
    for name, delay in delays.items():
        results[name] = {'delay': delay, 'speed_kbps': int(speeds.get(name) or 0)}
    return results
