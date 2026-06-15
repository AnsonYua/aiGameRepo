const state = {
  replay: null,
  events: [],
  index: 0,
};

const isMobileBoard = window.location.pathname.replace(/\/+$/, "") === "/mobile";
document.body.classList.toggle("mobile-board", isMobileBoard);
if (isMobileBoard) {
  document.getElementById("prevBtn")?.setAttribute("aria-label", "Menu");
  document.getElementById("nextBtn")?.setAttribute("aria-label", "Game log");
}

const ids = [
  "stepTitle",
  "stepSubtle",
  "topbarMessage",
  "seqBadge",
  "phaseBadge",
  "timeline",
  "prevBtn",
  "nextBtn",
  "stepSlider",
];

const el = Object.fromEntries(ids.map((id) => [id, document.getElementById(id)]));

const phaseLabels = {
  "pre-game": "Pre-game",
  start: "Start",
  draw: "Draw",
  resource: "Resource",
  main: "Main",
  battle: "Battle",
  end: "End",
};

const cardAliases = {
  "EX-BASE": "st01/EXB-001.png",
  "EX-RESOURCE": "st01/EXR-001.png",
};

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function imageFor(cardId) {
  if (!cardId) return null;
  if (cardAliases[cardId]) return cardAliases[cardId];
  const normalized = String(cardId).replace(/^\/+/, "");
  if (normalized.endsWith(".png")) return normalized;
  return `${normalized}.png`;
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

function renderRepeated(containerId, count, renderer, max = 10) {
  const container = document.getElementById(containerId);
  container.replaceChildren();
  const safeCount = clamp(visibleCount(count), 0, max);
  for (let i = 0; i < safeCount; i += 1) {
    container.appendChild(renderer(i));
  }
}

function handCardIds(player) {
  const candidates = [player.review_hand, player.hand, player.hand_cards, player.hand_card_ids, player.visible_hand];
  for (const candidate of candidates) {
    if (!Array.isArray(candidate) || candidate.length === 0) continue;
    const cards = candidate
      .map((card) => {
        if (!card) return null;
        return typeof card === "string" ? card : card?.card_id || card?.id || null;
      });
    if (cards.some(Boolean) || candidate.some((card) => card === null)) return cards;
  }
  return [];
}

function renderHand(playerId, player) {
  const cards = handCardIds(player);
  const unknown = visibleCount(player.review_hand_unknown_count);
  const count = cards.length || unknown || visibleCount(player.hand_count);
  setText(`${playerId}HandCount`, `(${count})`);
  const container = document.getElementById(`${playerId}Hand`);
  container.replaceChildren();
  if (cards.length) {
    for (const cardId of cards.slice(0, 10)) {
      container.appendChild(cardId ? imageCard(cardId) : cardBack());
    }
    for (let i = 0; i < Math.min(unknown, Math.max(0, 10 - cards.length)); i += 1) {
      container.appendChild(cardBack());
    }
    return;
  }
  renderRepeated(`${playerId}Hand`, count, () => cardBack(), 10);
}

function renderShields(playerId, player) {
  const count = visibleCount(player.shields ?? player.shield_count);
  setText(`${playerId}ShieldCount`, `(${count})`);
  renderRepeated(
    `${playerId}Shields`,
    count,
    () => {
      const shield = document.createElement("div");
      shield.className = "shield";
      return shield;
    },
    6,
  );
}

function renderResources(playerId, player) {
  const resources = player.resources || {};
  const active = visibleCount(resources.active);
  const rested = visibleCount(resources.rested);
  const ex = visibleCount(resources.ex);
  const total = active + rested + ex;
  setText(`${playerId}ResourceText`, `${total} / 10`);

  const container = document.getElementById(`${playerId}Resources`);
  container.replaceChildren();
  const pips = [
    ...Array(active).fill("active"),
    ...Array(rested).fill("rested"),
    ...Array(ex).fill("ex"),
    ...Array(Math.max(0, 10 - total)).fill("empty"),
  ];
  for (const kind of pips.slice(0, 10)) {
    const pip = document.createElement("span");
    pip.className = `pip ${kind}`;
    pip.title = kind === "active" ? "active resource" : kind === "rested" ? "rested resource" : kind === "ex" ? "EX resource" : "empty resource";
    pip.textContent = kind === "active" ? "A" : kind === "rested" ? "R" : kind === "ex" ? "EX" : "";
    container.appendChild(pip);
  }
}

function renderBase(playerId, player) {
  const container = document.getElementById(`${playerId}Base`);
  container.replaceChildren();
  const base = player.base;
  if (!base || !base.card_id) {
    const empty = document.createElement("div");
    empty.className = "base-stats";
    empty.textContent = "Base: none";
    empty.dataset.mobileHp = "-";
    container.appendChild(empty);
    return;
  }

  const image = imageCard(base.card_id, "base-image");
  if (base.alive === false) image.classList.add("destroyed");
  container.appendChild(image);
  const stats = document.createElement("div");
  stats.className = "base-stats";
  const remaining = Math.max(0, visibleCount(base.hp) - visibleCount(base.damage));
  stats.textContent = `AP|HP ${base.ap ?? 0}|${remaining}`;
  stats.dataset.mobileHp = String(remaining);
  container.appendChild(stats);
}

function renderDecks(playerId, player) {
  setText(`${playerId}Deck`, `Deck ${visibleCount(player.deck_count)}`);
  const energy = document.getElementById(`${playerId}EnergyDeck`);
  const resourceDeckCount = visibleCount(player.resource_deck_count);
  energy.title = `${resourceDeckCount} cards`;
  energy.dataset.count = String(resourceDeckCount);
  const trashCount = visibleCount(player.trash?.length);
  const trash = document.getElementById(`${playerId}Trash`);
  trash.textContent = trashCount;
  trash.dataset.trashCount = String(trashCount);
}

function renderSlots(playerId, player) {
  const container = document.getElementById(`${playerId}Slots`);
  container.replaceChildren();
  const slots = player.board?.slots || [];
  for (let i = 0; i < 6; i += 1) {
    const slotData = slots.find((slot) => Number(slot.slot) === i) || { slot: i };
    const slot = document.createElement("div");
    slot.className = `slot ${slotData.unit_id ? "filled" : "empty"} ${slotData.status === "rested" ? "rested" : ""}`;

    if (slotData.unit_id) {
      const cardWrap = document.createElement("div");
      cardWrap.className = "slot-card";
      cardWrap.appendChild(imageCard(slotData.unit_id, "card-img"));
      slot.appendChild(cardWrap);

      if (slotData.pilot_id) {
        const pilotCard = document.createElement("div");
        pilotCard.className = "pilot-card";
        pilotCard.title = slotData.pilot_name || slotData.pilot_id;
        pilotCard.appendChild(imageCard(slotData.pilot_id, "card-img"));
        slot.appendChild(pilotCard);
      }

      const info = document.createElement("div");
      info.className = "slot-info";
      const apHp = document.createElement("span");
      apHp.className = "stat-pill";
      apHp.textContent = `${slotData.ap ?? 0}/${Math.max(0, visibleCount(slotData.hp) - visibleCount(slotData.damage))}`;
      info.appendChild(apHp);
      if (slotData.pilot_id) {
        const pilot = document.createElement("span");
        pilot.className = "status-chip";
        pilot.textContent = slotData.is_link ? "Link" : "Pilot";
        info.appendChild(pilot);
      }
      slot.appendChild(info);

      const keywords = document.createElement("div");
      keywords.className = "keywords";
      for (const keyword of slotData.keywords || []) {
        const chip = document.createElement("span");
        chip.className = "keyword";
        chip.textContent = keyword;
        keywords.appendChild(chip);
      }
      slot.appendChild(keywords);
    }

    const number = document.createElement("span");
    number.className = "slot-number";
    number.textContent = String(i + 1);
    slot.appendChild(number);
    container.appendChild(slot);
  }
}

function renderPlayer(playerId, player = {}) {
  const visiblePlayer = player || {};
  renderHand(playerId, visiblePlayer);
  renderShields(playerId, visiblePlayer);
  renderResources(playerId, visiblePlayer);
  renderBase(playerId, visiblePlayer);
  renderDecks(playerId, visiblePlayer);
  renderSlots(playerId, visiblePlayer);
}

function renderTimeline() {
  el.timeline.replaceChildren();
  state.events.forEach((event, index) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = index === state.index ? "active" : "";
    item.textContent = `${event.seq}. ${event.message || event.event_type}`;
    item.addEventListener("click", () => setIndex(index));
    el.timeline.appendChild(item);
  });
}

