"""P3 の検査：設定（config）・画面（build）・自動の作り直し（refresh）。

使い方:
  python check_page.py            検査だけ（一時フォルダを使い、終わったら消す）
  python check_page.py <出力先>   検査のあと、ダミーの画面を <出力先> に残す（目で見る用）

本物の会話の記録も、本物の置き場所も触らない。
"""

import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "glancenow" / "scripts"
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
    keep = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
    work = Path(tempfile.mkdtemp(prefix="glancenow-check-"))
    dummy = work / "claude_config"
    home = work / "home"
    os.environ["CLAUDE_CONFIG_DIR"] = str(dummy)
    os.environ["GLANCENOW_HOME"] = str(home)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    entry = [sys.executable, str(SCRIPTS / "glancenow.py")]

    import make_dummy
    from glance import build, config, refresh, rooms, scan, state

    expected = make_dummy.build(dummy)
    first = expected["rooms"][0]
    transcript = dummy / "projects" / scan.encode_path(first["path"]) / "0002.jsonl"
    page = home / "glancenow.html"

    def run(*args):
        return subprocess.run(entry + list(args), env=env, capture_output=True)

    def hook(event="Stop", **extra):
        payload = {"hook_event_name": event, "cwd": first["path"], "transcript_path": str(transcript)}
        payload.update(extra)
        sent = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if event == "SessionStart":
            # hooks.json と同じ：会話の始まりは、記録を読む方（hook scan）も走る。log.txt の最後が軽い方になる順で呼ぶ
            subprocess.run(entry + ["hook", "scan"], env=env, input=sent, capture_output=True)
        return subprocess.run(entry + ["hook"], env=env, input=sent, capture_output=True)

    def log_rows(kind=None):
        try:
            rows = [json.loads(line) for line in (home / "log.txt").read_text(encoding="utf-8").splitlines()]
        except OSError:
            return []
        return [row for row in rows if kind is None or row.get("kind") == kind]

    def builds():
        return len(log_rows("build"))

    def last_refresh():
        rows = log_rows("hook")
        steps = rows[-1].get("done", []) if rows else []
        return next((step for step in steps if step.startswith("refresh")), "")

    def rewind(seconds=30):
        """前回の作り直しから seconds 秒たった事にする。"""
        state.update(last_build=time.time() - seconds)

    def html():
        return page.read_text(encoding="utf-8")

    def write_config(change):
        data = json.loads(config.config_file().read_text(encoding="utf-8"))
        change(data)
        config.config_file().write_text(config.to_text(data), encoding="utf-8")

    def rebuild():
        return build.build("check")

    # ---------- 最初の質問が済むまで、画面は作らない ----------
    hook("SessionStart", source="startup")
    check("最初の質問が済むまで、フックは画面を作らない", not page.exists() and last_refresh() == "refresh(not-setup)", last_refresh())
    make_dummy.add_notes()
    done = run("setup-done")
    check("setup-done で画面ができる", done.returncode == 0 and page.exists())

    # ---------- 画面の中身 ----------
    text = html()
    data = rooms.load()
    now = time.time()
    in_30 = [room for room in data["rooms"].values() if now - room["last_active"] <= 30 * 86400]
    in_7 = [room for room in in_30 if now - room["last_active"] <= 7 * 86400]

    def block(name, source=None):
        found = re.search(r'<section class="block" id="%s"(?: hidden)?>(.*?)</section>' % name, source or html(), re.S)
        return found.group(1) if found else ""

    def members(name, source=None):
        """その節に入っている部屋の数。"""
        return block(name, source).count(' data-room="')

    def shown_sections(source=None):
        """出している節（hidden の付いていない節）を、書かれた順に。"""
        return re.findall(r'<section class="block" id="(\w+)">', source or html())

    def html_tag(source=None):
        return re.search(r"<html [^>]*>", source or html()).group(0)

    def body_of(source=None):
        return (source or html()).split("<body>", 1)[1]

    check("節が4つ、標準の順に出る", shown_sections(text) == ["waiting", "recent", "all", "stalled"], shown_sections(text))
    check("「全部の部屋」の行の数＝30日以内の部屋の数（%d）" % len(in_30), members("all") == len(in_30), members("all"))
    check("「最近動いた部屋」のカードの数＝7日以内の部屋の数（%d）" % len(in_7),
          block("recent").count('<article class="card"') == len(in_7) == members("recent"), members("recent"))
    check("「判断待ち」に2件", members("waiting") == 2, members("waiting"))
    check("いちばん上に、部屋の数と判断待ちの数", '<b data-count="rooms">%d</b>部屋' % len(in_30) in text and '<b data-count="waiting">2</b>判断待ち' in text)
    check("載せていない部屋の数と訳を下に書く", "ほかに %d部屋あります（30日より前に動いた部屋）。" % (len(data["rooms"]) - len(in_30)) in text)
    check("読めなかった記録の本数を下に書く", "読めなかった記録が 1本あります" in text)
    check("状態は 形＋文字 で出る", '<span class="chip active i-status"><i aria-hidden="true">●</i>動かしている</span>' in text
          and '<i aria-hidden="true">◐</i>維持だけ' in text and '<i aria-hidden="true">－</i>記録なし' in text)
    check("文の中の < & は、そのまま字として出る", "在庫の表に &lt;b&gt;合計&lt;/b&gt; の列を足す &amp; 確かめる" in text and "<b>合計</b>" not in text)

    loads = re.findall(r'(?:src|href)\s*=\s*["\'](?!data:|#)[^"\']*', text) + re.findall(r'url\(|@import', text)
    check("外から読む物が 0件", not loads, loads[:3])
    check("絵文字の favicon がある", '<link rel="icon" href="data:image/svg+xml' in text)
    check("左の色帯（border-left）が 0件", "border-left" not in text and "border-inline-start" not in text)
    check("暗い画面・明るい画面の両方の色がある", "prefers-color-scheme: dark" in text and 'html[data-theme="dark"]' in text)
    embedded = re.search(r'<script type="application/json" id="glancenow-data">(.*?)</script>', text, re.S)
    inside = json.loads(embedded.group(1)) if embedded else {}
    check("中に入れたデータが JSON として読める", sorted(inside) == ["base", "built", "labels", "marks", "version"], sorted(inside))
    check("データに、設定ファイルの値とまとまりごとの指紋がある", sorted(inside["marks"]) == ["items", "look", "rooms", "sections"]
          and inside["base"]["look"] == {"theme": "auto", "font_size": "normal", "accent": "blue"}
          and inside["base"]["sections"] == ["waiting", "recent", "all", "stalled"] and all(inside["base"]["items"].values()))
    check("「変える」ボタンは hidden で入っている（JavaScript が動く所でだけ出す）", '<button type="button" class="btn" data-tune-open hidden>変える</button>' in text)
    check("JavaScript は <head> の中（中身が描かれる前に見た目を当てる）", text.index("glancenow:v1:") < text.index("<body>"))

    # ---------- 30日より前に止まった部屋は、数だけを出す ----------
    older = len(data["rooms"]) - len(in_30)
    stalled = block("stalled", text)
    check("30日より前に止まった部屋は、数だけを「止まっている部屋」の節の終わりに出す（%d）" % older, older == 2
          and ('</details><p class="older">このほかに、30日より前に止まった部屋が %d つあります。</p>' % older) in stalled, stalled[-160:])
    check("その部屋の名前は、画面に出ない", "レポート" not in body_of(text))
    check("節に入る部屋が0件の時は、「載せている部屋の中に」と書く", members("stalled", text) == 0
          and "載せている部屋の中に、止まっている部屋はありません。" in stalled)
    check("数が10以上の時は「つ」を付けない", build.older_text(9).endswith("が 9 つあります。") and build.older_text(12).endswith("が 12 あります。"),
          build.older_text(12))

    # ---------- 自動の作り直し ----------
    rewind()
    os.utime(page, (time.time() - 30, time.time() - 30))
    before = builds()
    for _ in range(10):
        hook("Stop")
    check("フックを続けて10回 → 作り直しは1回だけ", builds() - before == 1, builds() - before)
    rewind()
    before = builds()
    hook("Stop")
    check("何も変えずに呼ぶ → 0回", builds() - before == 0 and last_refresh() == "refresh(fresh)", last_refresh())
    before = builds()
    run("note", "--cwd", first["path"], "--status", "動かしている", "--next", "検査で足した1行")
    check("note を1回 → 作り直しは1回", builds() - before == 1 and "検査で足した1行" in html(), builds() - before)
    hook("Stop")
    check("その次の呼び出し → 0回", builds() - before == 1, builds() - before)

    config.init()
    before = builds()
    hook("Stop")
    check("直前に作ったばかりの時は、元が変わっても見送る（20秒）", builds() - before == 0 and last_refresh() == "refresh(too-soon)", last_refresh())
    rewind()
    hook("Stop")
    check("間があけば、見送った分を次の呼び出しで作る", builds() - before == 1, builds() - before)

    rewind()
    write_config(lambda data: data["look"].update(accent="green"))
    lock = home / "build.lock"
    lock.write_text("0")
    before = builds()
    hook("Stop")
    check("ほかの処理が作っている間（ロック）は作らない", builds() - before == 0 and last_refresh() == "refresh(busy)", last_refresh())
    old = time.time() - 120
    os.utime(lock, (old, old))
    hook("Stop")
    check("古いロック（60秒より前）は無視して作る", builds() - before == 1 and not lock.exists(), builds() - before)
    check("設定ファイルで変えた色が出る", 'data-accent="green"' in html_tag() and 'html[data-accent="green"] { --accent: #1d7a50; }' in html())

    # ---------- 設定ファイルを書き間違えた時 ----------
    good = config.config_file().read_text(encoding="utf-8")
    check("config-init は全部の項目を書く", all(key in good for key in ('"show"', '"hide"', '"names"', '"last_prompt"', '"sections"', '"accent"')))
    check("config-check は exit 0", run("config-check").returncode == 0)
    config.config_file().write_text(good.replace('"theme": "auto",', '"theme": "auto"'), encoding="utf-8")
    rebuild()
    text = html()
    check("カンマを1つ消す → 画面は前の設定で出る", 'data-accent="green"' in html_tag(text))
    line = good.splitlines().index('    "theme": "auto",') + 1
    check("画面の上に「何行目」の知らせが出る", "設定ファイルに読めない所があります" in text and ("%d行目の終わりに、カンマ" % line) in text,
          re.findall(r"<li>([^<]*行目[^<]*)</li>", text))
    report = run("config-check")
    check("config-check は exit 1 で同じ知らせを出す", report.returncode == 1 and ("%d行目" % line) in report.stdout.decode("utf-8"))
    config.config_file().write_text(good, encoding="utf-8")
    rebuild()
    check("直す → 知らせが消える", "設定ファイルに読めない所があります" not in html())
    config.config_file().write_text(good.replace('"theme": "auto"', '"theme": "midnight"'), encoding="utf-8")
    rebuild()
    check("知らない値 → 行と、書ける値を知らせる", ("%d行目: look.theme は auto／light／dark のどれか" % line) in html())
    config.config_file().write_text(good.replace('"next": true', '"next": "yes"'), encoding="utf-8")
    rebuild()
    next_line = good.splitlines().index('    "next": true,') + 1
    check("型が違う値 → 行と、書き方を知らせる", ("%d行目: items.next は true か false で書きます" % next_line) in html(),
          re.findall(r"<li>([^<]*行目[^<]*)</li>", html()))
    config.config_file().write_text(good.replace('"version": 1,', '"version": 1,\n  "colour": "red",'), encoding="utf-8")
    rebuild()
    text = html()
    check("知らない項目 → 気になる所として知らせ、ほかの設定は使う", "知らない項目 colour" in text and "設定ファイルに読めない所" not in text)
    config.config_file().write_text(good, encoding="utf-8")

    # ---------- 設定で変えられる物 ----------
    write_config(lambda data: data["rooms"].update(show="all"))
    rebuild()
    check("rooms.show=all → 全部の部屋が載る（%d）" % len(data["rooms"]), members("all") == len(data["rooms"]), members("all"))
    check("止まっている部屋は畳んで出す", "<details>" in block("stalled") and members("stalled") == 2, members("stalled"))
    check("全部の部屋を載せている時は、30日より前の部屋の数の行を出さない", 'class="older"' not in html())

    # OS の一時フォルダの下の部屋（rooms.show_temp）
    temp_room = os.path.join(tempfile.gettempdir(), "glancenow-temp-room")
    rooms.touch(temp_room, exact=True)
    result = rebuild()
    check("OS の一時フォルダの下の部屋は、載せない（下に、載せていない訳を書く）", members("all") == len(data["rooms"])
          and "glancenow-temp-room" not in body_of() and result["temp_out"] == 1
          and "ほかに 1部屋あります（一時フォルダの下の部屋）。ここには載せていません。" in html(), (members("all"), result["temp_out"]))
    write_config(lambda data: data["rooms"].update(show_temp=True))
    result = rebuild()
    check("rooms.show_temp=true → 一時フォルダの下の部屋も載る", members("all") == len(data["rooms"]) + 1
          and "glancenow-temp-room" in block("all") and result["temp_out"] == 0, (members("all"), result["temp_out"]))
    write_config(lambda data: data["rooms"].update(show_temp="yes"))
    rebuild()
    check("rooms.show_temp に true／false でない値 → 書き方を知らせる", "rooms.show_temp は true か false で書きます" in html())
    write_config(lambda data: data["rooms"].update(show_temp=False))
    rooms.update(lambda stored: stored["rooms"].pop(rooms.room_id(temp_room), None))
    rebuild()
    write_config(lambda data: data["rooms"].update(hide=["big-log", first["path"]]))
    rebuild()
    check("rooms.hide（名前でも場所でも） → 載らない", "big-log" not in block("all") and "shop-site" not in block("all"))
    write_config(lambda data: data["rooms"].update(hide=[], names={"shop-site": "お店のサイト"}, order="name"))
    rebuild()
    names = re.findall(r'<span class="room" title="[^"]*">([^<]*)</span>', block("all"))
    check("rooms.names → 画面に出す名前が変わる", "お店のサイト" in names and "shop-site" not in names)
    check("rooms.order=name → 名前の順", names == sorted(names, key=str.casefold), names)
    write_config(lambda data: data["rooms"].update(order="manual", manual_order=["big-log", "メモ書き"]))
    rebuild()
    names = re.findall(r'<span class="room" title="[^"]*">([^<]*)</span>', block("all"))
    check("rooms.order=manual → 書いた順が先、残りは新しい順", names[:3] == ["big-log", "メモ書き", "お店のサイト"], names)
    write_config(lambda data: data["rooms"].update(show="list", list=["レポート", "big-log"], order="last_active"))
    rebuild()
    names = re.findall(r'<span class="room" title="[^"]*">([^<]*)</span>', block("all"))
    check("rooms.show=list → 書いた部屋だけ", sorted(names) == ["big-log", "レポート"], names)
    write_config(lambda data: (data["rooms"].update(show="recent30", list=[]), data.update(sections=["all", "waiting"])))
    rebuild()
    check("sections → 書いた節だけ、書いた順", shown_sections() == ["all", "waiting"], shown_sections())
    hidden_blocks = re.findall(r'<section class="block" id="(\w+)" hidden>', html())
    check("出さない節も中には入れてある（画面から出せるように hidden で）", sorted(hidden_blocks) == ["recent", "stalled"]
          and html().index('id="waiting"') < html().index('id="recent" hidden'), hidden_blocks)
    check("節への移動も、出す節だけ", re.findall(r'<li data-jump="(\w+)">', html()) == ["all", "waiting"])
    check("「止まっている部屋」を出さない時は、30日より前の部屋の数の行も、その節と一緒に隠れる", html().count('<p class="older">') == 1
          and '<p class="older">' in block("stalled") and 'id="stalled" hidden>' in html())
    write_config(lambda data: (data.update(sections=["recent"]), data["items"].update(status=False, next=False, last_active=False)))
    rebuild()
    check("items → 隠した項目は <html data-off> に並ぶ（CSS で隠す）", 'data-off="status next last_active"' in html_tag(), html_tag())
    check("隠す項目ごとの CSS がある", all(('html[data-off~="%s"] .i-%s' % (key, key)) in html() for key in config.ITEMS))
    check("隠した項目も中には入れてある（画面から出せるように）", "i-next" in block("recent") and "i-status" in block("recent"))
    write_config(lambda data: (data["look"].update(theme="dark", font_size="large", accent="#aa5500"),
                               data["items"].update(status=True, next=True, last_active=True)))
    rebuild()
    text = html()
    check("look → 暗い画面・大きい文字・自分で書いた色", 'data-theme="dark"' in html_tag(text) and 'data-font="large"' in html_tag(text)
          and 'data-accent="custom"' in html_tag(text) and 'html[data-accent="custom"] { --accent: #aa5500; }' in text)

    # ---------- 「最後に頼んだ文」を隠した時は、控えもしない ----------
    hook("UserPromptSubmit", prompt="控えてよい時の質問")
    check("出している間は、フックが頼んだ文を控える", rooms.load()["rooms"][rooms.room_id(first["path"])].get("last_prompt") == "控えてよい時の質問")
    write_config(lambda data: data["items"].update(last_prompt=False))
    hook("SessionStart", source="startup")
    hook("UserPromptSubmit", prompt="控えてほしくない質問")
    kept = [room for room in rooms.load()["rooms"].values() if room.get("last_prompt")]
    cache = (home / "scan_cache.json").read_text(encoding="utf-8")
    rebuild()
    check("隠すと、控えてあった文も消す（rooms.json・scan_cache.json・画面）",
          not kept and "買い物のメモを整理して" not in cache and "最後に頼んだ文" not in body_of() and "i-last_prompt" not in body_of(), len(kept))
    write_config(lambda data: data["items"].update(last_prompt=True))
    hook("SessionStart", source="startup")
    check("出すに戻すと、記録から拾い直す", sum(1 for room in rooms.load()["rooms"].values() if room.get("last_prompt")) >= 5)

    # ---------- 作り直しの速さ ----------
    config.config_file().write_text(good, encoding="utf-8")
    times = [rebuild()["sec"] for _ in range(10)]
    print("    作り直し10回（ダミー %d部屋）: 中央 %.3f秒・最大 %.3f秒" % (len(data["rooms"]), statistics.median(times), max(times)))
    check("作り直しが1秒より短い", max(times) < 1.0, max(times))
    started = time.perf_counter()
    hook("Stop")
    whole = time.perf_counter() - started
    print("    フック1回（Python の起動から終わりまで）: %.3f秒" % whole)
    check("フック1回が1秒より短い", whole < 1.0, whole)
    errors = log_rows("error")
    check("log.txt に失敗の行が無い", not errors, errors[:1])

    if keep:
        keep.mkdir(parents=True, exist_ok=True)
        for name in ("home", "claude_config"):
            target = keep / name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(work / name, target)
        print("\nダミーの画面を残しました: %s" % (keep / "home" / "glancenow.html"))
    shutil.rmtree(work, ignore_errors=True)
    passed = sum(results)
    print("\n%d / %d が合いました" % (passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
