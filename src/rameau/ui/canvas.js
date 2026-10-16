// Rameau Studio canvas: talks to Python through Qt's web channel ("bridge").
"use strict";

let bridge = null;
let piece = null;          // current piece (chords, beat times, pages)
let state = {};            // playing, position, loop, tempo, macros, styleKey, soundKey
let catalog = {styles: [], sounds: [], samples: []};
let selected = -1;

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));

new QWebChannel(qt.webChannelTransport, (channel) => {
  bridge = channel.objects.bridge;
  bridge.pieceChanged.connect((j) => renderPiece(JSON.parse(j)));
  bridge.stateChanged.connect((j) => renderState(JSON.parse(j)));
  bridge.catalogChanged.connect((j) => { catalog = JSON.parse(j); renderCatalog(); });
  bridge.toast.connect(showToast);
  bridge.tutorAnswer.connect((j) => addMessage(JSON.parse(j)));
  bridge.fingerprintChanged.connect((html) => { $("fingerprint").innerHTML = html; });
  bridge.ready();
});

// ------------------------------------------------------------------ catalog: eras, sounds, journeys
function renderCatalog() {
  if (catalog.dark !== undefined) document.body.classList.toggle("dark", !!catalog.dark);
  const eras = $("eras");
  eras.querySelectorAll(".era").forEach((e) => e.remove());
  // in time order, evenly spaced so every name stays readable (the date is in the tooltip)
  const n = catalog.styles.length;
  catalog.styles.forEach((s, i) => {
    const x = 4 + 92 * (n > 1 ? i / (n - 1) : 0.5);
    const b = document.createElement("button");
    b.className = "era" + (s.key === state.styleKey ? " on" : "");
    b.style.left = x + "%";
    b.title = `${s.title} (c. ${s.year}): ${s.description}`;
    b.innerHTML = `<span class="dot"></span><span class="name">${esc(s.short)}</span>`;
    b.onclick = () => bridge.chooseStyle(s.key);
    eras.appendChild(b);
  });
  const j = $("journeys");
  j.innerHTML = "";
  (catalog.journeys || []).forEach((jr, i) => {
    const b = document.createElement("button");
    b.className = "journey";
    b.innerHTML = `<b>${esc(jr.title)}</b><span>${esc(jr.text)}</span>`;
    b.onclick = () => bridge.journey(i);
    j.appendChild(b);
  });
  renderSounds();
  renderSuggestions();
}

function renderSounds() {
  const box = $("sounds");
  box.innerHTML = "";
  (catalog.sounds || []).slice(0, 3).forEach((s) => {
    const b = document.createElement("button");
    b.className = "chip" + (s.key === state.soundKey ? " on" : "");
    b.textContent = s.name;
    b.title = s.why;
    b.onclick = () => bridge.chooseSound(s.key);
    box.appendChild(b);
  });
  const more = document.createElement("select");
  more.innerHTML = `<option value="">More sounds…</option>` +
    (catalog.sounds || []).slice(3).map((s) => `<option value="${esc(s.key)}" ${s.key === state.soundKey ? "selected" : ""}>${esc(s.name)}</option>`).join("") +
    `<option disabled>──────────</option>` +
    (catalog.grooves || []).map((g) => `<option value="groove:${esc(g)}">${esc(g)} (band)</option>`).join("");
  more.onchange = () => { if (more.value) bridge.chooseSound(more.value); };
  box.appendChild(more);
}

// ------------------------------------------------------------------ piece: score, strip, card
function renderPiece(p) {
  piece = p;
  $("welcome").hidden = !!p.chords.length;
  $("stripWrap").hidden = !p.chords.length;
  $("tuneTitle").textContent = p.title || "Choose a tune";
  $("tuneMeta").textContent = p.chords.length ? `${p.key} · ${p.styleTitle}` : "";
  $("pages").innerHTML = (p.svg || []).map((s) => `<div class="page">${s}</div>`).join("");
  const strip = $("strip");
  strip.querySelectorAll(".chord").forEach((e) => e.remove());
  p.chords.forEach((c, i) => {
    const b = document.createElement("button");
    b.className = `chord ${c.function}` + (i === selected ? " sel" : "");
    b.style.flexGrow = c.beats;
    b.title = `${c.where}: ${c.symbol} (${c.name}), ${c.functionText}`;
    b.innerHTML = `<span class="num">${esc(c.name)}${c.locked ? '<span class="lock">●</span>' : ""}</span><span class="sym">${esc(c.symbol)}</span>`;
    b.onclick = (ev) => { ev.stopPropagation(); openCard(i, b); };
    strip.appendChild(b);
  });
  // clicking a chord symbol in the score opens the same card
  document.querySelectorAll("#pages g.harm").forEach((g, i) => {
    g.style.cursor = "pointer";
    g.onclick = (ev) => { ev.stopPropagation(); if (p.chords[i]) openCard(i, strip.children[i + 1]); };
  });
  if (selected >= p.chords.length) closeCard();
  else if (selected >= 0) openCard(selected, strip.children[selected + 1]);
}

