"""config.json＝使う人が変えられる設定。

読めない所がある時は、前に読めた設定（config.lastgood.json）で画面を出し、
どこが読めないかを知らせる。設定ファイルが無い時は、標準の値を使う。
"""

import copy
import hashlib
import json
import re

from . import paths, util

SHOW = ("recent30", "all", "list")
ORDER = ("last_active", "manual", "name")
ITEMS = ("status", "next", "waiting", "last_active", "last_prompt")
SECTIONS = ("waiting", "recent", "all", "stalled")
THEMES = ("auto", "light", "dark")
FONT_SIZES = ("small", "normal", "large")
ACCENTS = ("blue", "green", "orange", "purple", "pink", "gray")

DEFAULT = {
    "version": 1,
    "rooms": {
        "show": "recent30",
        "list": [],
        "hide": [],
        "order": "last_active",
        "manual_order": [],
        "names": {},
    },
    "items": {
        "status": True,
        "next": True,
        "waiting": True,
        "last_active": True,
        "last_prompt": True,
    },
    "sections": ["waiting", "recent", "all", "stalled"],
    "look": {
        "theme": "auto",
        "font_size": "normal",
        "accent": "blue",
    },
}

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def default_config():
    return copy.deepcopy(DEFAULT)


def config_file():
    return paths.home() / "config.json"


def lastgood_file():
    return paths.home() / "config.lastgood.json"


def to_text(config):
    return json.dumps(config, ensure_ascii=False, indent=2) + "\n"


def marks(config):
    """設定のまとまりごとの指紋（そのまとまりが書き換わったかを見分ける）。"""
    out = {}
    for group in ("rooms", "items", "sections", "look"):
        text = json.dumps(config.get(group), ensure_ascii=False, sort_keys=True)
        out[group] = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return out


def _line_of(raw, key):
    """設定ファイルの中で、"key" が最初に出る行（1から数える）。無ければ 0。"""
    needle = '"%s"' % key
    for number, line in enumerate(raw.splitlines(), 1):
        if needle in line:
            return number
    return 0


def _syntax_message(raw, error):
    """JSON として読めない時の知らせを、行と直し方で書く。"""
    lines = raw.splitlines()
    line, column, reason = error.lineno, error.colno, error.msg
    before = lines[line - 1][: column - 1] if 0 < line <= len(lines) else ""
    if reason.startswith("Expecting ',' delimiter"):
        if not before.strip() and line > 1:
            return "%d行目の終わりに、カンマ（,）が足りません" % (line - 1)
        return "%d行目の%d文字目の前に、カンマ（,）が足りません" % (line, column)
    if reason.startswith("Expecting property name"):
        return "%d行目: 項目の名前がありません（1つ前の項目の後ろに、余分なカンマが残っていませんか）" % line
    if reason.startswith("Expecting value"):
        return "%d行目の%d文字目: 値がありません（余分なカンマか、\" の付け忘れ）" % (line, column)
    if reason.startswith("Expecting ':' delimiter"):
        return "%d行目: 項目の名前の後ろに、コロン（:）がありません" % line
    if reason.startswith("Unterminated string") or reason.startswith("Invalid control character"):
        return "%d行目: \" が閉じていません" % line
    if reason.startswith("Extra data"):
        return "%d行目: 設定の終わりの後ろに、余分な文字があります" % line
    return "%d行目の%d文字目: JSON として読めません（%s）" % (line, column, reason)


