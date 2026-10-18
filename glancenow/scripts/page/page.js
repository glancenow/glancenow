(function () {
  "use strict";

  // 画面で変えた事は、このブラウザの中に「まとまり」ごとに持つ。
  //   まとまり＝rooms（部屋の並び・隠す）／items（出す項目）／sections（節）／look（見た目）
  // 一緒に、その時の設定ファイルのそのまとまりの指紋（mark）を持つ。
  // 開いた時に指紋が今の設定ファイルと違えば、設定ファイルが書き換わったという事なので、
  // そのまとまりの画面での変更を外す（設定ファイルの方を出す）。
  var KEY = "glancenow:v1:";
  var GROUPS = ["look", "items", "sections", "rooms"];
  var GROUP_LABEL = { look: "見た目", items: "出す項目", sections: "節", rooms: "部屋（並び・隠す）" };

  var root = document.documentElement;
  var loadedAt = Date.now();
  var data = JSON.parse(document.getElementById("glancenow-data").textContent);
  var base = data.base;   // 設定ファイルどおりの値
  var saved = {};         // まとまり → 画面で変えた値
  var dropped = [];       // 設定ファイルが変わったので外した、まとまり
  var canSave = true;
  var baseOrder = [];     // 設定ファイルどおりの部屋の並び（id）
  var roomNames = {};
  var panel = null;
  var opener = null;

  function merge(first, second) {
    var out = {}, key;
    for (key in first) out[key] = first[key];
    for (key in (second || {})) out[key] = second[key];
    return out;
  }

  function isEmpty(object) {
    for (var key in object) return false;
    return true;
  }

  function same(left, right) {
    if (left.length !== right.length) return false;
    for (var i = 0; i < left.length; i++) if (left[i] !== right[i]) return false;
    return true;
  }

  // ---------- 保存 ----------

  function readSaved() {
    try {
      localStorage.setItem(KEY + "probe", "1");
      localStorage.removeItem(KEY + "probe");
    } catch (error) {
      canSave = false;
      return;
    }
    for (var i = 0; i < GROUPS.length; i++) {
      var group = GROUPS[i];
      var raw = localStorage.getItem(KEY + group);
      if (!raw) continue;
      var entry = null;
      try { entry = JSON.parse(raw); } catch (error) { entry = null; }
      if (entry && entry.mark === data.marks[group] && entry.value && typeof entry.value === "object") {
        saved[group] = entry.value;
      } else {
        localStorage.removeItem(KEY + group);
        if (entry) dropped.push(group);
      }
    }
  }

  function store(group, value) {
    saved[group] = value;
    if (!canSave) return;
    try {
      if (value) localStorage.setItem(KEY + group, JSON.stringify({ mark: data.marks[group], value: value }));
      else localStorage.removeItem(KEY + group);
    } catch (error) {
      canSave = false;
    }
  }

  // ---------- 今の値（設定ファイルの値に、画面で変えた値を重ねる） ----------

  function look() {
    return merge(base.look, saved.look);
  }

  function items() {
    var out = merge(base.items, saved.items);
    if (!base.items.last_prompt) out.last_prompt = false;  // 設定ファイルで隠している間は、文を控えていない
    return out;
  }

  function sectionOrder() {
    return (saved.sections && saved.sections.order) || base.sections;
  }

  function roomOrder() {
    var mine = (saved.rooms && saved.rooms.order) || [];
    var out = mine.filter(function (id) { return baseOrder.indexOf(id) >= 0; });
    baseOrder.forEach(function (id) { if (out.indexOf(id) < 0) out.push(id); });  // 新しい部屋は後ろに付く
    return out;
  }

  function hiddenRooms() {
    var mine = (saved.rooms && saved.rooms.hide) || [];
    return mine.filter(function (id) { return baseOrder.indexOf(id) >= 0; });
  }

  // ---------- 画面に当てる ----------

  function applyLook() {
    var now = look();
    root.setAttribute("data-theme", now.theme);
    root.setAttribute("data-font", now.font_size);
    root.setAttribute("data-accent", now.accent);
  }

  function applyItems() {
    var now = items(), off = [];
    data.labels.items.forEach(function (pair) { if (!now[pair[0]]) off.push(pair[0]); });
    root.setAttribute("data-off", off.join(" "));
  }

  function applySections() {
    var order = sectionOrder();
    var main = document.querySelector("main");
    var jump = document.querySelector(".jump");
    var names = data.labels.sections.map(function (pair) { return pair[0]; });
    var rest = names.filter(function (name) { return order.indexOf(name) < 0; });
    order.concat(rest).forEach(function (name) {
      var visible = order.indexOf(name) >= 0;
      var block = document.getElementById(name);
      if (block) { block.hidden = !visible; main.appendChild(block); }
      var link = jump.querySelector('[data-jump="' + name + '"]');
      if (link) { link.hidden = !visible; jump.appendChild(link); }
    });
    var none = document.querySelector("[data-nosection]");
    if (none) none.hidden = order.length > 0;
    // 30日より前の部屋の数は「止まっている部屋」の節の終わりに出す。その節を出さない時だけ、画面の終わりに出す
    var olderFoot = document.querySelector("[data-older-foot]");
    if (olderFoot) olderFoot.hidden = order.indexOf("stalled") >= 0;
  }

  function applyRooms() {
    var hide = hiddenRooms(), rank = {};
    roomOrder().forEach(function (id, index) { rank[id] = index; });
    var lists = document.querySelectorAll("[data-list]");
    for (var i = 0; i < lists.length; i++) {
      var list = lists[i];
      var members = Array.prototype.slice.call(list.children);
      members.sort(function (left, right) {
        return rank[left.getAttribute("data-room")] - rank[right.getAttribute("data-room")];
      });
      members.forEach(function (member) {
        member.hidden = hide.indexOf(member.getAttribute("data-room")) >= 0;
        list.appendChild(member);
      });
    }
    recount();
  }

  // 隠した部屋を除いて、数を数え直す
  function recount() {
    var blocks = document.querySelectorAll("section.block");
    for (var i = 0; i < blocks.length; i++) {
      var block = blocks[i];
      var list = block.querySelector("[data-list]");
      var count = 0;
      for (var j = 0; j < list.children.length; j++) if (!list.children[j].hidden) count++;
      list.hidden = count === 0;
      block.querySelector(".empty").hidden = count > 0;
      block.querySelector(".n").textContent = count;
      var link = document.querySelector('[data-jump="' + block.id + '"] .n');
      if (link) link.textContent = count;
      if (block.id === "waiting") {
        var jumpItem = document.querySelector('[data-jump="waiting"]');
        if (jumpItem) jumpItem.classList.toggle("has-wait", count > 0);
      }
    }
    var note = document.querySelector("[data-screen-note]");
    var hidden = hiddenRooms().length;
    note.hidden = hidden === 0;
    note.textContent = hidden ? "画面で隠している部屋が " + hidden + " あります（「変える」から戻せます）。" : "";
  }

  // ---------- 小さな部品 ----------

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function button(label, className, key, onClick) {
    var node = el("button", className, label);
    node.type = "button";
    if (key) node.setAttribute("data-k", key);
    node.addEventListener("click", onClick);
    return node;
  }

  function choiceRow(title, key, options, current, onPick) {
    var row = el("div", "tune-row");
    row.appendChild(el("span", "tune-k", title));
    var set = el("div", "tune-set");
    set.setAttribute("role", "group");
    set.setAttribute("aria-label", title);
    options.forEach(function (option) {
      var node = button(option[1], "btn", key + "." + option[0], function () { onPick(option[0]); });
      node.setAttribute("aria-pressed", String(option[0] === current));
      if (option[2]) {
        var dot = el("i", "dot");
        dot.setAttribute("aria-hidden", "true");
        dot.style.background = "linear-gradient(135deg, " + option[2] + " 50%, " + option[3] + " 50%)";
        node.insertBefore(dot, node.firstChild);
      }
      set.appendChild(node);
    });
    row.appendChild(set);
    return row;
  }

  function checkLine(label, key, checked, onChange, why) {
    var line = el("label", checked ? "" : "off");
    var box = el("input");
    box.type = "checkbox";
    box.checked = checked;
    box.setAttribute("data-k", key);
    box.setAttribute("aria-label", label);
    if (why) box.disabled = true;
    box.addEventListener("change", function () { onChange(box.checked); });
    line.appendChild(box);
    var text = el("span", "", label);
    if (why) text.appendChild(el("small", "tune-why", why));
    line.appendChild(text);
    return line;
  }

  function group(title, name, children) {
    var box = el("section", "tune-group");
    var head = el("header");
    head.appendChild(el("h3", "", title));
    if (saved[name]) {
      head.appendChild(el("span", "tune-tag", "画面で変更中"));
      head.appendChild(button("この変更を消す", "btn small", name + ".reset", function () {
        store(name, null);
        applyAll();
        fill(name + ".reset");
      }));
    }
    box.appendChild(head);
    children.forEach(function (child) { box.appendChild(child); });
    return box;
  }

  // ---------- 変えた時 ----------

  function setLook(key, value) {
    var mine = merge(saved.look), name;
    mine[key] = value;
    for (name in mine) if (mine[name] === base.look[name]) delete mine[name];  // 設定ファイルと同じ値は持たない
    store("look", isEmpty(mine) ? null : mine);
    applyLook();
    fill("look." + key + "." + value);
  }

  function setItem(key, on) {
    var mine = merge(saved.items), name;
    mine[key] = on;
    for (name in mine) if (mine[name] === base.items[name]) delete mine[name];
    store("items", isEmpty(mine) ? null : mine);
    applyItems();
    fill("items." + key);
  }

  function setSections(order, focusKey) {
    store("sections", same(order, base.sections) ? null : { order: order });
    applySections();
    fill(focusKey);
  }

  function setRooms(order, hide, focusKey) {
    var mine = {};
    if (!same(order, baseOrder)) mine.order = order;
    if (hide.length) mine.hide = hide;
    store("rooms", isEmpty(mine) ? null : mine);
    applyRooms();
    fill(focusKey);
  }

  function moved(list, from, to) {
    var out = list.slice();
    if (to < 0 || to >= out.length) return out;
    out.splice(to, 0, out.splice(from, 1)[0]);
    return out;
  }

  // ---------- 「変える」の中身 ----------

  function lookGroup() {
    var now = look();
    return group(GROUP_LABEL.look, "look", [
      choiceRow("明るさ", "look.theme", [["auto", "PCに合わせる"], ["light", "明るい"], ["dark", "暗い"]], now.theme,
        function (value) { setLook("theme", value); }),
      choiceRow("文字の大きさ", "look.font_size", [["small", "小さめ"], ["normal", "ふつう"], ["large", "大きめ"]], now.font_size,
        function (value) { setLook("font_size", value); }),
      choiceRow("色", "look.accent", data.labels.accents, now.accent,
        function (value) { setLook("accent", value); })
    ]);
  }

  function itemsGroup() {
    var now = items();
    var list = el("ul", "tune-list");
    data.labels.items.forEach(function (pair) {
      var locked = pair[0] === "last_prompt" && !base.items.last_prompt;
      var line = el("li");
      line.appendChild(checkLine(pair[1], "items." + pair[0], now[pair[0]], function (on) { setItem(pair[0], on); },
        locked ? "設定ファイルで隠している間は文を控えていないので、ここからは出せません" : ""));
      list.appendChild(line);
    });
    return group(GROUP_LABEL.items, "items", [list]);
  }

  function sectionsGroup() {
    var order = sectionOrder();
    var list = el("ul", "tune-list");
    var pairs = data.labels.sections.slice().sort(function (left, right) {
      var a = order.indexOf(left[0]), b = order.indexOf(right[0]);
      return (a < 0 ? 99 : a) - (b < 0 ? 99 : b);
    });
    pairs.forEach(function (pair) {
      var name = pair[0], at = order.indexOf(name), line = el("li");
      line.appendChild(checkLine(pair[1], "sections." + name, at >= 0, function (on) {
        setSections(on ? order.concat([name]) : order.filter(function (other) { return other !== name; }), "sections." + name);
      }));
      if (at >= 0) {
        line.appendChild(button("↑", "btn small", "sections." + name + ".up", function () {
          setSections(moved(order, at, at - 1), "sections." + name + ".up");
        })).setAttribute("aria-label", pair[1] + "を上へ");
        line.appendChild(button("↓", "btn small", "sections." + name + ".down", function () {
          setSections(moved(order, at, at + 1), "sections." + name + ".down");
        })).setAttribute("aria-label", pair[1] + "を下へ");
      }
      list.appendChild(line);
    });
    return group(GROUP_LABEL.sections, "sections", [list]);
  }

  function roomsGroup() {
    var order = roomOrder(), hide = hiddenRooms();
    var list = el("ul", "tune-list");
    order.forEach(function (id, at) {
      var name = roomNames[id], line = el("li");
      line.appendChild(checkLine(name, "rooms." + id, hide.indexOf(id) < 0, function (on) {
        setRooms(order, on ? hide.filter(function (other) { return other !== id; }) : hide.concat([id]), "rooms." + id);
      }));
      line.appendChild(button("先頭へ", "btn small", "rooms." + id + ".top", function () {
        setRooms(moved(order, at, 0), hide, "rooms." + id + ".top");
      })).setAttribute("aria-label", name + "を先頭へ");
      line.appendChild(button("↑", "btn small", "rooms." + id + ".up", function () {
        setRooms(moved(order, at, at - 1), hide, "rooms." + id + ".up");
      })).setAttribute("aria-label", name + "を上へ");
      line.appendChild(button("↓", "btn small", "rooms." + id + ".down", function () {
        setRooms(moved(order, at, at + 1), hide, "rooms." + id + ".down");
      })).setAttribute("aria-label", name + "を下へ");
      list.appendChild(line);
    });
    var note = el("p", "tune-note", "チェックを外すと隠れます。並べ替えると、その並びのまま出します（新しい部屋は後ろに付きます）。");
    return group(GROUP_LABEL.rooms + " " + order.length, "rooms", [note, list]);
  }

  // 「変える」の中身を作り直す。focusKey＝作り直した後に、選んだままにする部品
  function fill(focusKey) {
    if (!panel) return;
    var body = panel.querySelector(".tune-body");
    var top = body.scrollTop;
    while (body.firstChild) body.removeChild(body.firstChild);
    body.appendChild(el("p", "tune-note", canSave
      ? "ここで変えた事は、このブラウザだけに残ります。AI に頼んで変えた設定とぶつかった時は、AI に頼んだ方が出ます。"
      : "このブラウザでは保存できないので、読み込み直すと元に戻ります。"));
    body.appendChild(lookGroup());
    body.appendChild(itemsGroup());
    body.appendChild(sectionsGroup());
    body.appendChild(roomsGroup());
    if (!isEmpty(saved) && GROUPS.some(function (name) { return saved[name]; })) {
      var all = el("p", "tune-all");
      all.appendChild(button("画面での変更を全部消す", "btn", "all.reset", function () {
        GROUPS.forEach(function (name) { store(name, null); });
        applyAll();
        fill();
        panel.querySelector(".tune-head button").focus();
      }));
      body.appendChild(all);
    }
    body.scrollTop = top;
    if (focusKey) {
      var target = body.querySelector('[data-k="' + focusKey + '"]');
      if (target) target.focus();
      else panel.querySelector(".tune-head button").focus();
    }
  }

  function openPanel() {
    panel = el("aside", "tune");
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "画面から変える");
    var head = el("div", "tune-head");
    head.appendChild(el("h2", "", "変える"));
    head.appendChild(button("閉じる", "btn", "", closePanel));
    panel.appendChild(head);
    panel.appendChild(el("div", "tune-body"));
    document.body.appendChild(panel);
    root.setAttribute("data-tuning", "");
    opener.setAttribute("aria-expanded", "true");
    fill();
    head.querySelector("button").focus();
  }

  function closePanel() {
    if (!panel) return;
    panel.parentNode.removeChild(panel);
    panel = null;
    root.removeAttribute("data-tuning");
    opener.setAttribute("aria-expanded", "false");
    opener.focus();
  }

  // 設定ファイルが変わって外した変更を、1回だけ知らせる
  function showDropped() {
    if (!dropped.length) return;
    var box = el("div", "notice");
    box.setAttribute("role", "status");
    box.setAttribute("data-dropped", dropped.join(" "));
    dropped.forEach(function (name) {
      box.appendChild(el("p", "", "設定ファイルが変わったので、画面での「" + GROUP_LABEL[name] + "」の変更を外しました。"));
    });
    box.appendChild(button("閉じる", "btn small", "", function () { box.parentNode.removeChild(box); }));
    var top = document.querySelector(".top");
    top.parentNode.insertBefore(box, top.nextSibling);
  }

  // ---------- 「続きから開く」（その部屋で会話の続きを始める行をコピーする） ----------

  function copyText(text, done) {
    function fallback() {
      var area = el("textarea", "");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (error) { ok = false; }
      document.body.removeChild(area);
      done(ok);
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () { done(true); }, fallback);
    } else {
      fallback();
    }
  }

  function setupOpen() {
    var buttons = document.querySelectorAll("[data-open]");
    for (var i = 0; i < buttons.length; i++) {
      (function (node) {
        var label = node.textContent;
        node.hidden = false;
        node.addEventListener("click", function () {
          var line = node.getAttribute("data-open");
          copyText(line, function (ok) {
            if (!ok) {
              window.prompt("この行をコピーして、端末に貼ってください。", line);
              return;
            }
            node.textContent = "コピーしました";
            node.classList.add("done");
            setTimeout(function () { node.textContent = label; node.classList.remove("done"); }, 2000);
          });
        });
      })(buttons[i]);
    }
  }

  // ---------- 「◯日前」 ----------

  function ago(seconds) {
    if (seconds < 60) return "たった今";
    if (seconds < 3600) return Math.floor(seconds / 60) + "分前";
    if (seconds < 86400) return Math.floor(seconds / 3600) + "時間前";
    return Math.floor(seconds / 86400) + "日前";
  }

  // 「◯日前」を、開いた時の時刻で数え直す
  function tick() {
    var now = Date.now() / 1000;
    var marks = document.querySelectorAll("time[data-t] .ago");
    for (var i = 0; i < marks.length; i++) {
      var at = Number(marks[i].parentNode.getAttribute("data-t"));
      if (at > 0) marks[i].textContent = ago(Math.max(0, now - at));
    }
  }

  // ---------- 始まり ----------

  function applyAll() {
    applyLook();
    applyItems();
    applySections();
    applyRooms();
  }

  function start() {
    var rows = document.querySelectorAll("#all [data-list] > [data-room]");
    for (var i = 0; i < rows.length; i++) {
      var id = rows[i].getAttribute("data-room");
      baseOrder.push(id);
      roomNames[id] = rows[i].querySelector(".room").textContent;
    }
    applySections();
    applyRooms();
    showDropped();
    setupOpen();
    tick();
    opener = document.querySelector("[data-tune-open]");
    opener.hidden = false;
    opener.setAttribute("aria-expanded", "false");
    opener.addEventListener("click", function () { if (panel) closePanel(); else openPanel(); });
    document.addEventListener("keydown", function (event) { if (event.key === "Escape") closePanel(); });
  }

  // 見た目と項目は <html> の属性だけで決まるので、中身が描かれる前に当てる（ちらつかせない）
  readSaved();
  applyLook();
  applyItems();
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();

  // 別のタブから戻ってきた時、開いてから1分より長ければ読み直す（作り直された画面を出す）
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) return;
    if (!panel && Date.now() - loadedAt > 60000) {
      location.reload();
    } else {
      tick();
    }
  });
})();
