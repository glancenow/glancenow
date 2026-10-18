"""画面（glancenow.html）を作る。

1ファイルで開ける HTML。CSS も JavaScript も中に入れ、外から読む物は無い。
JavaScript が動かない所で開いても、設定ファイルどおりの中身が全部読める。

画面から変えられるように、次の形で書き出す。
  - 節は4つとも入れる（設定で出さない節には hidden を付ける）
  - 項目は部屋ごとに全部入れ、出す・隠すは <html data-off="…"> と CSS で決める
    （「最後に頼んだ文」だけは、設定で隠している時は入れない）
  - 部屋の1件ごとに data-room（部屋の id）を付ける
"""

import html
import json
import os
import shlex
import time

from . import VERSION, config as config_module, log, paths, records, rooms as rooms_module, state, util

DAY = 24 * 3600
SHOW_DAYS = 30     # rooms.show が recent30 の時に載せる日数
STALLED_DAYS = 21  # 節「止まっている部屋」に入れる日数
PROMPT_CHARS = 60  # 「最後に頼んだ文」の先頭から出す字数
SHORT_PROMPT = util.SHORT_PROMPT  # 「最後に頼んだ文」がこの字数より短い時は、1つ前に頼んだ文も並べる
PREV_CHARS = 40    # その「1つ前に頼んだ文」の先頭から出す字数
# 節「最近動いた部屋」に入れる日数は、設定の rooms.recent_days（標準 2）

STATUS_KIND = {"動かしている": "active", "維持だけ": "keep", "休眠": "sleep"}
STATUS_MARK = {"active": "●", "keep": "◐", "sleep": "○", "none": "－"}

SECTION_TITLE = {
    "waiting": "判断待ち",
    "recent": "最近動いた部屋",
    "all": "全部の部屋",
    "stalled": "止まっている部屋",
}
SECTION_ABOUT = {
    "waiting": "あなたの返事を待っている事",
    "recent": "この%d日のあいだに動いた、区切りの記録がある部屋",  # %d＝rooms.recent_days
    "all": "載せている部屋の一覧",
    "stalled": "%d日以上、動きのない部屋" % STALLED_DAYS,
}
SECTION_EMPTY = {
    "waiting": "判断待ちはありません。",
    "recent": "この%d日のあいだに動いた部屋はありません。",
    "all": "載せる部屋がありません。",
    "stalled": "止まっている部屋はありません。",
}
# 動いた部屋はあるが、どれにも区切りの記録が無い時の「最近動いた部屋」の空の文
RECENT_EMPTY_NO_RECORD = "この%d日に動いた部屋に、区切りの記録はまだありません。部屋で「区切り」と言うと、次の一手がここに出ます。"
# 載せていない古い部屋がある時の「止まっている部屋」の空の文（すぐ下に、その数の1行が続く）
STALLED_EMPTY_WITH_OLDER = "載せている部屋の中に、止まっている部屋はありません。"

OPEN_LABEL = "続きから開く"
OPEN_ABOUT = "押すと、この部屋の最後の会話の続きを始める行をコピーします。端末に貼って実行します。"

ITEM_LABEL = {
    "status": "状態",
    "next": "次の一手",
    "waiting": "判断待ち",
    "last_active": "最後に動いた日時",
    "last_prompt": "最後に頼んだ文",
}

# 色の名前 → (画面に出す名前, 明るい画面の色, 暗い画面の色)
ACCENT_COLORS = {
    "blue": ("青", "#2a66c4", "#84b3ff"),
    "green": ("緑", "#1d7a50", "#6fd3a0"),
    "orange": ("オレンジ", "#b3560b", "#f3a561"),
    "purple": ("紫", "#6a48c0", "#b49cff"),
    "pink": ("ピンク", "#b53b78", "#f494c2"),
    "gray": ("グレー", "#4c5560", "#aab2bd"),
}

