const state = {
  gameId: null,
  viewerState: null,
  legalActions: [],
  events: [],
  status: "not_started",
  busy: false,
  error: null,
  pollTimer: null,
  selected: null,
};

const cardAliases = {
  "EX-BASE": "/st01/EXB-001.png",
  "EX-RESOURCE": "/st01/EXR-001.png",
};

const apiBase = "/api/battleV2";

const el = {
  startBtn: document.getElementById("startBtn"),
  startScreen: document.getElementById("startScreen"),
  statusMessage: document.getElementById("statusMessage"),
  combatMessage: document.getElementById("combatMessage"),
  actionsPanel: document.getElementById("actionsPanel"),
  errorBox: document.getElementById("errorBox"),
  endTurnBtn: document.getElementById("endTurnBtn"),
};

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

function applyPayload(payload) {
  state.gameId = payload.game_id || null;
  state.viewerState = payload.viewer_state || null;
  state.legalActions = Array.isArray(payload.legal_actions) ? payload.legal_actions : [];
  state.events = Array.isArray(payload.events) ? payload.events : [];
  state.status = payload.status || "not_started";
  state.error = payload.error || null;
  state.busy = false;
  state.selected = null;
  render(payload.message || "");
  updatePolling();
}

async function startBattle() {
  state.busy = true;
  render("建立對局中...");
  applyPayload(await postJson(`${apiBase}/start`));
}

async function refreshBattle() {
  if (state.status !== "waiting_ai") return;
  applyPayload(await fetchJson(`${apiBase}/state`));
}

