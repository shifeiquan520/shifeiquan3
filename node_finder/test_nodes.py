# -*- coding: utf-8 -*-
"""
test_nodes.py - 用 mihomo 核心做真实协议握手测速

思路：把节点写成一份临时 mihomo 配置，启动核心后调用
      external-controller 的 /proxies/{name}/delay 接口并发测延迟。
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

TEST_URL = 'http://cp.cloudflare.com/generate_204'
CHUNK_SIZE = 120


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
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            resp = requests.get(url, timeout=2)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def get_delay(ctrl_port, name, timeout_ms):
    url = 'http://127.0.0.1:%d/proxies/%s/delay' % (ctrl_port, quote(name, safe=''))
    try:
        resp = requests.get(
            url,
            params={'timeout': timeout_ms, 'url': TEST_URL},
            timeout=timeout_ms / 1000.0 + 5,
        )
        if resp.status_code == 200:
            delay = resp.json().get('delay')
            if isinstance(delay, int) and delay > 0:
                return delay
    except Exception:
        pass
    return None


def test_chunk(binary, proxies, timeout_ms, concurrency, tag):
    """测试一批节点，返回 {name: delay}"""
    if not proxies:
        return {}

    workdir = tempfile.mkdtemp(prefix='mihomo_%s_' % tag)
    ctrl_port = free_port()
    mixed_port = free_port()

    config = {
        'mixed-port': mixed_port,
        'allow-lan': False,
        'mode': 'rule',
        'log-level': 'silent',
        'ipv6': False,
        'external-controller': '127.0.0.1:%d' % ctrl_port,
        'proxies': proxies,
        'rules': ['MATCH,DIRECT'],
    }
    config_path = os.path.join(workdir, 'config.yaml')
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)

    log_path = os.path.join(workdir, 'mihomo.log')
    proc = None
    results = {}
    try:
        with open(log_path, 'wb') as log_file:
            proc = subprocess.Popen(
                [binary, '-d', workdir, '-f', config_path],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=workdir,
            )
            if not wait_ready(ctrl_port, proc, 25):
                message = ''
                try:
                    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                        message = f.read()[-400:].replace('\n', ' ')
                except Exception:
                    pass
                print('[test] chunk %s 启动失败: %s' % (tag, message[:200]))
                return {}

            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = {
                    pool.submit(get_delay, ctrl_port, p['name'], timeout_ms): p['name']
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

    return results


def test_all(binary, nodes, timeout_ms=5000, concurrency=30):
    """返回 {name: delay}，delay 为 None 表示不通"""
    proxies = [node['proxy'] for node in nodes if node.get('proxy', {}).get('name')]
    if not proxies:
        return {}

    print('[test] 开始测速: %d 个节点, 超时 %dms, 并发 %d' % (len(proxies), timeout_ms, concurrency))

    all_results = {}
    total = len(proxies)
    for start in range(0, total, CHUNK_SIZE):
        chunk = proxies[start:start + CHUNK_SIZE]
        tag = '%d_%d' % (start, start + len(chunk))
        print('[test] chunk %d-%d ...' % (start + 1, start + len(chunk)), end=' ', flush=True)

        chunk_results = test_chunk(binary, chunk, timeout_ms, concurrency, tag)
        if not chunk_results:
            chunk_results = test_chunk(binary, chunk, timeout_ms, concurrency, tag + '_retry')

        alive = sum(1 for v in chunk_results.values() if v)
        all_results.update(chunk_results)
        print('alive %d/%d' % (alive, len(chunk)))

    return all_results