function openCard(i, anchor) {
  selected = i;
  const c = piece.chords[i];
  document.querySelectorAll(".chord").forEach((e, k) => e.classList.toggle("sel", k === i));
  const card = $("card");
  card.innerHTML = `
    <button class="close" title="Close">×</button>
    <h3>${esc(c.symbol)}</h3>
    <div class="role">${esc(c.name)} · ${esc(c.functionText)} · ${esc(c.where)}</div>
    ${c.cadence ? `<div class="cad">${esc(c.cadence)}</div>` : ""}
    <ul>${c.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
    <div class="try">${c.locked ? "You chose this chord." : "Try instead — the rest re-fits around it:"}</div>
    <div class="chips">${c.alternatives.map((a) => `<button class="chip" data-label="${esc(a.label)}">${esc(a.symbol)} <small>${esc(a.name)} · ${esc(a.likelihood)}</small></button>`).join("")}
      ${piece.anyLocked ? `<button class="chip" data-clear="1">Undo my choices</button>` : ""}</div>`;
  card.querySelector(".close").onclick = closeCard;
  card.querySelectorAll("[data-label]").forEach((b) => b.onclick = () => bridge.tryAlternative(c.beat, b.dataset.label));
  const clear = card.querySelector("[data-clear]");
  if (clear) clear.onclick = () => bridge.clearLocks();
  card.classList.add("on");
  const r = (anchor || $("strip")).getBoundingClientRect();
  const w = 360, h = card.offsetHeight;
  card.style.left = Math.max(12, Math.min(window.innerWidth - w - 12, r.left + r.width / 2 - w / 2)) + "px";
  card.style.top = Math.max(12, r.top - h - 12) + "px";
}

function closeCard() {
  selected = -1;
  $("card").classList.remove("on");
  document.querySelectorAll(".chord").forEach((e) => e.classList.remove("sel"));
}
document.addEventListener("click", (ev) => {
  if (!$("card").contains(ev.target)) closeCard();
  if (!$("menu").contains(ev.target) && ev.target.closest("#tune") === null) $("menu").classList.remove("on");
});

// ------------------------------------------------------------------ state: transport, dials, playhead
function renderState(s) {
  const prevStyle = state.styleKey, prevSound = state.soundKey;
  state = s;
  $("play").disabled = !s.canPlay;
  $("play").textContent = s.playing ? "■" : "▶";
  $("loop").classList.toggle("on", !!s.loop);
  $("tempo").textContent = s.tempo;
  $("time").textContent = fmt(s.position || 0);
  document.body.classList.toggle("playing", !!s.playing);
  movePlayhead(s.position || 0);
  if (s.styleKey !== prevStyle) document.querySelectorAll(".era").forEach((e, i) =>
    e.classList.toggle("on", catalog.styles[i] && catalog.styles[i].key === s.styleKey));
  if (s.soundKey !== prevSound) renderSounds();
  renderDials(s.macros || {});
}
const fmt = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;

function movePlayhead(t) {
  if (!piece || !piece.chords.length || !piece.beatTimes.length) return;
  const bt = piece.beatTimes;
  let k = 0;
  while (k + 1 < bt.length && bt[k + 1] <= t) k++;
  const span = (k + 1 < bt.length ? bt[k + 1] : bt[k] + 0.6) - bt[k];
  const beat = k + Math.max(0, Math.min(1, (t - bt[k]) / (span || 1)));
  const strip = $("strip"), total = piece.totalBeats || 1;
  $("playhead").style.left = (beat / total * strip.clientWidth) + "px";
}

