const state = {
  gameId: null,
  viewerState: null,
  legalActions: [],
  events: [],
  status: "not_started",
  busy: false,
  error: null,
  pollTimer: null,
};

const ids = [
  "resetBtn",
  "startBtn",
  "startScreen",
  "battleBoard",
  "statusTitle",
  "statusMessage",
  "phaseText",
  "latestEvent",
  "errorBox",
  "actionsPanel",
  "p1Meta",
  "p2Meta",
  "p1Base",
  "p2Base",
  "p1Resources",
  "p2Resources",
  "p1Counts",
  "p2Counts",
  "p1Slots",
  "p2Slots",
  "p1Hand",
];

const el = Object.fromEntries(ids.map((id) => [id, document.getElementById(id)]));

const cardAliases = {
  "EX-BASE": "/st01/EXB-001.png",
  "EX-RESOURCE": "/st01/EXR-001.png",
};

const actionOrder = [
  ["choice", "選擇"],
  ["attack", "攻擊"],
  ["deploy", "部署"],
  ["deploy_base", "部署基地"],
  ["pair", "配對"],
  ["use", "使用"],
  ["block", "阻擋"],
  ["ability", "能力"],
  ["pass", "讓過"],
  ["other", "其他"],
];

function imageFor(cardId) {
  if (!cardId) return null;
  if (cardAliases[cardId]) return cardAliases[cardId];
  const normalized = String(cardId).replace(/^\/+/, "");
  if (normalized.endsWith(".png")) return `/${normalized}`;
  return `/${normalized}.png`;
}

function visibleCount(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) ? Math.max(0, number) : 0;
}

function cardBack() {
  const card = document.createElement("div");
  card.className = "battle-card-back";
  return card;
}

function imageCard(cardId, className = "battle-card-img") {
  const src = imageFor(cardId);
  if (!src) return cardBack();
  const img = document.createElement("img");
  img.className = className;
  img.src = src;
  img.alt = cardId;
  img.loading = "lazy";
  img.onerror = () => {
    const fallback = cardBack();
    fallback.title = cardId;
    img.replaceWith(fallback);
  };
  return img;
}

async function postJson(url, body = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return response.json();
}

async function fetchJson(url) {
  const response = await fetch(url);
  return response.json();
}

function applyPayload(payload) {
  state.gameId = payload.game_id || null;
  state.viewerState = payload.viewer_state || null;
  state.legalActions = Array.isArray(payload.legal_actions) ? payload.legal_actions : [];
  state.events = Array.isArray(payload.events) ? payload.events : [];
  state.status = payload.status || "not_started";
  state.error = payload.error || null;
  state.busy = false;
  render(payload.message || "");
  updatePolling();
}

async function startBattle() {
  state.busy = true;
  render("建立對局中...");
  applyPayload(await postJson("/api/battle/start"));
}

async function resetBattle() {
  stopPolling();
  state.busy = true;
  render("重置中...");
  applyPayload(await postJson("/api/battle/reset"));
}

async function refreshBattle() {
  if (state.status !== "waiting_ai") return;
  applyPayload(await fetchJson("/api/battle/state"));
}

async function submitCommand(command) {
  if (state.busy || state.status !== "waiting_human") return;
  state.busy = true;
  render("執行操作中...");
  applyPayload(await postJson("/api/battle/command", { command }));
}

function updatePolling() {
  if (state.status === "waiting_ai") {
    if (!state.pollTimer) {
      state.pollTimer = window.setInterval(refreshBattle, 1500);
    }
    return;
  }
  stopPolling();
}

