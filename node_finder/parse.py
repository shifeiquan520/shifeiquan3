# -*- coding: utf-8 -*-
"""
parse.py - 解析分享链接为 mihomo(clash) 代理字典
支持：vmess / vless / trojan / ss / hysteria2 / tuic
"""

import base64
import json
from urllib.parse import urlparse, parse_qs, unquote

SUPPORTED_TYPES = ('vmess', 'vless', 'trojan', 'ss', 'hysteria2', 'tuic')


def b64decode(s):
    s = (s or '').strip().replace('-', '+').replace('_', '/')
    s += '=' * (-len(s) % 4)
    return base64.b64decode(s).decode('utf-8', 'ignore')


def b64encode(s):
    return base64.b64encode(s.encode('utf-8')).decode('ascii')


def split_hostport(s):
    s = (s or '').strip()
    if s.startswith('['):
        host, _, port = s[1:].partition(']:')
        return host, int(port or 443)
    if ':' in s:
        host, _, port = s.rpartition(':')
        return host, int(port or 443)
    return s, 443


def truthy(v):
    return str(v).lower() in ('1', 'true', 'yes')


def first(q, *keys):
    for k in keys:
        v = q.get(k)
        if v and v[0]:
            return v[0]
    return None


def parse_vmess(url):
    payload = url[len('vmess://'):].strip()
    j = json.loads(b64decode(payload))
    server = str(j.get('add') or '').strip()
    uuid = str(j.get('id') or '').strip()
    if not server or not uuid:
        return None
    try:
        port = int(str(j.get('port') or 443).strip())
    except Exception:
        port = 443

    net = str(j.get('net') or 'tcp').lower()
    tls = str(j.get('tls') or '').lower() in ('tls', 'reality', 'true', '1')
    host = str(j.get('host') or j.get('sni') or '').strip()
    path = str(j.get('path') or '/').strip() or '/'

    p = {
        'type': 'vmess',
        'server': server,
        'port': port,
        'uuid': uuid,
        'alterId': int(str(j.get('aid') or 0) or 0),
        'cipher': str(j.get('scy') or 'auto'),
        'udp': True,
    }
    if tls:
        p['tls'] = True
        if host:
            p['servername'] = host
        p['skip-cert-verify'] = True

    if net == 'ws':
        p['network'] = 'ws'
        opts = {'path': path}
        if host:
            opts['headers'] = {'Host': host}
        p['ws-opts'] = opts
    elif net == 'grpc':
        p['network'] = 'grpc'
        p['grpc-opts'] = {'grpc-service-name': path.lstrip('/')}
    elif net in ('h2', 'http'):
        p['network'] = 'h2'
        opts = {'path': path}
        if host:
            opts['host'] = [host]
        p['h2-opts'] = opts

    fp = str(j.get('fp') or '').strip()
    if fp:
        p['client-fingerprint'] = fp
    return p


def parse_vless(url):
    u = urlparse(url)
    if not u.username or not u.hostname:
        return None
    q = parse_qs(u.query)
    security = (first(q, 'security') or 'none').lower()
    net = (first(q, 'type') or 'tcp').lower()

    p = {
        'type': 'vless',
        'server': u.hostname,
        'port': u.port or 443,
        'uuid': unquote(u.username),
        'udp': True,
        'skip-cert-verify': True,
    }
    if security in ('tls', 'xtls', 'reality'):
        p['tls'] = True

    sni = first(q, 'sni', 'peer', 'host')
    if sni:
        p['servername'] = sni

    if security == 'reality':
        pbk = first(q, 'pbk')
        if not pbk:
            return None
        ro = {'public-key': pbk}
        sid = first(q, 'sid')
        if sid:
            ro['short-id'] = sid
        p['reality-opts'] = ro

    flow = first(q, 'flow')
    if flow:
        p['flow'] = flow

    if net == 'ws':
        p['network'] = 'ws'
        opts = {'path': first(q, 'path') or '/'}
        h = first(q, 'host')
        if h:
            opts['headers'] = {'Host': h}
        p['ws-opts'] = opts
    elif net == 'grpc':
        p['network'] = 'grpc'
        p['grpc-opts'] = {'grpc-service-name': first(q, 'serviceName') or ''}
    elif net in ('h2', 'http'):
        p['network'] = 'h2'
        opts = {'path': first(q, 'path') or '/'}
        h = first(q, 'host')
        if h:
            opts['host'] = [h]
        p['h2-opts'] = opts
    elif net == 'httpupgrade':
        p['network'] = 'ws'
        opts = {'path': first(q, 'path') or '/', 'v2ray-http-upgrade': True}
        h = first(q, 'host')
        if h:
            opts['headers'] = {'Host': h}
        p['ws-opts'] = opts

    fp = first(q, 'fp')
    if fp:
        p['client-fingerprint'] = fp
    elif security == 'reality':
        p['client-fingerprint'] = 'chrome'

    alpn = first(q, 'alpn')
    if alpn:
        p['alpn'] = [a for a in alpn.split(',') if a]
    return p