async function submitCommand(command) {
  if (state.busy || state.status !== "waiting_human") return;
  state.busy = true;
  render("執行操作中...");
  applyPayload(await postJson(`${apiBase}/command`, { command }));
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

function render(fallbackMessage = "") {
  const hasGame = Boolean(state.viewerState);
  el.startScreen.hidden = hasGame && state.status !== "not_started";
  renderStatus(fallbackMessage);
  renderError();
  renderBoard();
  renderActionPanel();
}

function renderStatus(fallbackMessage) {
  const message = state.error || fallbackMessage || statusMessage();
  el.statusMessage.textContent = message;
  el.combatMessage.textContent = latestEventMessage() || message;
  el.endTurnBtn.disabled = state.busy || state.status !== "waiting_human" || !passAction();
}

function statusMessage() {
  if (state.status === "waiting_ai") return "對手思考中...";
  if (state.status === "waiting_human") return "點擊亮起的手牌、場上卡或目標來操作。";
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
  setText(`${playerId}HandCount`, `(${count})`);
  const container = document.getElementById(`${playerId}Hand`);
  container.replaceChildren();

  if (!isSelf) {
    for (let i = 0; i < Math.min(count, 10); i += 1) {
      container.appendChild(cardBack());
    }
    return;
  }

  for (const cardId of cards.slice(0, 10)) {
    const button = document.createElement("button");
    button.className = "hand-card-button";
    button.type = "button";
    button.title = cardId;
    button.disabled = state.status !== "waiting_human" || !actionsForCard(cardId).length;
    if (actionsForCard(cardId).length) button.classList.add("selectable");
    if (selectedCard() === cardId) button.classList.add("selected");
    button.appendChild(imageCard(cardId));
    button.addEventListener("click", () => handleHandClick(cardId));
    container.appendChild(button);
  }
}

function renderShields(playerId, player) {
  const count = visibleCount(player.shield_count ?? player.shields);
  setText(`${playerId}ShieldCount`, `(${count})`);
  const container = document.getElementById(`${playerId}Shields`);
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
  setText(`${playerId}ResourceText`, ex ? `${normal}/10 + EX ${ex}/5` : `${normal} / 10`);
  const container = document.getElementById(`${playerId}Resources`);
  container.replaceChildren();
  const pips = [
    ...Array(active).fill("active"),
    ...Array(rested).fill("rested"),
    ...Array(Math.max(0, 10 - normal)).fill("empty"),
    ...Array(ex).fill("ex"),
  ];
  for (const kind of pips.slice(0, 15)) {
    const pip = document.createElement("span");
    pip.className = `pip ${kind}`;
    container.appendChild(pip);
  }
}

function renderBase(playerId, player, isSelf) {
  const container = document.getElementById(`${playerId}Base`);
  container.replaceChildren();
  container.classList.remove("selectable", "selected", "targetable");
  const ability = isSelf ? baseAbilityAction() : null;
  if (ability) container.classList.add("selectable");
  if (!isSelf && canTargetOpponentBase()) container.classList.add("targetable");
  container.disabled = isSelf ? !ability : !canTargetOpponentBase();
  container.onclick = isSelf ? () => ability && submitCommand(ability.command) : () => handleOpponentBaseClick();

  const base = player.base || {};
  if (!base.present || !base.card_id) {
    const empty = document.createElement("div");
    empty.className = "base-stats";
    empty.textContent = "Base: none";
    empty.dataset.mobileHp = "-";
    container.appendChild(empty);
    return;
  }

  container.appendChild(imageCard(base.card_id, "base-image"));
  const stats = document.createElement("div");
  stats.className = "base-stats";
  const remaining = visibleCount(base.remaining_hp ?? (visibleCount(base.hp) - visibleCount(base.damage)));
  stats.textContent = `AP|HP ${base.ap ?? 0}|${remaining}`;
  stats.dataset.mobileHp = String(remaining);
  container.appendChild(stats);
}

function renderDecks(playerId, player) {
  const energy = document.getElementById(`${playerId}EnergyDeck`);
  energy.dataset.count = String(visibleCount(player.resource_deck_count));
  const trash = document.getElementById(`${playerId}Trash`);
  const trashCount = visibleCount(player.trash?.length);
  trash.textContent = trashCount;
  trash.dataset.trashCount = String(trashCount);
}

function renderSlots(playerId, slots, isSelf) {
  const container = document.getElementById(`${playerId}Slots`);
  container.replaceChildren();
  for (let i = 0; i < 6; i += 1) {
    const data = slots.find((slot) => Number(slot.slot) === i) || { slot: i, empty: true };
    const slot = document.createElement("button");
    slot.type = "button";
    slot.className = `slot slot-button ${data.empty || !data.unit_id ? "empty" : "filled"} ${data.status === "rested" ? "rested" : ""}`;
    markSlotState(slot, i, isSelf, data);
    slot.addEventListener("click", () => handleSlotClick(i, isSelf, data));

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

function markSlotState(slot, index, isSelf, data) {
  if (isSelf && selectedOwnSlot() === index) slot.classList.add("selected");
  if (isSelf && canStartFromOwnSlot(index, data)) slot.classList.add("selectable");
  if (isSelf && selectedCardCanUseSlot(index)) slot.classList.add("targetable");
  if (!isSelf && selectedAttackCanTargetSlot(index)) slot.classList.add("targetable");
}

function renderActionPanel() {
  el.actionsPanel.replaceChildren();
  const shouldShow = state.status === "waiting_human" && (
    state.legalActions.some((action) => action.kind === "choice")
    || selectedCardOptions().length
    || state.selected?.type
  );
  el.actionsPanel.hidden = !shouldShow;
  if (!shouldShow) return;

  const prompt = document.createElement("div");
  prompt.className = "battle-v2-prompt";
  prompt.textContent = interactionPrompt();
  el.actionsPanel.appendChild(prompt);

  const choices = state.legalActions.filter((action) => action.kind === "choice");
  if (choices.length) el.actionsPanel.appendChild(optionGrid(choices));

  const selectedOptions = selectedCardOptions();
  if (selectedOptions.length) el.actionsPanel.appendChild(optionGrid(selectedOptions));
}

function interactionPrompt() {
  if (state.selected?.type === "card") {
    if (selectedCardActions().some((action) => action.kind === "deploy")) return "選擇我方空格部署這張卡。";
    if (selectedCardActions().some((action) => action.kind === "pair")) return "選擇我方場上一張單位進行配對。";
    return "確認這張卡的操作。";
  }
  if (state.selected?.type === "attack_source") return "選擇對手單位或基地作為攻擊目標。";
  if (state.legalActions.some((action) => action.kind === "choice")) return "選擇目前對局選項。";
  return "點擊亮起的卡牌。";
}

function optionGrid(actions) {
  const grid = document.createElement("div");
  grid.className = "battle-v2-options";
  for (const action of actions) {
    const button = document.createElement("button");
    button.className = "battle-v2-option";
    button.type = "button";
    button.disabled = state.busy;
    button.textContent = action.label || action.command;
    button.addEventListener("click", () => submitCommand(action.command));
    grid.appendChild(button);
  }
  return grid;
}

function actionsForCard(cardId) {
  return state.legalActions.filter((action) => action.card_id === cardId);
}

function selectedCardActions() {
  const cardId = selectedCard();
  return cardId ? actionsForCard(cardId) : [];
}

function selectedCardOptions() {
  return selectedCardActions().filter((action) => !["deploy", "pair"].includes(action.kind));
}

function passAction() {
  return state.legalActions.find((action) => action.kind === "pass");
}

function baseAbilityAction() {
  return state.legalActions.find((action) => action.kind === "ability");
}

function selectedCard() {
  return state.selected?.type === "card" ? state.selected.cardId : null;
}

function selectedOwnSlot() {
  return state.selected?.type === "attack_source" ? state.selected.slot : null;
}

function canStartFromOwnSlot(index, data) {
  if (state.status !== "waiting_human" || data.empty || !data.unit_id) return false;
  return state.legalActions.some((action) => (
    (action.kind === "attack" && action.source_slot === index)
    || (action.kind === "block" && action.slot === index)
  ));
}

function selectedCardCanUseSlot(index) {
  return selectedCardActions().some((action) => (
    (action.kind === "deploy" && action.slot === index)
    || (action.kind === "pair" && action.slot === index)
  ));
}

function selectedAttackCanTargetSlot(index) {
  if (state.selected?.type !== "attack_source") return false;
  return state.legalActions.some((action) => (
    action.kind === "attack"
    && action.source_slot === state.selected.slot
    && action.target_slot === index
  ));
}

function canTargetOpponentBase() {
  if (state.selected?.type !== "attack_source") return false;
  return state.legalActions.some((action) => (
    action.kind === "attack"
    && action.source_slot === state.selected.slot
    && action.target === "opponent_base"
  ));
}

function handleHandClick(cardId) {
  if (state.status !== "waiting_human") return;
  const actions = actionsForCard(cardId);
  if (!actions.length) return;
  state.selected = { type: "card", cardId };
  if (actions.length === 1 && !["deploy", "pair"].includes(actions[0].kind)) {
    submitCommand(actions[0].command);
    return;
  }
  render();
}

function handleSlotClick(index, isSelf, data) {
  if (state.status !== "waiting_human") return;
  if (isSelf) {
    const cardSlotAction = selectedCardActions().find((action) => (
      (action.kind === "deploy" || action.kind === "pair") && action.slot === index
    ));
    if (cardSlotAction) {
      submitCommand(cardSlotAction.command);
      return;
    }

    const block = state.legalActions.find((action) => action.kind === "block" && action.slot === index);
    if (block) {
      submitCommand(block.command);
      return;
    }

    const attacks = state.legalActions.filter((action) => action.kind === "attack" && action.source_slot === index);
    if (attacks.length) {
      state.selected = { type: "attack_source", slot: index };
      render();
    }
    return;
  }

  const attack = state.legalActions.find((action) => (
    state.selected?.type === "attack_source"
    && action.kind === "attack"
    && action.source_slot === state.selected.slot
    && action.target_slot === index
  ));
  if (attack) submitCommand(attack.command);
}

function handleOpponentBaseClick() {
  const attack = state.legalActions.find((action) => (
    state.selected?.type === "attack_source"
    && action.kind === "attack"
    && action.source_slot === state.selected.slot
    && action.target === "opponent_base"
  ));
  if (attack) submitCommand(attack.command);
}

el.startBtn.addEventListener("click", startBattle);
el.endTurnBtn.addEventListener("click", () => {
  const pass = passAction();
  if (pass) submitCommand(pass.command);
});

render();
