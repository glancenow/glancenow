"""records/<部屋のid>.md＝部屋ごとの記録。

1行＝ 日時 | 状態 | 次の一手 | 判断待ち | 一言
いちばん下の行が「今」。# で始まる行は説明として読み飛ばす。
"""

import time

from . import paths, util

STATUSES = ("動かしている", "維持だけ", "休眠")
ALIASES = {
    "active": "動かしている",
    "keep": "維持だけ",
    "sleep": "休眠",
}


def normal_status(value):
    """状態の書き方をそろえる。知らない書き方は None。"""
    value = (value or "").strip()
    if value in STATUSES:
        return value
    return ALIASES.get(value.lower())


def records_dir():
    return paths.home() / "records"


def record_file(room_id):
    return records_dir() / (room_id + ".md")


def _field(text):
    """1行の中に入れられる形にする（区切りの | と改行を置き換える）。"""
    return util.clean_text(text, limit=400).replace("|", "｜")


def add(room_id, room_path, status, next_step, waiting="", memo="", now=None):
    """記録に1行足して、その行を返す。"""
    now = time.time() if now is None else now
    paths.ensure_home()
    folder = records_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = record_file(room_id)
    line = " | ".join(
        [util.local_text(now), status, _field(next_step), _field(waiting), _field(memo)]
    )
    is_new = not target.exists()
    with open(target, "a", encoding="utf-8", newline="\n") as handle:
        if is_new:
            handle.write("# GlanceNow の記録｜%s\n" % _field(room_path))
            handle.write("# 1行＝日時 | 状態 | 次の一手 | 判断待ち | 一言（いちばん下の行が「今」）\n")
        handle.write(line + "\n")
    return line


def read_all(room_id):
    """記録の行を、古い順の一覧で返す。"""
    out = []
    try:
        with open(record_file(room_id), "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return out
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 3:
            continue  # 形が違う行は読み飛ばす
        parts += [""] * (5 - len(parts))
        out.append(
            {
                "time": parts[0],
                "status": parts[1],
                "next": parts[2],
                "waiting": parts[3],
                "memo": parts[4],
            }
        )
    return out


def latest(room_id):
    """いちばん下の行（＝今）。無ければ None。"""
    lines = read_all(room_id)
    return lines[-1] if lines else None
