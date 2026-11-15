"""Bound display work without changing the original messages in the journal."""

import json


MAX_LOG_LINE = 1400


def display_value(value, depth=0, key="") -> str:
    """Build a short preview without serializing a full image or spectrum."""
    if key.lower() in ("imagebuff", "imagebuffer", "imagedata", "spectrumdata"):
        size = len(value) if isinstance(value, (str, bytes, list, dict)) else 0
        return f"<大字段，长度 {size}>"
    if isinstance(value, str):
        text = value[:160]
        return json.dumps(text, ensure_ascii=False) + (f"…（共 {len(value)} 字符）" if len(value) > 160 else "")
    if isinstance(value, bytes):
        return f"<二进制，{len(value)} 字节>"
    if isinstance(value, dict):
        if depth >= 3:
            return f"<对象，{len(value)} 个字段>"
        parts = []
        for index, (name, child) in enumerate(value.items()):
            if index == 16:
                parts.append(f"…（共 {len(value)} 个字段）")
                break
            parts.append(f"{str(name)[:80]}: {display_value(child, depth + 1, str(name))}")
        return "{" + ", ".join(parts) + "}"
    if isinstance(value, (list, tuple)):
        if depth >= 3:
            return f"<数组，{len(value)} 项>"
        parts = [display_value(child, depth + 1) for child in value[:4]]
        if len(value) > 4:
            parts.append(f"…（共 {len(value)} 项）")
        return "[" + ", ".join(parts) + "]"
    return str(value)[:160]


def log_preview(value) -> str:
    return bounded_line(display_value(value))


def bounded_line(text: str) -> str:
    # A single device packet must never create thousands of wrapped Tk lines.
    text = str(text)
    truncated = len(text) > MAX_LOG_LINE
    text = text[:MAX_LOG_LINE].encode("utf-8", "backslashreplace").decode("utf-8")
    text = text.replace("\r", "\\r").replace("\n", "\\n").replace("\0", "\\0")
    if truncated or len(text) > MAX_LOG_LINE:
        return text[:MAX_LOG_LINE - 25] + "…（完整内容见日志文件）"
    return text
