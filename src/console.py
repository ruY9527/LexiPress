"""控制台编码保障：在 Windows（GBK/CP936）下强制 UTF-8 输出。

所有 CLI 入口（main.py / scripts/*）在启动最初调用 `ensure_utf8_console()`，
避免日志中的 ✓ ✗ ⊘ 等符号触发 UnicodeEncodeError。
"""

from __future__ import annotations

import io
import sys


def ensure_utf8_console() -> None:
    """把 stdout / stderr 重新包装为 UTF-8，失败时静默跳过。"""

    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        encoding = (getattr(stream, "encoding", "") or "").lower()
        if encoding.replace("-", "") in {"utf8", "utf8mb4"}:
            continue
        try:
            buffer = getattr(stream, "buffer", None)
            if buffer is not None:
                setattr(
                    sys,
                    name,
                    io.TextIOWrapper(buffer, encoding="utf-8", errors="replace", line_buffering=True),
                )
        except (AttributeError, ValueError, OSError):
            continue