function render() {
  const event = state.events[state.index];
  if (!event) return;

  const features = event.features || {};
  const phase = phaseLabels[event.phase] || event.phase || "-";
  el.stepTitle.textContent = `Turn ${event.turn ?? "-"} · ${phase}`;
  el.stepSubtle.textContent = `${event.event_type || "event"} · actor ${event.actor || "-"}`;
  el.topbarMessage.textContent = event.message || "";
  el.seqBadge.textContent = `${state.index + 1} / ${state.events.length}`;
  el.phaseBadge.textContent = phase;
  el.stepSlider.max = String(Math.max(0, state.events.length - 1));
  el.stepSlider.value = String(state.index);
  el.prevBtn.disabled = state.index === 0;
  el.nextBtn.disabled = state.index === state.events.length - 1;

  renderPlayer("p1", features.p1);
  renderPlayer("p2", features.p2);
  renderTimeline();
  document.body.classList.add("replay-ready");
}

function setIndex(nextIndex) {
  state.index = clamp(nextIndex, 0, Math.max(0, state.events.length - 1));
  render();
}

function mobileEventScore(event) {
  const features = event?.features || {};
  return ["p1", "p2"].reduce(
    (score, playerId) => {
      const player = features[playerId] || {};
      const handCount = handCardIds(player).length || visibleCount(player.hand_count);
      const filledSlots = (player.board?.slots || []).filter((slot) => slot.unit_id).length;
      const resources = player.resources || {};
      const resourceCount = visibleCount(resources.active) + visibleCount(resources.rested) + visibleCount(resources.ex);
      const shieldCount = visibleCount(player.shields ?? player.shield_count);
      return {
        bases: score.bases + ((player.base || {}).card_id ? 1 : 0),
        filledSlots: score.filledSlots + filledSlots,
        hands: score.hands + handCount,
        resources: score.resources + resourceCount,
        shields: score.shields + shieldCount,
      };
    },
    { bases: 0, filledSlots: 0, hands: 0, resources: 0, shields: 0 },
  );
}

