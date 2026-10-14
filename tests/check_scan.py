"""P2 の検査：会話の記録を読む（scan）と、記録に1行足す（note）。

使い方:
  python check_scan.py

一時フォルダにダミーの記録を作り、そこだけを読んで答えを比べる。
本物の会話の記録も、本物の置き場所も触らない。
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "glancenow" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

results = []


def check(label, ok, detail=""):
    results.append(bool(ok))
    print("%s  %s%s" % ("OK" if ok else "NG", label, ("  ← " + detail) if (detail and not ok) else ""))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    work = Path(tempfile.mkdtemp(prefix="glancenow-check-"))
    dummy = work / "claude_config"
    home = work / "home"
    os.environ["CLAUDE_CONFIG_DIR"] = str(dummy)
    os.environ["GLANCENOW_HOME"] = str(home)

    import make_dummy
    from glance import records, rooms, scan

    expected = make_dummy.build(dummy)

    # --- 1回目の scan ---
    stats = scan.scan()
    data = json.loads((home / "rooms.json").read_text(encoding="utf-8"))
    found = data["rooms"]
    check("部屋の数が %d" % len(expected["rooms"]), len(found) == len(expected["rooms"]), "実際は %d" % len(found))
    check("記録のあるフォルダが %d" % expected["folders"], stats["folders"] == expected["folders"], str(stats["folders"]))
    check("記録が %d本" % expected["files"], stats["files"] == expected["files"], str(stats["files"]))
    check("読めなかった本数が %d" % expected["unreadable"], stats["unreadable"] == expected["unreadable"], str(stats["unreadable"]))
    check("rooms.json にも読めなかった本数が入っている", data["scan"].get("unreadable") == expected["unreadable"])

    for want in expected["rooms"]:
        key = rooms.room_id(want["path"]) if want["path"] else rooms.project_id(want["project"])
        got = found.get(key)
        label = want["label"]
        if got is None:
            check("[%s] 部屋が見つかる" % label, False, "id %s が無い" % key)
            continue
        check("[%s] 部屋が見つかる" % label, True)
        check("[%s] 場所" % label, got.get("path", "") == want["path"], repr(got.get("path")))
        check("[%s] 名前" % label, got.get("name") == want["name"], repr(got.get("name")))
        check("[%s] 最後に動いた日時" % label, abs((got.get("last_active") or 0) - want["last_active"]) < 1,
              "%s と %s" % (got.get("last_active"), want["last_active"]))
        check("[%s] 日時の出どころ" % label, got.get("last_active_from") == want["last_active_from"],
              repr(got.get("last_active_from")))
        check("[%s] 最後に頼んだ文" % label, got.get("last_prompt", "") == want["last_prompt"],
              repr(got.get("last_prompt")))

    check("子エージェントの記録だけのフォルダは部屋に入らない",
          all(room.get("project") != expected["not_a_room"] for room in found.values()))

    # --- OS の一時フォルダの下かどうかを見分ける ---
    temp = tempfile.gettempdir()
    inside = os.path.join(temp, "some-room", "src")
    check("一時フォルダと、その下の場所を見分ける", rooms.is_temp(temp) and rooms.is_temp(inside)
          and (os.name != "nt" or rooms.is_temp(inside.upper())), repr(rooms.temp_roots()))
    check("一時フォルダの外・名前が似ているだけの場所・場所の分からない部屋は、一時フォルダとしない",
          not rooms.is_temp(expected["rooms"][0]["path"]) and not rooms.is_temp(temp.rstrip("\\/") + "-other") and not rooms.is_temp(""),
          repr(rooms.temp_roots()))

    # --- 2回目の scan（変わっていない記録は読み直さない） ---
    again = scan.scan()
    check("2回目は1本も読み直さない", again["read"] == 0 and again["reused"] == expected["files"],
          "read=%s reused=%s" % (again["read"], again["reused"]))

    # --- 記録が消えても、部屋は残す ---
    gone = next(room for room in expected["rooms"] if room["label"].startswith("5"))
    shutil.rmtree(dummy / "projects" / gone["project"])
    scan.scan()
    data = json.loads((home / "rooms.json").read_text(encoding="utf-8"))
    kept = data["rooms"].get(rooms.project_id(gone["project"]))
    check("記録が消えた部屋も rooms.json に残る", kept is not None and kept.get("record_gone") is True)
    check("残した部屋の「最後に頼んだ文」も残る", bool(kept) and kept.get("last_prompt") == gone["last_prompt"])

    # --- note（入口から呼ぶ） ---
    first = expected["rooms"][0]
    entry = [sys.executable, str(SCRIPTS / "glancenow.py"), "note", "--cwd", first["path"]]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    runs = [
        ["--status", "動かしている", "--next", "見出しの文を決める"],
        ["--status", "keep", "--next", "A | B の2案を見せる", "--waiting", "どちらの案に\nするか", "--memo", "色は後で"],
        ["--status", "休眠", "--next", "来月に再開する"],
    ]
    codes = [subprocess.run(entry + extra, env=env, capture_output=True).returncode for extra in runs]
    check("note が3回とも exit 0", codes == [0, 0, 0], str(codes))
    lines = records.read_all(rooms.room_id(first["path"]))
    check("記録が3行", len(lines) == 3, str(len(lines)))
    now_line = records.latest(rooms.room_id(first["path"]))
    check("いちばん下の行が「今」", bool(now_line) and now_line["status"] == "休眠" and now_line["next"] == "来月に再開する")
    second = lines[1] if len(lines) > 1 else {}
    check("| と改行を含む文で形が崩れない",
          second.get("status") == "維持だけ" and second.get("next") == "A ｜ B の2案を見せる"
          and second.get("waiting") == "どちらの案に するか" and second.get("memo") == "色は後で", repr(second))
    bad = subprocess.run(entry + ["--status", "わからない", "--next", "x"], env=env, capture_output=True)
    check("知らない状態は書かずに exit 2", bad.returncode == 2 and len(records.read_all(rooms.room_id(first["path"]))) == 3)

    # --- 下のフォルダから note しても、同じ部屋に入る ---
    sub = first["path"] + ("\\" if os.name == "nt" else "/") + "src"
    subprocess.run([sys.executable, str(SCRIPTS / "glancenow.py"), "note", "--cwd", sub,
                    "--status", "active", "--next", "下のフォルダから"], env=env, capture_output=True)
    check("下のフォルダから書いても同じ部屋の記録になる", len(records.read_all(rooms.room_id(first["path"]))) == 4)

    # --- フック：質問を送った時に「最後に頼んだ文」が新しくなる ---
    hook = [sys.executable, str(SCRIPTS / "glancenow.py"), "hook"]
    transcript = dummy / "projects" / scan.encode_path(first["path"]) / "0002.jsonl"

    def call_hook(payload):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return subprocess.run(hook, env=env, input=raw, capture_output=True)

    def log_lines():
        try:
            return (home / "log.txt").read_text(encoding="utf-8").splitlines()
        except OSError:
            return []

    done = call_hook({"hook_event_name": "UserPromptSubmit", "cwd": sub, "transcript_path": str(transcript),
                      "prompt": "フックから入った\n新しい質問"})
    data = json.loads((home / "rooms.json").read_text(encoding="utf-8"))
    room = data["rooms"].get(rooms.room_id(first["path"]), {})
    check("フックは exit 0 で、何も出力しない", done.returncode == 0 and done.stdout == b"", repr(done.stdout[:80]))
    check("フックの後、頼んだ文が新しい", room.get("last_prompt") == "フックから入った 新しい質問"
          and room.get("last_prompt_from") == "hook", repr(room.get("last_prompt")))
    check("下のフォルダの cwd でも、同じ部屋に入る（部屋は増えない）", len(data["rooms"]) == len(expected["rooms"]),
          str(len(data["rooms"])))
    scan.scan()
    data = json.loads((home / "rooms.json").read_text(encoding="utf-8"))
    check("その後に scan しても、フックの文は古い記録の文に戻らない",
          data["rooms"][rooms.room_id(first["path"])].get("last_prompt") == "フックから入った 新しい質問")

    before = len(log_lines())
    stopped = call_hook({"hook_event_name": "Stop", "stop_hook_active": True, "cwd": first["path"]})
    check("Stop が続いている時（stop_hook_active）は何もしない", stopped.returncode == 0 and len(log_lines()) == before)
    broken = call_hook(b"\xff\xfe not json")
    check("壊れた入力でも exit 0", broken.returncode == 0)
    # --- 会話の始まり：案内を返す軽い方と、記録を読む重い方（裏で走らせる）に分けてある ---
    payload = {"hook_event_name": "SessionStart", "source": "startup", "cwd": first["path"],
               "transcript_path": str(transcript)}
    started = call_hook(payload)
    last = json.loads(log_lines()[-1]) if log_lines() else {}
    check("SessionStart の軽い方は、記録を読まない（案内を待たせない）", started.returncode == 0
          and last.get("event") == "SessionStart" and not any(step.startswith("scan") for step in last.get("done", [])),
          repr(last.get("done")))
    scanned = subprocess.run(hook + ["scan"], env=env, input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                             capture_output=True)
    last = json.loads(log_lines()[-1]) if log_lines() else {}
    check("SessionStart の重い方（hook scan）が記録を読み、何も出力しない", scanned.returncode == 0 and scanned.stdout == b""
          and last.get("event") == "SessionStart" and any(step.startswith("scan(") for step in last.get("done", [])),
          repr(last.get("done")))
    declared = json.loads((SCRIPTS.parent / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    entries = [item for group in declared["SessionStart"] for item in group["hooks"]]
    light = [item for item in entries if " hook scan " not in item["command"]]
    heavy = [item for item in entries if " hook scan " in item["command"]]
    check("hooks.json：会話の始まりは2つ（軽い方は待つ・重い方は async）", len(light) == 1 and len(heavy) == 1
          and not light[0].get("async") and heavy[0].get("async") is True and light[0].get("timeout", 0) >= 30,
          repr([(item.get("async"), item.get("timeout")) for item in entries]))
    # 返事が終わる時の止める形（stopcheck）は、止めるために async にしない。印が無い時は Python を起動しない（check_entry で見る）
    others = [item for name in ("UserPromptSubmit", "Stop") for group in declared[name] for item in group["hooks"]
              if "stopcheck" not in item["command"]]
    check("hooks.json：質問を送った時・返事が終わった時は async（会話を待たせない。止める形の stopcheck は除く）",
          len(others) == 2 and all(item.get("async") is True for item in others),
          repr([(item.get("async"), item.get("timeout")) for item in others]))

    shutil.rmtree(work, ignore_errors=True)
    passed = sum(results)
    print("\n%d / %d が合いました" % (passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
