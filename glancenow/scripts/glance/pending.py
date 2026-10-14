"""pending/<会話>.json＝「区切り」のスキルが動いたのに、まだ GlanceNow の1行が書かれていない会話の印。

スキルが動いた直後のフック（PostToolUse・Skill）が置き、note（1行を書く）が消す。
返事が終わる時のフック（Stop・止める形）は、自分の会話の印があれば消して、AI に1行を書かせる。
1つの印で頼むのは1回だけ（印を消してから頼むので、続けて止め続ける事は無い）。
"""

import re
import time

from . import config, paths, records, rooms, state, util

STALE = 12 * 60 * 60  # 秒。これより古い印は、会話が途中で終わった物として消す
OWN = "checkpoint"  # このプラグインの、1行を書くスキル

REASON = (
    "GlanceNow：この返事の中で「%s」のスキルが動きましたが、この部屋の GlanceNow の1行は、まだ書かれていません。"
    "glancenow:checkpoint のスキルを使い、その手順どおりに1行を書いてください。"
    "そのあとの返事は、道具が出した「記録しました…」の行だけにしてください（前に書いた文は繰り返さない）。"
)


def pending_dir():
    return paths.home() / "pending"


def session_key(value):
    """会話の id を、ファイルの名前に使える形にする。使えない時は空の文字。"""
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(value or ""))[:80].strip("_")


def _short(name):
    """プラグインのスキル（プラグイン:スキル）は、: の後ろ。頭の / は外す。"""
    return (name or "").strip().lstrip("/").split(":")[-1]


def matches(skill, names):
    """動いたスキルが、区切りとして見るスキルか。名前の全体か、: の後ろが同じなら合う。"""
    skill = (skill or "").strip().lstrip("/")
    if not skill:
        return False
    for name in names:
        name = (name or "").strip().lstrip("/")
        if name and name in (skill, _short(skill)):
            return True
    return False


def is_own(skill):
    """このプラグインの、1行を書くスキルか。"""
    skill = (skill or "").strip().lstrip("/")
    return skill in ("glancenow:" + OWN, OWN)


def on_skill(data, room_path):
    """スキルが動いた直後に呼ぶ。区切りとして見るスキルなら、その会話の印を置く。返す物＝log の印。"""
    tool_input = data.get("tool_input")
    skill = str(tool_input.get("skill") or "") if isinstance(tool_input, dict) else ""
    session = session_key(data.get("session_id"))
    if not skill or not session or is_own(skill):
        return "skip"
    if not matches(skill, config.load()["config"]["checkpoint"]["after_skills"]):
        return "skip"
    if not state.load()["setup_done"]:
        return "skip(setup)"  # 最初の質問の前・「あとで」と答えた人には頼まない
    paths.ensure_home()
    pending_dir().mkdir(exist_ok=True)
    util.write_json(pending_dir() / (session + ".json"), {
        "session": session,
        "room": rooms.room_id(room_path) if room_path else "",
        "path": room_path,
        "skill": skill,
        "at": time.time(),
    })
    return "set"


def clear(room_key="", session=""):
    """note が1行を書いた時に呼ぶ。その部屋か、その会話の印を消す。返す物＝消した数。"""
    folder = pending_dir()
    if not folder.is_dir():
        return 0
    session = session_key(session)
    count = 0
    for item in folder.glob("*.json"):
        flag = util.read_json(item, {})
        room = flag.get("room") if isinstance(flag, dict) else ""
        if (room_key and room == room_key) or (session and item.stem == session):
            try:
                item.unlink()
                count += 1
            except OSError:
                pass
    return count


def on_stop(data):
    """返事が終わる時に呼ぶ。返す物＝(AI に返す文か None, log の印)。

    自分の会話の印があれば消し、その後でその部屋の記録が書かれていなければ、1行を頼む文を返す。
    古い印（ほかの会話の物も）は、ついでに消す。
    """
    folder = pending_dir()
    if not folder.is_dir():
        return None, "stopcheck(none)"
    now = time.time()
    session = session_key(data.get("session_id"))
    reason = None
    mark = "stopcheck(none)"
    for item in folder.glob("*.json"):
        flag = util.read_json(item, {})
        flag = flag if isinstance(flag, dict) else {}
        at = flag.get("at")
        mine = bool(session) and item.stem == session
        old = not isinstance(at, (int, float)) or now - at > STALE
        if not (mine or old):
            continue
        try:
            item.unlink()
        except OSError:
            continue
        if not mine:
            continue
        room = flag.get("room") or ""
        record = records.record_file(room) if room else None
        written = record.stat().st_mtime if record and record.exists() else 0
        if isinstance(at, (int, float)) and written >= at:
            mark = "stopcheck(written)"  # 印を消し損ねたが、1行はもう書かれている
        else:
            reason = REASON % (flag.get("skill") or "区切り")
            mark = "stopcheck(asked)"
    return reason, mark
