"""小さな道具：JSON の読み書き・ロック・日時・文の整え。"""

import json
import os
import re
import time
from datetime import datetime, timezone


def read_json(path, default):
    """JSON を読む。無い・読めない時は default を返す。"""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def write_json(path, data):
    """一時ファイルに書いてから差し替える（書いている途中の物を読ませない）。"""
    path = str(path)
    temp = "%s.%d.tmp" % (path, os.getpid())
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
    _replace(temp, path)


def write_text(path, text):
    """文字のファイルを、一時ファイル経由で差し替える。"""
    path = str(path)
    temp = "%s.%d.tmp" % (path, os.getpid())
    with open(temp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    _replace(temp, path)


def _replace(temp, path):
    # Windows では、ほかの処理が読んでいる間は差し替えに失敗する事がある
    for attempt in range(6):
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            if attempt == 5:
                try:
                    os.remove(temp)
                except OSError:
                    pass
                raise
            time.sleep(0.05)


class Lock:
    """ロックのファイル。取れなかった時は ok が False になる（待ち続けない）。"""

    def __init__(self, path, wait=1.5, stale=60.0):
        self.path = str(path)
        self.wait = wait
        self.stale = stale
        self.ok = False

    def __enter__(self):
        deadline = time.time() + self.wait
        while True:
            try:
                handle = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(handle, str(os.getpid()).encode("ascii"))
                os.close(handle)
                self.ok = True
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.path) > self.stale:
                        os.remove(self.path)  # 古いロックは無視する
                        continue
                except OSError:
                    pass
            except OSError:
                return self
            if time.time() >= deadline:
                return self
            time.sleep(0.03)

    def __exit__(self, *_exc):
        if self.ok:
            try:
                os.remove(self.path)
            except OSError:
                pass
        return False


_TIME_PATTERN = re.compile(r"(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d):(\d\d)")


def parse_time(text):
    """ISO 形式の日時（例 2026-10-10T14:40:00.123Z）を、1970年からの秒にする。"""
    if not isinstance(text, str):
        return None
    value = text.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        match = _TIME_PATTERN.match(value)
        if not match:
            return None
        moment = datetime(*[int(part) for part in match.groups()], tzinfo=timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def local_text(seconds, with_seconds=False):
    """秒を、このPCの時刻の文字にする（例 2026-10-10 23:40）。"""
    form = "%Y-%m-%d %H:%M:%S" if with_seconds else "%Y-%m-%d %H:%M"
    return time.strftime(form, time.localtime(seconds))


def clean_text(text, limit=300):
    """改行と続いた空白を1つの空白にして、長さを切る。"""
    if not isinstance(text, str):
        return ""
    value = " ".join(text.split())
    return value[:limit]
