"""rooms.json＝見つけた部屋の控え。

部屋＝Claude Code を開いた作業フォルダ。会話の記録が消えた後も、ここには残す。
中身が変わらない時は、ファイルを書き直さない（画面の作り直しのきっかけにしないため）。
"""

import hashlib
import json
import os
import time

from . import paths, util

VERSION = 1
ACTIVE_STEP = 60  # 秒。「最後に動いた日時」は、これより細かくは書き直さない


def room_id(path):
    """作業フォルダの場所から、部屋の id（10文字）を作る。"""
    normal = os.path.normcase(os.path.normpath(path))
    return hashlib.sha1(normal.encode("utf-8", errors="replace")).hexdigest()[:10]


def project_id(folder_name):
    """場所が分からない記録は、記録のフォルダの名前から id を作る。"""
    return hashlib.sha1(("project:" + folder_name).encode("utf-8")).hexdigest()[:10]


def room_name(path):
    """場所のいちばん後ろの名前。"""
    trimmed = path.rstrip("\\/")
    cut = max(trimmed.rfind("\\"), trimmed.rfind("/"))
    return trimmed[cut + 1:] or trimmed


def parent_of(path):
    """1つ上のフォルダ。無ければ空の文字。"""
    trimmed = path.rstrip("\\/")
    cut = max(trimmed.rfind("\\"), trimmed.rfind("/"))
    return trimmed[:cut] if cut > 0 else ""


def rooms_file():
    return paths.home() / "rooms.json"


def load():
    data = util.read_json(rooms_file(), {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", VERSION)
    if not isinstance(data.get("rooms"), dict):
        data["rooms"] = {}
    if not isinstance(data.get("scan"), dict):
        data["scan"] = {}
    return data


def update(change):
    """ロックを取って rooms.json を読み、change(data) で書き換えて保存する。

    返す物＝"saved"（書いた）／"same"（変わらないので書かなかった）／
            "busy"（ロックが取れず見送った。次の機会に書く）
    """
    home = paths.ensure_home()
    with util.Lock(home / "rooms.lock") as lock:
        if not lock.ok:
            return "busy"
        data = load()
        before = json.dumps(data, ensure_ascii=False, sort_keys=True)
        change(data)
        if rooms_file().exists() and json.dumps(data, ensure_ascii=False, sort_keys=True) == before:
            return "same"
        util.write_json(rooms_file(), data)
    return "saved"


def find_by_cwd(data, cwd):
    """cwd か、その上のフォルダの中で、知っている部屋を探す。無ければ None。"""
    current = cwd
    for _ in range(40):
        if not current:
            break
        found = data["rooms"].get(room_id(current))
        if found and found.get("path"):
            return found
        current = parent_of(current)
    return None


def touch(path, prompt=None, now=None, exact=False):
    """その部屋の「最後に動いた日時」と「最後に頼んだ文」を新しくする。

    日時は ACTIVE_STEP 秒より細かくは書き直さない（exact=True の時は必ず書く）。
    """
    now = time.time() if now is None else now
    key = room_id(path)

    def change(data):
        room = data["rooms"].get(key)
        if room is None:
            room = {"id": key, "first_seen": now}
            data["rooms"][key] = room
        room["path"] = path
        room["name"] = room_name(path)
        text = util.clean_text(prompt) if prompt else ""
        new_prompt = bool(text) and text != room.get("last_prompt")
        old = room.get("last_active") or 0
        if exact or new_prompt or now - old >= ACTIVE_STEP:
            room["last_active"] = now
            room["last_active_from"] = "hook"
        if text and (new_prompt or room.get("last_prompt_from") != "hook"):
            room["last_prompt"] = text
            room["last_prompt_at"] = now
            room["last_prompt_from"] = "hook"

    return update(change)
