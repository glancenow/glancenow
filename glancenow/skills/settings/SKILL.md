---
name: settings
description: GlanceNow の画面の設定を、言葉で頼まれた時に変える。例：「GlanceNow で止まっている部屋を出さないで」「GlanceNow を暗い画面にして」「GlanceNow で shop-site を一番上にして」「GlanceNow の設定を変えて」。
allowed-tools:
  - Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/glancenow.py" *)
  - Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/glancenow.py" *)
---

# GlanceNow の設定を、頼まれた言葉から変える

## 道具

使うのは、次の1つだけです（以下「道具」）。python3 が無い所では、python3 を python に置き換えます。

    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/glancenow.py" <入口> [引数]

設定ファイルを直接書き換えません。`config-set` で入れます（書ける値は、道具が確かめます）。
今の設定ファイルが読めない形になっている時だけは、`config-check` が知らせた行を、設定ファイルを開いて直します。

## 手順

1. `config-show` を実行して、今の設定を見る。
2. 頼まれた事が部屋に関わる時（載せる・隠す・並び・名前）は、`rooms` を実行して、部屋の名前と id を確かめる。
   どの部屋の事か決められない時だけ、1問だけ聞く。
3. 項目と書ける値を確かめたい時は、`config-help` を実行する（設定の説明が出る）。説明のファイルを直接開かない（開いてよいかの確認が出るため）。
4. `config-set 項目=値 [項目=値 …]` で入れる。一覧の項目（`rooms.hide` など）は、今の一覧に足した全体を書く。
5. `config-check` を実行する。「読めない所」が出たら、入れ直す。
6. `status` を実行する。「最初の質問: 済み」なら `build` を実行して画面を作り直す。
   「まだ」の時は、画面を作らない。「設定は入れました。画面は、最初の質問が済むと出ます。今、質問を始めますか」と1回だけ聞く。
7. 変えた事を1〜2行で伝える（何を・どの値に）。

## 伝える事

- 画面の「変える」ボタンで同じまとまり（部屋／出す項目／節／見た目）を変えていた時は、その画面での変更は外れて、設定ファイルの方が出る。当てはまりそうな時だけ1行で伝える。
- 開いたままの画面は、読み込み直すと新しくなる。

## 例

| 頼まれた言葉 | 入れる設定 |
|---|---|
| 止まっている部屋を出さないで | `sections=waiting,recent,all`（今の節の並びから `stalled` を外した全体） |
| 暗い画面にして | `look.theme=dark` |
| 文字を大きく | `look.font_size=large` |
| shop-site を隠して | `rooms.hide=<今の一覧>,shop-site` |
| shop-site を「お店のサイト」と出して | `rooms.names.shop-site=お店のサイト` |
| 全部の部屋を載せて | `rooms.show=all` |
| 一時フォルダの部屋も載せて | `rooms.show_temp=true` |
| 最後に頼んだ文は出さないで | `items.last_prompt=false` |
