"""会話の記録（Claude Code が残す .jsonl）を読んで、部屋を見つける。

読むだけ。会話の記録には何も書かない。
拾う物は3つ：最後の日時／作業フォルダの場所／最後に頼んだ文。
記録の行の書式は Claude Code の内部の物で、版によって変わる。
読めない行は飛ばし、読めなかった本数を数えて返す。
"""

import json
import os
import time
from pathlib import Path

from . import paths, rooms, util

TAIL_SMALL = 64 * 1024
TAIL_LARGE = 512 * 1024
CACHE_VERSION = 3  # 3＝1つ前に頼んだ文を控える・裏の作業の知らせを頼んだ文に数えない（0.1.4）


def projects_dir():
    """会話の記録の置き場所。"""
    base = (os.environ.get("CLAUDE_CONFIG_DIR") or "").strip()
    root = Path(base).expanduser() if base else Path.home() / ".claude"
    return root / "projects"


def encode_path(path):
    """Claude Code が記録のフォルダ名を作る時の置き換え（英数字以外を - にする）。"""
    out = []
    for char in path:
        if char.isascii() and char.isalnum():
            out.append(char)
        else:
            out.append("-" * (len(char.encode("utf-16-le")) // 2))
    return "".join(out)


def room_root(cwd, folder_name):
    """cwd から上へたどり、記録のフォルダ名と合う場所を返す。無ければ cwd のまま。

    会話の途中で下のフォルダへ移った時も、会話を始めたフォルダを部屋とするため。
    """
    current = cwd.rstrip("\\/")
    for _ in range(40):
        if not current:
            break
        if encode_path(current) == folder_name:
            return current
        current = rooms.parent_of(current)
    return cwd


def _tail_rows(path, size, limit):
    """ファイルの末尾 limit バイトを読み、JSON として読めた行を返す。"""
    start = max(0, size - limit)
    with open(path, "rb") as handle:
        handle.seek(start)
        raw = handle.read()
    lines = raw.split(b"\n")
    if start > 0:
        lines = lines[1:]  # 途中から始まった行は捨てる
    rows = []
    for raw_line in lines:
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line.decode("utf-8", errors="replace"))
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _user_text(row):
    """人が打った文なら、その文を返す。道具の結果・自動で入る文なら空の文字。"""
    if row.get("type") != "user":
        return ""
    for flag in ("isMeta", "isSidechain", "isCompactSummary", "isVisibleInTranscriptOnly"):
        if row.get(flag):
            return ""
    if row.get("toolUseResult") is not None:
        return ""
    message = row.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                return ""
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
        text = " ".join(parts)
    else:
        return ""
    # コマンドの包み・中断の知らせ・裏の作業の知らせなど、自動で入る文は空になる
    return util.prompt_text(text)


def _pick(rows):
    """読めた行から、最後の日時・場所・頼んだ文（とその日時）・その1つ前に頼んだ文を拾う。"""
    last_time = None
    cwds = []
    prompts = []  # 人が頼んだ文。続けて同じ文は1つにまとめる
    prompt_time = None
    for row in rows:
        moment = util.parse_time(row.get("timestamp"))
        if moment is not None:
            last_time = moment
        cwd = row.get("cwd")
        if isinstance(cwd, str) and cwd and (not cwds or cwds[-1] != cwd):
            cwds.append(cwd)
        # 「最後に頼んだ文」の行と、人が打った文の行のうち、後ろにある方を使う
        if row.get("type") == "last-prompt":
            text = util.prompt_text(row.get("lastPrompt"))
            this_time = None
        else:
            text = _user_text(row)
            this_time = moment
        if text:
            if not prompts or prompts[-1] != text:
                prompts.append(text)
            if this_time is not None:
                prompt_time = this_time
    prompt = prompts[-1] if prompts else ""
    previous = prompts[-2] if len(prompts) > 1 else ""
    return last_time, cwds, prompt, prompt_time, previous


def read_record(path, folder_name):
    """記録1本を読む。返す物＝ok（1行でも読めたか）・path・time・prompt・prompt_time・prev_prompt。"""
    info = {"ok": False, "path": "", "time": None, "prompt": "", "prompt_time": None, "prev_prompt": ""}
    try:
        size = os.path.getsize(path)
        for limit in (TAIL_SMALL, TAIL_LARGE):
            rows = _tail_rows(path, size, limit)
            last_time, cwds, prompt, prompt_time, previous = _pick(rows)
            info["ok"] = bool(rows)
            info["time"] = last_time
            info["prompt"] = util.clean_text(prompt)
            info["prompt_time"] = prompt_time
            info["prev_prompt"] = util.clean_text(previous)
            # 新しい方から見て、記録のフォルダ名と合う場所を部屋とする。
            # 合う物が無ければ、いちばん新しい cwd をそのまま使う。
            info["path"] = cwds[-1] if cwds else ""
            for cwd in reversed(cwds):
                root = room_root(cwd, folder_name)
                if encode_path(root) == folder_name:
                    info["path"] = root
                    break
            # 頼んだ文が短い合図の時は、1つ前の文も欲しいので、見つかるまで長く読む
            wants_previous = len(info["prompt"]) < util.SHORT_PROMPT and not info["prev_prompt"]
            complete = last_time is not None and info["path"] and info["prompt"] and not wants_previous
            if complete or limit >= size:
                break
    except Exception:
        info["ok"] = False
    return info


def scan(keep_prompts=True):
    """会話の記録を全部見て、rooms.json に重ねる。数えた物を返す。

    keep_prompts が False の時は、「最後に頼んだ文」を控えない（控えてあった物も消す）。
    """
    started = time.perf_counter()
    home = paths.ensure_home()
    cache_file = home / "scan_cache.json"
    cache = util.read_json(cache_file, {})
    old_files = None
    if isinstance(cache, dict) and cache.get("version") == CACHE_VERSION and cache.get("prompts") == keep_prompts:
        old_files = cache.get("files")
    if not isinstance(old_files, dict):
        old_files = {}

    stats = {"folders": 0, "files": 0, "read": 0, "reused": 0, "unreadable": 0, "rooms": 0}
    new_files = {}
    found = {}  # 部屋の id → いちばん新しい記録から拾った物
    asked = {}  # 部屋の id → [(記録の日時, その記録で最後に頼んだ文)]（1つ前の会話の文を探すため）
    root = projects_dir()
    stats["projects_dir_found"] = root.is_dir()

    folders = []
    if root.is_dir():
        with os.scandir(root) as entries:
            folders = sorted((e for e in entries if e.is_dir()), key=lambda e: e.name)

    for folder in folders:
        try:
            with os.scandir(folder.path) as entries:
                record_files = [e for e in entries if e.is_file() and e.name.endswith(".jsonl")]
        except OSError:
            continue
        if not record_files:
            continue  # 下の階層にしか記録が無いフォルダは、部屋として数えない
        stats["folders"] += 1
        for record in record_files:
            try:
                stat = record.stat()
            except OSError:
                continue
            stats["files"] += 1
            key = folder.name + "/" + record.name
            old = old_files.get(key)
            if isinstance(old, list) and len(old) == 3 and old[0] == stat.st_mtime_ns and old[1] == stat.st_size:
                info = old[2]
                stats["reused"] += 1
            else:
                info = read_record(record.path, folder.name)
                if not keep_prompts:
                    info["prompt"] = ""
                    info["prompt_time"] = None
                    info["prev_prompt"] = ""
                stats["read"] += 1
            new_files[key] = [stat.st_mtime_ns, stat.st_size, info]

            if not info.get("ok"):
                stats["unreadable"] += 1
            moment = info.get("time")
            time_from = "record"
            if moment is None:
                moment = stat.st_mtime  # 読めない時は、ファイルの更新時刻を使う
                time_from = "file_time"
            path = info.get("path") or ""
            room_key = rooms.room_id(path) if path else rooms.project_id(folder.name)
            if info.get("prompt"):
                asked.setdefault(room_key, []).append((moment, info["prompt"]))
            best = found.get(room_key)
            if best is None or moment > best["time"]:
                found[room_key] = {
                    "path": path,
                    "project": folder.name,
                    "time": moment,
                    "time_from": time_from,
                    "prompt": info.get("prompt") or "",
                    "prompt_time": info.get("prompt_time"),
                    "prev_prompt": info.get("prev_prompt") or "",
                }

    if stats["read"] or set(new_files) != set(old_files):
        util.write_json(cache_file, {"version": CACHE_VERSION, "prompts": keep_prompts, "files": new_files})

    # 「再開」のような短い合図は、新しい会話の最初に打つ事が多い（同じ会話の中に1つ前の文が無い）。
    # その時は、同じ部屋の1つ前の会話で最後に頼んだ文を「1つ前に頼んだ文」にする
    for room_key, hit in found.items():
        if hit["prompt"] and len(hit["prompt"]) < util.SHORT_PROMPT and not hit["prev_prompt"]:
            earlier = sorted((item for item in asked.get(room_key, []) if item[0] < hit["time"] and item[1] != hit["prompt"]),
                             key=lambda item: item[0])
            if earlier:
                hit["prev_prompt"] = earlier[-1][1]

    merged = _merge_pathless(found)
    now = time.time()
    stats["rooms"] = len(found)

    def change(data):
        for key in merged:
            data["rooms"].pop(key, None)  # 前の版が別の部屋として控えた物も消す
        for key, room in data["rooms"].items():
            if key not in found and room.get("project"):
                room["record_gone"] = True  # 記録は消えたが、部屋は残す
            if not keep_prompts:
                for name in PROMPT_KEYS:
                    room.pop(name, None)
        for key, hit in found.items():
            room = data["rooms"].get(key)
            if room is None:
                room = {"id": key, "first_seen": now}
                data["rooms"][key] = room
            room["path"] = hit["path"]
            room["project"] = hit["project"]
            room["name"] = rooms.room_name(hit["path"]) if hit["path"] else hit["project"]
            room["record_gone"] = False
            if hit["time"] >= (room.get("last_active") or 0):
                room["last_active"] = hit["time"]
                room["last_active_from"] = hit["time_from"]
            if hit["prompt"] and keep_prompts:
                if room.get("last_prompt_from") == "hook":
                    # フックで入った文は、記録の方が新しいと分かる時だけ置き換える
                    newer = hit["prompt_time"] is not None and hit["prompt_time"] > (room.get("last_prompt_at") or 0)
                else:
                    newer = True
                if newer:
                    room["last_prompt"] = hit["prompt"]
                    room["last_prompt_at"] = hit["prompt_time"] or hit["time"]
                    room["last_prompt_from"] = "record"
                    if hit["prev_prompt"]:
                        room["prev_prompt"] = hit["prev_prompt"]
                    else:
                        room.pop("prev_prompt", None)
        data["scan"] = {
            "folders": stats["folders"],
            "files": stats["files"],
            "unreadable": stats["unreadable"],
            "projects_dir_found": stats["projects_dir_found"],
        }

    stats["saved"] = rooms.update(change)
    stats["sec"] = round(time.perf_counter() - started, 3)
    return stats


def _merge_pathless(found):
    """場所の分からない記録を、同じ記録のフォルダの部屋にまとめる。まとめて消した部屋の id を返す。

    作業フォルダの場所が1行も書かれていない記録は、記録のフォルダの名前で別の部屋になる。
    同じ記録のフォルダに、場所の分かる部屋が1つだけある時は、同じ部屋とみなしてそちらに足す
    （場所の分かる部屋が2つ以上ある時＝名前の置き換えで重なった別々のフォルダは、どちらか分からないので足さない）。
    """
    by_project = {}
    for key, hit in found.items():
        if hit["path"]:
            by_project.setdefault(hit["project"], []).append(key)
    merged = []
    for folder_name, keys in by_project.items():
        lost_key = rooms.project_id(folder_name)
        lost = found.get(lost_key)
        if lost is None or lost["path"] or len(keys) != 1:
            continue
        target = found[keys[0]]
        if lost["time"] > target["time"]:
            target["time"] = lost["time"]
            target["time_from"] = lost["time_from"]
            if lost["prompt"]:
                for name in ("prompt", "prompt_time", "prev_prompt"):
                    target[name] = lost[name]
        del found[lost_key]
        merged.append(lost_key)
    return merged


PROMPT_KEYS = ("last_prompt", "last_prompt_at", "last_prompt_from", "prev_prompt")


def holds_prompts():
    """控えた「最後に頼んだ文」が、rooms.json に残っているか。"""
    return any(room.get("last_prompt") for room in rooms.load()["rooms"].values())


def drop_prompts():
    """控えてあった「最後に頼んだ文」を、置き場所から消す（会話の記録は読み直さない）。

    「最後に頼んだ文」を隠す設定に変えた、その場で呼ぶ。消した物があれば True。
    先に scan_cache.json、あとに rooms.json を書く（途中で止まっても、次の機会にもう一度消しに来る）。
    """
    home = paths.ensure_home()
    dropped = False
    cache_file = home / "scan_cache.json"
    cache = util.read_json(cache_file, {})
    if isinstance(cache, dict) and cache.get("prompts") and isinstance(cache.get("files"), dict):
        for entry in cache["files"].values():
            if isinstance(entry, list) and len(entry) == 3 and isinstance(entry[2], dict):
                entry[2]["prompt"] = ""
                entry[2]["prompt_time"] = None
        cache["prompts"] = False
        util.write_json(cache_file, cache)
        dropped = True

    def change(data):
        for room in data["rooms"].values():
            for name in PROMPT_KEYS:
                room.pop(name, None)

    if rooms.update(change) == "saved":
        dropped = True
    return dropped