def parse(raw):
    """設定ファイルの文字を読む。返す物＝(設定, 読めない所の一覧, 気になる所の一覧)。

    読めない所が1つでもあれば、設定は None。
    """
    errors = []
    warnings = []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        return None, [_syntax_message(raw, error)], warnings
    if not isinstance(data, dict):
        return None, ["1行目: 全体を { } で囲んでください"], warnings

    result = default_config()

    def where(key):
        line = _line_of(raw, key)
        return ("%d行目: " % line) if line else ""

    def choice(group, key, allowed, extra=None, also=""):
        value = data[group][key]
        if (isinstance(value, str) and value in allowed) or (extra and extra(value)):
            result[group][key] = value
        else:
            errors.append("%s%s.%s は %s%s のどれかで書きます（今は %s）" % (
                where(key), group, key, "／".join(allowed), also, json.dumps(value, ensure_ascii=False)))

    def text_list(group, key):
        value = data[group][key]
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            result[group][key] = value
        else:
            errors.append("%s%s.%s は [\"…\", \"…\"] の形で書きます" % (where(key), group, key))

    for key in data:
        if key not in DEFAULT:
            warnings.append("%s知らない項目 %s があります（使いません）" % (where(key), key))

    for group in ("rooms", "items", "look"):
        if group not in data:
            continue
        if not isinstance(data[group], dict):
            errors.append("%s%s は { } で囲んで書きます" % (where(group), group))
            continue
        for key in data[group]:
            if key not in DEFAULT[group]:
                warnings.append("%s知らない項目 %s.%s があります（使いません）" % (where(key), group, key))

    rooms = data.get("rooms")
    if isinstance(rooms, dict):
        if "show" in rooms:
            choice("rooms", "show", SHOW)
        if "order" in rooms:
            choice("rooms", "order", ORDER)
        for key in ("list", "hide", "manual_order"):
            if key in rooms:
                text_list("rooms", key)
        if "names" in rooms:
            names = rooms["names"]
            if isinstance(names, dict) and all(isinstance(v, str) for v in names.values()):
                result["rooms"]["names"] = names
            else:
                errors.append("%srooms.names は {\"場所か名前\": \"画面に出す名前\"} の形で書きます" % where("names"))

    items = data.get("items")
    if isinstance(items, dict):
        for key in ITEMS:
            if key in items:
                if isinstance(items[key], bool):
                    result["items"][key] = items[key]
                else:
                    errors.append("%sitems.%s は true か false で書きます" % (where(key), key))

    if "sections" in data:
        sections = data["sections"]
        if not isinstance(sections, list):
            errors.append("%ssections は [\"…\", \"…\"] の形で書きます" % where("sections"))
        else:
            kept = []
            for name in sections:
                if name not in SECTIONS:
                    errors.append("%ssections に書けるのは %s です（今は %s）" % (
                        where("sections"), "／".join(SECTIONS), json.dumps(name, ensure_ascii=False)))
                elif name in kept:
                    warnings.append("%ssections に %s が2回あります（1回だけ出します）" % (where("sections"), name))
                else:
                    kept.append(name)
            result["sections"] = kept

    look = data.get("look")
    if isinstance(look, dict):
        if "theme" in look:
            choice("look", "theme", THEMES)
        if "font_size" in look:
            choice("look", "font_size", FONT_SIZES)
        if "accent" in look:
            choice("look", "accent", ACCENTS, also="／#rrggbb の形の色",
                   extra=lambda value: isinstance(value, str) and bool(_HEX_COLOR.match(value)))

    if errors:
        return None, errors, warnings
    return result, errors, warnings


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            return handle.read()
    except OSError:
        return None


def load():
    """今使う設定を返す。

    返す物＝{"config": 設定, "source": "file"／"lastgood"／"default",
             "errors": [読めない所], "warnings": [気になる所]}
    """
    raw = _read_text(config_file())
    if raw is None:
        return {"config": default_config(), "source": "default", "errors": [], "warnings": []}

    parsed, errors, warnings = parse(raw)
    if parsed is not None:
        if _read_text(lastgood_file()) != raw:
            try:
                util.write_text(lastgood_file(), raw)  # 読めた設定を控える
            except OSError:
                pass
        return {"config": parsed, "source": "file", "errors": [], "warnings": warnings}

    good_raw = _read_text(lastgood_file())
    if good_raw is not None:
        good, _good_errors, _good_warnings = parse(good_raw)
        if good is not None:
            return {"config": good, "source": "lastgood", "errors": errors, "warnings": warnings}
    return {"config": default_config(), "source": "default", "errors": errors, "warnings": warnings}


