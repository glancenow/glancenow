#!/usr/bin/env python3
"""GlanceNow の入口。

使い方:
  glancenow.py hook           フックから呼ぶ（標準入力に JSON が来る）
  glancenow.py hook scan      フックから呼ぶ。会話の記録を読むだけの方（会話の始まりに、裏で走らせる）
  glancenow.py scan           会話の記録を読んで、部屋を見つける
  glancenow.py note           部屋の記録に1行足す（状態・次の一手・判断待ち・一言）
  glancenow.py build          画面を今すぐ作る
  glancenow.py open           画面を、いつものブラウザで開く
  glancenow.py rooms          見つけた部屋を、最後に動いた順に並べて出す
  glancenow.py config-init    全部の項目を書いた設定ファイルを作る
  glancenow.py config-check   設定ファイルに読めない所が無いかを見る
  glancenow.py config-show    今使っている設定を出す
  glancenow.py config-set     設定を書き換える（例: config-set rooms.show=all look.theme=dark）
  glancenow.py config-help    設定の項目と、書ける値の説明を出す
  glancenow.py setup-done     最初の質問が済んだ事を覚えて、画面を作る
  glancenow.py guide          最初の案内の状態を出す（--answer later＝「あとで」と答えた事を覚える）
  glancenow.py status         今の状態を出す

フックで何が起きても exit 0 で終わる（会話を止めない）。
"""

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from glance import VERSION, build, config, guide, log, paths, records, refresh, rooms, scan, state, util  # noqa: E402


def _utf8_output():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _read_hook_input():
    """標準入力の JSON を読む。Windows でも UTF-8 として読む。"""
    try:
        raw = sys.stdin.buffer.read()
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _hook_room(data):
    """フックに渡された cwd から、部屋の場所を決める。"""
    cwd = str(data.get("cwd") or "")
    if not cwd:
        return ""
    transcript = str(data.get("transcript_path") or "")
    if transcript:
        folder_name = Path(transcript).parent.name
        return scan.room_root(cwd, folder_name)
    known = rooms.find_by_cwd(rooms.load(), cwd)
    return known["path"] if known else cwd


def _keep_prompts():
    """「最後に頼んだ文」を控えてよいか（設定で隠している時は控えない）。"""
    return bool(config.load()["config"]["items"]["last_prompt"])


def _drop_hidden_prompts():
    """「最後に頼んだ文」を隠す設定なのに、控えた文が残っている時は、その場で消す。消した時 True。"""
    if _keep_prompts() or not scan.holds_prompts():
        return False
    return scan.drop_prompts()


def cmd_hook(args):
    started = time.perf_counter()
    data = _read_hook_input()
    event = str(data.get("hook_event_name") or "")

    # Stop のフックが続けさせた結果としてまた Stop に来た時は、何もしない
    if event == "Stop" and data.get("stop_hook_active"):
        return 0

    done = []
    room_path = _hook_room(data)
    if args[:1] == ["scan"]:
        # 会話の記録を全部読む方。時間がかかるので、会話の始まりに裏で走らせる（hooks.json の async）。
        # 案内を返す方と分けてある＝こちらが長引いても、案内は時間切れにならない。何も出力しない。
        stats = scan.scan(keep_prompts=_keep_prompts())
        state.update(last_scan=time.time())
        done.append("scan(read=%d,reused=%d,%s)" % (stats["read"], stats["reused"], stats["saved"]))
        done.append("refresh(%s)" % refresh.check("scan"))
    elif event in ("SessionStart", "UserPromptSubmit", "Stop"):
        keep_prompts = _keep_prompts()
        if not keep_prompts and scan.holds_prompts():
            # 設定ファイルを手で書き換えて隠した時も、次の機会に消す
            done.append("drop-prompts(%s)" % ("done" if scan.drop_prompts() else "none"))
        if room_path:
            prompt = data.get("prompt") if (event == "UserPromptSubmit" and keep_prompts) else None
            done.append("touch(%s)" % rooms.touch(room_path, prompt=prompt if isinstance(prompt, str) else None))
        done.append("refresh(%s)" % refresh.check(event))
        if event == "SessionStart":
            # 最初の質問がまだの時だけ、AI に案内の文を渡す
            text, mark = guide.check(str(data.get("source") or ""))
            if mark:
                done.append(mark)
            if text:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}))

    log.write(
        "hook",
        event=event,
        source=str(data.get("source") or ""),
        cwd=str(data.get("cwd") or ""),
        room=room_path,
        done=done,
        home_env=paths.home_env(),
        python="%d.%d.%d" % sys.version_info[:3],
        sec=round(time.perf_counter() - started, 3),
    )
    return 0


