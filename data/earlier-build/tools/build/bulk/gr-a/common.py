"""GR-A shared helpers: paths, curl-based HTTP (Python TLS fails on this machine), request logging, rate limits.

Every request is logged to <SRC>/requests-<host>.jsonl as {ts, url, status, bytes, sha256}.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

SRC = Path(r'C:\Users\alany\Documents\greece-law-src')
HERE = Path(__file__).resolve().parent
WORK = Path(r'C:\Users\alany\Documents\balkan-deep\greece-serbia\gr-a')
UA = 'lexifina-watch/1.0 (+https://lexifina.com/watch; corpus@lexifina.com)'
BLOB = 'https://ia37rg02wpsa01.blob.core.windows.net/fek'
SEARCH = 'https://searchetv99.azurewebsites.net/api'
NOWIN = 0x08000000  # CREATE_NO_WINDOW

_last: dict[str, float] = {}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def free_gb() -> float:
    return shutil.disk_usage('C:\\').free / 1e9


def _pace(host: str, interval: float) -> None:
    wait = interval - (time.monotonic() - _last.get(host, 0.0))
    if wait > 0:
        time.sleep(wait)
    _last[host] = time.monotonic()


def log_request(url: str, status: str, size: int, digest: str | None) -> None:
    host = urlparse(url).hostname
    with open(SRC / f'requests-{host}.jsonl', 'a', encoding='utf-8') as f:
        f.write(json.dumps({'ts': now(), 'url': url, 'status': status, 'bytes': size, 'sha256': digest},
                           ensure_ascii=False) + '\n')


def curl(url: str, out: Path, interval: float, data: str | None = None, headers: dict | None = None,
         timeout: int = 180) -> str:
    """Fetch url into out (atomically via .part). Returns the HTTP status as a string ('000' on transport error)."""
    host = urlparse(url).hostname
    _pace(host, interval)
    tmp = out.with_name(out.name + '.part')
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ['curl', '-sS', '--compressed', '-L', '--max-time', str(timeout), '-A', UA, '-o', str(tmp),
           '-w', '%{http_code}']
    for k, v in (headers or {}).items():
        cmd += ['-H', f'{k}: {v}']
    if data is not None:
        cmd += ['-X', 'POST', '-H', 'Content-Type: application/json', '--data-binary', data]
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=NOWIN)
    status = (r.stdout.strip() or '000')[-3:]
    size = tmp.stat().st_size if tmp.exists() else 0
    digest = hashlib.sha256(tmp.read_bytes()).hexdigest() if size else None
    log_request(url if data is None else f'{url} POST {data}', status, size, digest)
    if status == '200' and size > 0:
        os.replace(tmp, out)
    elif tmp.exists():
        tmp.unlink()
    return status


def http_get(url: str, out: Path, interval: float, data: str | None = None, headers: dict | None = None,
             timeout: int = 180) -> str:
    """As curl(), in-process with urllib (no process spawn per request: under full CPU load a curl spawn took
    ~12 s). Falls back to curl() on a TLS/transport error. Returns the HTTP status as a string."""
    import ssl
    import urllib.error
    import urllib.request
    host = urlparse(url).hostname
    _pace(host, interval)
    tmp = out.with_name(out.name + '.part')
    out.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, data=data.encode('utf-8') if data is not None else None,
                                 headers={'User-Agent': UA, **({'Content-Type': 'application/json'} if data else {}),
                                          **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            status = str(r.status)
    except urllib.error.HTTPError as e:
        body, status = b'', str(e.code)
    except (ssl.SSLError, urllib.error.URLError, OSError) as e:
        if isinstance(e, urllib.error.URLError) and not isinstance(getattr(e, 'reason', None), ssl.SSLError):
            log_request(url, '000', 0, None)
            return '000'
        _last[host] = 0.0
        return curl(url, out, interval, data, headers, timeout)
    if status == '200' and body:
        tmp.write_bytes(body)
        os.replace(tmp, out)
    log_request(url if data is None else f'{url} POST {data}', status, len(body),
                hashlib.sha256(body).hexdigest() if body else None)
    return status


def write_json_atomic(path: Path, obj, gz: bool = False, indent=None) -> None:
    import gzip
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    data = json.dumps(obj, ensure_ascii=False, indent=indent, sort_keys=False).encode('utf-8')
    if gz:
        with open(tmp, 'wb') as raw:
            with gzip.GzipFile(fileobj=raw, mode='wb', mtime=0, filename='') as f:
                f.write(data)
    else:
        tmp.write_bytes(data + b'\n')
    os.replace(tmp, path)


def pdf_url(series: str, year: int, num: int) -> str:
    return f'{BLOB}/{series}/{year}/{year}{series}{num:05d}.pdf'


def api_url(series: str, year: int, num: int) -> str:
    return f'https://api.et.gr/apiFEK/{int(series)}/{year}/{num}/pdf'
