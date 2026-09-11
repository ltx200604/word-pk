/* Word PK mobile client — fixed two-player flow */
const state = {
  users: [],
  meId: Number(localStorage.getItem("meId") || 0),
  opponentId: 0,
  answerMode: "mixed",
  selectMode: "mixed",
  wordCount: 20,
  roomCode: "",
  matchId: 0,
  questions: [],
  qIndex: 0,
  myScore: 0,
  opAnswered: 0,
  ready: false,
  started: false,
  finished: false,
  ws: null,
  qStartTs: 0,
  results: [],
  timerHandle: null,
  elapsedSec: 0,
  pendingTimer: null,
  pendingInvite: null,
};

const $ = (id) => document.getElementById(id);

function show(id) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.remove("active"));
  $(id).classList.add("active");
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
  if (!res.ok) {
    const msg = (data && (data.detail || data.message)) || res.statusText;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function labelAnswer(m) {
  return { choice: "选择题", input: "输入意思", mixed: "混合" }[m] || m;
}
function labelSelect(m) {
  return { mixed: "共同短板优先", gap: "拉开差距", weak: "两边都弱" }[m] || m;
}

function otherUser() {
  return state.users.find((u) => u.id !== state.meId) || null;
}

/* ---------- users ---------- */
async function loadUsers() {
  const data = await api("/api/users");
  state.users = data.users || [];
  if (!state.meId && state.users.length === 1) {
    state.meId = state.users[0].id;
    localStorage.setItem("meId", String(state.meId));
  }
  const other = otherUser();
  if (other) state.opponentId = other.id;
  renderUsers();
  await checkPending();
}

function renderUsers() {
  const list = $("user-list");
  list.innerHTML = "";
  if (!state.users.length) {
    list.innerHTML = `<div class="hint">还没有账号。你和对方各注册一次。</div>`;
  }
  for (const u of state.users) {
    const el = document.createElement("div");
    el.className = "user-item" + (u.id === state.meId ? " on" : "");
    const sync = u.last_sync_at
      ? new Date(u.last_sync_at * 1000).toLocaleString()
      : "未同步";
    const st = u.shanbay_status === "ok" ? "扇贝已同步" : (u.shanbay_status || "未配置扇贝");
    el.innerHTML = `
      <div>
        <div><strong>${escapeHtml(u.display_name || u.name)}</strong>${u.id === state.meId ? "（我）" : ""}</div>
        <div class="meta">${st} · 已学 ${u.learned || 0} · 弱词 ${u.weak || 0}</div>
        <div class="meta">上次同步：${sync}</div>
      </div>
      <div class="meta">${u.id === state.meId ? "当前" : "设为我"}</div>
    `;
    el.onclick = () => {
      state.meId = u.id;
      localStorage.setItem("meId", String(u.id));
      const other = otherUser();
      state.opponentId = other ? other.id : 0;
      renderUsers();
      renderOpponents();
    };
    list.appendChild(el);
  }
  renderOpponents();
}

function renderOpponents() {
  const sel = $("opponent-select");
  const others = state.users.filter((u) => u.id !== state.meId);
  sel.innerHTML = "";
  for (const u of others) {
    const opt = document.createElement("option");
    opt.value = u.id;
    opt.textContent = `${u.display_name || u.name}（弱词 ${u.weak || 0}）`;
    sel.appendChild(opt);
  }
  if (others.length === 1) {
    state.opponentId = others[0].id;
    sel.value = String(others[0].id);
  } else if (sel.options.length) {
    state.opponentId = Number(sel.value);
  } else {
    state.opponentId = 0;
  }
  $("btn-create").disabled = !state.meId || !state.opponentId;
}

/* ---------- cookie / password ---------- */
async function saveCookie() {
  if (!state.meId) { alert("请先选择自己"); return; }
  const cookie = $("cookie-input").value.trim();
  if (!cookie) { alert("请粘贴 Cookie"); return; }
  $("sync-status").textContent = "同步中…";
  try {
    const data = await api("/api/shanbay/cookie", {
      method: "POST",
      body: JSON.stringify({ user_id: state.meId, cookie }),
    });
    $("sync-status").textContent = `同步成功：写入 ${data.imported.imported} 词 · 词书 ${data.book || "-"}`;
    await loadUsers();
  } catch (e) {
    $("sync-status").textContent = `同步失败：${e.message}`;
  }
}

async function shanbayLogin() {
  if (!state.meId) { alert("请先选择自己"); return; }
  const username = $("sb-user").value.trim();
  const password = $("sb-pass").value;
  if (!username || !password) { alert("请填写扇贝账号和密码"); return; }
  $("sync-status").textContent = "登录并同步中…";
  $("btn-sb-login").disabled = true;
  try {
    const data = await api("/api/shanbay/login", {
      method: "POST",
      body: JSON.stringify({ user_id: state.meId, username, password }),
    });
    $("sync-status").textContent = `同步成功：写入 ${data.imported.imported} 词 · 词书 ${data.book || "-"}`;
    $("sb-pass").value = "";
    await loadUsers();
  } catch (e) {
    $("sync-status").textContent = `失败：${e.message}`;
  } finally {
    $("btn-sb-login").disabled = false;
  }
}

async function resync() {
  if (!state.meId) { alert("请先选择自己"); return; }
  $("sync-status").textContent = "再次同步中…";
  try {
    const data = await api(`/api/shanbay/sync/${state.meId}`, { method: "POST" });
    $("sync-status").textContent = `同步成功：写入 ${data.imported.imported} 词`;
    await loadUsers();
  } catch (e) {
    $("sync-status").textContent = `同步失败：${e.message}`;
  }
}

/* ---------- pending invites ---------- */
async function checkPending() {
  if (!state.meId) return;
  try {
    const data = await api(`/api/room/pending?user_id=${state.meId}`);
    const invites = data.invites || [];
    const card = $("invite-card");
    if (invites.length) {
      const inv = invites[0];
      state.pendingInvite = inv;
      const host = state.users.find((u) => u.id === inv.host_id);
      $("invite-text").textContent =
        `${host ? (host.display_name || host.name) : "对方"} 邀请你对战 · ${inv.word_count} 题 · ${labelAnswer(inv.answer_mode || "mixed")}`;
      card.classList.remove("hidden");
    } else {
      state.pendingInvite = null;
      card.classList.add("hidden");
    }
    // host returning to an open room
    const hostRooms = data.host_rooms || [];
    if (!state.started && hostRooms.length && !$("screen-room").classList.contains("active")) {
      const hr = hostRooms[0];
      state.roomCode = hr.room_code;
      state.opponentId = hr.guest_id || state.opponentId;
      // re-fetch questions via join (same user as host is allowed? host is user_a, join requires user in room)
      // host already has questions in memory only if they created this session; after reload need join-like restore
      await restoreHostRoom(hr.room_code);
    }
  } catch {
    /* ignore poll errors */
  }
}

async function restoreHostRoom(roomCode) {
  try {
    // host uses join endpoint too — it accepts either player
    const data = await api("/api/room/join", {
      method: "POST",
      body: JSON.stringify({ room_code: roomCode, user_id: state.meId }),
    });
    state.roomCode = data.room_code;
    state.matchId = data.match_id;
    state.questions = data.questions || [];
    state.qIndex = 0;
    state.myScore = 0;
    state.opAnswered = 0;
    state.ready = false;
    state.started = !!data.started;
    state.finished = false;
    state.results = [];
    $("room-title").textContent = "对战中";
    $("room-meta").textContent = `${data.word_count} 题`;
    $("room-status").textContent = "对局仍在进行，点准备或等待对方。";
    $("btn-ready").disabled = false;
    $("btn-ready").textContent = "我准备好了";
    show("screen-room");
    connectWS();
  } catch {
    /* room gone */
  }
}

async function joinInvite() {
  if (!state.pendingInvite) return;
  const code = state.pendingInvite.room_code;
  await joinRoom(code);
}

async function joinRoom(roomCode) {
  try {
    const data = await api("/api/room/join", {
      method: "POST",
      body: JSON.stringify({ room_code: roomCode, user_id: state.meId }),
    });
    enterRoom(data, {
      title: "对战中",
      status: "已加入，点「我准备好了」",
    });
  } catch (e) {
    alert(e.message);
    await checkPending();
  }
}

function enterRoom(data, { title, status }) {
  state.roomCode = data.room_code;
  state.matchId = data.match_id;
  state.questions = data.questions || [];
  state.qIndex = 0;
  state.myScore = 0;
  state.opAnswered = 0;
  state.ready = false;
  state.started = !!data.started;
  state.finished = false;
  state.results = [];
  if (data.user_a && data.user_b) {
    state.opponentId = data.user_a === state.meId ? data.user_b : data.user_a;
  }
  $("room-title").textContent = title;
  $("room-meta").textContent = `${data.word_count} 题 · ${labelAnswer(state.answerMode)} · ${labelSelect(state.selectMode)}`;
  $("room-status").textContent = status;
  $("btn-ready").disabled = false;
  $("btn-ready").textContent = "我准备好了";
  show("screen-room");
  connectWS();
  if (data.started) startQuiz();
}

async function createRoom() {
  if (!state.meId || !state.opponentId) {
    alert("请先注册你和对方");
    return;
  }
  $("btn-create").disabled = true;
  $("btn-create").textContent = "同步数据并出题中…";
  try {
    const data = await api("/api/room/create", {
      method: "POST",
      body: JSON.stringify({
        user_id: state.meId,
        opponent_id: state.opponentId,
        word_count: state.wordCount,
        answer_mode: state.answerMode,
        select_mode: state.selectMode,
      }),
    });
    enterRoom(data, {
      title: "等待对方",
      status: "已发起对战。把邀请链接发给对方，或等对方打开本页点「加入对战」。",
    });
  } catch (e) {
    alert(e.message);
  } finally {
    $("btn-create").disabled = false;
    $("btn-create").textContent = "发起对战";
  }
}

function inviteLink() {
  const base = `${location.origin}/?join=${state.roomCode}`;
  return base;
}

async function copyInvite() {
  const link = inviteLink();
  try {
    await navigator.clipboard.writeText(link);
    $("room-status").textContent = `已复制邀请链接：${link}`;
  } catch {
    prompt("复制这个链接发给对方：", link);
  }
}

/* ---------- websocket ---------- */
function connectWS() {
  if (state.ws) {
    try { state.ws.close(); } catch {}
  }
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const url = `${proto}://${location.host}/ws/${state.roomCode}/${state.meId}`;
  const ws = new WebSocket(url);
  state.ws = ws;
  ws.onopen = () => {
    $("online-badge").textContent = "已连接";
    $("online-badge").classList.add("ok");
  };
  ws.onclose = () => {
    $("online-badge").textContent = "连接断开";
    $("online-badge").classList.remove("ok");
  };
  ws.onerror = () => {};
  ws.onmessage = (ev) => {
    let msg = {};
    try { msg = JSON.parse(ev.data); } catch { return; }
    handleWS(msg);
  };
}

function handleWS(msg) {
  if (msg.type === "presence") {
    const n = (msg.online || []).length;
    $("online-badge").textContent = n >= 2 ? "双方在线" : "等待对手…";
    $("online-badge").classList.toggle("ok", n >= 2);
    if (n >= 2 && !state.started) {
      $("room-status").textContent = "对方已上线，点「我准备好了」即可开赛。";
    }
  } else if (msg.type === "ready_state") {
    const ready = msg.ready || [];
    const opReady = ready.includes(state.opponentId);
    if (!state.ready) {
      $("room-status").textContent = opReady
        ? "对方已准备，等你准备后开赛。"
        : "等待双方准备…";
    } else {
      $("room-status").textContent = opReady
        ? "双方已准备，马上开赛…"
        : "你已准备，等待对方…";
    }
  } else if (msg.type === "start") {
    startQuiz();
  } else if (msg.type === "opponent_progress") {
    if (msg.user_id !== state.meId) {
      state.opAnswered = msg.answered || 0;
      $("op-progress").textContent = String(state.opAnswered);
    }
  } else if (msg.type === "finished") {
    showResult(msg.result);
  }
}

function sendWS(obj) {
  if (state.ws && state.ws.readyState === 1) {
    state.ws.send(JSON.stringify(obj));
  }
}

function markReady() {
  state.ready = true;
  $("btn-ready").disabled = true;
  $("btn-ready").textContent = "已准备，等待对手…";
  sendWS({ type: "ready" });
}

function joinDemoOpponent() {
  const opp = otherUser();
  if (!opp || !state.roomCode) {
    alert("请先发起对战");
    return;
  }
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws2 = new WebSocket(`${proto}://${location.host}/ws/${state.roomCode}/${opp.id}`);
  ws2.onopen = () => {
    ws2.send(JSON.stringify({ type: "ready" }));
    $("room-status").textContent = "同机演示：对手已准备。请点「我准备好了」。";
  };
  ws2.onerror = () => alert("演示加入失败");
}

/* ---------- quiz ---------- */
function startQuiz() {
  if (state.started) return;
  state.started = true;
  state.qIndex = 0;
  state.elapsedSec = 0;
  $("q-total").textContent = String(state.questions.length);
  $("op-progress").textContent = "0";
  $("my-score").textContent = "0";
  show("screen-quiz");
  renderQuestion();
  if (state.timerHandle) clearInterval(state.timerHandle);
  state.timerHandle = setInterval(() => {
    state.elapsedSec += 1;
    $("timer").textContent = formatTime(state.elapsedSec);
  }, 1000);
}

function formatTime(sec) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m > 0 ? `${m}:${String(s).padStart(2, "0")}` : String(s);
}

