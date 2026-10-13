"""state.json＝道具が自分で覚えておく事（最初の質問が済んだか・案内の回数・最後に画面を作った時刻）。

使う人が書くファイルではない（設定は config.json）。
"""

from . import paths, util


def state_file():
    return paths.home() / "state.json"


def load():
    data = util.read_json(state_file(), {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", 1)
    data.setdefault("setup_done", False)
    data.setdefault("guide_count", 0)       # 最初の案内を出した回数
    data.setdefault("guide_answer", "")     # 案内への答え（"later"＝あとで）
    data.setdefault("guide_stopped", False)  # 答えが無いまま、案内をやめたか
    data.setdefault("last_build", 0)
    data.setdefault("last_scan", 0)
    return data


def update(**values):
    """いくつかの項目を書き換えて保存する。ロックが取れない時は見送る。"""
    home = paths.ensure_home()
    with util.Lock(home / "state.lock") as lock:
        if not lock.ok:
            return False
        data = load()
        data.update(values)
        util.write_json(state_file(), data)
    return True
