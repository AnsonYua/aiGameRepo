// Battle V3 — redesigned action selection UX.
// Core idea: tapping a card / unit / base only SELECTS it and opens a bottom
// sheet of actions. Nothing commits on the first tap. When an action needs a
// board target (deploy / pair / attack), the sheet collapses to a thin prompt
// bar so it never covers the slots you must tap. A picked target shows a
// confirm bar before submitting. A persistent "可操作 (N)" button lists every
// legal action for discoverability.

const state = {
  gameId: null,
  viewerState: null,
  legalActions: [],
  events: [],
  status: "not_started",
  busy: false,
  error: null,
  pollTimer: null,
  revealTimer: null,
  openingReveal: null,
  // selected: { type: 'card'|'unit'|'base'|'list', cardId?, slot?, phase: 'pickAction'|'pickTarget', action? }
  selected: null,
  // confirm: { command, label } — target picked, awaiting confirm
  confirm: null,
};

const cardAliases = {
  "EX-BASE": "/st01/EXB-001.png",
  "EX-RESOURCE": "/st01/EXR-001.png",
};

const prewarmAssets = [
  "/assets/card-back-opponent.webp",
  "/assets/ui-ornaments.webp",
  "/assets/coin-p1-token.webp",
  "/assets/coin-p2-token.webp",
];

const el = {
  app: document.querySelector(".app"),
  dialog: null,
  startBtn: document.getElementById("startBtn"),
  startScreen: document.getElementById("startScreen"),
  statusMessage: document.getElementById("statusMessage"),
  combatMessage: document.getElementById("combatMessage"),
  thinkingLabel: document.getElementById("opponentThinkingLabel"),
  sheet: document.getElementById("sheet"),
  sheetBackdrop: document.getElementById("sheetBackdrop"),
  coinFlipOverlay: document.getElementById("coinFlipOverlay"),
  coinFlipToken: document.getElementById("coinFlipToken"),
  coinFlipTitle: document.getElementById("coinFlipTitle"),
  coinFlipSub: document.getElementById("coinFlipSub"),
  errorBox: document.getElementById("errorBox"),
  endTurnBtn: document.getElementById("endTurnBtn"),
  actionsListBtn: document.getElementById("actionsListBtn"),
  actionsCount: document.getElementById("actionsCount"),
  actionsFooterCount: document.getElementById("actionsFooterCount"),
};

function prewarmImages() {
  for (const src of prewarmAssets) {
    const img = new Image();
    img.decoding = "async";
    img.src = src;
  }
}

// ---------------------------------------------------------------------------
// small dom helpers (carried over from V2)
// ---------------------------------------------------------------------------

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

function setText(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = value;
}

function cardBack(className = "card-back") {
  const card = document.createElement("div");
  card.className = className;
  return card;
}