function renderQuestion() {
  const q = state.questions[state.qIndex];
  if (!q) return;
  state.qStartTs = Date.now();
  $("q-now").textContent = String(state.qIndex + 1);
  $("progress-fill").style.width = `${((state.qIndex) / state.questions.length) * 100}%`;
  $("quiz-word").textContent = q.word;
  $("quiz-phonetic").textContent = q.phonetic || "";
  $("feedback").className = "feedback hidden";
  $("feedback").textContent = "";
  $("btn-next").classList.add("hidden");
  $("btn-next").disabled = false;
  $("choice-box").innerHTML = "";
  $("input-box").classList.add("hidden");
  $("choice-box").classList.add("hidden");

  if (q.type === "choice") {
    $("choice-box").classList.remove("hidden");
    (q.choices || []).forEach((c, idx) => {
      const b = document.createElement("button");
      b.className = "choice";
      b.textContent = c.text;
      b.onclick = () => submitChoice(idx, b);
      $("choice-box").appendChild(b);
    });
  } else {
    $("input-box").classList.remove("hidden");
    $("answer-input").value = "";
    $("answer-input").disabled = false;
    $("btn-submit-input").disabled = false;
    setTimeout(() => $("answer-input").focus(), 50);
  }
}

async function submitChoice(idx, btn) {
  const elapsed = Date.now() - state.qStartTs;
  const buttons = [...$("choice-box").children];
  buttons.forEach((b) => (b.disabled = true));
  try {
    const r = await api("/api/room/answer", {
      method: "POST",
      body: JSON.stringify({
        room_code: state.roomCode,
        user_id: state.meId,
        q_index: state.qIndex,
        choice_index: idx,
        elapsed_ms: elapsed,
      }),
    });
    applyFeedback(r, buttons, idx);
  } catch (e) {
    alert(e.message);
    buttons.forEach((b) => (b.disabled = false));
  }
}