const DIALS = [
  ["character", "Character", "plain", "adventurous", "How surprising the chord choices are"],
  ["motion", "Motion", "still", "flowing", "How much the inner voices and bass move"],
  ["feel", "Feel", "strict", "expressive", "Dynamics, slowing into cadences, human timing"],
  ["space", "Space", "dry", "cathedral", "The room the music plays in"],
];
let dragging = null;
function renderDials(m) {
  const box = $("dials");
  if (!box.children.length) {
    DIALS.forEach(([key, label, lo, hi, tip]) => {
      const d = document.createElement("div");
      d.className = "dial";
      d.dataset.key = key;
      d.title = `${tip}. Drag up or down; double-click to reset.`;
      d.innerHTML = `<svg viewBox="0 0 40 40"><circle cx="20" cy="20" r="15" fill="none" stroke="var(--rule)" stroke-width="4"
        stroke-dasharray="70.7 94.2" transform="rotate(135 20 20)"/><circle class="arc" cx="20" cy="20" r="15" fill="none"
        stroke="var(--accent)" stroke-width="4" stroke-linecap="round" stroke-dasharray="0 94.2" transform="rotate(135 20 20)"/>
        <circle class="knob" cx="20" cy="20" r="2.6" fill="var(--ink)"/></svg><span class="lbl">${label}</span><span class="val"></span>`;
      d.dataset.lo = lo; d.dataset.hi = hi;
      d.onpointerdown = (ev) => { dragging = {d, y: ev.clientY, v: +d.dataset.value}; d.setPointerCapture(ev.pointerId); };
      d.onpointermove = (ev) => {
        if (!dragging || dragging.d !== d) return;
        const v = Math.max(0, Math.min(1, dragging.v + (dragging.y - ev.clientY) / 160));
        setDial(d, v);
        bridge.setMacro(key, v);
      };
      d.onpointerup = () => { dragging = null; };
      d.ondblclick = () => { const v = key === "space" ? 0.35 : (key === "character" ? 0 : 0.5); setDial(d, v); bridge.setMacro(key, v); };
      box.appendChild(d);
    });
  }
  [...box.children].forEach((d) => { if (!dragging || dragging.d !== d) setDial(d, m[d.dataset.key] ?? 0.5); });
}
function setDial(d, v) {
  d.dataset.value = v;
  d.querySelector(".arc").setAttribute("stroke-dasharray", `${(70.7 * v).toFixed(1)} 94.2`);
  const a = (135 + 270 * v) * Math.PI / 180;
  const k = d.querySelector(".knob");
  k.setAttribute("cx", (20 + 9 * Math.cos(a)).toFixed(1));
  k.setAttribute("cy", (20 + 9 * Math.sin(a)).toFixed(1));
  d.querySelector(".val").textContent = v < 0.2 ? d.dataset.lo : (v > 0.8 ? d.dataset.hi : "");
}

// ------------------------------------------------------------------ tune menu
$("tune").onclick = (ev) => {
  ev.stopPropagation();
  const m = $("menu");
  m.innerHTML = `<div class="hint">Sample tunes</div>` +
    (catalog.samples || []).map((s) => `<button data-sample="${esc(s.file)}">${esc(s.title)}</button>`).join("") +
    `<hr><button data-act="edit">Write or edit a tune…</button><button data-act="open">Open a file…</button>
     <button data-act="chords">Start from chords…</button><button data-act="ireal">Open an iReal Pro chart…</button>
     ${catalog.ai ? `<button data-act="ai">Compose a tune with AI…</button>` : ""}`;
  m.querySelectorAll("[data-sample]").forEach((b) => b.onclick = () => { m.classList.remove("on"); bridge.loadSample(b.dataset.sample); });
  m.querySelectorAll("[data-act]").forEach((b) => b.onclick = () => { m.classList.remove("on"); bridge.tuneAction(b.dataset.act); });
  const r = $("tune").getBoundingClientRect();
  m.style.left = r.left + "px";
  m.style.top = (r.bottom + 6) + "px";
  m.classList.add("on");
};

// ------------------------------------------------------------------ views, tutor
document.querySelectorAll("#views button").forEach((b) => b.onclick = () => {
  document.querySelectorAll("#views button").forEach((x) => x.classList.toggle("on", x === b));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("on", v.id === "view-" + b.dataset.view));
  if (b.dataset.view === "fingerprint") bridge.requestFingerprint();
  closeCard();
});
function renderSuggestions() {
  $("suggest").innerHTML = ["Why does this cadence sound final?", "What makes this sound like the style?",
    "Which chord is the most surprising here?"].map((q) => `<button class="chip">${esc(q)}</button>`).join("");
  $("suggest").querySelectorAll(".chip").forEach((b) => b.onclick = () => ask(b.textContent));
}
function ask(q) {
  if (!q.trim()) return;
  addMessage({who: "me", html: esc(q)});
  addMessage({who: "ai", html: "<i>Thinking…</i>", pending: true});
  bridge.askTutor(q);
}
function addMessage(m) {
  const chat = $("chat");
  const pending = chat.querySelector(".pending");
  if (pending && m.who !== "me") pending.remove();
  const d = document.createElement("div");
  d.className = `msg ${m.who}` + (m.pending ? " pending" : "");
  d.innerHTML = m.html;
  chat.appendChild(d);
  d.scrollIntoView({block: "end"});
}
$("askForm").onsubmit = (ev) => { ev.preventDefault(); ask($("askInput").value); $("askInput").value = ""; };

// ------------------------------------------------------------------ transport buttons and keys
$("play").onclick = () => bridge.togglePlay();
$("rewind").onclick = () => bridge.rewind();
$("loop").onclick = () => bridge.setLoop(!state.loop);
$("slower").onclick = () => bridge.setTempo(Math.max(30, (state.tempo || 80) - 4));
$("faster").onclick = () => bridge.setTempo(Math.min(240, (state.tempo || 80) + 4));
$("advanced").onclick = () => bridge.toggleAdvanced();
document.addEventListener("keydown", (ev) => {
  if (ev.target.tagName === "INPUT") return;
  if (ev.code === "Space") { ev.preventDefault(); bridge.togglePlay(); }
  if (ev.key === "Escape") closeCard();
});

let toastTimer = null;
function showToast(text) {
  const t = $("toast");
  t.textContent = text;
  t.classList.add("on");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("on"), 2600);
}