PAGE_DIR = paths.SCRIPTS_DIR / "page"


def page_file():
    return paths.home() / "glancenow.html"


def esc(text):
    return html.escape(str(text), quote=True)


def ago_text(seconds):
    if seconds < 60:
        return "たった今"
    if seconds < 3600:
        return "%d分前" % (seconds // 60)
    if seconds < DAY:
        return "%d時間前" % (seconds // 3600)
    return "%d日前" % (seconds // DAY)


def date_text(moment, now):
    there = time.localtime(moment)
    if there.tm_year == time.localtime(now).tm_year:
        return time.strftime("%m/%d %H:%M", there)
    return time.strftime("%Y/%m/%d", there)


def time_tag(moment, now):
    """<time>：「3日前」と日付。JavaScript が動く所では、開いた時に数え直す。"""
    if not moment:
        return "<span class=\"abs\">分からない</span>"
    return "<time data-t=\"%d\"><span class=\"ago\">%s</span><span class=\"abs\">%s</span></time>" % (
        int(moment), ago_text(max(0, now - moment)), esc(date_text(moment, now)))


def _local_seconds(text):
    """記録の日時（このPCの時刻で「2026-10-10 23:40」と書いてある）を、秒にする。"""
    try:
        return time.mktime(time.strptime(text, "%Y-%m-%d %H:%M"))
    except (ValueError, OverflowError):
        return None


def _same_path(left, right):
    return os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right))


def matches(room, reference):
    """設定ファイルに書かれた1つの書き方（場所・名前・id）が、この部屋を指すか。"""
    reference = reference.strip()
    if not reference:
        return False
    if reference == room["id"] or reference == room["folder_name"]:
        return True
    return bool(room["path"]) and _same_path(reference, room["path"])


def collect(config, rooms_data, now):
    """設定に合わせて、載せる部屋を並べて返す。

    返す物＝(載せる部屋, 載せなかった数)。載せなかった数は
    {"all": 全部で, "temp": OS の一時フォルダの下だから, "older": 30日より前に動いたきりだから}。
    """
    rule = config["rooms"]
    everything = []
    for key, raw in rooms_data["rooms"].items():
        latest = records.latest(key) or {}
        room = {
            "id": key,
            "path": raw.get("path") or "",
            "folder_name": raw.get("name") or key,
            "last_active": raw.get("last_active") or 0,
            "last_prompt": raw.get("last_prompt") or "",
            "prev_prompt": raw.get("prev_prompt") or "",
            "has_record": bool(latest),
            "status": latest.get("status", ""),
            "next": latest.get("next", ""),
            "waiting": latest.get("waiting", ""),
            "record_time": _local_seconds(latest.get("time", "")),
        }
        room["kind"] = STATUS_KIND.get(room["status"], "none")
        room["name"] = room["folder_name"]
        for reference, shown_name in rule["names"].items():
            if shown_name.strip() and matches(room, reference):
                room["name"] = shown_name.strip()
        everything.append(room)

    shown = []
    left = {"all": 0, "temp": 0, "older": 0}
    for room in everything:
        if not rule["show_temp"] and rooms_module.is_temp(room["path"]):
            left["temp"] += 1
            continue
        if any(matches(room, reference) for reference in rule["hide"]):
            continue
        if rule["show"] == "recent30" and now - room["last_active"] > SHOW_DAYS * DAY:
            left["older"] += 1
            continue
        if rule["show"] == "list" and not any(matches(room, reference) for reference in rule["list"]):
            continue
        shown.append(room)
    left["all"] = len(everything) - len(shown)

    shown.sort(key=lambda room: -room["last_active"])
    if rule["order"] == "name":
        shown.sort(key=lambda room: room["name"].casefold())
    elif rule["order"] == "manual":
        def place(room):
            for index, reference in enumerate(rule["manual_order"]):
                if matches(room, reference):
                    return index
            return len(rule["manual_order"])
        shown.sort(key=place)  # 並びに書かれていない部屋は、後ろに新しい順で続く
    return shown, left


def continue_line(path):
    """その部屋で、最後の会話の続きを始める行（端末に貼る）。場所が分からない部屋は空の文字。"""
    if not path:
        return ""
    if os.name == "nt":
        # PowerShell と Git Bash の両方で動く形（PowerShell 5.1 は && を使えない）
        return "cd \"%s\"; claude --continue" % path
    return "cd %s && claude --continue" % shlex.quote(path)


def open_button(room):
    """「続きから開く」のボタン。JavaScript が動く時だけ出す（押すと行をコピーする）。"""
    line = continue_line(room["path"])
    if not line:
        return ""
    return "<button type=\"button\" class=\"btn small open\" data-open=\"%s\" title=\"%s\" hidden>%s</button>" % (
        esc(line), esc(OPEN_ABOUT), esc(OPEN_LABEL))


def prompt_html(room):
    """「最後に頼んだ文」。短い合図（「再開」など）の時は、1つ前に頼んだ文も並べる。"""
    text = room["last_prompt"]
    out = esc(text[:PROMPT_CHARS] + ("…" if len(text) > PROMPT_CHARS else ""))
    previous = room["prev_prompt"]
    if len(text) < SHORT_PROMPT and previous:
        short = previous[:PREV_CHARS] + ("…" if len(previous) > PREV_CHARS else "")
        out += "<span class=\"prev\" title=\"1つ前に頼んだ文\">← %s</span>" % esc(short)
    return out


def chip(room):
    kind = room["kind"]
    label = room["status"] if kind != "none" else "記録なし"
    return "<span class=\"chip %s i-status\"><i aria-hidden=\"true\">%s</i>%s</span>" % (kind, STATUS_MARK[kind], esc(label))


def card(room, now, keep_prompt):
    facts = []
    if room["next"]:
        facts.append("<li class=\"i-next\"><span class=\"k\">次の一手</span><span class=\"v\">%s</span></li>" % esc(room["next"]))
    if room["waiting"]:
        facts.append("<li class=\"i-waiting\"><span class=\"k\">判断待ち</span><span class=\"v wait\">%s</span></li>" % esc(room["waiting"]))
    facts.append("<li class=\"i-last_active\"><span class=\"k\">最後に動いた</span><span class=\"v\">%s</span></li>" % time_tag(room["last_active"], now))
    if keep_prompt and room["last_prompt"]:
        facts.append("<li class=\"i-last_prompt\"><span class=\"k\">最後に頼んだ文</span><span class=\"v prompt\">%s</span></li>" % prompt_html(room))
    return (
        "<article class=\"card\" data-room=\"%s\"><header><h3 title=\"%s\">%s</h3>%s</header><ul class=\"facts\">%s</ul>%s</article>"
        % (esc(room["id"]), esc(room["path"]), esc(room["name"]), chip(room), "".join(facts), open_button(room))
    )


def row(room, now):
    # 判断待ちの印は、次の一手の文と離して、行の終わりの列に置く（次の一手が判断待ちの中身に見えないように）
    flag = "<span class=\"flag i-waiting\" title=\"%s\">⚠ 判断待ちあり</span>" % esc(room["waiting"]) if room["waiting"] else ""
    text = "<span class=\"i-next\">%s</span>" % esc(room["next"]) if room["next"] else ""
    return (
        "<li data-room=\"%s\"><span class=\"room\" title=\"%s\">%s</span>%s"
        "<span class=\"when i-last_active\">%s</span><span class=\"next\">%s</span>%s%s</li>"
        % (esc(room["id"]), esc(room["path"]), esc(room["name"]), chip(room), time_tag(room["last_active"], now), text,
           flag, open_button(room))
    )


def wait_row(room):
    return "<li data-room=\"%s\"><span class=\"room\">%s</span><span class=\"what\">%s</span><span class=\"since\">%s</span></li>" % (
        esc(room["id"]), esc(room["name"]), esc(room["waiting"]),
        ("記録 " + esc(room["status_time"])) if room.get("status_time") else "")


def older_text(count):
    """載せていない古い部屋の数を知らせる1行（部屋の名前は出さない）。"""
    amount = ("%d つ" % count) if count < 10 else ("%d " % count)  # 「つ」で数えるのは9まで
    return "このほかに、%d日より前に止まった部屋が %sあります。" % (SHOW_DAYS, amount)


def section_html(name, shown, now, keep_prompt, visible, older=0, recent_days=2):
    """節1つの HTML と、その節に入った部屋の数を返す。visible＝設定でこの節を出すか。

    older＝30日より前に動いたきりで載せていない部屋の数（「止まっている部屋」の節の終わりに1行で出す）。
    recent_days＝「最近動いた部屋」に入れる日数。カードにするのは、区切りの記録がある部屋だけ
    （記録の無い部屋には、カードで読む次の一手が無い。「全部の部屋」の表には出る）。
    """
    empty = SECTION_EMPTY[name]
    about = SECTION_ABOUT[name]
    if name == "waiting":
        members = [room for room in shown if room["waiting"]]
        kind, inner = "ul class=\"waits\"", "".join(wait_row(room) for room in members)
    elif name == "recent":
        moved = [room for room in shown if now - room["last_active"] <= recent_days * DAY]
        members = [room for room in moved if room["has_record"]]
        kind, inner = "div class=\"cards\"", "".join(card(room, now, keep_prompt) for room in members)
        about = about % recent_days
        empty = (RECENT_EMPTY_NO_RECORD if moved else empty) % recent_days
    elif name == "all":
        members = list(shown)
        kind, inner = "ul class=\"rows\"", "".join(row(room, now) for room in members)
    else:  # stalled
        members = [room for room in shown if now - room["last_active"] >= STALLED_DAYS * DAY]
        kind, inner = "ul class=\"rows\"", "".join(row(room, now) for room in members)

    tag = kind.split(" ")[0]
    if name == "stalled" and older:
        empty = STALLED_EMPTY_WITH_OLDER
    body = "<%s data-list%s>%s</%s><p class=\"empty\"%s>%s</p>" % (
        kind, "" if members else " hidden", inner, tag, " hidden" if members else "", esc(empty))
    heading = "<h2>%s</h2><span class=\"n\">%d</span><span class=\"about\">%s</span>" % (
        esc(SECTION_TITLE[name]), len(members), esc(about))
    if name == "stalled":
        body = "<details><summary>%s</summary>%s</details>" % (heading, body)  # 動きのない部屋は畳んでおく
        if older:
            body += "<p class=\"older\">%s</p>" % esc(older_text(older))  # 畳んでいても見える所に置く
    else:
        body = heading + body
    return "<section class=\"block\" id=\"%s\"%s>%s</section>" % (name, "" if visible else " hidden", body), len(members)


def notice_html(loaded):
    """設定ファイルの知らせ（読めない所・気になる所）。無ければ空の文字。"""
    out = ""
    if loaded["errors"]:
        using = "前に読めた設定" if loaded["source"] == "lastgood" else "標準の設定"
        out += "<div class=\"notice\" role=\"alert\"><p>設定ファイルに読めない所があります。%sで画面を出しています。</p><ul>%s</ul>" \
               "<p class=\"file\">設定ファイル: %s</p></div>" % (
                   using, "".join("<li>%s</li>" % esc(text) for text in loaded["errors"]), esc(config_module.config_file()))
    if loaded["warnings"]:
        out += "<div class=\"notice\"><p>設定ファイルに気になる所があります。</p><ul>%s</ul></div>" % "".join(
            "<li>%s</li>" % esc(text) for text in loaded["warnings"])
    return out


def accent_name(value):
    """<html data-accent="…"> に書く名前。自分で書いた色（#rrggbb）は custom。"""
    return value if value in ACCENT_COLORS else "custom"


def accent_css(value):
    """色の名前ごとの CSS。画面から色を変えられるように、6色とも入れる。"""
    rules = []
    for name, (_label, light, dark) in ACCENT_COLORS.items():
        rules.append("html[data-accent=\"%s\"] { --accent: %s; }" % (name, light))
        rules.append("html[data-accent=\"%s\"][data-theme=\"dark\"] { --accent: %s; }" % (name, dark))
        rules.append("@media (prefers-color-scheme: dark) { html[data-accent=\"%s\"][data-theme=\"auto\"] { --accent: %s; } }" % (name, dark))
    if value not in ACCENT_COLORS:
        rules.append("html[data-accent=\"custom\"] { --accent: %s; }" % value)
    return "\n".join(rules)


def page_data(config, now):
    """画面の JavaScript に渡すデータ（設定ファイルの値・まとまりごとの指紋・名前の一覧）。"""
    look = config["look"]
    accents = [[name, label, light, dark] for name, (label, light, dark) in ACCENT_COLORS.items()]
    if look["accent"] not in ACCENT_COLORS:
        accents.append(["custom", "設定ファイルの色", look["accent"], look["accent"]])
    return {
        "version": VERSION,
        "built": int(now),
        "marks": config_module.marks(config),
        "base": {
            "look": {"theme": look["theme"], "font_size": look["font_size"], "accent": accent_name(look["accent"])},
            "items": dict(config["items"]),
            "sections": list(config["sections"]),
        },
        "labels": {
            "items": [[key, ITEM_LABEL[key]] for key in config_module.ITEMS],
            "sections": [[key, SECTION_TITLE[key]] for key in config_module.SECTIONS],
            "accents": accents,
        },
    }


def render(loaded, rooms_data, now):
    """画面の HTML を作って返す。返す物＝{"html": 文字, "shown": 載せた部屋の数, ...}"""
    config = loaded["config"]
    items = config["items"]
    shown, left = collect(config, rooms_data, now)
    left_out = left["all"]
    for room in shown:
        room["status_time"] = ago_text(max(0, now - room["record_time"])) if room["record_time"] else ""
    waiting_count = sum(1 for room in shown if room["waiting"])

    blocks = []
    jump = []
    order = list(config["sections"])
    for name in order + [name for name in config_module.SECTIONS if name not in order]:
        visible = name in order
        block, count = section_html(name, shown, now, items["last_prompt"], visible, older=left["older"],
                                    recent_days=config["rooms"]["recent_days"])
        blocks.append(block)
        # 判断待ちがある時は、その丸ボタンを判断待ちの色にする（いちばん上の数の代わり）
        busy = " class=\"has-wait\"" if (name == "waiting" and count) else ""
        jump.append("<li data-jump=\"%s\"%s%s><a href=\"#%s\">%s<span class=\"n\">%d</span></a></li>" % (
            name, busy, "" if visible else " hidden", name, esc(SECTION_TITLE[name]), count))

    hint = "<p class=\"hint\" data-nosection%s>出す節が1つも選ばれていません（設定の sections）。</p>" % (" hidden" if order else "")
    if not rooms_data["rooms"]:
        hint += "<p class=\"hint\">まだ部屋が見つかっていません。Claude Code で会話を始めると、その作業フォルダがここに出ます。</p>"
    elif shown and not any(room["has_record"] for room in shown):
        hint += "<p class=\"hint\">状態・次の一手・判断待ちは、まだ記録がありません。会話の区切りで記録すると、ここに出ます。</p>"

    scan_info = rooms_data.get("scan") or {}
    unreadable = scan_info.get("unreadable") or 0
    foot = ["<p>会話の記録 %s本から作りました。</p>" % esc(scan_info.get("files", 0))]
    if unreadable:
        foot.append("<p class=\"warn\">読めなかった記録が %d本あります（その記録は、ファイルの更新時刻を「最後に動いた日時」に使っています）。</p>" % unreadable)
    else:
        foot.append("<p>読めなかった記録は 0本です。</p>")
    # 載せていない部屋の数。30日より前の部屋の数は「止まっている部屋」の節の終わりに出すので、
    # その節を出している間は、ここでは言わない（同じ事を2回言わない）。節を出さない時に見える行を別に置く
    others = left_out - left["older"]
    if others:
        reasons = []
        if others - left["temp"]:
            reasons.append("設定で外した部屋")
        if left["temp"]:
            reasons.append("一時フォルダの下の部屋")
        foot.append("<p>ほかに %d部屋あります（%s）。ここには載せていません。</p>" % (others, "・".join(reasons)))
    if left["older"]:
        foot.append("<p data-older-foot%s>%s</p>" % (" hidden" if "stalled" in order else "", esc(older_text(left["older"]))))
    foot.append("<p data-screen-note hidden></p>")
    foot.append("<p>GlanceNow %s</p>" % esc(VERSION))

    body = (
        "<div class=\"wrap\">"
        "<header class=\"top\"><h1>GlanceNow</h1><ul class=\"stats\">"
        "<li>作った日時 %s</li>"
        "<li><button type=\"button\" class=\"btn\" data-tune-open hidden>変える</button></li>"
        "</ul></header>"
        "%s%s"
        "<ul class=\"jump\">%s</ul>"
        "<main>%s</main>"
        "<footer>%s</footer>"
        "</div>"
    ) % (
        time_tag(now, now),
        notice_html(loaded), hint, "".join(jump), "".join(blocks), "".join(foot),
    )

    data_text = json.dumps(page_data(config, now), ensure_ascii=False).replace("<", "\\u003c")

    def part(name):
        with open(PAGE_DIR / name, "r", encoding="utf-8") as handle:
            return handle.read()

    # ひな形の名前は .tpl（.html にすると、HTML を自動で書き換える道具に触られる事がある）
    page = part("template.tpl")
    for key, value in (
        ("{{theme}}", esc(config["look"]["theme"])),
        ("{{font}}", esc(config["look"]["font_size"])),
        ("{{accent}}", esc(accent_name(config["look"]["accent"]))),
        ("{{off}}", " ".join(key for key in config_module.ITEMS if not items[key])),
        ("{{built}}", str(int(now))),
        ("{{css}}", part("page.css")),
        ("{{accent_css}}", accent_css(config["look"]["accent"])),
        ("{{js}}", part("page.js")),
        ("{{data}}", data_text),
        ("{{body}}", body),  # 部屋の文が入るので、最後に入れる
    ):
        page = page.replace(key, value)
    return {"html": page, "shown": len(shown), "left_out": left_out, "temp_out": left["temp"],
            "older": left["older"], "waiting": waiting_count}


def build(reason="manual"):
    """画面を作って書き出す。"""
    started = time.perf_counter()
    paths.ensure_home()
    now = time.time()
    loaded = config_module.load()
    page = render(loaded, rooms_module.load(), now)
    target = page_file()
    util.write_text(target, page["html"])
    # 作り始めた時刻を画面の時刻にする（作っている間に変わった元を、次で拾えるように）
    os.utime(target, (now, now))
    state.update(last_build=now)
    seconds = round(time.perf_counter() - started, 3)
    log.write("build", reason=reason, rooms=page["shown"], config=loaded["source"], sec=seconds)
    return {"path": str(target), "sec": seconds, "rooms": page["shown"], "waiting": page["waiting"],
            "temp_out": page["temp_out"],
            "config": loaded["source"], "errors": loaded["errors"], "warnings": loaded["warnings"]}