async function submitInput() {
  const text = $("answer-input").value.trim();
  if (!text) { alert("请输入中文意思"); return; }
  const elapsed = Date.now() - state.qStartTs;
  $("btn-submit-input").disabled = true;
  $("answer-input").disabled = true;
  try {
    const r = await api("/api/room/answer", {
      method: "POST",
      body: JSON.stringify({
        room_code: state.roomCode,
        user_id: state.meId,
        q_index: state.qIndex,
        text,
        elapsed_ms: elapsed,
      }),
    });
    applyFeedback(r, null, null, text);
  } catch (e) {
    alert(e.message);
    $("btn-submit-input").disabled = false;
    $("answer-input").disabled = false;
  }
}

function applyFeedback(r, buttons, choiceIdx) {
  state.results.push({
    word: r.word,
    correct: r.correct,
    correct_definition: r.correct_definition,
    definitions: r.definitions,
    mode: r.mode,
    score: r.score,
  });
  if (r.correct) {
    state.myScore += 1;
    $("my-score").textContent = String(state.myScore);
  }
  sendWS({ type: "progress", answered: state.qIndex + 1 });

  const fb = $("feedback");
  fb.classList.remove("hidden", "ok", "bad");
  if (r.mode === "choice" && buttons) {
    buttons.forEach((b, i) => {
      if (i === choiceIdx) b.classList.add(r.correct ? "ok" : "bad");
      if (Number.isInteger(r.correct_choice_index) && i === r.correct_choice_index) {
        b.classList.add("ok");
      }
    });
  }
  if (r.correct) {
    fb.classList.add("ok");
    fb.innerHTML = `✓ 正确！标准义：<strong>${escapeHtml(r.correct_definition)}</strong>`;
  } else {
    fb.classList.add("bad");
    const extra = r.matched ? `（最接近：${escapeHtml(r.matched)}）` : "";
    fb.innerHTML = `✗ 不对。标准义：<strong>${escapeHtml(r.correct_definition)}</strong>${extra}`;
  }
  $("btn-next").classList.remove("hidden");
  $("btn-next").textContent =
    state.qIndex + 1 >= state.questions.length ? "查看结果" : "下一题";
}