function stopPolling() {
  if (state.pollTimer) {
    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

function render(fallbackMessage = "") {
  const hasGame = Boolean(state.viewerState);
  el.startScreen.hidden = hasGame && state.status !== "not_started";
  el.battleBoard.hidden = !hasGame;
  el.resetBtn.disabled = state.busy;

  renderStatus(fallbackMessage);
  renderError();
  if (hasGame) {
    renderBoard();
  }
  renderActions();
}

function renderStatus(fallbackMessage) {
  const viewer = state.viewerState || {};
  const titleByStatus = {
    not_started: "準備開始",
    waiting_human: "輪到你行動",
    waiting_ai: "等待對手",
    game_over: "對局結束",
    error: "發生錯誤",
  };
  el.statusTitle.textContent = titleByStatus[state.status] || "對戰中";
  el.statusMessage.textContent = state.error || fallbackMessage || statusMessage();
  if (viewer.turn !== undefined) {
    el.phaseText.textContent = `回合 ${viewer.turn ?? "-"} | ${viewer.phase || "-"} / ${viewer.step || "無"} | 優先權 ${viewer.priority_player || "無"}`;
  } else {
    el.phaseText.textContent = "-";
  }
  const latest = state.events[state.events.length - 1];
  el.latestEvent.textContent = latest?.message || "-";
}

function statusMessage() {
  if (state.status === "waiting_ai") return "對手思考中...";
  if (state.status === "waiting_human") return "請選擇一個合法操作。";
  if (state.status === "game_over") return `勝者：${state.viewerState?.winner || "-"}`;
  return "點擊開始對戰。";
}

function renderError() {
  el.errorBox.hidden = !state.error;
  el.errorBox.textContent = state.error || "";
}

function playerBlock(playerId) {
  return state.viewerState?.players?.[playerId] || {};
}

function renderBoard() {
  renderPlayer("p2", playerBlock("P2"), false);
  renderPlayer("p1", playerBlock("P1"), true);
}

function renderPlayer(prefix, player, isSelf) {
  const handCount = visibleCount(player.hand_count);
  const deckCount = visibleCount(player.deck_count);
  const shieldCount = visibleCount(player.shield_count);
  const trashCount = visibleCount(player.trash?.length);
  const resourceCount = totalResources(player.resources || {});
  document.getElementById(`${prefix}Meta`).textContent = `手牌 ${handCount} | 牌庫 ${deckCount}`;
  document.getElementById(`${prefix}Counts`).textContent = `盾牌 ${shieldCount} | 廢棄 ${trashCount}`;
  renderBase(`${prefix}Base`, player.base);
  renderResources(`${prefix}Resources`, player.resources || {});
  renderSlots(`${prefix}Slots`, player.battle_area || [], isSelf);
  if (isSelf) renderHand(player.hand || []);
  if (!isSelf) renderOpponentHand(handCount);
  document.getElementById(`${prefix}Resources`).dataset.total = String(resourceCount);
}

function totalResources(resources) {
  return visibleCount(resources.active) + visibleCount(resources.rested) + visibleCount(resources.ex);
}

function renderBase(containerId, base) {
  const container = document.getElementById(containerId);
  container.replaceChildren();
  if (!base?.present || !base.card_id) {
    const empty = document.createElement("span");
    empty.className = "battle-empty-text";
    empty.textContent = "基地：無";
    container.appendChild(empty);
    return;
  }
  container.appendChild(imageCard(base.card_id, "battle-base-img"));
  const stats = document.createElement("strong");
  stats.textContent = `基地 ${base.card_id} | AP|HP ${base.ap ?? 0}|${base.remaining_hp ?? 0}`;
  container.appendChild(stats);
}

function renderResources(containerId, resources) {
  const container = document.getElementById(containerId);
  container.replaceChildren();
  const pips = [
    ...Array(visibleCount(resources.active)).fill("active"),
    ...Array(visibleCount(resources.rested)).fill("rested"),
    ...Array(visibleCount(resources.ex)).fill("ex"),
  ];
  const label = document.createElement("span");
  label.textContent = `資源 ${pips.length}/10`;
  container.appendChild(label);
  const row = document.createElement("div");
  row.className = "battle-pips";
  for (const kind of pips.slice(0, 10)) {
    const pip = document.createElement("span");
    pip.className = `battle-pip battle-pip-${kind}`;
    pip.textContent = kind === "ex" ? "EX" : "";
    row.appendChild(pip);
  }
  container.appendChild(row);
}

function renderSlots(containerId, slots, isSelf) {
  const container = document.getElementById(containerId);
  container.replaceChildren();
  for (let i = 0; i < 6; i += 1) {
    const data = slots.find((slot) => Number(slot.slot) === i) || { slot: i, empty: true };
    const slot = document.createElement("div");
    slot.className = `battle-slot ${data.empty || !data.unit_id ? "battle-slot-empty" : "battle-slot-filled"} ${data.status === "rested" ? "battle-slot-rested" : ""}`;
    if (data.unit_id) {
      slot.appendChild(imageCard(data.unit_id, "battle-slot-img"));
      const stats = document.createElement("span");
      stats.className = "battle-slot-stats";
      stats.textContent = `${data.ap ?? 0}/${data.remaining_hp ?? 0}`;
      slot.appendChild(stats);
      if (data.pilot_id) {
        const pilot = document.createElement("span");
        pilot.className = "battle-pilot";
        pilot.textContent = data.is_link ? "Link" : "Pilot";
        slot.appendChild(pilot);
      }
    }
    const number = document.createElement("span");
    number.className = "battle-slot-number";
    number.textContent = String(i + 1);
    slot.appendChild(number);
    container.appendChild(slot);
  }
}

function renderHand(cards) {
  el.p1Hand.replaceChildren();
  for (const cardId of cards.slice(0, 10)) {
    const wrap = document.createElement("button");
    wrap.className = "battle-hand-card";
    wrap.type = "button";
    wrap.title = cardId;
    wrap.setAttribute("aria-label", `查看手牌 ${cardId} 的可用操作`);
    wrap.appendChild(imageCard(cardId));
    wrap.addEventListener("click", () => scrollToCardActions(cardId));
    el.p1Hand.appendChild(wrap);
  }
}

function renderOpponentHand(count) {
  const meta = document.createElement("span");
  meta.className = "battle-opponent-hand";
  meta.textContent = `對手手牌 ${count} 張`;
  el.p2Counts.appendChild(document.createTextNode(" | "));
  el.p2Counts.appendChild(meta);
}

function scrollToCardActions(cardId) {
  const button = el.actionsPanel.querySelector(`[data-card-id="${CSS.escape(cardId)}"]`);
  button?.scrollIntoView({ behavior: "smooth", block: "center" });
}

function renderActions() {
  el.actionsPanel.replaceChildren();
  const showPanel = state.viewerState && state.status !== "not_started";
  el.actionsPanel.hidden = !showPanel;
  if (!showPanel) return;

  if (state.status === "waiting_ai") {
    const waiting = document.createElement("div");
    waiting.className = "battle-waiting";
    waiting.innerHTML = `<span class="battle-spinner"></span><strong>對手思考中...</strong>`;
    el.actionsPanel.appendChild(waiting);
    return;
  }

  if (state.status === "game_over") {
    const done = document.createElement("button");
    done.className = "battle-primary";
    done.type = "button";
    done.textContent = "再來一局";
    done.addEventListener("click", startBattle);
    el.actionsPanel.appendChild(done);
    return;
  }

  if (state.status === "error") {
    const retry = document.createElement("button");
    retry.className = "battle-primary";
    retry.type = "button";
    retry.textContent = "重新開始";
    retry.addEventListener("click", startBattle);
    el.actionsPanel.appendChild(retry);
    return;
  }

  if (!state.legalActions.length) {
    const empty = document.createElement("p");
    empty.className = "battle-empty-text";
    empty.textContent = "目前沒有可用操作。";
    el.actionsPanel.appendChild(empty);
    return;
  }

  const grouped = groupActions(state.legalActions);
  for (const [kind, title] of actionOrder) {
    const actions = grouped.get(kind) || [];
    if (!actions.length) continue;
    const details = document.createElement("details");
    details.className = "battle-action-group";
    details.open = kind === "choice" || kind === "attack" || kind === "deploy" || kind === "pass";
    const summary = document.createElement("summary");
    summary.textContent = title;
    details.appendChild(summary);
    const list = document.createElement("div");
    list.className = "battle-action-list";
    for (const action of actions) {
      list.appendChild(actionButton(action));
    }
    details.appendChild(list);
    el.actionsPanel.appendChild(details);
  }
}

function groupActions(actions) {
  const grouped = new Map();
  for (const action of actions) {
    const key = action.kind || "other";
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(action);
  }
  return grouped;
}

function actionButton(action) {
  const button = document.createElement("button");
  button.className = `battle-action battle-action-${action.kind || "other"}`;
  button.type = "button";
  button.disabled = state.busy;
  button.dataset.command = action.command;
  if (action.card_id) button.dataset.cardId = action.card_id;
  if (action.card_id) {
    button.appendChild(imageCard(action.card_id, "battle-action-card"));
  }
  const label = document.createElement("span");
  label.textContent = action.label || action.command;
  button.appendChild(label);
  button.addEventListener("click", () => submitCommand(action.command));
  return button;
}

el.startBtn.addEventListener("click", startBattle);
el.resetBtn.addEventListener("click", startBattle);

render();
