from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import threading
import time
from urllib.parse import urlparse

import requests
import urllib3
from flask import current_app
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..extensions import cache

log = logging.getLogger("watercast.http")

SACHET_HOST = "sachet.ndma.gov.in"
BROWSER_UA = "Mozilla/5.0 (compatible; WaterCast/1.0; +https://github.com/watercast)"
_local = threading.local()
_tls_unverified_hosts: set[str] = set()


class UpstreamError(Exception):

    def __init__(self, url: str, cause: Exception):
        super().__init__(str(cause))
        self.url, self.cause = url, cause

    def describe(self) -> str:
        host = urlparse(self.url).hostname or "the server"
        c = self.cause
        if isinstance(c, requests.HTTPError) and c.response is not None:
            code = c.response.status_code
            hint = (" (access refused)" if code in (401, 403) else " (not found)" if code == 404
                    else " (rate limited)" if code == 429 else "")
            return f"{host} answered HTTP {code}{hint}"
        if isinstance(c, requests.exceptions.SSLError):
            return f"the secure connection (TLS) to {host} failed"
        if isinstance(c, requests.exceptions.Timeout):
            return f"{host} took too long to answer (timeout)"
        if isinstance(c, requests.exceptions.ConnectionError):
            text = str(c).lower()
            if "timed out" in text or "timeout" in text:
                return f"{host} took too long to answer (timeout)"
            if "name or service not known" in text or "getaddrinfo" in text or "nodename" in text:
                return f"could not find {host} (DNS lookup failed)"
            return f"could not connect to {host}"
        if isinstance(c, (ValueError, UnicodeDecodeError)):
            return f"{host} did not return valid data"
        return f"{host}: {type(c).__name__}"


def _session() -> requests.Session:
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        retry = Retry(total=2, connect=2, read=1, backoff_factor=0.4, status_forcelist=(502, 503, 504),
                      allowed_methods=("GET",), respect_retry_after_header=True)
        s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=16))
        s.mount("http://", HTTPAdapter(max_retries=retry, pool_maxsize=16))
        _local.session = s
    return s


def _etag_key(url: str, params: dict | None) -> str:
    raw = url + "?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
    return "etag:" + hashlib.sha256(raw.encode()).hexdigest()


def fetch(url: str, *, params: dict | None = None, headers: dict | None = None, timeout: float | None = None,
          max_age: float = 0) -> bytes:
    cfg = current_app.config
    timeout = timeout or cfg["HTTP_TIMEOUT"]
    host = urlparse(url).hostname or ""
    key = _etag_key(url, params)
    entry = cache.get(key)
    if entry and max_age and time.time() - entry["at"] < max_age:
        return entry["body"]

    h = {"User-Agent": cfg["HTTP_USER_AGENT"], "Accept": "application/json, application/xml, text/xml, */*"}
    if host == SACHET_HOST:
        h.update({"User-Agent": BROWSER_UA, "Accept-Language": "en-IN,en;q=0.9"})
    h.update(headers or {})
    if entry and entry.get("etag"):
        h["If-None-Match"] = entry["etag"]

    verify = host not in _tls_unverified_hosts
    tried_session = False
    while True:
        try:
            resp = _session().get(url, params=params, headers=h, timeout=timeout, verify=verify)
            if resp.status_code == 304 and entry:
                entry["at"] = time.time()
                cache.set(key, entry, timeout=86400)
                return entry["body"]
            if resp.status_code in (401, 403) and host == SACHET_HOST and not tried_session:
                tried_session = True
                parsed = urlparse(url)
                with contextlib.suppress(requests.RequestException):
                    _session().get(f"{parsed.scheme}://{parsed.netloc}/", headers=h, timeout=timeout, verify=verify)
                continue
            resp.raise_for_status()
            body = resp.content
            cache.set(key, {"etag": resp.headers.get("ETag"), "body": body, "at": time.time()}, timeout=86400)
            return body
        except requests.exceptions.SSLError as exc:
            if verify and host == SACHET_HOST and cfg["SACHET_INSECURE_TLS_FALLBACK"]:
                log.warning("TLS certificate of %s could not be verified; continuing WITHOUT verification for this "
                            "public alert feed (set SACHET_INSECURE_TLS_FALLBACK=false to forbid).", host)
                _tls_unverified_hosts.add(host)
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                verify = False
                continue
            raise UpstreamError(url, exc) from exc
        except requests.RequestException as exc:
            raise UpstreamError(url, exc) from exc


def fetch_json(url: str, *, params: dict | None = None, headers: dict | None = None, timeout: float | None = None):
    body = fetch(url, params=params, headers=headers, timeout=timeout)
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise UpstreamError(url, exc) from exc


def tls_was_unverified(host: str = SACHET_HOST) -> bool:
    return host in _tls_unverified_hosts
