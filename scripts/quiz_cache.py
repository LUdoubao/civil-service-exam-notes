"""带重试、代理和本地缓存的只读 HTTP 客户端。"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


class FetchError(RuntimeError):
    """远程资源在重试后仍无法读取。"""


class CacheStore:
    def __init__(self, root: Path, timeout: int = 15, retries: int = 2, proxy: str = "") -> None:
        self.root = root
        self.timeout = timeout
        self.retries = retries
        self.proxy = proxy
        self.opener = build_opener(ProxyHandler({"http": proxy, "https": proxy})) if proxy else build_opener()

    def _key(self, url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def read(self, namespace: str, url: str, suffix: str = ".bin") -> bytes | None:
        path = self.root / namespace / f"{self._key(url)}{suffix}"
        return path.read_bytes() if path.is_file() else None

    def write(self, namespace: str, url: str, content: bytes, suffix: str = ".bin") -> Path:
        path = self.root / namespace / f"{self._key(url)}{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def fetch(self, url: str, namespace: str, suffix: str = ".bin", refresh: bool = False) -> bytes:
        if not refresh:
            cached = self.read(namespace, url, suffix)
            if cached is not None:
                return cached

        request = Request(
            url,
            headers={
                "User-Agent": "civil-service-exam-notes/1.0 (public-source-cache)",
                "Accept": "text/html,application/json,image/*;q=0.8,*/*;q=0.5",
            },
        )
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    content = response.read()
                self.write(namespace, url, content, suffix)
                return content
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(2**attempt)
        raise FetchError(f"获取失败: {url}; {last_error}") from last_error

    def write_json(self, namespace: str, name: str, value: object) -> Path:
        path = self.root / namespace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def read_json(self, namespace: str, name: str) -> object | None:
        path = self.root / namespace / name
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