function nextQuestion() {
  if (state.qIndex + 1 >= state.questions.length) {
    $("btn-next").disabled = true;
    $("btn-next").textContent = "等待对方完成…";
    pollFinish();
    return;
  }
  state.qIndex += 1;
  renderQuestion();
}

async function pollFinish() {
  const tryOnce = async () => {
    try {
      const st = await api(`/api/room/${state.roomCode}/state`);
      if (st.finished && st.result) {
        showResult(st.result);
        return true;
      }
      const prog = st.progress || {};
      const other = Object.entries(prog).find(([k]) => Number(k) !== state.meId);
      if (other) $("op-progress").textContent = String(other[1]);
    } catch {}
    return false;
  };
  if (await tryOnce()) return;
  const t = setInterval(async () => {
    if (await tryOnce()) clearInterval(t);
  }, 1000);
}

function showResult(result) {
  if (state.finished) return;
  state.finished = true;
  if (state.timerHandle) clearInterval(state.timerHandle);
  const meIsA = result.user_a === state.meId;
  const my = meIsA ? result.score_a : result.score_b;
  const op = meIsA ? result.score_b : result.score_a;
  const myTime = meIsA ? result.time_a_ms : result.time_b_ms;
  const opTime = meIsA ? result.time_b_ms : result.time_a_ms;
  $("final-me").textContent = String(my);
  $("final-op").textContent = String(op);
  const total = state.questions.length;
  $("final-time").textContent =
    `用时 我 ${Math.round(myTime / 1000)}s · 对方 ${Math.round(opTime / 1000)}s · 共 ${total} 题`;
  if (result.winner == null) {
    $("result-sub").textContent = "平局";
  } else if (result.winner === state.meId) {
    $("result-sub").textContent = "你赢了";
  } else {
    $("result-sub").textContent = "对方获胜";
  }

  const wrong = state.results.filter((r) => !r.correct);
  const box = $("wrong-list");
  if (!wrong.length) {
    box.innerHTML = `<div class="hint">全对，很稳。</div>`;
  } else {
    box.innerHTML = wrong.map((r) => `
      <div class="wrong-item">
        <div class="w">${escapeHtml(r.word)}</div>
        <div class="d">${escapeHtml((r.definitions || []).join("；") || r.correct_definition)}</div>
        <span class="tag">需复习</span>
      </div>
    `).join("");
  }
  show("screen-result");
}

