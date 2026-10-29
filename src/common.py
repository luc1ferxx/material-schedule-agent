"""通用工具：路径、JSON 读写、时段解析、.env 读取。只依赖标准库。"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SLOT_FORMAT = "%Y-%m-%d %H:%M"


def load_json(path: Path):
    # utf-8-sig：兼容 Windows 记事本等保存的带 BOM 文件（评审可能手改 data/schedule.json）
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json_atomic(path: Path, data) -> None:
    """先写临时文件再替换，避免写一半留下损坏的草稿库。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def canonical_hash(obj) -> str:
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_SLOT_INPUT_FORMATS = (SLOT_FORMAT, "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d %H:%M")


def parse_slot(text: str) -> datetime:
    """解析时间；接受 '2026-11-03 19:00'、'2026-11-3 19:00'、'2026-11-03T19:00' 等常见写法，格式不对抛 ValueError。

    所有比较都应先 fmt_slot(parse_slot(x)) 规范化，避免“同一时刻、不同写法”被当成不同时段。
    """
    text = str(text).strip()
    for fmt in _SLOT_INPUT_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"无法解析时间：{text}")


def canonical_slot(text: str) -> str:
    return fmt_slot(parse_slot(text))


def fmt_slot(dt: datetime) -> str:
    return dt.strftime(SLOT_FORMAT)


def is_empty(value) -> bool:
    return value is None or value == "" or value == [] or value == {}


def load_dotenv(path: Path) -> None:
    """极简 .env 读取：KEY=VALUE，忽略注释和空值；不覆盖已存在的环境变量。"""
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(key.strip(), value)
