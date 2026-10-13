"""ダミーの会話の記録を作る（検査と、画面の見た目の確認に使う）。

使い方:
  python make_dummy.py <出力先のフォルダ>

出力先の下に projects/<フォルダ名>/*.jsonl と expected.json を作る。
環境変数 CLAUDE_CONFIG_DIR を <出力先> に向けると、GlanceNow はこれを読む。

行の形は、2026-10 の Claude Code が残す記録の項目名に合わせてある
（type・timestamp・cwd・message・isMeta・toolUseResult・lastPrompt）。
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "glancenow" / "scripts"))

from glance import scan  # noqa: E402

BASE = "D:\\dummy\\rooms" if os.name == "nt" else "/dummy/rooms"
SEP = "\\" if os.name == "nt" else "/"
DAY = 24 * 3600


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def user(text, when, cwd=None):
    row = {"parentUuid": None, "isSidechain": False, "type": "user",
           "message": {"role": "user", "content": text},
           "uuid": "u-%d" % when, "timestamp": iso(when), "sessionId": "s1", "version": "2.1.201"}
    if cwd:
        row["cwd"] = cwd
    return row


def assistant(text, when, cwd=None):
    row = {"parentUuid": "u", "isSidechain": False, "type": "assistant",
           "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
           "uuid": "a-%d" % when, "timestamp": iso(when), "sessionId": "s1", "version": "2.1.201"}
    if cwd:
        row["cwd"] = cwd
    return row


def tool_result(text, when, cwd):
    return {"parentUuid": "a", "isSidechain": False, "type": "user",
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": text}]},
            "toolUseResult": {"stdout": text}, "sourceToolAssistantUUID": "a",
            "uuid": "r-%d" % when, "timestamp": iso(when), "cwd": cwd, "sessionId": "s1"}


def meta(text, when, cwd):
    row = user(text, when, cwd)
    row["isMeta"] = True
    return row


def last_prompt(text):
    return {"type": "last-prompt", "lastPrompt": text, "leafUuid": "x", "sessionId": "s1"}


def title(text):
    return {"type": "custom-title", "customTitle": text, "sessionId": "s1"}


def write_record(folder, name, rows, mtime, raw_extra=None):
    """rows を1行ずつ書く。rows の中の bytes は、そのまま（壊れた行として）書く。"""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    with open(target, "wb") as handle:
        for row in rows:
            if isinstance(row, bytes):
                handle.write(row + b"\n")
            else:
                handle.write(json.dumps(row, ensure_ascii=False).encode("utf-8") + b"\n")
        if raw_extra:
            handle.write(raw_extra)
    os.utime(target, (mtime, mtime))
    return target


def build(target, now=None):
    """ダミーを作り、期待する答えを返す（expected.json にも書く）。"""
    now = int(time.time() if now is None else now)
    target = Path(target)
    projects = target / "projects"
    expected = []
    files = 0

    # ① 今日動いた部屋。記録が2本あり、新しい方は途中で下のフォルダへ移っている
    path = BASE + SEP + "shop-site"
    folder = projects / scan.encode_path(path)
    old = now - 3 * DAY
    write_record(folder, "0001.jsonl", [
        user("古い方の会話の質問", old - 60, path),
        assistant("古い方の返事", old, path),
        last_prompt("古い方の会話の質問"),
    ], old)
    t = now - 600
    write_record(folder, "0002.jsonl", [
        title("トップページの直し"),
        user("トップページの見出しを直して", t - 120, path),
        assistant("直します", t - 100, path),
        tool_result("<html>…</html>", t - 90, path),
        meta("<system-reminder>自動で入る文</system-reminder>", t - 80, path),
        assistant("src の中を見ます", t - 30, path + SEP + "src"),
        tool_result("ファイルの一覧", t, path + SEP + "src"),
        title("トップページの直し"),
        last_prompt("トップページの見出しを直して"),
    ], t)
    files += 2
    expected.append({"label": "1 今日動いた", "path": path, "name": "shop-site", "last_active": t,
                     "last_active_from": "record", "last_prompt": "トップページの見出しを直して"})

    # ② 31日前に動いた部屋（名前が日本語）。
    # ②b 名前の長さが同じ別の部屋。記録のフォルダ名が同じになるが、別の部屋として出す
    path_a = BASE + SEP + "レポート"
    path_b = BASE + SEP + "メモ書き"
    folder = projects / scan.encode_path(path_a)
    assert scan.encode_path(path_a) == scan.encode_path(path_b)
    t_a = now - 31 * DAY
    write_record(folder, "0001.jsonl", [
        user("第3章の下書きを書いて", t_a - 50, path_a),
        assistant("書きました", t_a, path_a),
        last_prompt("第3章の下書きを書いて"),
    ], t_a)
    t_b = now - 3 * DAY
    write_record(folder, "0002.jsonl", [
        user("買い物のメモを整理して", t_b - 50, path_b),
        assistant("整理しました", t_b, path_b),
        last_prompt("買い物のメモを整理して"),
    ], t_b)
    files += 2
    expected.append({"label": "2 31日前に動いた", "path": path_a, "name": "レポート", "last_active": t_a,
                     "last_active_from": "record", "last_prompt": "第3章の下書きを書いて"})
    expected.append({"label": "2b 同じフォルダ名になる別の部屋", "path": path_b, "name": "メモ書き", "last_active": t_b,
                     "last_active_from": "record", "last_prompt": "買い物のメモを整理して"})

    # ③ 途中に壊れた行がある。last-prompt の行も無い（人が打った文を自分で選り分ける）
    path = BASE + SEP + "broken-lines"
    folder = projects / scan.encode_path(path)
    t = now - 2 * DAY
    write_record(folder, "0001.jsonl", [
        user("最初の質問", t - 500, path),
        b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"te',
        b"\xff\xfe\x00\x81 not json at all",
        user("在庫の表を作り直して\n列は3つで", t - 300, path),
        b"[1, 2, 3]",
        assistant("作り直します", t - 290, path),
        tool_result("実行の結果", t - 280, path),
        meta("自動で入る文", t - 270, path),
        user("<command-name>/clear</command-name>", t - 260, path),
        assistant("終わりました", t, path),
        b'{"type":"user","message":',
    ], t)
    files += 1
    expected.append({"label": "3 壊れた行がある", "path": path, "name": "broken-lines", "last_active": t,
                     "last_active_from": "record", "last_prompt": "在庫の表を作り直して 列は3つで"})

    # ④ 5MB ある。末尾の1行が200KB（末尾64KBだけでは1行も読めない）
    path = BASE + SEP + "big-log"
    folder = projects / scan.encode_path(path)
    t = now - 9 * DAY
    filler = "x" * 1000
    rows = [tool_result(filler, t - 5000 + index, path) for index in range(4700)]
    rows.append(user("ログを集計して", t - 60, path))
    rows.append(last_prompt("ログを集計して"))
    rows.append(assistant("y" * 200000, t, path))
    big = write_record(folder, "0001.jsonl", rows, t)
    files += 1
    expected.append({"label": "4 5MB ある", "path": path, "name": "big-log", "last_active": t,
                     "last_active_from": "record", "last_prompt": "ログを集計して"})

    # ⑤ cwd も last-prompt も無い古い形
    path = BASE + SEP + "old-form"
    project = scan.encode_path(path)
    folder = projects / project
    t = now - 40 * DAY
    write_record(folder, "0001.jsonl", [
        user("古い形の質問です", t - 30),
        assistant("古い形の返事です", t),
    ], t)
    files += 1
    expected.append({"label": "5 古い形", "path": "", "project": project, "name": project, "last_active": t,
                     "last_active_from": "record", "last_prompt": "古い形の質問です"})

    # ⑥ 下の階層に子エージェントの記録だけがある（部屋として数えない）
    path = BASE + SEP + "agents-only"
    agents_project = scan.encode_path(path)
    write_record(projects / agents_project / "session-1" / "subagents", "agent-1.jsonl", [
        user("子エージェントへの頼み", now - 100, path),
    ], now - 100)

    # ⑦ 1行も読めない記録（読めなかった本数に数える。日時はファイルの更新時刻）
    path = BASE + SEP + "all-broken"
    project = scan.encode_path(path)
    t = now - 5 * DAY
    write_record(projects / project, "0001.jsonl", [b"\x00\x01\x02 broken", b"{{{{"], t)
    files += 1
    expected.append({"label": "7 1行も読めない", "path": "", "project": project, "name": project, "last_active": t,
                     "last_active_from": "file_time", "last_prompt": ""})

    answer = {
        "made_at": now,
        "rooms": expected,
        "folders": 6,
        "files": files,
        "unreadable": 1,
        "not_a_room": agents_project,
        "big_file_bytes": big.stat().st_size,
    }
    with open(target / "expected.json", "w", encoding="utf-8") as handle:
        json.dump(answer, handle, ensure_ascii=False, indent=1)
    return answer


def add_notes(now=None):
    """ダミーの部屋に、記録（状態・次の一手・判断待ち）を書く。

    先に scan を済ませておく事。書き先は GLANCENOW_HOME。
    """
    from glance import records, rooms

    now = int(time.time() if now is None else now)
    notes = [
        ("shop-site", "動かしている", "見出しの文を3案から選ぶ", "見出しの文をA・B・Cのどれにするか", 900),
        ("メモ書き", "維持だけ", "来週の買い物の分を足す", "", 3 * DAY),
        ("broken-lines", "動かしている", "在庫の表に <b>合計</b> の列を足す & 確かめる", "列の名前を「数」と「在庫数」のどちらにするか", 2 * DAY),
        ("big-log", "休眠", "集計の結果を表にまとめる", "", 9 * DAY),
    ]
    for name, status, next_step, waiting, before in notes:
        path = BASE + SEP + name
        records.add(rooms.room_id(path), path, status, next_step, waiting, now=now - before)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    result = build(sys.argv[1])
    print("作りました: 部屋 %d・記録 %d本（大きい記録 %.1fMB）" % (
        len(result["rooms"]), result["files"], result["big_file_bytes"] / 1024 / 1024))