def cmd_scan(_args):
    stats = scan.scan(keep_prompts=_keep_prompts())
    state.update(last_scan=time.time())
    if not stats["projects_dir_found"]:
        print("会話の記録の置き場所が見つかりません: %s" % scan.projects_dir())
    print(
        "部屋 %(rooms)d／記録のあるフォルダ %(folders)d／記録 %(files)d本"
        "（読んだ %(read)d・読み直さなかった %(reused)d・読めなかった %(unreadable)d）／%(sec)s秒" % stats
    )
    if stats["saved"] == "busy":
        print("rooms.json は書けませんでした（ほかの処理が書いている途中）。もう一度実行してください。")
        return 1
    return 0


def cmd_note(args):
    parser = argparse.ArgumentParser(prog="glancenow.py note", description="部屋の記録に1行足す")
    parser.add_argument("--status", required=True, help="動かしている／維持だけ／休眠（active／keep／sleep でも可）")
    parser.add_argument("--next", required=True, dest="next_step", help="次の一手")
    parser.add_argument("--waiting", default="", help="判断待ち（無ければ書かない）")
    parser.add_argument("--memo", default="", help="一言")
    parser.add_argument("--cwd", default="", help="部屋の場所（書かなければ今のフォルダ）")
    options = parser.parse_args(args)

    status = records.normal_status(options.status)
    if status is None:
        print("状態は「%s」のどれかで書いてください。" % "／".join(records.STATUSES))
        return 2

    cwd = os.path.abspath(options.cwd) if options.cwd else os.getcwd()
    known = rooms.find_by_cwd(rooms.load(), cwd)
    room_path = known["path"] if known else cwd
    room_key = rooms.room_id(room_path)

    now = time.time()
    line = records.add(room_key, room_path, status, options.next_step, options.waiting, options.memo, now=now)
    rooms.touch(room_path, now=now, exact=True)
    print("記録しました（%s）: %s" % (rooms.room_name(room_path), line))
    # 書いた直後に画面を見る事が多いので、すぐ作り直す
    if refresh.check("note", force=True) == "not-setup":
        print("画面は、最初の質問が済むと出ます（『%s』で始められます）。" % guide.START_WORDS)
    return 0


def _print_config_report(loaded):
    for text in loaded["errors"]:
        print("読めない所: %s" % text)
    for text in loaded["warnings"]:
        print("気になる所: %s" % text)


def cmd_build(_args):
    result = build.build("manual")
    print("画面を作りました: %s（部屋 %d・判断待ち %d・%s秒）" % (
        result["path"], result["rooms"], result["waiting"], result["sec"]))
    _print_config_report(result)
    return 0


def cmd_config_init(_args):
    if config.init():
        print("設定ファイルを作りました: %s" % config.config_file())
    else:
        print("設定ファイルは、もうあります（書き換えていません）: %s" % config.config_file())
    return 0


def cmd_config_check(_args):
    target = config.config_file()
    if not target.exists():
        print("設定ファイルは、まだありません（標準の設定で動きます）: %s" % target)
        return 0
    loaded = config.load()
    _print_config_report(loaded)
    if loaded["errors"]:
        using = "前に読めた設定" if loaded["source"] == "lastgood" else "標準の設定"
        print("→ 直すまで、%sで画面を出します。" % using)
        return 1
    print("設定ファイルは読めました: %s" % target)
    return 0


def cmd_config_show(_args):
    loaded = config.load()
    print("設定ファイル: %s%s" % (config.config_file(), "" if config.config_file().exists() else "（まだありません。標準の設定で動いています）"))
    _print_config_report(loaded)
    if loaded["source"] == "lastgood":
        print("今使っているのは、前に読めた設定です:")
    print(config.to_text(loaded["config"]), end="")
    return 0


def cmd_config_set(args):
    if not args:
        print("使い方: glancenow.py config-set 項目=値 [項目=値 …]（例: rooms.show=all look.theme=dark sections=waiting,recent）")
        return 2
    result = config.set_values(args)
    for text in result["errors"]:
        print("書けません: %s" % text)
    for text in result["warnings"]:
        print("気になる所: %s" % text)
    if not result["ok"]:
        print("→ 設定ファイルは書き換えていません。")
        return 1
    print("設定ファイルを書き換えました（%s）: %s" % ("・".join(result["changed"]), config.config_file()))
    if _drop_hidden_prompts():
        print("「最後に頼んだ文」を出さない設定なので、控えてあった文を消しました。")
    return 0


def cmd_config_help(_args):
    guide_file = paths.PLUGIN_ROOT / "docs" / "設定の書き方.md"
    try:
        print(guide_file.read_text(encoding="utf-8"), end="")
    except OSError:
        print("説明のファイルが見つかりません: %s" % guide_file)
        return 1
    return 0


