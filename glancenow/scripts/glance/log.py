"""log.txt に1行ずつ書く。1行＝JSON 1つ。

書けなくても、呼んだ側を止めない。
"""

import json
import time

from . import paths

MAX_BYTES = 512 * 1024  # これを超えたら log.old.txt へ回す


def now_text():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def write(kind, **fields):
    """log.txt に1行足す。kind は行の種類（hook・error など）。"""
    line = {"t": now_text(), "kind": kind}
    line.update(fields)
    text = json.dumps(line, ensure_ascii=False) + "\n"
    try:
        paths.ensure_home()
        target = paths.log_file()
        if target.exists() and target.stat().st_size > MAX_BYTES:
            old = target.with_name("log.old.txt")
            if old.exists():
                old.unlink()
            target.rename(old)
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(text)
    except paths.HomeNotAllowed:
        _write_devguard(text)
    except Exception:
        pass


def _write_devguard(text):
    try:
        with open(paths.DEVGUARD_LOG, "a", encoding="utf-8") as handle:
            handle.write(text)
    except Exception:
        pass
