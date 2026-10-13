"""ファイルの置き場所を決める。

GlanceNow が書くファイルは、全部 home() の下に置く。
  - 環境変数 GLANCENOW_HOME があれば、その場所
  - 無ければ、ホームフォルダの下の .glancenow
"""

import os
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = SCRIPTS_DIR.parent

# 作っている間だけ置く安全の印。このファイルがある時は、
# GLANCENOW_HOME が無いまま標準の場所へ書きに行かない。
DEVGUARD = SCRIPTS_DIR / ".devguard"
DEVGUARD_LOG = SCRIPTS_DIR / ".devguard.log"


class HomeNotAllowed(Exception):
    """安全の印があるのに GLANCENOW_HOME が無い時に出す。"""


def home_env():
    """GLANCENOW_HOME の値（無ければ空の文字）。"""
    return (os.environ.get("GLANCENOW_HOME") or "").strip()


def home():
    """GlanceNow のファイルを置くフォルダ。まだ作らない。"""
    value = home_env()
    if value:
        return Path(value).expanduser()
    if DEVGUARD.exists():
        raise HomeNotAllowed("GLANCENOW_HOME が無い（安全の印があるので標準の場所へは書かない）")
    return Path.home() / ".glancenow"


def ensure_home():
    """home() を作って返す。"""
    folder = home()
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def log_file():
    return home() / "log.txt"