def cmd_rooms(_args):
    data = rooms.load()
    now = time.time()
    listed = sorted(data["rooms"].values(), key=lambda room: -(room.get("last_active") or 0))
    recent = sum(1 for room in listed if now - (room.get("last_active") or 0) <= build.SHOW_DAYS * build.DAY)
    if not listed:
        print("部屋は、まだ見つかっていません（先に scan を実行します）。")
        return 0
    print("見つけた部屋 %d（この%d日に動いた部屋 %d）。最後に動いた順:" % (len(listed), build.SHOW_DAYS, recent))
    for number, room in enumerate(listed, 1):
        moved = room.get("last_active") or 0
        print("%d. %s｜%s｜id=%s｜%s" % (
            number, room.get("name") or room.get("id"),
            build.ago_text(max(0, now - moved)) if moved else "分からない",
            room.get("id"), room.get("path") or "場所は分からない"))
    print("設定に部屋を書く時は、名前・場所・id のどれでも書けます（同じ名前の部屋が2つある時は id）。")
    return 0


def cmd_open(_args):
    page = build.page_file()
    if not page.exists():
        print("画面は、まだありません（最初の質問が済むと作ります）。")
        return 1
    import webbrowser
    opened = webbrowser.open(page.resolve().as_uri())
    print("画面: %s" % page)
    if not opened:
        print("ブラウザを開けませんでした。上のファイルを、ブラウザで開いてください。")
    return 0


def cmd_setup_done(_args):
    state.update(setup_done=True)
    _drop_hidden_prompts()
    result = build.build("setup")
    print("画面を作りました: %s" % result["path"])
    _print_config_report(result)
    return 0


def cmd_guide(args):
    parser = argparse.ArgumentParser(prog="glancenow.py guide", description="最初の案内")
    parser.add_argument("--answer", choices=["later"], help="later＝「あとで」と答えた事を覚える")
    options = parser.parse_args(args)
    if options.answer == "later":
        guide.answer_later()
        print("覚えました。案内は、もう出しません。始める時は『%s』と言うか、/glancenow:setup と打ちます。" % guide.START_WORDS)
        return 0
    print(_guide_text(state.load()))
    return 0


def _guide_text(current):
    if current["setup_done"]:
        return "最初の質問: 済み"
    if current["guide_answer"] == "later":
        return "最初の質問: まだ（「あとで」と答えた。案内は出さない）"
    return "最初の質問: まだ（案内を出した回数 %d／%d%s）" % (
        current["guide_count"], guide.MAX_SHOWN, "・答えが無いので案内をやめた" if current["guide_stopped"] else "")


def cmd_status(_args):
    print("GlanceNow %s" % VERSION)
    print("道具の場所: %s" % paths.PLUGIN_ROOT)
    try:
        home = paths.home()
    except paths.HomeNotAllowed as error:
        print("置き場所: %s" % error)
        return 0
    print("置き場所: %s" % home)
    print("会話の記録: %s" % scan.projects_dir())
    current = state.load()
    print(_guide_text(current) + ("" if current["setup_done"] else "。済むまで画面は作りません"))
    data = rooms.load()
    last = data.get("scan") or {}
    print("見つけた部屋: %d" % len(data["rooms"]))
    if current["last_scan"]:
        print("最後に記録を読んだ日時: %s（記録 %s本・読めなかった %s本）" % (
            util.local_text(current["last_scan"]), last.get("files", "?"), last.get("unreadable", "?")))
    else:
        print("会話の記録は、まだ読んでいません。")
    page = build.page_file()
    if page.exists():
        print("画面: %s（最後に作った日時 %s）" % (page, util.local_text(current["last_build"] or page.stat().st_mtime)))
    else:
        print("画面は、まだ作っていません。")
    loaded = config.load()
    print("設定: %s" % {"file": "設定ファイル", "lastgood": "前に読めた設定（今の設定ファイルに読めない所がある）",
                       "default": "標準の設定"}[loaded["source"]])
    _print_config_report(loaded)
    return 0


COMMANDS = {
    "hook": cmd_hook,
    "scan": cmd_scan,
    "note": cmd_note,
    "build": cmd_build,
    "open": cmd_open,
    "rooms": cmd_rooms,
    "config-init": cmd_config_init,
    "config-check": cmd_config_check,
    "config-show": cmd_config_show,
    "config-set": cmd_config_set,
    "config-help": cmd_config_help,
    "setup-done": cmd_setup_done,
    "guide": cmd_guide,
    "status": cmd_status,
}


def main(argv):
    _utf8_output()
    name = argv[1] if len(argv) > 1 else ""
    command = COMMANDS.get(name)
    if command is None:
        print("使い方: glancenow.py <%s>" % "|".join(sorted(COMMANDS)))
        return 0 if name == "" else 2
    if name == "hook":
        try:
            return command(argv[2:])
        except Exception:
            log.write("error", where="hook", detail=traceback.format_exc()[-1500:])
            return 0
    try:
        return command(argv[2:])
    except paths.HomeNotAllowed as error:
        print(str(error))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