function mobileInitialIndex() {
  const denseIndex = state.events.findIndex((event) => {
    const score = mobileEventScore(event);
    return score.filledSlots >= 5 && score.bases >= 2 && score.resources >= 4;
  });
  if (denseIndex >= 0) return denseIndex;

  const boardIndex = state.events.findIndex((event) => {
    const score = mobileEventScore(event);
    return score.filledSlots >= 2 && score.bases >= 2 && score.resources >= 2;
  });
  if (boardIndex >= 0) return boardIndex;

  return Math.max(
    0,
    state.events.findIndex((event) => {
      const score = mobileEventScore(event);
      return score.hands > 0 || score.shields > 0;
    }),
  );
}

async function init() {
  const response = await fetch("/api/replay");
  const replay = await response.json();
  if (!response.ok || replay.error) {
    throw new Error(replay.error || `HTTP ${response.status}`);
  }
  state.replay = replay;
  state.events = Array.isArray(replay.events) ? replay.events : [];
  const initialIndex = isMobileBoard ? mobileInitialIndex() : 0;
  setIndex(initialIndex);
}

el.prevBtn.addEventListener("click", () => setIndex(state.index - 1));
el.nextBtn.addEventListener("click", () => setIndex(state.index + 1));
el.stepSlider.addEventListener("input", (event) => setIndex(Number(event.target.value)));
window.addEventListener("keydown", (event) => {
  if (event.key === "ArrowLeft") setIndex(state.index - 1);
  if (event.key === "ArrowRight") setIndex(state.index + 1);
});

init().catch((error) => {
  el.stepTitle.textContent = "Could not load replay";
  el.topbarMessage.textContent = error.message;
});