function imageCard(cardId, className = "card-img") {
  const src = imageFor(cardId);
  if (!src) return cardBack(className);
  const img = document.createElement("img");
  img.className = className;
  img.src = src;
  img.alt = cardId;
  img.loading = "lazy";
  img.onerror = () => {
    const fallback = cardBack(className);
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

function gameApiUrl(path = "") {
  if (!state.gameId) throw new Error("missing game id");
  const suffix = path ? `/${path.replace(/^\/+/, "")}` : "";
  return `/api/games/${encodeURIComponent(state.gameId)}${suffix}`;
}

function setGameUrl(gameId) {
  const url = new URL(window.location.href);
  if (gameId) url.searchParams.set("game_id", gameId);
  else url.searchParams.delete("game_id");
  window.history.replaceState({}, "", url);
}

// card id -> detail (cached for the session). Fetched lazily when a card's
// action sheet opens, so the player can read what a card does before acting.
const cardDetailCache = new Map();
const pendingCardDetail = new Map();

async function fetchCardDetail(cardId) {
  if (!cardId || !state.gameId) return null;
  if (cardDetailCache.has(cardId)) return cardDetailCache.get(cardId);
  if (pendingCardDetail.has(cardId)) return pendingCardDetail.get(cardId);
  const promise = (async () => {
    try {
      const data = await fetchJson(`${gameApiUrl("card")}?card_id=${encodeURIComponent(cardId)}`);
      const detail = data && data.id ? data : null;
      cardDetailCache.set(cardId, detail);
      return detail;
    } catch (err) {
      cardDetailCache.set(cardId, null);
      return null;
    } finally {
      pendingCardDetail.delete(cardId);
    }
  })();
  pendingCardDetail.set(cardId, promise);
  return promise;
}

function renderDetailInto(container, detail) {
  if (!detail) return;
  const block = document.createElement("div");
  block.className = "b3-card-detail";

  if (detail.traits?.length) {
    const t = document.createElement("div");
    t.className = "b3-detail-traits";
    t.textContent = detail.traits.join(" / ");
    block.appendChild(t);
  }

  if (detail.descriptions?.length) {
    const desc = document.createElement("div");
    desc.className = "b3-detail-desc";
    for (const line of detail.descriptions) {
      const p = document.createElement("p");
      p.textContent = line;
      desc.appendChild(p);
    }
    block.appendChild(desc);
  }
  if (block.childElementCount) container.appendChild(block);
}

function detailSummary(detail, fallback = "") {
  if (!detail) return fallback;
  const chips = [];
  if (detail.cardType) chips.push(typeLabel(detail.cardType));
  if (detail.color) chips.push(detail.color);
  if (detail.cost != null) chips.push(`耗 ${detail.cost}`);
  if (detail.ap || detail.hp) chips.push(`AP${detail.ap ?? 0}/HP${detail.hp ?? 0}`);
  if (detail.level) chips.push(`LV${detail.level}`);
  if (detail.id) chips.push(detail.id);
  return chips.join(" · ") || fallback;
}

function typeLabel(cardType) {
  return { unit: "單位", pilot: "駕駛", command: "指令", base: "基地", resource: "資源" }[cardType] || cardType;
}

// If the open sheet is for a card whose detail just arrived, re-render so the
// detail block appears without the player closing/reopening the sheet.
function maybeRefreshDetail(cardId) {
  const sel = state.selected;
  if (!sel || sel.phase !== "pickAction") return;
  if (sel.type === "card" && sel.cardId !== cardId) return;
  if (sel.type === "unit") {
    const unit = (state.viewerState?.players?.P1?.battle_area || []).find((s) => Number(s.slot) === sel.slot);
    if (unit?.unit_id !== cardId) return;
  }
  render();
}

// ---------------------------------------------------------------------------
// api flow
// ---------------------------------------------------------------------------

// snapshot of the previous render, used to diff "what changed" and drive
// animations. Animations fire once per change, guarded by event seq so a
// re-poll never replays them.
const prev = { players: null, status: null, handSet: null };
let lastAnimatedSeq = 0;
// cardId -> count of newly-drawn copies this render → get a deal-in class.
// A count map (not a Set) so drawing a second copy of a card already in hand
// still animates.
let pendingDealIn = new Map();

function countMap(arr) {
  const m = new Map();
  for (const x of arr) m.set(x, (m.get(x) || 0) + 1);
  return m;
}

function applyPayload(payload, options = {}) {
  const prevStatus = state.status;
  const prevPlayers = state.viewerState?.players || null;
  const prevHand = prevPlayers?.P1?.hand ? countMap(prevPlayers.P1.hand) : null;

  state.gameId = payload.game_id || null;
  state.viewerState = payload.viewer_state || null;
  state.legalActions = Array.isArray(payload.legal_actions) ? payload.legal_actions : [];
  state.events = Array.isArray(payload.events) ? payload.events : [];
  state.status = payload.status || "not_started";
  state.error = payload.error || null;
  state.busy = false;
  state.openingReveal = options.openingReveal || state.openingReveal;
  // a fresh decision boundary invalidates any in-progress selection
  state.selected = null;
  state.confirm = null;

  const diff = diffBoard(prevPlayers, state.viewerState?.players || null, prevHand);
  // hand deal-in must be known during render; everything else animates after.
  pendingDealIn = diff ? new Map(diff.handGained) : new Map();

  render(payload.message || "");
  updatePolling();

  if (diff) animateChanges(diff, prevStatus, state.status);
}

// Compare two player snapshots. Returns null if there's no prior snapshot to
// diff against (first render / reset).
function diffBoard(prevPlayers, currPlayers, prevHand) {
  if (!prevPlayers || !currPlayers) return null;
  const out = { unitDamaged: [], unitEntered: [], unitLeft: [], shieldLost: [], handGained: [] };
  // viewer_state.players uses uppercase keys P1/P2; the DOM data-b3-player
  // attribute uses lowercase p1/p2 (from renderPlayer), so emit lowercase.
  for (const [dom, key] of [["p1", "P1"], ["p2", "P2"]]) {
    const prevP = prevPlayers[key] || {};
    const currP = currPlayers[key] || {};

    const prevSlots = indexSlots(prevP.battle_area || []);
    const currSlots = indexSlots(currP.battle_area || []);
    for (const slot of new Set([...Object.keys(prevSlots), ...Object.keys(currSlots)])) {
      const a = prevSlots[slot];
      const b = currSlots[slot];
      const aId = a?.unit_id || null;
      const bId = b?.unit_id || null;
      if (aId && bId && aId === bId) {
        const aHp = visibleCount(a.remaining_hp ?? a.hp);
        const bHp = visibleCount(b.remaining_hp ?? b.hp);
        if (bHp < aHp) out.unitDamaged.push({ player: dom, slot: Number(slot), delta: aHp - bHp });
      } else if (bId && !aId) {
        out.unitEntered.push({ player: dom, slot: Number(slot) });
      } else if (aId && !bId) {
        out.unitLeft.push({ player: dom, slot: Number(slot) });
      }
    }

    const prevShields = visibleCount(prevP.shield_count ?? prevP.shields);
    const currShields = visibleCount(currP.shield_count ?? currP.shields);
    if (currShields < prevShields) out.shieldLost.push({ player: dom, delta: prevShields - currShields });
  }

  // own hand deal-in: only animate cards that are genuinely new (drawn), not
  // the whole hand re-rendering. Count-based so a second copy of a card
  // already in hand still counts as newly drawn.
  const ownHand = currPlayers.P1?.hand;
  out.handGained = new Map();
  if (prevHand && Array.isArray(ownHand)) {
    const currCounts = countMap(ownHand);
    for (const [cardId, curr] of currCounts) {
      const prevCount = prevHand.get(cardId) || 0;
      if (curr > prevCount) out.handGained.set(cardId, curr - prevCount);
    }
  }
  return out;
}

// Given the current hand (array, may contain duplicate ids) and a cardId->count
// map of newly-drawn copies, return a per-index boolean array marking which
// buttons should play the deal-in animation. New copies are assumed to be the
// trailing ones (draw appends to hand), so we consume the count from the right.
function dealInFlags(handCards, dealCounts) {
  const flags = new Array(handCards.length).fill(false);
  if (!dealCounts || !dealCounts.size) return flags;
  const remaining = new Map(dealCounts);
  for (let i = handCards.length - 1; i >= 0; i -= 1) {
    const cardId = handCards[i];
    const left = remaining.get(cardId) || 0;
    if (left > 0) {
      flags[i] = true;
      remaining.set(cardId, left - 1);
    }
  }
  return flags;
}

function indexSlots(slots) {
  const map = {};
  for (const slot of slots) map[Number(slot.slot)] = slot;
  return map;
}

// ---------------------------------------------------------------------------
// animations (driven by diffBoard + status flip)
// ---------------------------------------------------------------------------

function animateChanges(diff, prevStatus, currStatus) {
  for (const hit of diff.unitDamaged) animateDamage(hit.player, hit.slot, hit.delta);
  for (const enter of diff.unitEntered) animateUnitEnter(enter.player, enter.slot);
  for (const left of diff.unitLeft) animateUnitLeave(left.player, left.slot);
  for (const shield of diff.shieldLost) animateShieldLost(shield.player, shield.delta);
  const turn = statusFlippedToTurn(prevStatus, currStatus);
  if (turn) showTurnBanner(turn);
}

function statusFlippedToTurn(prevStatus, currStatus) {
  const viewer = state.viewerState || {};
  if (viewer.phase === "pre-game" || viewer.decision_type === "pending_choice") return null;
  if (currStatus === "waiting_human" && prevStatus !== "waiting_human") return "human";
  if (currStatus === "waiting_ai" && prevStatus !== "waiting_ai") return "ai";
  return null;
}

function slotElement(player, slot) {
  return document.querySelector(
    `button.slot-button[data-b3-player="${player}"][data-b3-slot="${slot}"]`,
  );
}

function animateDamage(player, slot, delta) {
  const target = slotElement(player, slot);
  if (!target || !el.app) return;
  target.classList.remove("b3-hit");
  // force reflow so the class re-triggers the keyframes if hit again
  void target.offsetWidth;
  target.classList.add("b3-hit");
  window.setTimeout(() => target.classList.remove("b3-hit"), 500);

  // floating damage number, rendered at app level so no slot overflow
  // can clip it as it rises.
  const rect = target.getBoundingClientRect();
  const appRect = el.app.getBoundingClientRect();
  const floater = document.createElement("span");
  floater.className = "b3-float-dmg";
  floater.textContent = `-${delta}`;
  floater.style.left = `${rect.left - appRect.left + rect.width / 2}px`;
  floater.style.top = `${rect.top - appRect.top + rect.height * 0.3}px`;
  el.app.appendChild(floater);
  window.setTimeout(() => floater.remove(), 900);
}

function animateUnitEnter(player, slot) {
  const el = slotElement(player, slot);
  if (!el) return;
  el.classList.add("b3-enter");
  window.setTimeout(() => el.classList.remove("b3-enter"), 450);
}

function animateUnitLeave(player, slot) {
  // unit already gone from DOM; nothing to animate on the element, but a
  // brief puff on the empty slot communicates the loss.
  const el = slotElement(player, slot);
  if (!el) return;
  el.classList.add("b3-leave");
  window.setTimeout(() => el.classList.remove("b3-leave"), 450);
}

function animateShieldLost(player, delta) {
  const container = document.getElementById(`${player}Shields`);
  if (!container) return;
  container.classList.remove("b3-shield-break");
  void container.offsetWidth;
  container.classList.add("b3-shield-break");
  window.setTimeout(() => container.classList.remove("b3-shield-break"), 600);
}

let turnBannerTimer = null;
function showTurnBanner(who) {
  let banner = document.getElementById("turnBanner");
  if (!banner) {
    banner = document.createElement("div");
    banner.id = "turnBanner";
    banner.className = "b3-turn-banner";
    el.app.appendChild(banner);
  }
  banner.classList.remove("show", "human", "ai");
  void banner.offsetWidth;
  banner.textContent = who === "human" ? "你的回合" : "對手回合";
  banner.classList.add(who, "show");
  if (turnBannerTimer) window.clearTimeout(turnBannerTimer);
  turnBannerTimer = window.setTimeout(() => banner.classList.remove("show"), 1100);
}

async function startBattle() {
  state.busy = true;
  state.openingReveal = null;
  clearOpeningRevealTimer();
  cardDetailCache.clear();
  pendingCardDetail.clear();
  render("建立對局中...");
  const payload = await postJson("/api/games");
  if (payload.game_id) setGameUrl(payload.game_id);
  const chooser = openingChoicePlayer(payload);
  applyPayload(payload, chooser ? { openingReveal: buildOpeningReveal(chooser) } : {});
  if (chooser) scheduleOpeningRevealDone();
}

async function refreshBattle() {
  if (state.status !== "waiting_ai" || !state.gameId) return;
  applyPayload(await fetchJson(gameApiUrl("state")));
}

async function submitCommand(command) {
  if (state.busy || state.status !== "waiting_human" || !state.gameId) return;
  state.busy = true;
  state.selected = null;
  state.confirm = null;
  render("執行操作中...");
  applyPayload(await postJson(gameApiUrl("command"), { command }));
}

async function resumeBattle(gameId) {
  state.gameId = gameId;
  state.busy = true;
  cardDetailCache.clear();
  pendingCardDetail.clear();
  render("載入對局中...");
  const payload = await fetchJson(gameApiUrl("state"));
  applyPayload(payload);
  if (!payload.ok) setGameUrl(null);
}

function updatePolling() {
  if (state.status === "waiting_ai") {
    if (!state.pollTimer) state.pollTimer = window.setInterval(refreshBattle, 1500);
    return;
  }
  if (state.pollTimer) {
    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

// ---------------------------------------------------------------------------
// legal-action queries
// ---------------------------------------------------------------------------

function actionsForCard(cardId) {
  return state.legalActions.filter((action) => action.card_id === cardId);
}

function cardDeployActions(cardId) {
  return actionsForCard(cardId).filter((action) => action.kind === "deploy");
}

function cardPairActions(cardId) {
  return actionsForCard(cardId).filter((action) => action.kind === "pair");
}

function attacksFromSlot(slot) {
  return state.legalActions.filter(
    (action) => action.kind === "attack" && action.source_slot === slot,
  );
}

function blockAtSlot(slot) {
  return state.legalActions.find((action) => action.kind === "block" && action.slot === slot);
}

function passAction() {
  return state.legalActions.find((action) => action.kind === "pass");
}

function baseAbilityAction() {
  return state.legalActions.find((action) => action.kind === "ability");
}

function choiceActions() {
  return state.legalActions.filter((action) => action.kind === "choice");
}

function actionableCount() {
  // distinct "things you can tap": playable hand cards + own units that can act
  // + base ability + forced choices. Pass is reachable via End Turn.
  const cards = new Set();
  for (const action of state.legalActions) {
    if (action.card_id) cards.add(action.card_id);
  }
  const units = new Set();
  for (const action of state.legalActions) {
    if (action.kind === "attack") units.add(action.source_slot);
    if (action.kind === "block") units.add(action.slot);
  }
  const base = baseAbilityAction() ? 1 : 0;
  return cards.size + units.size + base + choiceActions().length;
}

// ---------------------------------------------------------------------------
// render
// ---------------------------------------------------------------------------

function render(fallbackMessage = "") {
  const hasGame = Boolean(state.viewerState);
  el.startScreen.hidden = hasGame && state.status !== "not_started";
  renderStatus(fallbackMessage);
  renderError();
  renderBoard();
  renderSheet();
  renderDialog();
  renderOpeningReveal();
  document.body.classList.toggle("picking-target", state.selected?.phase === "pickTarget");
}

function renderStatus(fallbackMessage) {
  const message = state.error || fallbackMessage || statusMessage();
  const combatMessage = latestEventMessage() || message;
  const opponentThinking = state.status === "waiting_ai";
  el.statusMessage.textContent = message;
  el.combatMessage.textContent = combatMessage;
  el.combatMessage.title = combatMessage;
  if (el.thinkingLabel) el.thinkingLabel.hidden = !opponentThinking;
  const waiting = state.status === "waiting_human";
  el.endTurnBtn.disabled = state.busy || !waiting || !passAction();
  el.actionsListBtn.disabled = state.busy || !waiting || actionableCount() === 0;
  const count = String(actionableCount());
  if (el.actionsCount) el.actionsCount.textContent = count;
  if (el.actionsFooterCount) el.actionsFooterCount.textContent = count;
}

function statusMessage() {
  if (state.status === "waiting_ai") return "對手思考中...";
  if (state.status === "waiting_human") {
    const pending = state.viewerState?.pending_choice || {};
    if (pending.visible && pending.message) return pending.message;
    if (actionableCount() > 0) return "點擊亮起的卡牌或單位選擇行動。";
    if (passAction()) return "目前沒有可用操作，可以讓過。";
    return "等待操作。";
  }
  if (state.status === "game_over") return `對局結束，勝者：${state.viewerState?.winner || "-"}`;
  return "準備開始";
}

function latestEventMessage() {
  return state.events[state.events.length - 1]?.message || "";
}

function renderError() {
  el.errorBox.hidden = !state.error;
  el.errorBox.textContent = state.error || "";
}

function renderBoard() {
  renderPlayer("p2", playerBlock("P2"), false);
  renderPlayer("p1", playerBlock("P1"), true);
}

function playerBlock(playerId) {
  return state.viewerState?.players?.[playerId] || {};
}

function renderPlayer(playerId, player, isSelf) {
  renderHand(playerId, player, isSelf);
  renderShields(playerId, player);
  renderResources(playerId, player);
  renderBase(playerId, player, isSelf);
  renderDecks(playerId, player);
  renderSlots(playerId, player.battle_area || [], isSelf);
}

function renderHand(playerId, player, isSelf) {
  const cards = Array.isArray(player.hand) ? player.hand : [];
  const count = isSelf ? cards.length : visibleCount(player.hand_count);
  setText(`${playerId}HandCount`, String(count));
  const container = document.getElementById(`${playerId}Hand`);
  const handCards = isSelf ? cards : [];
  const key = isSelf ? handCards.join("\u0001") : `indicators:${Math.min(count, 10)}`;

  if (container.dataset.b3HandKey === key && !pendingDealIn.size) {
    syncHandButtons(container, handCards, isSelf);
    return;
  }

  container.dataset.b3HandKey = key;
  container.replaceChildren();

  if (!isSelf) {
    for (let i = 0; i < Math.min(count, 10); i += 1) {
      const back = cardBack("card-back opponent-hand-card");
      back.setAttribute("aria-label", `對手手牌 ${i + 1}`);
      container.appendChild(back);
    }
    return;
  }

  // Deal-in flags per index: only the newly-drawn copies animate (count-based
  // so duplicate card ids are handled, not Set membership).
  const dealFlags = dealInFlags(handCards, pendingDealIn);
  let dealStagger = 0;
  for (let idx = 0; idx < handCards.length; idx += 1) {
    const cardId = handCards[idx];
    const button = document.createElement("button");
    button.className = "hand-card-button";
    button.type = "button";
    button.title = cardId;
    button.dataset.b3Card = cardId;
    syncHandButton(button, cardId);
    if (dealFlags[idx]) {
      button.classList.add("dealing");
      button.style.setProperty("--b3-deal-delay", `${dealStagger * 55}ms`);
      dealStagger += 1;
    }
    button.appendChild(imageCard(cardId));
    button.addEventListener("click", () => handleHandClick(cardId));
    container.appendChild(button);
  }
  // deal-in counts are consumed by this render
  pendingDealIn = new Map();
}

function syncHandButtons(container, handCards, isSelf) {
  if (!isSelf) return;
  const buttons = Array.from(container.querySelectorAll(".hand-card-button"));
  for (let idx = 0; idx < buttons.length; idx += 1) {
    syncHandButton(buttons[idx], handCards[idx]);
    buttons[idx].classList.remove("dealing");
    buttons[idx].style.removeProperty("--b3-deal-delay");
  }
}

function syncHandButton(button, cardId) {
  const playable = state.status === "waiting_human" && actionsForCard(cardId).length > 0;
  // Every own hand card is tappable to inspect it — even unplayable ones.
  // Only block taps while busy or when it's not the human's moment.
  button.disabled = state.busy || state.status !== "waiting_human";
  button.classList.toggle("selectable", playable);
  button.classList.toggle("dimmed", !playable);
  button.classList.toggle("selected", isActiveCard(cardId));
}

function renderShields(playerId, player) {
  const count = visibleCount(player.shield_count ?? player.shields);
  setText(`${playerId}ShieldCount`, String(count));
  const container = document.getElementById(`${playerId}Shields`);
  const key = String(Math.min(count, 6));
  if (container.dataset.b3ShieldKey === key) return;
  container.dataset.b3ShieldKey = key;
  container.replaceChildren();
  for (let i = 0; i < Math.min(count, 6); i += 1) {
    const shield = document.createElement("div");
    shield.className = "shield";
    container.appendChild(shield);
  }
}

function renderResources(playerId, player) {
  const resources = player.resources || {};
  const active = visibleCount(resources.active);
  const rested = visibleCount(resources.rested);
  const ex = visibleCount(resources.ex);
  const normal = active + rested;
  setText(`${playerId}ResourceText`, `${active} 可用 / ${rested} 休息`);
  setText(`${playerId}ExResourceText`, `${ex} 可用`);
  const container = document.getElementById(`${playerId}Resources`);
  const pips = [
    ...Array(active).fill("active"),
    ...Array(rested).fill("rested"),
    ...Array(Math.max(0, 10 - normal)).fill("empty"),
    "ex",
  ];
  const key = pips.join("|");
  if (container.dataset.b3ResourceKey === key) return;
  container.dataset.b3ResourceKey = key;
  container.replaceChildren();
  for (let idx = 0; idx < pips.length; idx += 1) {
    const kind = idx === 10 ? (ex ? "ex active" : "ex empty") : pips[idx];
    const pip = document.createElement("span");
    pip.className = `pip ${kind}`;
    pip.dataset.label = idx === 10 ? (ex ? `EX${ex}` : "EX") : kind === "active" ? "可" : kind === "rested" ? "橫" : "";
    container.appendChild(pip);
  }
}

function renderBase(playerId, player, isSelf) {
  const container = document.getElementById(`${playerId}Base`);
  container.classList.remove("selectable", "selectable-ability", "selected", "targetable");
  const ability = isSelf ? baseAbilityAction() : null;
  const canTarget = !isSelf && isPickingAttack() && attackOnBaseExists();
  if (isSelf) {
    if (ability && !isPickingTarget()) container.classList.add("selectable-ability");
    if (isSelectedBase()) container.classList.add("selected");
  } else if (canTarget) {
    container.classList.add("targetable");
  }
  container.disabled = isSelf ? !ability : !canTarget;
  container.onclick = isSelf
    ? () => ability && handleBaseClick()
    : () => handleOpponentBaseClick();

  const base = player.base || {};
  const baseCardId = base.card_id || "";
  const remaining = visibleCount(base.remaining_hp ?? (visibleCount(base.hp) - visibleCount(base.damage)));
  const key = base.present && baseCardId
    ? [baseCardId, base.ap ?? 0, remaining].join("|")
    : "none";
  if (container.dataset.b3BaseKey === key) return;
  container.dataset.b3BaseKey = key;
  container.replaceChildren();

  if (!base.present || !baseCardId) {
    const placeholder = document.createElement("div");
    placeholder.className = "base-placeholder";
    container.appendChild(placeholder);
    const empty = document.createElement("div");
    empty.className = "base-stats base-empty-stats";
    empty.textContent = "無基地";
    empty.dataset.mobileHp = "-";
    container.appendChild(empty);
    return;
  }

  container.appendChild(imageCard(baseCardId, "base-image"));
  const stats = document.createElement("div");
  stats.className = "base-stats";
  stats.setAttribute("aria-label", `AP ${base.ap ?? 0} HP ${remaining}`);
  stats.dataset.mobileHp = String(remaining);
  const ap = document.createElement("span");
  ap.className = "base-stat-value";
  ap.textContent = String(base.ap ?? 0);
  const divider = document.createElement("span");
  divider.className = "base-stat-divider";
  divider.textContent = "/";
  const hp = document.createElement("span");
  hp.className = "base-stat-value";
  hp.textContent = String(remaining);
  stats.append(ap, divider, hp);
  container.appendChild(stats);
}

function renderDecks(playerId, player) {
  const energy = document.getElementById(`${playerId}EnergyDeck`);
  const count = visibleCount(player.deck_count);
  energy.dataset.count = String(count);
  energy.textContent = String(count);
  const trash = document.getElementById(`${playerId}Trash`);
  const trashCount = visibleCount(player.trash?.length);
  trash.textContent = trashCount;
  trash.dataset.trashCount = String(trashCount);
}

function renderSlots(playerId, slots, isSelf) {
  const container = document.getElementById(`${playerId}Slots`);
  const normalized = [];
  for (let i = 0; i < 6; i += 1) {
    const data = slots.find((slot) => Number(slot.slot) === i) || { slot: i, empty: true };
    normalized.push(data);
  }
  const key = normalized.map(slotKey).join("||");
  if (container.dataset.b3SlotsKey === key) {
    syncSlots(container, normalized, isSelf);
    return;
  }
  container.dataset.b3SlotsKey = key;
  container.replaceChildren();
  for (let i = 0; i < 6; i += 1) {
    const data = normalized[i];
    const slot = document.createElement("button");
    slot.type = "button";
    slot.dataset.b3Player = playerId;
    slot.dataset.b3Slot = String(i);
    slot.className = `slot slot-button ${data.empty || !data.unit_id ? "empty" : "filled"} ${data.status === "rested" ? "rested" : ""}`;
    markSlotState(slot, i, isSelf, data);
    slot.onclick = () => handleSlotClick(i, isSelf, data);

    if (data.unit_id) {
      const cardWrap = document.createElement("div");
      cardWrap.className = "slot-card";
      cardWrap.appendChild(imageCard(data.unit_id, "card-img"));
      slot.appendChild(cardWrap);

      if (data.pilot_id) {
        const pilotCard = document.createElement("div");
        pilotCard.className = "pilot-card";
        pilotCard.appendChild(imageCard(data.pilot_id, "card-img"));
        slot.appendChild(pilotCard);
      }

      const tags = slotTags(data);
      if (tags.length) {
        const tagRow = document.createElement("div");
        tagRow.className = "slot-tags";
        for (const tag of tags.slice(0, 3)) {
          const item = document.createElement("span");
          item.textContent = tag;
          tagRow.appendChild(item);
        }
        slot.appendChild(tagRow);
      }

      const info = document.createElement("div");
      info.className = "slot-info";
      const apHp = document.createElement("span");
      apHp.className = "stat-pill";
      apHp.textContent = `${data.ap ?? 0}/${data.remaining_hp ?? 0}`;
      info.appendChild(apHp);
      slot.appendChild(info);
    }

    const number = document.createElement("span");
    number.className = "slot-number";
    number.textContent = String(i + 1);
    slot.appendChild(number);
    container.appendChild(slot);
  }
}

function slotTags(data) {
  const tags = [];
  if (Array.isArray(data.buffs)) tags.push(...data.buffs.map((buff) => String(buff).slice(0, 2).toUpperCase()));
  if (Array.isArray(data.status_icons)) tags.push(...data.status_icons.map((status) => String(status).slice(0, 2).toUpperCase()));
  if (data.status && data.status !== "active" && data.status !== "rested") {
    tags.push(String(data.status).slice(0, 2).toUpperCase());
  }
  return tags;
}

function slotKey(data) {
  if (data.empty || !data.unit_id) return `${data.slot}:empty`;
  return [
    data.slot,
    data.unit_id || "",
    data.pilot_id || "",
    data.status || "",
    (data.buffs || []).join(","),
    (data.status_icons || []).join(","),
    data.ap ?? 0,
    data.remaining_hp ?? 0,
  ].join("|");
}

function syncSlots(container, normalized, isSelf) {
  const slotEls = Array.from(container.querySelectorAll(".slot"));
  for (let i = 0; i < 6; i += 1) {
    const slot = slotEls[i];
    if (!slot) continue;
    const data = normalized[i];
    slot.className = `slot slot-button ${data.empty || !data.unit_id ? "empty" : "filled"} ${data.status === "rested" ? "rested" : ""}`;
    markSlotState(slot, i, isSelf, data);
    slot.onclick = () => handleSlotClick(i, isSelf, data);
  }
}

function markSlotState(slot, index, isSelf, data) {
  slot.disabled = state.busy || state.status !== "waiting_human";
  if (isSelf) {
    // target candidate while deploying / pairing a selected card
    if (isDeployPairTarget(index)) {
      slot.classList.add("targetable");
      return;
    }
    // keep the attacking unit lit while its target is being picked
    if (isAttackingSource(index)) {
      slot.classList.add("attacking");
      return;
    }
    if (isPickingTarget()) return; // own slots aren't attack targets
    // selected unit (action sheet open)
    if (isSelectedUnit(index)) slot.classList.add("selected");
    const canAttack = attacksFromSlot(index).length > 0;
    const canBlock = Boolean(blockAtSlot(index));
    if (canAttack) slot.classList.add("selectable-attack");
    if (canBlock) slot.classList.add("selectable-block");
    return;
  }
  // opponent slot: target candidate while attacking
  if (isAttackTarget(index)) slot.classList.add("targetable");
}

// ---------------------------------------------------------------------------
// selection predicates
// ---------------------------------------------------------------------------

function isSelectedCard(cardId) {
  return state.selected?.type === "card" && state.selected.cardId === cardId && state.selected.phase === "pickAction";
}
function isActiveCard(cardId) {
  // highlighted in both pickAction (sheet open) and pickTarget (deploying/pairing this card)
  return state.selected?.type === "card" && state.selected.cardId === cardId;
}
function isSelectedUnit(index) {
  return state.selected?.type === "unit" && state.selected.slot === index && state.selected.phase === "pickAction";
}
function isSelectedBase() {
  return state.selected?.type === "base" && state.selected.phase === "pickAction";
}
function isAttackingSource(index) {
  return state.selected?.type === "unit" && state.selected.slot === index && state.selected.phase === "pickTarget" && state.selected.action?.kind === "attack";
}
function isPickingTarget() {
  return state.selected?.phase === "pickTarget";
}
function isPickingAttack() {
  return isPickingTarget() && state.selected?.action?.kind === "attack";
}
function isPickingDeployPair() {
  return isPickingTarget() && ["deploy", "pair"].includes(state.selected?.action?.kind);
}
function isDeployPairTarget(index) {
  if (!isPickingDeployPair()) return false;
  const action = state.selected.action;
  return state.legalActions.some(
    (a) => a.kind === action.kind && a.card_id === action.card_id && a.slot === index,
  );
}
function isAttackTarget(index) {
  if (!isPickingAttack()) return false;
  return state.legalActions.some(
    (a) => a.kind === "attack" && a.source_slot === state.selected.slot && a.target_slot === index,
  );
}
function attackOnBaseExists() {
  if (!isPickingAttack()) return false;
  return state.legalActions.some(
    (a) => a.kind === "attack" && a.source_slot === state.selected.slot && a.target === "opponent_base",
  );
}

// ---------------------------------------------------------------------------
// the sheet
// ---------------------------------------------------------------------------

function renderSheet() {
  el.sheet.replaceChildren();
  el.sheet.className = "b3-sheet";
  el.sheetBackdrop.hidden = true;

  if (state.openingReveal?.active || state.status !== "waiting_human" || state.busy) {
    el.sheet.hidden = true;
    return;
  }

  if (state.confirm) {
    el.sheet.hidden = true;
    return;
  }

  if (state.selected?.phase === "pickTarget") {
    el.sheet.classList.add("mode-prompt");
    el.sheet.appendChild(buildPromptBar());
    el.sheet.hidden = false;
    return;
  }

  if (state.selected?.phase === "pickAction") {
    el.sheet.classList.add("mode-actions");
    buildActionSheet(state.selected, el.sheet);
    el.sheetBackdrop.hidden = false;
    el.sheet.hidden = false;
    return;
  }

  // forced choice with nothing selected → surface automatically
  if (!state.selected && choiceActions().length) {
    el.sheet.hidden = true;
    return;
  }

  el.sheet.hidden = true;
}

function renderDialog() {
  clearDialog();

  if (state.openingReveal?.active) return;
  if (state.status !== "waiting_human" || state.busy) return;

  if (state.confirm) {
    el.dialog = buildModal();
    el.dialog.querySelector(".b3-modal").appendChild(buildConfirmDialog(state.confirm));
    el.app.appendChild(el.dialog);
    return;
  }

  if (!state.selected && choiceActions().length) {
    el.dialog = buildModal();
    el.dialog.querySelector(".b3-modal").appendChild(buildChoiceDialog());
    el.app.appendChild(el.dialog);
  }
}

function clearDialog() {
  if (!el.dialog) return;
  el.dialog.remove();
  el.dialog = null;
}

function openingChoicePlayer(payload) {
  const pending = payload?.viewer_state?.pending_choice || {};
  if (!pending.visible || pending.type !== "choose_turn_order") return null;
  const choices = Array.isArray(payload.legal_actions) ? payload.legal_actions : [];
  const canChooseFirst = choices.some((action) => action.choice_id === "go_first");
  const canChooseSecond = choices.some((action) => action.choice_id === "go_second");
  return canChooseFirst && canChooseSecond ? pending.waiting_player : null;
}

function buildOpeningReveal(chooser) {
  return {
    active: true,
    chooser,
    resultClass: chooser === "P2" ? "result-p2" : "result-p1",
    title: chooser === "P2" ? "對手取得開局選擇權" : "你取得開局選擇權",
    sub: chooser === "P2" ? "對手正在選擇先攻或後攻" : "選擇先攻或後攻",
  };
}

function clearOpeningRevealTimer() {
  if (!state.revealTimer) return;
  window.clearTimeout(state.revealTimer);
  state.revealTimer = null;
}

function scheduleOpeningRevealDone() {
  clearOpeningRevealTimer();
  const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
  state.revealTimer = window.setTimeout(() => {
    state.revealTimer = null;
    if (!state.openingReveal) return;
    state.openingReveal = { ...state.openingReveal, active: false };
    render();
  }, reducedMotion ? 1200 : 4200);
}

function renderOpeningReveal() {
  if (!el.coinFlipOverlay || !el.coinFlipToken) return;
  const reveal = state.openingReveal;
  const active = Boolean(reveal?.active);
  el.coinFlipOverlay.hidden = !active;
  if (!active) {
    el.coinFlipToken.className = "b3-coin-token";
    return;
  }
  el.coinFlipTitle.textContent = reveal.title;
  el.coinFlipSub.textContent = reveal.sub;
  el.coinFlipToken.className = `b3-coin-token ${reveal.resultClass}`;
}

function buildModal() {
  const backdrop = document.createElement("section");
  backdrop.className = "b3-modal-backdrop";
  const modal = document.createElement("div");
  modal.className = "b3-modal";
  backdrop.appendChild(modal);
  return backdrop;
}

function buildPromptBar() {
  const bar = document.createElement("div");
  bar.className = "b3-prompt-bar";

  const text = document.createElement("div");
  text.className = "b3-prompt-text";
  const headline = document.createElement("span");
  headline.textContent = promptHeadline();
  const hint = document.createElement("span");
  hint.className = "b3-hint";
  hint.textContent = "點擊亮起的目標，可再點取消重選";
  text.appendChild(headline);
  text.appendChild(hint);
  bar.appendChild(text);

  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "b3-btn cancel";
  cancel.textContent = "取消";
  cancel.addEventListener("click", backToPickAction);
  bar.appendChild(cancel);

  return bar;
}

function buildConfirmBar(confirm) {
  const bar = document.createElement("div");
  bar.className = "b3-confirm-bar";

  const text = document.createElement("div");
  text.className = "b3-confirm-text";
  text.textContent = confirm.label;
  bar.appendChild(text);

  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "b3-btn cancel";
  cancel.textContent = "取消";
  cancel.addEventListener("click", () => {
    state.confirm = null;
    render();
  });
  bar.appendChild(cancel);

  const ok = document.createElement("button");
  ok.type = "button";
  ok.className = "b3-btn confirm";
  ok.textContent = "確認";
  ok.addEventListener("click", () => submitCommand(confirm.command));
  bar.appendChild(ok);

  return bar;
}

function buildDialogHeader({ title, sub, onClose }) {
  const head = document.createElement("div");
  head.className = "b3-sheet-head";

  const meta = document.createElement("div");
  meta.className = "b3-sheet-meta";
  const titleEl = document.createElement("div");
  titleEl.className = "b3-sheet-title";
  titleEl.textContent = title;
  meta.appendChild(titleEl);
  if (sub) {
    const subEl = document.createElement("div");
    subEl.className = "b3-sheet-sub";
    subEl.textContent = sub;
    meta.appendChild(subEl);
  }
  head.appendChild(meta);

  if (onClose) {
    const close = document.createElement("button");
    close.type = "button";
    close.className = "b3-close";
    close.setAttribute("aria-label", "關閉");
    close.textContent = "×";
    close.addEventListener("click", onClose);
    head.appendChild(close);
  }

  return head;
}

function buildConfirmDialog(confirm) {
  const fragment = document.createDocumentFragment();
  fragment.appendChild(buildDialogHeader({
    title: "確認",
    onClose: cancelConfirm,
  }));
  fragment.appendChild(buildConfirmBar(confirm));
  return fragment;
}

function buildChoiceDialog() {
  const fragment = document.createDocumentFragment();
  fragment.appendChild(buildDialogHeader({
    title: choiceDialogTitle(),
  }));
  const grid = document.createElement("div");
  grid.className = "b3-options";
  for (const action of choiceActions()) grid.appendChild(actionButton(action, action.label, "primary"));
  fragment.appendChild(grid);
  return fragment;
}

function choiceDialogTitle() {
  const labels = choiceActions().map((action) => action.label || action.command || "").join(" ");
  if (labels.includes("先攻") || labels.includes("後攻")) return "選擇先後攻";
  if (labels.includes("保留") || labels.includes("重新調度")) return "起手牌";
  return "選擇";
}

function cancelConfirm() {
  state.confirm = null;
  render();
}

function promptHeadline() {
  const action = state.selected?.action;
  if (!action) return "選擇目標";
  if (action.kind === "deploy") return `部署「${action.card_id}」— 選擇我方空格`;
  if (action.kind === "pair") return `配對「${action.card_id}」— 選擇我方單位`;
  if (action.kind === "attack") return `以 ${slotLabel(state.selected.slot)} 號位攻擊 — 選擇對手目標`;
  return "選擇目標";
}

function buildActionSheet(sel, sheet) {
  if (sel.type === "card") buildCardSheet(sel.cardId, sheet);
  else if (sel.type === "unit") buildUnitSheet(sel.slot, sheet);
  else if (sel.type === "base") buildBaseSheet(sheet);
  else if (sel.type === "list") buildListSheet(sheet);
}

function sheetHeader({ thumbCard, title, sub }) {
  const head = document.createElement("div");
  head.className = "b3-sheet-head";
  if (!thumbCard) head.classList.add("no-thumb");

  if (thumbCard) {
    const thumb = document.createElement("div");
    thumb.className = "b3-sheet-thumb";
    thumb.appendChild(imageCard(thumbCard));
    head.appendChild(thumb);
  }

  const meta = document.createElement("div");
  meta.className = "b3-sheet-meta";
  const titleEl = document.createElement("div");
  titleEl.className = "b3-sheet-title";
  titleEl.textContent = title;
  meta.appendChild(titleEl);
  if (sub) {
    const subEl = document.createElement("div");
    subEl.className = "b3-sheet-sub";
    subEl.textContent = sub;
    meta.appendChild(subEl);
  }
  head.appendChild(meta);

  const close = document.createElement("button");
  close.type = "button";
  close.className = "b3-close";
  close.setAttribute("aria-label", "關閉");
  close.textContent = "×";
  close.addEventListener("click", closeSheet);
  head.appendChild(close);

  return head;
}

function buildCardSheet(cardId, sheet) {
  const detail = cardDetailCache.get(cardId) || null;
  const title = detail?.name || cardId;
  const sub = detailSummary(detail, cardId);
  sheet.appendChild(sheetHeader({ thumbCard: cardId, title, sub }));
  if (detail) renderDetailInto(sheet, detail);
  else if (!cardDetailCache.has(cardId)) fetchCardDetail(cardId).then(() => maybeRefreshDetail(cardId));

  const grid = document.createElement("div");
  grid.className = "b3-options";

  const use = actionsForCard(cardId).find((a) => a.kind === "use");
  const deployBase = actionsForCard(cardId).find((a) => a.kind === "deploy_base");
  const deploys = cardDeployActions(cardId);
  const pairs = cardPairActions(cardId);

  if (use) grid.appendChild(actionButton(use, "使用", "primary"));
  if (deployBase) grid.appendChild(actionButton(deployBase, "部署為基地", "primary"));
  if (deploys.length) grid.appendChild(targetActionButton(deploys[0], "部署到場上"));
  if (pairs.length) grid.appendChild(targetActionButton(pairs[0], "配對駕駛"));

  // any remaining kinds not covered above
  const covered = new Set(["use", "deploy_base", "deploy", "pair"]);
  for (const action of actionsForCard(cardId)) {
    if (covered.has(action.kind)) continue;
    grid.appendChild(actionButton(action, action.label || action.kind));
  }

  if (!grid.children.length) {
    const note = document.createElement("div");
    note.className = "b3-sheet-sub";
    note.textContent = "目前無法使用此卡（資源不足或時機不對），僅供查看。";
    sheet.appendChild(note);
  } else {
    sheet.appendChild(grid);
  }
}

function buildUnitSheet(slot, sheet) {
  const unit = (state.viewerState?.players?.P1?.battle_area || []).find((s) => Number(s.slot) === slot);
  const cardId = unit?.unit_id;
  const detail = cardId ? (cardDetailCache.get(cardId) || null) : null;
  const name = detail?.name || cardId || "";
  const title = `${slotLabel(slot)} 號位${name ? ` · ${name}` : ""}`;
  const sub = detailSummary(detail, `AP ${unit?.ap ?? 0} / HP ${unit?.remaining_hp ?? 0}`);
  sheet.appendChild(sheetHeader({ thumbCard: cardId, title, sub }));
  if (detail) renderDetailInto(sheet, detail);
  else if (cardId && !cardDetailCache.has(cardId)) fetchCardDetail(cardId).then(() => maybeRefreshDetail(cardId));

  const grid = document.createElement("div");
  grid.className = "b3-options";
  const attacks = attacksFromSlot(slot);
  const block = blockAtSlot(slot);
  if (attacks.length) grid.appendChild(targetActionButton(attacks[0], "攻擊", "primary"));
  if (block) grid.appendChild(actionButton(block, "阻擋"));
  if (!grid.children.length) {
    const note = document.createElement("div");
    note.className = "b3-sheet-sub";
    note.textContent = "這個單位目前沒有可用操作。";
    sheet.appendChild(note);
  } else {
    sheet.appendChild(grid);
  }
}

function buildBaseSheet(sheet) {
  const ability = baseAbilityAction();
  sheet.appendChild(sheetHeader({ title: "我方基地", sub: "基地能力" }));
  const grid = document.createElement("div");
  grid.className = "b3-options";
  if (ability) grid.appendChild(actionButton(ability, "發動基地能力", "primary"));
  else {
    const note = document.createElement("div");
    note.className = "b3-sheet-sub";
    note.textContent = "基地目前沒有可發動的能力。";
    sheet.appendChild(note);
    return;
  }
  sheet.appendChild(grid);
}

function buildListSheet(sheet) {
  sheet.appendChild(sheetHeader({ title: "可操作清單", sub: "目前所有合法操作" }));

  const choices = choiceActions();
  if (choices.length) {
    sheet.appendChild(groupLabel("對局選項"));
    const grid = document.createElement("div");
    grid.className = "b3-options";
    for (const action of choices) grid.appendChild(actionButton(action, action.label));
    sheet.appendChild(grid);
  }

  // group by card
  const cardIds = [];
  for (const action of state.legalActions) {
    if (action.card_id && !cardIds.includes(action.card_id)) cardIds.push(action.card_id);
  }
  if (cardIds.length) {
    sheet.appendChild(groupLabel("手牌"));
    for (const cardId of cardIds) {
      const sub = document.createElement("div");
      sub.className = "b3-sheet-sub";
      sub.style.marginTop = "6px";
      sub.textContent = cardId;
      sheet.appendChild(sub);
      const grid = document.createElement("div");
      grid.className = "b3-options";
      const use = actionsForCard(cardId).find((a) => a.kind === "use");
      const deployBase = actionsForCard(cardId).find((a) => a.kind === "deploy_base");
      const deploys = cardDeployActions(cardId);
      const pairs = cardPairActions(cardId);
      if (use) grid.appendChild(actionButton(use, "使用"));
      if (deployBase) grid.appendChild(actionButton(deployBase, "部署為基地"));
      if (deploys.length) grid.appendChild(targetActionButton(deploys[0], "部署到場上"));
      if (pairs.length) grid.appendChild(targetActionButton(pairs[0], "配對駕駛"));
      sheet.appendChild(grid);
    }
  }

  // attacks / blocks
  const attackSlots = [];
  for (const action of state.legalActions) {
    if (action.kind === "attack" && !attackSlots.includes(action.source_slot)) attackSlots.push(action.source_slot);
  }
  const blockSlots = [];
  for (const action of state.legalActions) {
    if (action.kind === "block" && !blockSlots.includes(action.slot)) blockSlots.push(action.slot);
  }
  if (attackSlots.length || blockSlots.length) {
    sheet.appendChild(groupLabel("場上單位"));
    const grid = document.createElement("div");
    grid.className = "b3-options";
    for (const slot of attackSlots) {
      const action = attacksFromSlot(slot)[0];
      grid.appendChild(targetActionButton(action, `${slotLabel(slot)} 號位 攻擊`));
    }
    for (const slot of blockSlots) {
      const action = blockAtSlot(slot);
      grid.appendChild(actionButton(action, `${slotLabel(slot)} 號位 阻擋`));
    }
    sheet.appendChild(grid);
  }

  if (baseAbilityAction()) {
    sheet.appendChild(groupLabel("基地"));
    const grid = document.createElement("div");
    grid.className = "b3-options";
    grid.appendChild(actionButton(baseAbilityAction(), "發動基地能力"));
    sheet.appendChild(grid);
  }

  if (passAction()) {
    sheet.appendChild(groupLabel("讓過"));
    const grid = document.createElement("div");
    grid.className = "b3-options";
    grid.appendChild(actionButton(passAction(), "讓過（結束回合）"));
    sheet.appendChild(grid);
  }
}

function groupLabel(text) {
  const label = document.createElement("div");
  label.className = "b3-group-label";
  label.textContent = text;
  return label;
}

function actionButton(action, label, variant) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "b3-option";
  if (variant) button.classList.add(variant);
  button.textContent = label || action.label || action.command;
  button.addEventListener("click", () => chooseAction(action));
  return button;
}

function targetActionButton(action, label, variant) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "b3-option target";
  if (variant) button.classList.add(variant);
  button.textContent = label || action.label;
  button.addEventListener("click", () => chooseAction(action));
  return button;
}

function chooseAction(action) {
  if (state.busy) return;
  if (["deploy", "pair", "attack"].includes(action.kind)) {
    enterPickTarget(action);
    render();
    return;
  }
  // unambiguous single-step actions commit directly — but only after an
  // explicit button press, never a first tap on a board element.
  submitCommand(action.command);
}

function enterPickTarget(action) {
  if (action.kind === "attack") {
    state.selected = { type: "unit", slot: action.source_slot, phase: "pickTarget", action };
  } else {
    state.selected = { type: "card", cardId: action.card_id, phase: "pickTarget", action };
  }
  state.confirm = null;
}

function backToPickAction() {
  if (!state.selected) return;
  state.selected = { ...state.selected, phase: "pickAction" };
  delete state.selected.action;
  state.confirm = null;
  render();
}

function closeSheet() {
  state.selected = null;
  state.confirm = null;
  render();
}

// ---------------------------------------------------------------------------
// click handlers — first tap only selects / picks target, never commits
// ---------------------------------------------------------------------------

function handleHandClick(cardId) {
  if (state.status !== "waiting_human" || state.busy) return;
  // Any own hand card is inspectable, playable or not. The sheet shows the
  // card detail + (if any) its legal actions.
  if (isSelectedCard(cardId)) {
    closeSheet();
    return;
  }
  state.selected = { type: "card", cardId, phase: "pickAction" };
  state.confirm = null;
  render();
}

function handleBaseClick() {
  if (state.status !== "waiting_human" || state.busy) return;
  if (!baseAbilityAction()) return;
  if (isSelectedBase()) {
    closeSheet();
    return;
  }
  state.selected = { type: "base", phase: "pickAction" };
  state.confirm = null;
  render();
}

function handleSlotClick(index, isSelf, data) {
  if (state.status !== "waiting_human" || state.busy) return;

  // target pick: clicking a valid target stages a confirm
  if (isSelf && isDeployPairTarget(index)) {
    stageTargetConfirm(findDeployPairAction(index));
    return;
  }
  if (!isSelf && isAttackTarget(index)) {
    stageTargetConfirm(findAttackSlotAction(index));
    return;
  }
  if (isPickingTarget()) return; // ignore non-target taps during target pick

  if (isSelf) {
    if (!data.unit_id) return;
    const canAct = attacksFromSlot(index).length > 0 || Boolean(blockAtSlot(index));
    if (!canAct) return;
    if (isSelectedUnit(index)) {
      closeSheet();
      return;
    }
    state.selected = { type: "unit", slot: index, phase: "pickAction" };
    state.confirm = null;
    render();
  }
}

function handleOpponentBaseClick() {
  if (state.status !== "waiting_human" || state.busy) return;
  if (!isPickingAttack()) return;
  const action = state.legalActions.find(
    (a) => a.kind === "attack" && a.source_slot === state.selected.slot && a.target === "opponent_base",
  );
  if (action) stageTargetConfirm(action);
}

function stageTargetConfirm(action) {
  if (!action) return;
  state.confirm = { command: action.command, label: `${action.label}  —  確認執行？` };
  render();
}

function findDeployPairAction(index) {
  const action = state.selected.action;
  return state.legalActions.find(
    (a) => a.kind === action.kind && a.card_id === action.card_id && a.slot === index,
  );
}

function findAttackSlotAction(index) {
  return state.legalActions.find(
    (a) => a.kind === "attack" && a.source_slot === state.selected.slot && a.target_slot === index,
  );
}

function slotLabel(slot) {
  return String((slot ?? 0) + 1);
}

// ---------------------------------------------------------------------------
// wiring
// ---------------------------------------------------------------------------

el.startBtn.addEventListener("click", startBattle);
el.endTurnBtn.addEventListener("click", () => {
  const pass = passAction();
  if (pass) submitCommand(pass.command);
});
el.actionsListBtn.addEventListener("click", () => {
  if (state.status !== "waiting_human" || state.busy) return;
  if (state.selected?.type === "list") {
    closeSheet();
    return;
  }
  state.selected = { type: "list", phase: "pickAction" };
  state.confirm = null;
  render();
});

el.sheetBackdrop.addEventListener("click", closeSheet);

function applyQaLayoutState() {
  const params = new URLSearchParams(window.location.search);
  const qaMode = params.get("qa");
  if (qaMode !== "layout" && qaMode !== "nobase") return false;

  const fullBoard = ["ST01-008", "ST01-009", "ST01-010", "ST01-011", "ST01-012", "ST01-013"].map((unit, slot) => ({
    slot,
    unit_id: `st01/${unit}`,
    pilot_id: slot % 2 === 0 ? "st01/ST01-001" : "",
    status: slot === 1 ? "rested" : "active",
    buffs: slot >= 3 ? ["+2"] : [],
    status_icons: slot === 4 ? ["盾"] : [],
    ap: slot === 5 ? 99 : 12 + slot,
    remaining_hp: slot === 5 ? 99 : 12 + slot,
  }));

  const qaBase = qaMode === "nobase"
    ? { present: false, card_id: "", ap: 0, remaining_hp: 0 }
    : { present: true, card_id: "EX-BASE", ap: 0, remaining_hp: 3 };

  state.gameId = `qa-${qaMode}`;
  state.viewerState = {
    winner: null,
    players: {
      P1: {
        hand: ["st01/ST01-001", "st01/ST01-002", "st01/ST01-003", "st01/ST01-004", "st01/ST01-005"],
        shield_count: 6,
        resources: { active: 1, rested: 3, ex: 1 },
        base: qaBase,
        deck_count: 999,
        trash: ["a", "b", "c"],
        battle_area: fullBoard,
      },
      P2: {
        hand_count: 5,
        shield_count: 6,
        resources: { active: 2, rested: 2, ex: 1 },
        base: qaBase,
        deck_count: 120,
        trash: ["a"],
        battle_area: fullBoard,
      },
    },
  };
  state.legalActions = [
    { kind: "pass", command: "pass" },
    { kind: "attack", source_slot: 0, target_slot: 0, label: "1 號位攻擊", command: "attack 1 1" },
  ];
  state.events = [{ message: qaMode === "nobase" ? "QA layout: 無基地。" : "QA layout: 滿場、駕駛、增益、狀態、大數字。" }];
  state.status = "waiting_human";
  render();
  return true;
}

prewarmImages();
if (!applyQaLayoutState()) {
  const gameId = new URLSearchParams(window.location.search).get("game_id");
  if (gameId) resumeBattle(gameId);
  else render();
}