function backHome() {
  if (state.ws) { try { state.ws.close(); } catch {} state.ws = null; }
  if (state.timerHandle) clearInterval(state.timerHandle);
  state.started = false;
  state.finished = false;
  state.roomCode = "";
  show("screen-profile");
  loadUsers();
}

/* ---------- boot / URL join ---------- */
async function tryUrlJoin() {
  const params = new URLSearchParams(location.search);
  const code = params.get("join");
  if (!code) return false;
  if (!state.meId) {
    // wait until user picks identity
    state.pendingInvite = { room_code: code.toUpperCase() };
    const card = $("invite-card");
    $("invite-text").textContent = "收到对战链接，请先选择「我是谁」再加入";
    card.classList.remove("hidden");
    return false;
  }
  try {
    await joinRoom(code.toUpperCase());
    history.replaceState({}, "", location.pathname);
    return true;
  } catch {
    return false;
  }
}

/* ---------- events ---------- */
function bind() {
  $("btn-register").onclick = async () => {
    const name = $("new-name").value.trim().toLowerCase();
    if (!name) { alert("请输入用户名"); return; }
    try {
      const data = await api("/api/users/register", {
        method: "POST",
        body: JSON.stringify({ name, display_name: $("new-display").value.trim() || name }),
      });
      state.meId = data.user.id;
      localStorage.setItem("meId", String(data.user.id));
      $("new-name").value = "";
      $("new-display").value = "";
      await loadUsers();
      await tryUrlJoin();
    } catch (e) {
      alert(e.message);
    }
  };
  $("btn-save-cookie").onclick = saveCookie;
  $("btn-sb-login").onclick = shanbayLogin;
  $("btn-resync").onclick = resync;
  $("btn-resync2").onclick = resync;
  document.querySelectorAll("#seg-shanbay button").forEach((b) => {
    b.onclick = () => {
      document.querySelectorAll("#seg-shanbay button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      const mode = b.dataset.v;
      $("shanbay-password").classList.toggle("hidden", mode !== "password");
      $("shanbay-cookie").classList.toggle("hidden", mode !== "cookie");
    };
  });
  $("btn-create").onclick = createRoom;
  $("btn-ready").onclick = markReady;
  $("btn-join-invite").onclick = joinInvite;
  $("btn-copy-link").onclick = copyInvite;
  $("btn-join-demo-home").onclick = () => {
    if (!state.roomCode) {
      alert("请先发起对战");
      return;
    }
    show("screen-room");
    joinDemoOpponent();
  };
  $("btn-next").onclick = nextQuestion;
  $("btn-submit-input").onclick = submitInput;
  $("answer-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") submitInput();
  });
  $("btn-back").onclick = backHome;

  $("word-count").oninput = (e) => {
    state.wordCount = Number(e.target.value);
    $("wc-label").textContent = String(state.wordCount);
  };
  $("opponent-select").onchange = (e) => {
    state.opponentId = Number(e.target.value);
  };

  document.querySelectorAll("#seg-answer button").forEach((b) => {
    b.onclick = () => {
      document.querySelectorAll("#seg-answer button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      state.answerMode = b.dataset.v;
    };
  });
  document.querySelectorAll("#seg-select button").forEach((b) => {
    b.onclick = () => {
      document.querySelectorAll("#seg-select button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      state.selectMode = b.dataset.v;
    };
  });
}

bind();
loadUsers()
  .then(() => tryUrlJoin())
  .catch((e) => {
    $("profile-hint").textContent = `加载失败：${e.message}`;
  });

state.pendingTimer = setInterval(() => {
  if (!state.started && !state.finished) checkPending();
}, 4000);