def init():
    """全部の項目を書いた config.json を作る。もうある時は作らない。"""
    target = config_file()
    if target.exists():
        return False
    paths.ensure_home()
    util.write_text(target, to_text(default_config()))
    return True


_LINE_PREFIX = re.compile(r"^\d+行目(の終わり|の\d+文字目(の前)?)?(: |に、)?")


def _as_list(text):
    """["a", "b"] の形か、カンマ区切り（a,b）を一覧にする。"""
    if text.startswith("["):
        try:
            return json.loads(text)
        except ValueError:
            return text  # 読めない形は、そのまま検査に回して知らせる
    return [part.strip() for part in re.split(r"[,、]", text) if part.strip()]


def set_values(pairs):
    """「項目=値」の組で、設定ファイルを書き換える（AI に頼んだ時・最初の質問から使う）。

    例: rooms.show=all  items.last_prompt=false  sections=waiting,recent  rooms.names.shop-site=お店
    読めない所ができる時は、書かない。
    返す物＝{"ok": 書いたか, "changed": [書き換えた項目], "errors": [...], "warnings": [...]}
    """
    out = {"ok": False, "changed": [], "errors": [], "warnings": []}
    raw = _read_text(config_file())
    if raw is None:
        data = default_config()
    else:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as error:
            out["errors"].append("今の設定ファイルが読めません。先にそこを直します: " + _syntax_message(raw, error))
            return out
        if not isinstance(data, dict):
            out["errors"].append("今の設定ファイルが読めません。全体を { } で囲んでください")
            return out

    for pair in pairs:
        key, found, text = pair.partition("=")
        key, text = key.strip(), text.strip()
        parts = key.split(".", 2)  # rooms.names.<部屋> の <部屋> には . が入ってもよい
        group = parts[0]
        if not found or not key:
            out["errors"].append("「項目=値」の形で書きます（今は %s）" % pair)
            continue
        if group == "sections" and len(parts) == 1:
            data["sections"] = _as_list(text)
        elif group in ("rooms", "items", "look") and len(parts) >= 2 and parts[1] in DEFAULT[group]:
            if not isinstance(data.get(group), dict):
                data[group] = {}
            name = parts[1]
            if (group, name) == ("rooms", "names") and len(parts) == 3:
                names = data[group].get("names")
                names = names if isinstance(names, dict) else {}
                if text:
                    names[parts[2]] = text
                else:
                    names.pop(parts[2], None)  # 空にすると、付けた名前を外す
                data[group]["names"] = names
            elif len(parts) == 3:
                out["errors"].append("知らない項目 %s" % key)
                continue
            elif isinstance(DEFAULT[group][name], list):
                data[group][name] = _as_list(text)
            elif isinstance(DEFAULT[group][name], bool) and text.lower() in ("true", "false"):
                data[group][name] = text.lower() == "true"
            elif isinstance(DEFAULT[group][name], dict):
                try:
                    data[group][name] = json.loads(text)
                except ValueError:
                    data[group][name] = text
            else:
                data[group][name] = text
        else:
            out["errors"].append("知らない項目 %s" % key)
            continue
        out["changed"].append(key)

    if out["errors"]:
        return out
    new_raw = to_text(data)
    parsed, errors, warnings = parse(new_raw)
    out["warnings"] = [_LINE_PREFIX.sub("", message) for message in warnings]
    if parsed is None:
        out["errors"] = [_LINE_PREFIX.sub("", message) for message in errors]
        return out
    paths.ensure_home()
    util.write_text(config_file(), new_raw)
    out["ok"] = True
    return out
