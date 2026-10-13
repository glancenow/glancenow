"""画面を、元が変わった時だけ作り直す。フックから毎回呼ばれる。

元＝config.json・rooms.json・records の中のファイル。
どれかが画面より新しい時だけ作る。時間で動く仕組みは持たない。
"""

import os
import time

from . import build, config, paths, records, rooms, state, util

MIN_INTERVAL = 20  # 秒。フックからの作り直しは、前回からこれより短い間隔では行わない
LOCK_STALE = 60    # 秒。これより古いロックは、途中で止まった跡とみなす


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0


def sources_time():
    """元のファイルのうち、いちばん新しい更新時刻。"""
    newest = max(_mtime(config.config_file()), _mtime(rooms.rooms_file()))
    folder = records.records_dir()
    newest = max(newest, _mtime(folder))  # 記録が増えた・消えたは、フォルダの時刻に出る
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.name.endswith(".md"):
                    newest = max(newest, entry.stat().st_mtime)
    except OSError:
        pass
    return newest


def check(reason, force=False):
    """作り直すかを決めて、要る時だけ作る。

    返す物＝"built"（作った）／"not-setup"（最初の質問がまだ）／"fresh"（元が変わっていない）／
            "too-soon"（前回から間が無い。次の機会に作る）／"busy"（ほかの処理が作っている）
    force=True は、間隔を見ずに作る（記録を書いた直後など、使う人がすぐ見る時）。
    """
    current = state.load()
    if not current["setup_done"]:
        return "not-setup"
    page = build.page_file()
    exists = page.exists()
    if exists and sources_time() <= _mtime(page):
        return "fresh"
    if exists and not force and time.time() - (current["last_build"] or 0) < MIN_INTERVAL:
        return "too-soon"
    home = paths.ensure_home()
    with util.Lock(home / "build.lock", wait=2.0 if force else 0.0, stale=LOCK_STALE) as lock:
        if not lock.ok:
            return "busy"
        build.build(reason)
    return "built"