def parse_trojan(url):
    u = urlparse(url)
    if not u.username or not u.hostname:
        return None
    q = parse_qs(u.query)

    p = {
        'type': 'trojan',
        'server': u.hostname,
        'port': u.port or 443,
        'password': unquote(u.username),
        'udp': True,
        'skip-cert-verify': True,
    }
    sni = first(q, 'sni', 'peer')
    if sni:
        p['sni'] = sni

    net = (first(q, 'type') or 'tcp').lower()
    if net == 'ws':
        p['network'] = 'ws'
        opts = {'path': first(q, 'path') or '/'}
        h = first(q, 'host')
        if h:
            opts['headers'] = {'Host': h}
        p['ws-opts'] = opts
    elif net == 'grpc':
        p['network'] = 'grpc'
        p['grpc-opts'] = {'grpc-service-name': first(q, 'serviceName') or ''}

    alpn = first(q, 'alpn')
    if alpn:
        p['alpn'] = [a for a in alpn.split(',') if a]
    return p


def parse_ss(url):
    body = url[len('ss://'):].split('#', 1)[0]
    plugin = None
    if '?' in body:
        body, qs = body.split('?', 1)
        plugin = parse_qs(qs).get('plugin', [None])[0]

    if '@' in body:
        userinfo, hostport = body.rsplit('@', 1)
        if ':' not in userinfo:
            userinfo = b64decode(userinfo)
        if ':' not in userinfo:
            return None
        method, password = userinfo.split(':', 1)
    else:
        decoded = b64decode(body)
        if '@' not in decoded:
            return None
        userinfo, hostport = decoded.rsplit('@', 1)
        if ':' not in userinfo:
            return None
        method, password = userinfo.split(':', 1)

    host, port = split_hostport(hostport)
    if not host:
        return None

    p = {
        'type': 'ss',
        'server': host,
        'port': port,
        'cipher': method.strip(),
        'password': password.strip(),
        'udp': True,
    }
    if plugin:
        pname, _, opts = plugin.partition(';')
        p['plugin'] = pname.strip()
        if opts:
            po = {}
            for kv in opts.split(';'):
                if '=' in kv:
                    k, v = kv.split('=', 1)
                    po[k.strip()] = v.strip()
            if po:
                p['plugin-opts'] = po
    return p


def parse_hy2(url):
    u = urlparse(url)
    if not u.username or not u.hostname:
        return None
    q = parse_qs(u.query)

    pw = unquote(u.username)
    if u.password:
        pw = pw + ':' + unquote(u.password)

    p = {
        'type': 'hysteria2',
        'server': u.hostname,
        'port': u.port or 443,
        'password': pw,
        'skip-cert-verify': truthy(first(q, 'insecure')),
    }
    sni = first(q, 'sni')
    if sni:
        p['sni'] = sni

    obfs = first(q, 'obfs')
    if obfs and obfs.lower() != 'none':
        p['obfs'] = obfs
        op = first(q, 'obfs-password')
        if op:
            p['obfs-password'] = op
    return p


def parse_tuic(url):
    u = urlparse(url)
    if not u.hostname:
        return None
    q = parse_qs(u.query)

    uuid = unquote(u.username or '')
    password = unquote(u.password or '') or first(q, 'password') or ''
    if not uuid:
        return None

    p = {
        'type': 'tuic',
        'server': u.hostname,
        'port': u.port or 443,
        'uuid': uuid,
        'password': password,
        'udp': True,
        'alpn': ['h3'],
        'skip-cert-verify': truthy(first(q, 'insecure', 'allow_insecure')),
    }
    sni = first(q, 'sni')
    if sni:
        p['sni'] = sni
    return p


PARSERS = (
    ('vmess://', parse_vmess),
    ('vless://', parse_vless),
    ('trojan://', parse_trojan),
    ('ss://', parse_ss),
    ('hysteria2://', parse_hy2),
    ('hy2://', parse_hy2),
    ('tuic://', parse_tuic),
)


def parse_link(link):
    """解析单条分享链接，返回代理字典；不支持/失败返回 None"""
    link = (link or '').strip()
    if not link:
        return None
    low = link.lower()
    for prefix, fn in PARSERS:
        if low.startswith(prefix):
            try:
                p = fn(link)
            except Exception:
                return None
            return p if validate_proxy(p) else None
    return None


def validate_proxy(p):
    if not isinstance(p, dict):
        return False
    if p.get('type') not in SUPPORTED_TYPES:
        return False
    server = str(p.get('server') or '').strip()
    if not server or ' ' in server:
        return False
    if server.lower() in ('127.0.0.1', 'localhost', '0.0.0.0'):
        return False
    try:
        port = int(p.get('port') or 0)
    except Exception:
        return False
    if port <= 0 or port > 65535:
        return False
    p['server'] = server
    p['port'] = port
    return True


def extract_links(text):
    """从文本中提取所有可识别的分享链接（自动识别 base64 / 明文）"""
    text = (text or '').strip()
    if not text:
        return []

    lines = [ln.strip() for ln in text.splitlines() if '://' in ln]
    if len(lines) >= 3:
        return lines

    decoded = b64decode(text)
    if '://' in decoded:
        return [ln.strip() for ln in decoded.splitlines() if '://' in ln]

    return lines


def looks_like_yaml(text):
    """订阅内容是 clash 配置（完整 config 或仅 proxies 段）"""
    text = text or ''
    if '://' in text and text.count('\n') > 100 and 'proxies:' not in text:
        return False
    for line in text.splitlines():
        if line.strip().startswith('proxies:'):
            return True
    return False
