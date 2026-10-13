"""最初の案内。

入れたあと最初の会話で、AI が「設定の質問を今するか・あとでするか」を1回だけ聞く。
そのための文を、SessionStart のフックが AI に渡す。
答え（質問が済んだ／あとで）が記録されるまで、出すのは MAX_SHOWN 回まで。
"""

from . import log, paths, state

MAX_SHOWN = 3
SOURCES = ("startup", "clear")  # 新しい会話の始まりだけ（続きから開いた時・要約の後は出さない）
START_WORDS = "GlanceNow の設定を始めて"


def text(count):
    """AI に渡す文。命令ではなく、今の状態と決まりとして書く。"""
    entry = (paths.SCRIPTS_DIR / "glancenow.py").as_posix()  # Windows でも / で書く（シェルで \ が消えないように）
    return "\n".join([
        "GlanceNow（作業フォルダごとの今を、1枚の画面で見る道具）のプラグインが入っています。",
        "最初の設定の質問は、まだ済んでいません。済むまで、画面は作られません。（この案内は%d回目。%d回まで出ます）" % (count, MAX_SHOWN),
        "GlanceNow の決まり：使う人の最初の発言に答える前に、"
        "「GlanceNow の設定の質問を、今しますか。あとでしますか。」を選択形式で1回だけ聞きます（選択肢＝今する／あとで）。",
        "- 「今する」の時：スキル glancenow:setup の手順で進めます。終わったら、もとの用件に戻ります。",
        "- 「あとで」の時：次のコマンドを1回実行すると、この案内は出なくなります。",
        "  python3 \"%s\" guide --answer later   （python3 が無い所では python）" % entry,
        "  そのあと「始める時は『%s』と言うか、/glancenow:setup と打つ」と1行で伝えて、もとの用件に戻ります。" % START_WORDS,
        "- 選択形式の質問を出せない場面（人が見ていない実行など）では聞かず、"
        "返事の最後に「GlanceNow の設定がまだです。『%s』で始められます。」と1行だけ添えます。" % START_WORDS,
    ])


def check(source):
    """SessionStart で呼ぶ。返す物＝(AI に渡す文か None, log に書く印)"""
    current = state.load()
    if current["setup_done"]:
        return None, ""
    if current["guide_answer"] == "later":
        return None, "guide(later)"
    if source not in SOURCES:
        return None, "guide(skip:%s)" % source
    shown = current["guide_count"]
    if shown >= MAX_SHOWN:
        if not current["guide_stopped"]:
            state.update(guide_stopped=True)
            log.write("guide", result="stopped",
                      note="案内を%d回出したが、答えが記録されなかった。これ以上は出さない" % MAX_SHOWN)
        return None, "guide(stopped)"
    state.update(guide_count=shown + 1)
    return text(shown + 1), "guide(shown %d/%d)" % (shown + 1, MAX_SHOWN)


def answer_later():
    """「あとで」と答えた事を覚える。"""
    state.update(guide_answer="later")
    log.write("guide", result="later")
