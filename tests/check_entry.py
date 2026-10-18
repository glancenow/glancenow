"""P4 の検査：最初の案内（guide）・設定を書き換える入口（config-set）・スキルと説明の中身。

使い方:
  python check_entry.py

一時フォルダを使い、終わったら消す。本物の会話の記録も、本物の置き場所も触らない。
画面から変える部分（page.js）は、ブラウザで実際に押して確かめる（この検査には入らない）。
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent / "glancenow"
SCRIPTS = PLUGIN / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

results = []


def check(label, ok, detail=""):
    results.append(bool(ok))
    print("%s  %s%s" % ("OK" if ok else "NG", label, ("  ← " + str(detail)) if (detail and not ok) else ""))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    work = Path(tempfile.mkdtemp(prefix="glancenow-entry-"))
    dummy = work / "claude_config"
    home = work / "home"
    os.environ["CLAUDE_CONFIG_DIR"] = str(dummy)
    os.environ["GLANCENOW_HOME"] = str(home)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    entry = [sys.executable, str(SCRIPTS / "glancenow.py")]

    import make_dummy
    from glance import config, guide, rooms as rooms_module, scan, state

    expected = make_dummy.build(dummy)
    first = expected["rooms"][0]
    transcript = dummy / "projects" / scan.encode_path(first["path"]) / "0002.jsonl"

    def run(*args):
        done = subprocess.run(entry + list(args), env=env, capture_output=True)
        return done.returncode, done.stdout.decode("utf-8", errors="replace")

    def hook(event="SessionStart", **extra):
        payload = {"hook_event_name": event, "cwd": first["path"], "transcript_path": str(transcript)}
        payload.update(extra)
        sent = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if event == "SessionStart":
            # hooks.json と同じ：会話の始まりは、記録を読む方（hook scan）も走る。log.txt の最後が軽い方になる順で呼ぶ
            subprocess.run(entry + ["hook", "scan"], env=env, input=sent, capture_output=True)
        done = subprocess.run(entry + ["hook"], env=env, input=sent, capture_output=True)
        return done.stdout.decode("utf-8", errors="replace").strip()

    def skill_hook(skill, session="s1"):
        """スキルが動いた直後のフック（PostToolUse・Skill）と同じ形で呼ぶ。返す物＝log.txt の最後の行の印。"""
        payload = {"hook_event_name": "PostToolUse", "tool_name": "Skill", "tool_input": {"skill": skill},
                   "session_id": session, "cwd": first["path"], "transcript_path": str(transcript)}
        subprocess.run(entry + ["hook", "skill"], env=env, input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       capture_output=True)
        rows = log_rows("hook")
        return (rows[-1].get("done") or [""])[0] if rows else ""

    def stop_check(session="s1", active=False):
        """返事が終わる時の、止める形のフックと同じ形で呼ぶ。返す物＝標準出力。"""
        payload = {"hook_event_name": "Stop", "session_id": session, "stop_hook_active": active,
                   "cwd": first["path"], "transcript_path": str(transcript)}
        done = subprocess.run(entry + ["hook", "stopcheck"], env=env, input=json.dumps(payload).encode("utf-8"),
                              capture_output=True)
        return done.stdout.decode("utf-8", errors="replace").strip()

    def flags():
        folder = home / "pending"
        return sorted(item.stem for item in folder.glob("*.json")) if folder.is_dir() else []

    def log_rows(kind=None):
        try:
            rows = [json.loads(line) for line in (home / "log.txt").read_text(encoding="utf-8").splitlines()]
        except OSError:
            return []
        return [row for row in rows if kind is None or row.get("kind") == kind]

    def last_marks():
        rows = log_rows("hook")
        return [step for step in (rows[-1].get("done", []) if rows else []) if step.startswith("guide")]

    def config_text():
        return config.config_file().read_text(encoding="utf-8")

    def held_prompts():
        """控えてある「最後に頼んだ文」の数。返す物＝(rooms.json の中・scan_cache.json の中・cache の印)"""
        rooms_data = json.loads((home / "rooms.json").read_text(encoding="utf-8"))
        cache = json.loads((home / "scan_cache.json").read_text(encoding="utf-8"))
        in_rooms = sum(1 for room in rooms_data["rooms"].values() if room.get("last_prompt"))
        in_cache = sum(1 for entry in cache["files"].values() if entry[2].get("prompt"))
        return in_rooms, in_cache, cache.get("prompts")

    # ---------- 最初の案内 ----------
    out = hook(source="resume")
    check("続きから開いた会話（resume）では、案内を出さない・数えない", out == "" and state.load()["guide_count"] == 0
          and last_marks() == ["guide(skip:resume)"], last_marks())
    out = hook("UserPromptSubmit", prompt="こんにちは")
    check("質問を送った時（UserPromptSubmit）は、何も返さない", out == "" and not last_marks())

    out = hook(source="startup")
    try:
        sent = json.loads(out)
    except ValueError:
        sent = {}
    text = sent.get("hookSpecificOutput", {}).get("additionalContext", "")
    check("新しい会話の始まりで、案内を返す（hookSpecificOutput.additionalContext）",
          sent.get("hookSpecificOutput", {}).get("hookEventName") == "SessionStart" and bool(text), out[:120])
    check("返す文字は ASCII だけ（Windows の文字化けを避ける）", out.isascii())
    check("案内の文に、スキルの名前・「あとで」のコマンド・始める合言葉がある",
          "glancenow:setup" in text and "guide --answer later" in text and (SCRIPTS / "glancenow.py").as_posix() in text and "\\" not in text
          and guide.START_WORDS in text and "今する／あとで" in text)
    check("案内の文は1万字より短い（長いとファイルに回される）", 0 < len(text) < 10000, len(text))
    check("log.txt に「案内を返した」が1行", last_marks() == ["guide(shown 1/3)"], last_marks())

    hook(source="startup")
    hook(source="clear")
    check("3回目まで出す", state.load()["guide_count"] == 3 and last_marks() == ["guide(shown 3/3)"], last_marks())
    out = hook(source="startup")
    check("4回目は出さない", out == "" and last_marks() == ["guide(stopped)"], last_marks())
    hook(source="startup")
    stopped = [row for row in log_rows("guide") if row.get("result") == "stopped"]
    shown = sum(1 for row in log_rows("hook") for step in row.get("done", []) if step.startswith("guide(shown"))
    check("案内を返したのは3回・「やめた」の行は log.txt に1行だけ", shown == 3 and len(stopped) == 1, (shown, len(stopped)))
    code, said = run("guide")
    check("guide は今の状態を出す", code == 0 and "3／3" in said and "案内をやめた" in said, said)

    state.update(guide_count=0, guide_stopped=False)
    code, said = run("guide", "--answer", "later")
    check("guide --answer later → 覚えて、合言葉を出す", code == 0 and guide.START_WORDS in said and state.load()["guide_answer"] == "later", said)
    out = hook(source="startup")
    check("「あとで」のあとは、案内を出さない・数えない", out == "" and state.load()["guide_count"] == 0 and last_marks() == ["guide(later)"], last_marks())

    code, said = run("note", "--cwd", first["path"], "--status", "動かしている", "--next", "最初の質問の前に書いた1行")
    check("最初の質問の前の note → 記録は書き、画面はまだと伝える", code == 0 and "記録しました" in said and "最初の質問が済むと出ます" in said
          and not (home / "glancenow.html").exists(), said)
    code, said = run("open")
    check("画面が無い時の open → exit 1 で知らせる", code == 1 and "まだありません" in said, said)
    mark = skill_hook("区切り", "s0")
    check("最初の質問の前は、「区切り」のスキルが動いても印を置かない", mark == "mark(skip(setup))" and flags() == [], (mark, flags()))

    # ---------- 設定を書き換える入口 ----------
    code, said = run("config-show")
    check("設定ファイルが無い時の config-show → 標準の設定を出す", code == 0 and "まだありません" in said and '"show": "recent30"' in said, said[:200])
    had = held_prompts()
    code, said = run("config-set", "look.theme=dark", "items.last_prompt=false", "sections=waiting,recent")
    now = config.load()
    check("config-set → 設定ファイルができ、値が入る", code == 0 and now["source"] == "file" and not now["errors"]
          and now["config"]["look"]["theme"] == "dark" and now["config"]["items"]["last_prompt"] is False
          and now["config"]["sections"] == ["waiting", "recent"], said)
    check("「最後に頼んだ文」を隠す設定にした、その場で、控えてあった文が消える（rooms.json と scan_cache.json）",
          had[0] > 0 and had[1] > 0 and had[2] is True and held_prompts() == (0, 0, False) and "控えてあった文を消しました" in said,
          (had, held_prompts(), said))
    run("config-set", "items.last_prompt=true")
    run("scan")
    back = held_prompts()
    config.config_file().write_text(config_text().replace('"last_prompt": true', '"last_prompt": false'), encoding="utf-8")
    hook("UserPromptSubmit", prompt="設定ファイルを手で書き換えたあとに送った文")
    steps = (log_rows("hook")[-1].get("done") or [])
    check("設定ファイルを手で書き換えて隠した時も、次の機会（質問を送った時）に消え、その時の文も控えない",
          back[0] > 0 and back[1] > 0 and held_prompts() == (0, 0, False) and "drop-prompts(done)" in steps
          and config.load()["config"]["items"]["last_prompt"] is False, (back, held_prompts(), steps))
    hook("Stop")
    check("消したあとの機会では、もう消しに行かない", not any(step.startswith("drop-prompts") for step in (log_rows("hook")[-1].get("done") or [])),
          log_rows("hook")[-1].get("done"))
    before_marks = config.marks(now["config"])
    run("config-set", "look.font_size=large")
    after_marks = config.marks(config.load()["config"])
    changed = [group for group in before_marks if before_marks[group] != after_marks[group]]
    check("書き換えたまとまり（look）の指紋だけが変わる", changed == ["look"], changed)

    code, said = run("config-set", "rooms.hide=big-log, メモ書き", 'rooms.manual_order=["shop-site","big-log"]', "rooms.order=manual",
                     "rooms.names.shop-site=お店のサイト")
    rooms_now = config.load()["config"]["rooms"]
    check("一覧はカンマ区切りでも [ ] でも書ける・名前を付けられる", code == 0 and rooms_now["hide"] == ["big-log", "メモ書き"]
          and rooms_now["manual_order"] == ["shop-site", "big-log"] and rooms_now["names"] == {"shop-site": "お店のサイト"}, said)
    run("config-set", "rooms.names.shop-site=", "rooms.hide=")
    rooms_now = config.load()["config"]["rooms"]
    check("値を空にする → 名前を外す・一覧を空にする", rooms_now["names"] == {} and rooms_now["hide"] == [], rooms_now)
    code, said = run("config-set", "rooms.recent_days=7")
    check("rooms.recent_days に数を書ける（数として入る）", code == 0 and config.load()["config"]["rooms"]["recent_days"] == 7
          and '"recent_days": 7' in config_text(), said)
    run("config-set", "rooms.recent_days=2")

    kept = config_text()
    for value in ("0", "31", "みっか"):
        code, said = run("config-set", "rooms.recent_days=" + value)
        check("rooms.recent_days=%s → exit 1・範囲を知らせる・書き換えない" % value, code == 1 and "1 から 30 までの数" in said
              and config_text() == kept, said)
    code, said = run("config-set", "look.theme=midnight")
    check("書けない値 → exit 1・理由を出す・設定ファイルは書き換えない", code == 1 and "auto／light／dark" in said and "書き換えていません" in said
          and config_text() == kept, said)
    code, said = run("config-set", "look.colour=red")
    check("知らない項目 → exit 1・書き換えない", code == 1 and "知らない項目 look.colour" in said and config_text() == kept, said)
    code, said = run("config-set", "items.next=はい")
    check("true／false でない値 → exit 1・書き換えない", code == 1 and "true か false" in said and config_text() == kept, said)
    code, said = run("config-set", "sections=waiting,everything")
    check("知らない節 → exit 1・書き換えない", code == 1 and "sections に書けるのは" in said and config_text() == kept, said)

    broken = kept.replace('"theme": "dark",', '"theme": "dark"')
    config.config_file().write_text(broken, encoding="utf-8")
    code, said = run("config-set", "look.accent=green")
    check("今の設定ファイルが読めない形の時 → 上書きせず、先に直す所を知らせる", code == 1 and "カンマ" in said and config_text() == broken, said)
    config.config_file().write_text(kept, encoding="utf-8")
    code, said = run("config-show")
    check("config-show → 場所と、今の設定", code == 0 and str(config.config_file()) in said and '"theme": "dark"' in said)
    code, said = run("config-help")
    check("config-help → 設定の説明（docs の中身）をそのまま出す", code == 0
          and said.replace("\r\n", "\n") == (PLUGIN / "docs" / "設定の書き方.md").read_text(encoding="utf-8"), said[:80])
    settings_text = (PLUGIN / "skills" / "settings" / "SKILL.md").read_text(encoding="utf-8")
    check("settings のスキルは、説明のファイルを直接開かせない（config-help を使う）",
          "`config-help`" in settings_text and "docs/設定の書き方.md" not in settings_text)

    # ---------- 部屋の一覧・最初の質問の終わり ----------
    run("scan")
    code, said = run("rooms")
    lines = [line for line in said.splitlines() if re.match(r"^\d+\. ", line)]
    check("rooms → 番号つきの一覧と、30日以内の数・全部の数", code == 0 and len(lines) == len(expected["rooms"]) == 7
          and "見つけた部屋 7（この30日に動いた部屋 5）" in said and all("id=" in line for line in lines), said[:200])
    check("rooms は最後に動いた順", lines[0].startswith("1. %s｜" % os.path.basename(first["path"])), lines[:1])
    check("一時フォルダの下の部屋が無い時は、その知らせを出さない", "一時フォルダ" not in said, said[-200:])

    # OS の一時フォルダの下で会話をした部屋が、1つある時
    temp_room = os.path.join(tempfile.gettempdir(), "glancenow-temp-room")
    rooms_module.touch(temp_room, exact=True)
    code, said = run("rooms")
    lines = [line for line in said.splitlines() if re.match(r"^\d+\. ", line)]
    check("rooms → 一時フォルダの下の部屋は、一覧にも数にも入れず、数を1行で出す", len(lines) == 7 and "glancenow-temp-room" not in said
          and "見つけた部屋 7（この30日に動いた部屋 5）" in said and "一時フォルダの下の部屋 1 は、載せていません" in said, said[-300:])

    code, said = run("setup-done")
    check("setup-done → 画面ができる", code == 0 and (home / "glancenow.html").exists())
    check("setup-done → 載せなかった一時フォルダの部屋の数を出す（最初の質問の終わりの文に使う）",
          "一時フォルダの下の部屋 1 は、載せていません" in said, said)
    run("config-set", "rooms.show_temp=true")
    code, said = run("rooms")
    check("rooms.show_temp=true → 一覧と数に入り、知らせは出ない", "見つけた部屋 8（この30日に動いた部屋 6）" in said
          and "glancenow-temp-room" in said and "載せていません" not in said, said[:200])
    run("config-set", "rooms.show_temp=false")
    out = hook(source="startup")
    check("質問が済んだあとは、案内を出さない", out == "" and not last_marks(), last_marks())
    code, said = run("guide")
    check("guide → 「済み」", "済み" in said, said)

    # ---------- 「区切り」のスキルの後の1行（返事の終わりに頼む） ----------
    from glance import pending, records
    room_key = rooms_module.room_id(first["path"])
    check("「区切り」のスキル → その会話に印を置く（部屋の id つき）", skill_hook("区切り", "s1") == "mark(set)" and flags() == ["s1"]
          and json.loads((home / "pending" / "s1.json").read_text(encoding="utf-8"))["room"] == room_key, flags())
    check("プラグインのスキル（名前:区切り）でも印を置く", skill_hook("myplugin:区切り", "s2") == "mark(set)" and "s2" in flags(), flags())
    check("ほかのスキル・GlanceNow 自身の checkpoint では、印を置かない・消さない",
          skill_hook("AXログ", "s3") == "mark(skip)" and skill_hook("glancenow:checkpoint", "s1") == "mark(skip)"
          and flags() == ["s1", "s2"], flags())
    out = stop_check("s9")
    check("ほかの会話の返事の終わりでは、何も返さない・印は残す", out == "" and flags() == ["s1", "s2"], (out, flags()))
    out = stop_check("s1")
    try:
        asked = json.loads(out)
    except ValueError:
        asked = {}
    check("印のある会話の返事の終わり → 止めて、1行を頼む文を返す（decision: block）", asked.get("decision") == "block"
          and "glancenow:checkpoint" in asked.get("reason", "") and "「区切り」" in asked.get("reason", ""), out[:200])
    check("返す文字は ASCII だけ・頼んだ印は消す", out.isascii() and flags() == ["s2"], flags())
    check("同じ会話の次の返事の終わりでは、もう頼まない（1つの印で1回）", stop_check("s1") == "", flags())
    code, said = run("note", "--cwd", first["path"], "--status", "動かしている", "--next", "区切りの後に書いた1行")
    check("note で1行を書く → その部屋の印を消す（会話が違っても）", code == 0 and flags() == [], flags())
    skill_hook("区切り", "s5")
    records.add(room_key, first["path"], "動かしている", "印を消さずに書いた1行")
    out = stop_check("s5")
    check("印の後に1行が書かれていれば、頼まずに印を消す", out == "" and flags() == []
          and "stopcheck(written)" in (log_rows("hook")[-1].get("done") or []), log_rows("hook")[-1].get("done"))
    skill_hook("区切り", "s7")
    check("ほかのフックが続けさせた後（stop_hook_active）でも、印があれば1回だけ頼む",
          json.loads(stop_check("s7", active=True) or "{}").get("decision") == "block" and flags() == [], flags())
    (home / "pending" / "old.json").write_text(json.dumps({"session": "old", "room": room_key, "at": 1}), encoding="utf-8")
    stop_check("s8")
    check("古い印（12時間より前）は、ほかの会話の返事の終わりに消す", flags() == [], flags())
    run("config-set", "checkpoint.after_skills=")
    check("checkpoint.after_skills を空にする → 印を置かない", skill_hook("区切り", "s6") == "mark(skip)" and flags() == [], flags())
    code, said = run("config-set", "checkpoint.after_skills=区切り,wrap-up")
    check("checkpoint.after_skills に名前を足せる", code == 0 and config.load()["config"]["checkpoint"]["after_skills"] == ["区切り", "wrap-up"]
          and skill_hook("wrap-up", "s6") == "mark(set)", said)
    pending.clear(room_key)

    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    post = [(group.get("matcher"), item) for group in hooks.get("PostToolUse", []) for item in group["hooks"]]
    stops = [item for group in hooks.get("Stop", []) for item in group["hooks"] if "stopcheck" in item["command"]]
    check("hooks.json：スキルの直後（matcher Skill）に hook skill・返事の終わりに止める形（async なし）の stopcheck",
          len(post) == 1 and post[0][0] == "Skill" and "hook skill" in post[0][1]["command"]
          and len(stops) == 1 and not stops[0].get("async"), (post, stops))
    shell = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH") or (r"C:\Program Files\Git\bin\bash.exe" if os.name == "nt" else shutil.which("sh"))
    if shell and os.path.exists(shell) and stops:
        shell_env = dict(env, CLAUDE_PLUGIN_ROOT=str(PLUGIN))
        sent = json.dumps({"hook_event_name": "Stop", "session_id": "s6", "cwd": first["path"]}).encode("utf-8")
        rows_before = len(log_rows("hook"))
        idle = subprocess.run([shell, "-c", stops[0]["command"]], env=shell_env, input=sent, capture_output=True)
        check("印が無い時、返事の終わりのフックは Python を起動しない（%s）" % os.path.basename(shell),
              idle.returncode == 0 and idle.stdout == b"" and len(log_rows("hook")) == rows_before, (idle.returncode, idle.stdout[:80]))
        skill_hook("区切り", "s6")
        busy = subprocess.run([shell, "-c", stops[0]["command"]], env=shell_env, input=sent, capture_output=True)
        check("印がある時は、同じコマンドで止める形の文が返る", busy.returncode == 0
              and json.loads(busy.stdout.decode("utf-8") or "{}").get("decision") == "block" and flags() == [], busy.stdout[:120])
    else:
        print("（シェルが見つからないので、hooks.json のコマンドを走らせる2つは飛ばしました）")

    import webbrowser
    import glancenow
    opened = []
    real_open = webbrowser.open
    webbrowser.open = lambda url, *rest, **more: opened.append(url) or True
    try:
        code = glancenow.cmd_open([])
    finally:
        webbrowser.open = real_open
    check("open → 画面のファイルを file: の場所で開く", code == 0 and len(opened) == 1 and opened[0].startswith("file:")
          and opened[0].endswith("/glancenow.html"), opened)

    # ---------- スキルと説明の中身 ----------
    skills = {}
    for name in ("setup", "settings", "checkpoint"):
        path = PLUGIN / "skills" / name / "SKILL.md"
        skills[name] = path.read_text(encoding="utf-8") if path.exists() else ""
    front = {name: re.match(r"^---\n(.*?)\n---\n", text, re.S) for name, text in skills.items()}
    check("スキル3つに、名前・説明・道具の許可がある", all(
        found and ("name: %s\n" % name) in found.group(1) + "\n" and "description: " in found.group(1)
        and 'Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/glancenow.py" *)' in found.group(1)
        and 'Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/glancenow.py" *)' in found.group(1)
        for name, found in front.items()))
    check("スキルの本文は、道具の場所を ${CLAUDE_PLUGIN_ROOT} で指す", all(
        'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/glancenow.py"' in text.split("---", 2)[2] for text in skills.values()))

    body = {name: text.split("---", 2)[2] if text.count("---") >= 2 else "" for name, text in skills.items()}
    check("checkpoint：ほかの「区切り」を先に済ませる順番が、説明と本文の両方にある", bool(front["checkpoint"])
          and "先に全部済ませてから、最後にこれを使う" in front["checkpoint"].group(1)
          and "ほかの方の手順を、先に全部済ませる" in body["checkpoint"] and "最後に、このスキルの手順で1行を書く" in body["checkpoint"])
    check("setup：6つの質問の前に「全部おまかせ／1つずつ答える」を聞く", "全部おまかせ（標準で作る）" in body["setup"]
          and "1つずつ答える（6問）" in body["setup"]
          and body["setup"].index("全部おまかせ（標準で作る）") < body["setup"].index("**1問目 載せる部屋**"))
    check("setup：途中の「おすすめで」は、その問いだけ標準にして次へ進む", "その問いだけを「標準のまま」として入れ、次の問いへ進む" in body["setup"])
    check("setup：終わりの文に、タブの1行と、載せなかった一時フォルダの部屋の数の1行がある",
          "ブラウザの窓に、GlanceNow のタブが足されています。見当たらない時は、このファイルを開いてください" in body["setup"]
          and "一時フォルダの ◯ 部屋は載せていません" in body["setup"]
          and (glancenow.TEMP_OUT_LINE % 3).startswith("一時フォルダの下の部屋 3 は、載せていません")
          and "一時フォルダの下の部屋 ◯ は、載せていません" in body["setup"])

    docs = (PLUGIN / "docs" / "設定の書き方.md").read_text(encoding="utf-8")
    written = "\n".join(list(skills.values()) + [docs])
    used = set(re.findall(r"`(scan|rooms|open|build|status|note|guide|setup-done|config-[a-z]+)`", written))
    used |= set(re.findall(r"glancenow\.py (?:<入口>|([a-z-]+))", written)) - {""}
    check("スキルと説明に出てくる入口は、全部ある（%d個）" % len(used), used and used <= set(glancenow.COMMANDS), sorted(used - set(glancenow.COMMANDS)))

    # スキルと説明に書いた「項目=値」が、本当に書ける値か（1つずつ、標準の設定に当てて確かめる）
    pairs = set()
    for chunk in re.findall(r"`([^`\n]+)`", written) + re.findall(r"config-set ([^\n`]+)", written):
        for word in chunk.replace("config-set ", "").split(" "):
            if re.match(r"^(rooms\.[a-z_]+(\.[\w-]+)?|items\.[a-z_]+|look\.[a-z_]+|checkpoint\.[a-z_]+|sections)=[^<…]+$", word):
                pairs.add(word)
    bad = []
    config.config_file().write_text(config.to_text(config.default_config()), encoding="utf-8")
    fresh = config_text()
    for pair in sorted(pairs):
        result = config.set_values([pair])
        if not result["ok"] or result["warnings"]:
            bad.append((pair, result["errors"] + result["warnings"]))
        config.config_file().write_text(fresh, encoding="utf-8")
    check("スキルと説明に書いた「項目=値」は、全部書ける（%d個）" % len(pairs), len(pairs) >= 12 and not bad, bad[:3] or sorted(pairs))

    check("説明に、設定の全部の項目が出てくる", all(("`%s`" % key) in docs for group in ("rooms", "items", "look", "checkpoint")
                                                for key in config.DEFAULT[group])
          and "### sections" in docs and "### checkpoint" in docs)
    values = config.SHOW + config.ORDER + config.SECTIONS + config.THEMES + config.FONT_SIZES + config.ACCENTS
    check("説明に、書ける値が全部出てくる", all(('"%s"' % value) in docs or ("`%s`" % value) in docs for value in values),
          [value for value in values if ('"%s"' % value) not in docs and ("`%s`" % value) not in docs])
    example = re.search(r"```json\n(.*?)```", docs, re.S)
    parsed, errors, warnings = config.parse(example.group(1)) if example else (None, ["例が無い"], [])
    check("説明の例は、そのまま読める設定", parsed is not None and not errors and not warnings, errors + warnings)

    errors = log_rows("error")
    check("log.txt に失敗の行が無い", not errors, errors[:1])

    shutil.rmtree(work, ignore_errors=True)
    passed = sum(results)
    print("\n%d / %d が合いました" % (passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
