"use strict";

const byId = (id) => document.getElementById(id);
const settings = byId("settings");
const setup = byId("setup");
const hyperparameterFields = byId("hyperparameter-fields");
const hyperparameterSettings = byId("hyperparameter-settings");
const hyperparameterEdits = new Map();
const map = byId("map");
const mapContext = map.getContext("2d");
const floorLayers = new Map();
const previewFrames = new WeakSet();
const chart = byId("chart");
const scrub = byId("scrub");
const play = byId("play");
const eventReadout = document.querySelector(".event-readout");
const motion = matchMedia("(prefers-reduced-motion: reduce)");
const mapSize = 500;
const cellSize = 44;
const mapInset = 30;
const mapLime = "#e5f787";
const mapOrange = "#ffac73";
const mapBlue = "#a1dbf2";
const feedbackDuration = 440;
const history = [];
const averages = [];
const outcomeLabels = {
  delivered: "Delivered", returned: "Returned to base", collision: "Collision",
  depleted: "Battery depleted", timeout: "Step limit", shift_ended: "Shift ended with backlog",
};
const outcomeLabel = (result) => result.outcome === "delivered"
  ? result.released != null || result.shift ? "All released orders staged"
    : result.orders_completed != null || result.fleet ? "Both orders staged"
    : result.pack_tick !== undefined ? "Staged for shipment" : outcomeLabels.delivered
  : outcomeLabels[result.outcome];
const hasLayouts = (environment) => environment === "multiple_layouts";
const hasSharedAisles = (environment) => environment === "shared_aisles";
const hasShift = (environment) => environment === "continuous_fulfillment";
const hasFleet = (environment) => environment === "two_learning_robots" || hasShift(environment);
const hasPacking = (environment) => environment === "pack_and_stage" || hasLayouts(environment) || hasSharedAisles(environment);
const hasBattery = (environment) => environment === "charging_dock" || hasPacking(environment);
const layoutSuffix = (result) => result.layout ? ` · ${world.floor_plans[result.layout].name}` : "";
const trainingTraceLabel = (result) => `Training episode ${number(result.episode, 0)} · ${outcomeLabel(result)}${layoutSuffix(result)}`;
const completed = (result) => result?.outcome === "delivered" || result?.outcome === "returned";
const gridHeadings = new WeakMap();
const episodeGrid = new EpisodeGrid({
  paint: paintGridTrace,
  inspect: inspectGridTrace,
  describe: (episode) => ({
    title: `Episode ${number(episode.episode, 0)}`,
    summary: `${episode.released == null ? outcomeLabel(episode) : `${episode.orders_completed}/${episode.released} staged`} · Return ${signed(episode.reward)}${layoutSuffix(episode)}`,
  }),
  motion,
});
const emptyChartMessages = {
  Ready: ["No episodes yet", "Start training to see the return from each completed episode."],
  Training: ["Waiting for the first episode", "The plot appears as soon as the first results arrive."],
  Paused: ["Training paused", "Resume training to see episode returns here."],
  Disconnected: ["Warehouse unavailable", "Reload after starting the local server."],
};
const profileDescriptions = {
  balanced: "Scores delivery, time, energy, forklift clearance, blocked moves, and failure.",
  efficiency: "Scores delivery, failure, time, and energy. Exposure is still measured.",
  sparse: "Scores delivery and failure. Operating costs and exposure are still measured.",
};
const conflictLabels = { same_cell: "Same-cell request", swap: "Head-on swap prevented", occupied: "Aisle cell occupied" };
const workloadLabels = { paced: "Paced", burst: "Burst" };
let world;
let hyperparameterSchema;
let navigationSettings;
let fleetAlgorithm = "ippo";
let runId;
let runConfig;
let referenceTrace;
let total = byId("episodes").valueAsNumber;
let status = "Loading";
let pending = false;
let trainingTimer;
let trace = [];
let headings = {};
let queuedTrace = null;
let latestTrace = null;
let following = false;
let playing = false;
let playbackFrame = 0;
let playbackVisible = true;
let tick = 0;
let animationStart = null;
let stepProgress = 0;
let traceDuration = 115;

function number(value, digits = 1) {
  return value.toLocaleString("en-US", { maximumFractionDigits: digits });
}

function signed(value) {
  return value === 0 ? "0" : `${value > 0 ? "+" : ""}${number(value, 3)}`;
}

function showError(message) {
  byId("error").textContent = message;
  byId("error").hidden = !message;
}

async function request(path, body) {
  if (window.warehouseRequest) return window.warehouseRequest(path, body);
  const response = await fetch(`/api/${path}`, body === undefined ? undefined : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "The dashboard request failed.");
  return data;
}

function showHyperparameters() {
  const algorithm = byId("algorithm").value;
  const fields = hyperparameterSchema[algorithm] ?? [];
  const edits = hyperparameterEdits.get(algorithm) ?? {};
  hyperparameterEdits.set(algorithm, edits);
  hyperparameterFields.replaceChildren();
  hyperparameterSettings.hidden = !fields.length;
  byId("hyperparameter-note").textContent = fields.length
    ? "Edits apply when you start a new run."
    : "This algorithm uses fixed hyperparameters.";
  for (const { name, label, description, min, max, default: defaultValue } of fields) {
    const field = document.createElement("div");
    const title = document.createElement("label");
    title.textContent = label;
    const input = document.createElement("input");
    input.id = `hyperparameter-${name}`;
    title.htmlFor = input.id;
    input.type = "number";
    input.name = name;
    input.min = min;
    input.max = max;
    input.step = "any";
    input.required = true;
    input.value = edits[name] ?? defaultValue;
    const hint = document.createElement("span");
    hint.id = `${input.id}-hint`;
    hint.className = "field-hint";
    hint.textContent = description;
    input.setAttribute("aria-describedby", hint.id);
    input.addEventListener("input", () => { edits[name] = input.value; });
    field.append(title, input, hint);
    hyperparameterFields.append(field);
  }
}

function updateEnvironmentSettings() {
  const environment = byId("environment").value;
  const stocked = environment !== "navigation";
  const charging = hasBattery(environment);
  const packing = environment === "pack_and_stage";
  const layouts = hasLayouts(environment);
  const shared = hasSharedAisles(environment);
  const fleet = hasFleet(environment);
  const warmStart = charging && !layouts && !shared;
  const defaults = { algorithm: fleet ? fleetAlgorithm : layouts || shared ? "dqn" : "q_learning", traffic: "none", mission: "deliver" };
  if (stocked && !navigationSettings) {
    navigationSettings = Object.fromEntries(Object.keys(defaults).map((id) => [id, byId(id).value]));
  }
  for (const group of byId("algorithm").querySelectorAll("optgroup")) {
    group.hidden = group.disabled = (group.id === "fleet-methods") !== fleet;
  }
  for (const [id, value] of Object.entries(defaults)) {
    const field = byId(id);
    field.disabled = stocked && !(fleet && id === "algorithm");
    if (stocked) field.value = value;
    else if (navigationSettings) field.value = navigationSettings[id];
  }
  if (!stocked) navigationSettings = null;
  const note = byId("environment-note");
  note.hidden = !stocked;
  const environmentNotes = {
    stocked_racks: "Wait at the requested bay to load the tote, then deliver to the dock.",
    charging_dock: "Wait at the charging dock to recharge. Training uses both starting charges.",
    pack_and_stage: "Pick the item, wait at the packing station, then take the carton to outbound staging.",
    multiple_layouts: "Train a DQN on one or two floors. The offset cross-aisle is reserved for frozen-policy evaluation.",
    shared_aisles: "A scripted AMR replenishes a bay and returns to parking while the DQN handles the order.",
    two_learning_robots: "Each AMR fills one order. IPPO trains with a local critic per AMR. MAPPO trains with a critic that sees both.",
    continuous_fulfillment: "An 80-tick shift releases orders in waves. AMRs wait in marked bays for one packing slot.",
  };
  note.textContent = environmentNotes[environment] ?? "";
  byId("warm-start-option").textContent = packing ? "Warm start with packing practice" : "Warm start from V1";
  byId("training-start-setting").hidden = !warmStart;
  byId("layout-training-setting").hidden = !layouts;
  byId("traffic-setting").hidden = shared || fleet;
  const trainingNote = byId("training-start-note");
  trainingNote.textContent = packing
    ? "Warm start uses the first half of the episodes to practice packing without battery limits. The chart and grid show V3."
    : "Warm start uses the first half of the episodes on V1. The chart and grid show V2.";
  trainingNote.hidden = !warmStart || byId("training-start").value !== "warm";
  byId("charge-preview-setting").hidden = !charging || (shared && byId("aisle-preview").value !== "carton");
  byId("preview-floor-setting").hidden = !layouts;
  byId("aisle-preview-setting").hidden = !shared;
  showHyperparameters();
}

function refreshControls() {
  const running = status === "Training";
  const paused = status === "Paused";
  settings.disabled = !world || pending || running;
  byId("charge-preview").disabled = !world || pending || running;
  byId("preview-floor").disabled = byId("charge-preview").disabled;
  byId("aisle-preview").disabled = byId("charge-preview").disabled;
  byId("evaluation-floor-setting").hidden = !hasLayouts(runConfig?.environment);
  byId("evaluation-floor").disabled = pending || running || !history.length;
  byId("fleet-replay-settings").hidden = !hasFleet(runConfig?.environment);
  byId("fleet-case").disabled = byId("fleet-policy-mode").disabled = byId("evaluation-floor").disabled;
  byId("monitor-settings").disabled = pending || running;
  episodeGrid.setTrainingPaused(paused || status === "Starting");
  hyperparameterSettings.disabled = settings.disabled;
  byId("paused-note").hidden = !paused;
  byId("exposure").disabled = byId("profile").value !== "balanced";
  byId("start").disabled = !world || pending || running;
  byId("start").textContent = runId ? "Start new run" : "Start training";
  byId("pause").disabled = (!running && !paused) || (paused && pending);
  byId("pause").textContent = paused ? "Resume training" : "Pause training";
  byId("replay").disabled = pending || running || !history.length;
  byId("export").disabled = !history.length;
  byId("follow").disabled = !latestTrace;
  const tone = running ? "active" : status === "Complete" ? "success" : "";
  for (const id of ["status", "curve-status"]) {
    byId(id).textContent = status;
    byId(id).dataset.tone = tone;
  }
  const emptyMessage = emptyChartMessages[status === "Starting" ? "Training" : status];
  if (!history.length && emptyMessage) {
    const [title, note] = emptyMessage;
    const heading = byId("chart-empty-heading");
    if (heading.textContent !== title) {
      heading.textContent = title;
      byId("chart-empty-note").textContent = note;
    }
    byId("chart-setup-link").hidden = status !== "Ready" && !paused;
  }
}

function cellCenter(point) {
  return point.map((coordinate) => mapInset + (coordinate + 0.5) * cellSize);
}

function resizeMap() {
  const size = Math.max(1, Math.round(map.getBoundingClientRect().width * Math.min(devicePixelRatio || 1, 2)));
  if (size === map.width) return;
  map.width = map.height = size;
  const scale = size / mapSize;
  mapContext.setTransform(scale, 0, 0, scale, 0, 0);
  floorLayers.clear();
}

function floorLayerFor(layout) {
  if (floorLayers.has(layout)) return floorLayers.get(layout);
  const { cells: floor } = floorPlan(layout);
  const floorLayer = document.createElement("canvas");
  floorLayer.width = floorLayer.height = map.width;
  const scale = floorLayer.width / mapSize;
  const context = floorLayer.getContext("2d");
  context.setTransform(scale, 0, 0, scale, 0, 0);
  context.fillStyle = "#19241f";
  context.fillRect(0, 0, mapSize, mapSize);
  context.font = "650 11px ui-monospace, monospace";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillStyle = "#b0c2b3";
  for (const row of floor.keys()) {
    const [horizontal, vertical] = cellCenter([row, row]);
    context.fillText(String.fromCharCode(65 + row), horizontal, 16);
    context.fillText(String(row + 1).padStart(2, "0"), 15, vertical);
  }
  for (const [row, cells] of floor.entries()) {
    for (const [column, marker] of [...cells].entries()) {
      const left = mapInset + column * cellSize;
      const top = mapInset + row * cellSize;
      const wall = marker === "#" && (row === 0 || row === floor.length - 1 || column === 0 || column === cells.length - 1);
      context.fillStyle = wall ? "#23312a" : layout === "original" && row === 5 ? "#34453b" : "#2b3a32";
      context.fillRect(left + 0.5, top + 0.5, cellSize - 1, cellSize - 1);
      if (wall) {
        context.strokeStyle = "#3b4c41";
        context.beginPath();
        for (const offset of [0, 10, 20]) {
          context.moveTo(left + 8 + offset, top + 32);
          context.lineTo(left + 16 + offset, top + 12);
        }
        context.stroke();
      } else if (marker === "#") {
        context.fillStyle = "#1e2b24";
        context.fillRect(left + 5, top + 8, 36, 34);
        context.fillStyle = "#6f8575";
        context.fillRect(left + 4, top + 5, 36, 33);
        for (const offset of [9, 24]) {
          context.fillStyle = "#43584c";
          context.fillRect(left + 8, top + offset, 28, 10);
          context.fillStyle = "#97a68a";
          context.fillRect(left + 10, top + offset + 2, 9, 6);
          context.fillRect(left + 21, top + offset + 2, 12, 6);
        }
      }
      if (marker === "S" || marker === "D") {
        const dock = marker === "D";
        context.fillStyle = dock ? "#46573a" : "#3c5145";
        context.fillRect(left + 3, top + 3, cellSize - 6, cellSize - 6);
        context.strokeStyle = dock ? "#b5cc78" : "#88a398";
        context.lineWidth = 2;
        context.strokeRect(left + 3, top + 3, cellSize - 6, cellSize - 6);
        context.fillStyle = dock ? mapLime : "#d4e3d8";
        context.font = "650 9px ui-monospace, monospace";
        context.fillText(dock ? "DOCK" : "START", left + cellSize / 2, top + 37);
      }
    }
  }
  context.strokeStyle = "#5c7061";
  context.lineWidth = 1;
  context.strokeRect(mapInset - 0.5, mapInset - 0.5, cellSize * floor[0].length + 1, cellSize * floor.length + 1);
  floorLayers.set(layout, floorLayer);
  return floorLayer;
}

function floorPlan(layout) {
  return layout === "fulfillment" ? world.fulfillment.floor : world.floor_plans[layout];
}

function traceHeadings(frames, vehicle) {
  let angle = 0;
  return frames.map((frame, index) => {
    const before = frames[index - 1]?.[vehicle];
    const after = frame[vehicle];
    if (before && after && (before[0] !== after[0] || before[1] !== after[1])) {
      angle = Math.atan2(after[1] - before[1], after[0] - before[0]);
    }
    return angle;
  });
}

function vehicleHeadings(frames) {
  return Object.fromEntries(
    ["robot", "forklift", "scripted_robot", "second_robot"].filter((vehicle) => frames[0][vehicle])
      .map((vehicle) => [vehicle, traceHeadings(frames, vehicle)]),
  );
}

function vehiclePose(frames, targetTick, fraction, vehicle, headings) {
  const previousTick = Math.max(0, targetTick - 1);
  const destination = frames[targetTick][vehicle];
  const origin = frames[previousTick][vehicle] || destination;
  const position = cellCenter(destination.map((coordinate, axis) => origin[axis] + (coordinate - origin[axis]) * fraction));
  const turn = headings[targetTick] - headings[previousTick];
  const angle = headings[previousTick] + Math.atan2(Math.sin(turn), Math.cos(turn)) * fraction;
  return { position, angle };
}

function drawForklift(context, pose) {
  context.save();
  context.translate(...pose.position);
  context.rotate(pose.angle);
  context.fillStyle = "#141e19";
  context.fillRect(-12, -11, 19, 22);
  context.fillStyle = mapOrange;
  context.fillRect(-12, -8, 21, 16);
  context.fillRect(9, -7, 9, 3);
  context.fillRect(9, 4, 9, 3);
  context.fillStyle = "#503323";
  context.fillRect(-5, -5, 8, 10);
  context.fillRect(6, -10, 3, 20);
  context.restore();
}

function drawRobot(context, pose, carryingParcel, arrived, color = mapLime) {
  context.save();
  context.translate(...pose.position);
  context.rotate(pose.angle);
  context.fillStyle = "#131f18";
  context.beginPath();
  context.roundRect(-14, -12, 29, 26, 6);
  context.fill();
  context.fillStyle = color;
  context.beginPath();
  context.roundRect(-12, -10, 25, 20, [4, 7, 7, 4]);
  context.fill();
  context.fillStyle = "#3b512e";
  context.fillRect(8, -5, 2, 10);
  if (arrived) {
    context.rotate(-pose.angle);
    context.beginPath();
    context.moveTo(-6, 0);
    context.lineTo(-2, 4);
    context.lineTo(4, -4);
    context.strokeStyle = "#3b512e";
    context.lineWidth = 2;
    context.stroke();
  } else if (carryingParcel) {
    context.fillStyle = "#536b3a";
    context.fillRect(-8, -5, 11, 10);
    context.fillStyle = "#bfce71";
    context.fillRect(-4, -5, 2, 10);
  }
  context.restore();
}

function paintMap(targetTick, fraction = 1, feedbackProgress = 1) {
  if (!world || !trace.length) return;
  paintTrace(mapContext, trace, headings, targetTick, fraction, feedbackProgress);
}

function paintGridTrace(context, frames, position) {
  if (!gridHeadings.has(frames)) {
    gridHeadings.set(frames, vehicleHeadings(frames));
  }
  const headings = gridHeadings.get(frames);
  const scale = context.canvas.width / mapSize;
  context.setTransform(scale, 0, 0, scale, 0, 0);
  const targetTick = Math.ceil(position);
  const fraction = position % 1 || 1;
  paintTrace(context, frames, headings, targetTick, fraction);
}

function drawStation(context, point, label, fill, accent) {
  const [horizontal, vertical] = cellCenter(point);
  context.fillStyle = fill;
  context.fillRect(horizontal - 19, vertical - 19, 38, 38);
  context.fillStyle = context.strokeStyle = accent;
  context.lineWidth = 1.5;
  context.strokeRect(horizontal - 19, vertical - 19, 38, 38);
  context.font = "650 8px ui-monospace, monospace";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(label, horizontal, vertical + 15);
}

function paintTrace(context, frames, directions, targetTick, fraction, feedbackProgress = 1) {
  const frame = frames[fraction === 1 ? targetTick : Math.max(0, targetTick - 1)];
  const floor = floorPlan(frame.layout);
  const robot = vehiclePose(frames, targetTick, fraction, "robot", directions.robot);
  const forklift = frame.forklift && vehiclePose(frames, targetTick, fraction, "forklift", directions.forklift);
  context.drawImage(floorLayerFor(frame.layout), 0, 0, mapSize, mapSize);
  context.lineCap = "round";
  context.lineJoin = "round";
  if (frame.charge != null) {
    drawStation(context, floor.charger, "CHARGE", "#354f50", "#b8e4e6");
  }
  if (frame.pack_tick !== undefined) {
    drawStation(context, floor.packing_station, "PACK", "#574631", "#ffcc98");
    drawStation(context, floor.dock, "STAGE", "#46573a", mapLime);
  }
  if (frame.order) {
    for (const [item, [bay, point]] of Object.entries(floor.pick_bays)) {
      const highlighted = item === frame.order;
      drawStation(context, point, `PICK ${bay}`, highlighted ? "#46573a" : "#3c5145", highlighted ? mapLime : "#b0c2b3");
    }
  }
  if (frame.scripted_robot) {
    drawStation(context, world.shared_aisles.parking, "PARK", "#2c4652", mapBlue);
    drawStation(context, world.shared_aisles.replenishment_bay, "REFILL", "#2c4652", mapBlue);
  }
  if (frame.fleet) {
    world.fleet.chargers.forEach((point, index) =>
      drawStation(context, point, `CHARGE ${index + 1}`, "#354f50", "#b8e4e6"));
    const service = frame.shift?.service_left;
    drawStation(context, floor.packing_station, service ? `PACK ${service}` : "PACK", "#574631", "#ffcc98");
    drawStation(context, floor.dock, "STAGE", "#46573a", mapLime);
    if (frame.shift) {
      world.fulfillment.queue_bays.forEach((point, index) =>
        drawStation(context, point, `WAIT ${index + 1}`, "#333951", "#c4c9fc"));
    }
    for (const [item, [bay, point]] of Object.entries(floor.pick_bays)) {
      const color = frame.shift ? "#b0c2b3" : item === frame.fleet[0].order ? mapLime : mapBlue;
      drawStation(context, point, `PICK ${bay}`, "#3c5145", color);
    }
  }
  if (forklift) {
    context.beginPath();
    context.moveTo(...cellCenter(world.patrol[0]));
    for (const point of world.patrol.slice(1)) context.lineTo(...cellCenter(point));
    context.closePath();
    context.setLineDash([3, 6]);
    context.strokeStyle = "#cc946e";
    context.lineWidth = 2;
    context.stroke();
    context.setLineDash([]);
  }
  if (previewFrames.has(frames)) {
    context.beginPath();
    context.moveTo(...robot.position);
    for (let index = targetTick; index < frames.length; index += 1) context.lineTo(...cellCenter(frames[index].robot));
    context.setLineDash([3, 6]);
    context.strokeStyle = "#a0b26e";
    context.lineWidth = 2;
    context.stroke();
    context.setLineDash([]);
  }
  if (targetTick && !frame.fleet) {
    context.beginPath();
    context.moveTo(...cellCenter(frames[0].robot));
    for (let index = 1; index < targetTick; index += 1) context.lineTo(...cellCenter(frames[index].robot));
    context.lineTo(...robot.position);
    context.strokeStyle = "#afc56a";
    context.lineWidth = 3;
    context.stroke();
  }
  const arrived = completed(frame) || frame.tick === frame.delivery_tick;
  const failed = frame.outcome === "collision" || frame.outcome === "depleted";
  const [horizontal, vertical] = robot.position;
  if (arrived || failed || frame.exposure || frame.blocked || frame.primary_denied) {
    const color = failed ? "#ff8c7c" : arrived ? mapLime : mapOrange;
    context.strokeStyle = color;
    context.lineWidth = 1.5;
    context.beginPath();
    context.roundRect(horizontal - 19, vertical - 17, 38, 34, 7);
    context.stroke();
    if (feedbackProgress < 1) {
      const radius = 19 + 23 * (1 - (1 - feedbackProgress) ** 3);
      context.globalAlpha = 0.85 * (1 - feedbackProgress);
      context.beginPath();
      context.arc(horizontal, vertical, radius, 0, Math.PI * 2);
      context.stroke();
      context.globalAlpha = 1;
    }
  }
  if (forklift) drawForklift(context, forklift);
  if (frame.scripted_robot) {
    const scripted = vehiclePose(frames, targetTick, fraction, "scripted_robot", directions.scripted_robot);
    drawRobot(context, scripted, !frame.replenished, frame.script_parked, mapBlue);
    if (frame.scripted_denied) {
      const [column, row] = scripted.position;
      context.strokeStyle = mapOrange;
      context.lineWidth = 1.5;
      context.beginPath();
      context.roundRect(column - 19, row - 17, 38, 34, 7);
      context.stroke();
    }
  }
  if (frame.fleet) {
    paintFleetRobots(context, frames, directions, targetTick, fraction, frame);
  } else {
    drawRobot(context, robot, frame.order ? frame.cargo != null : frame.delivery_tick == null, arrived);
  }
}

function paintFleetRobots(context, frames, directions, targetTick, fraction, frame) {
  frame.fleet.forEach((robot, index) => {
    if (!frames[targetTick].fleet[index].present) return;
    const vehicle = index ? "second_robot" : "robot";
    const color = index ? mapBlue : mapLime;
    const pose = vehiclePose(frames, targetTick, fraction, vehicle, directions[vehicle]);
    drawRobot(context, pose, robot.cargo != null, robot.outcome === "delivered", color);
    if (robot.denied) {
      const [horizontal, vertical] = pose.position;
      context.strokeStyle = mapOrange;
      context.lineWidth = 1.5;
      context.beginPath();
      context.roundRect(horizontal - 19, vertical - 17, 38, 34, 7);
      context.stroke();
    }
  });
}

function paintChart() {
  const width = chart.clientWidth;
  const height = chart.clientHeight;
  if (!history.length || !width || !height) return;
  const ratio = window.devicePixelRatio || 1;
  chart.width = Math.round(width * ratio);
  chart.height = Math.round(height * ratio);
  const context = chart.getContext("2d");
  context.scale(ratio, ratio);
  const style = getComputedStyle(chart);
  const fontSize = parseFloat(style.fontSize) * 0.8;
  context.font = `${fontSize}px ${style.fontFamily}`;
  context.textBaseline = "middle";

  const lowest = Math.floor(Math.min(-100, ...history.map((result) => result.reward)) / 50) * 50;
  const highest = Math.max(100, Math.ceil(-lowest / 250) * 50);
  const ticks = [lowest, 0, highest];
  const left = Math.ceil(Math.max(...ticks.map((value) => context.measureText(signed(value)).width))) + 8;
  const right = width - 5;
  const top = fontSize;
  const bottom = height - fontSize * 3.5;
  if (right <= left || bottom <= top) return;
  const coordinates = (episode, reward) => [
    left + (right - left) * episode / total,
    bottom - (bottom - top) * (reward - lowest) / (highest - lowest),
  ];
  context.fillStyle = style.getPropertyValue("--muted").trim();
  context.textAlign = "right";
  for (const value of ticks) {
    const [, vertical] = coordinates(0, value);
    context.strokeStyle = style.getPropertyValue(value === 0 ? "--chart-zero" : "--line").trim();
    context.setLineDash(value === 0 ? [4, 3] : []);
    context.beginPath();
    context.moveTo(left, vertical);
    context.lineTo(right, vertical);
    context.stroke();
    context.fillText(signed(value), left - 8, vertical);
  }
  context.setLineDash([]);
  context.textAlign = "left";
  context.fillText("0", left, bottom + fontSize);
  context.textAlign = "right";
  context.fillText(number(total, 0), right, bottom + fontSize);
  context.textAlign = "center";
  const middleEpisode = Math.floor(total / 2);
  context.fillText(number(middleEpisode, 0), coordinates(middleEpisode, 0)[0], bottom + fontSize);
  context.fillText("Training episode", (left + right) / 2, bottom + fontSize * 2.5);

  const dotRadius = history.length <= 200 ? 2.5 : 1.5;
  context.fillStyle = style.getPropertyValue("--chart-dot").trim();
  context.globalAlpha = 0.8;
  for (const result of history) {
    const [horizontal, vertical] = coordinates(result.episode, result.reward);
    context.beginPath();
    context.arc(horizontal, vertical, dotRadius, 0, Math.PI * 2);
    context.fill();
  }
  context.globalAlpha = 1;
  context.beginPath();
  averages.forEach((reward, index) => {
    const point = coordinates(index + 1, reward);
    if (index === 0) context.moveTo(...point);
    else context.lineTo(...point);
  });
  context.strokeStyle = style.getPropertyValue("--orange").trim();
  context.lineWidth = 2.25;
  context.lineJoin = "round";
  context.stroke();
}

function refreshMetrics() {
  const count = history.length;
  const latest = history.at(-1);
  const recent = history.slice(-25);
  const success = latest?.released != null
    ? recent.reduce((total, row) => total + row.orders_completed, 0) / recent.reduce((total, row) => total + row.released, 0)
    : recent.filter(completed).length / recent.length;
  byId("completion-label").textContent = hasShift(runConfig?.environment) ? "Orders staged" : "Completion rate";
  const target = document.createElement("small");
  target.textContent = `/ ${number(total, 0)}`;
  byId("episode-stat").replaceChildren(`${number(count, 0)} `, target);
  byId("success-stat").textContent = count ? `${number(success * 100, 0)}%` : "—";
  byId("reward-stat").textContent = count ? signed(averages.at(-1)) : "—";
  const epsilonStat = byId("epsilon-stat");
  epsilonStat.textContent = "—";
  if (count) {
    epsilonStat.textContent = latest.epsilon == null ? "N/A" : `${number(latest.epsilon * 100)}%`;
  }
  byId("progress").max = total;
  byId("progress").value = count;
  byId("progress-label").textContent = `${number(count, 0)} of ${number(total, 0)} episodes`;
  byId("chart-empty").hidden = Boolean(count);
  byId("chart-figure").hidden = !count;
  if (count) {
    chart.setAttribute("aria-label", `Returns for ${number(count, 0)} training episodes. Latest episode return ${signed(latest.reward)}. Latest rolling average ${signed(averages.at(-1))}.`);
  }
  byId("outcome").textContent = count ? outcomeLabel(latest) : "—";
  byId("outcome").dataset.tone = completed(latest) ? "success" : latest ? "active" : "";
  byId("steps").textContent = count ? latest.steps : "—";
  byId("energy").textContent = count ? number(latest.energy, 2) : "—";
  byId("exposures").textContent = count ? latest.exposures : "—";
  const shared = latest?.release_tick != null;
  const fleet = latest?.orders_completed != null;
  const shift = latest?.released != null;
  for (const id of ["primary-denial-metric", "scripted-denial-metric"]) byId(id).hidden = !shared;
  byId("stall-metric").hidden = !shared && !fleet;
  if (shared) {
    byId("primary-denials").textContent = latest.primary_denials;
    byId("scripted-denials").textContent = latest.scripted_denials;
  }
  if (fleet || shared) byId("stall-ticks").textContent = latest.stall_ticks;
  for (const id of ["fleet-orders-metric", "fleet-waits-metric", "fleet-denials-metric"]) byId(id).hidden = !fleet;
  if (fleet) {
    byId("fleet-orders").textContent = `${latest.orders_completed}/${latest.released ?? 2}`;
    byId("fleet-waits").textContent = `${latest.first_waits} / ${latest.second_waits}`;
    byId("fleet-denials").textContent = `${latest.first_denials} / ${latest.second_denials}`;
  }
  for (const [id, field] of [["throughput", "throughput"], ["queue", "queue_wait_ticks"], ["backlog", "backlog"]]) {
    byId(`shift-${id}-metric`).hidden = !shift;
    if (shift) byId(`shift-${id}`).textContent = number(latest[field], 2);
  }
  paintChart();
}

function describeFleet(frame, location) {
  return frame.fleet.map((robot, index) => {
    const state = robot.outcome === "depleted" ? "Battery depleted"
      : robot.denied ? "Move denied"
      : robot.delivery_tick === frame.tick ? "Order staged"
      : frame.shift && robot.delivery_tick != null ? "Returning to charger"
      : frame.shift && robot.order_id === frame.shift.packing_id && robot.order_id != null ? "In packing service"
      : frame.shift?.queue.includes(robot.order_id) ? "Waiting for packing"
      : !robot.present ? "Exited through staging"
      : robot.pack_tick === frame.tick ? "Packed carton"
      : robot.pickup_tick === frame.tick ? "Picked up item"
      : robot.charged ? `Charged +${number(robot.charged)}`
      : robot.cargo ? robot.pack_tick == null ? "Carrying tote" : "Carrying packed carton" : "Tote empty";
    const [bay] = floorPlan(frame.layout).pick_bays[robot.order] ?? [];
    const job = robot.order ? `${robot.order_id ? `#${robot.order_id} ` : ""}${robot.order} at bay ${bay}` : "Available";
    const action = robot.action ? ` · ${robot.action}` : "";
    const status = `AMR ${index + 1} · ${job}${action} · ${state} · Battery ${number(robot.charge)}/${number(robot.charge_capacity)} · ${robot.waits} stationary · ${robot.denials} denied`;
    byId(index ? "fleet-second-status" : "fleet-first-status").textContent = status;
    return `${status}. ${robot.present ? `At ${location(robot.robot)}. ` : ""}`;
  }).join("");
}

function describeShift(shift) {
  byId("shift-panel").hidden = !shift;
  if (!shift) return;
  byId("shift-orders").textContent = `Released ${shift.released} · Staged ${shift.orders_completed} · Backlog ${shift.backlog} (${shift.unassigned} unassigned)`;
  const packing = shift.packing_id == null ? "Packing idle" : `Packing #${shift.packing_id} · ${shift.service_left} ticks left`;
  const queue = shift.queue.length ? shift.queue.map((id) => `#${id}`).join(", ") : "Empty";
  byId("shift-packing").textContent = `${packing} · FIFO queue ${queue} · ${shift.queue_wait_ticks} queue ticks`;
  const stock = Object.entries(shift.stock).map(([item, count]) => `${item} ${count} (${shift.reserved[item]} reserved)`);
  byId("shift-stock").textContent = `Rack stock · ${stock.join(" · ")}`;
  byId("shift-order-list").replaceChildren(...shift.orders.map((order) => {
    const stage = order.delivery_tick != null ? `Staged at tick ${order.delivery_tick}`
      : order.stranded_tick != null ? `Stranded at tick ${order.stranded_tick}`
      : order.pack_tick != null ? "Packed"
      : order.pack_start_tick != null ? "In packing"
      : order.queue_tick != null ? "Queued"
      : order.pickup_tick != null ? "Picked"
      : order.robot != null ? "Reserved" : "Awaiting assignment";
    const entry = document.createElement("li");
    const assigned = order.robot == null ? "" : ` · AMR ${order.robot}`;
    entry.textContent = `#${order.id} ${order.item} · Released ${order.release_tick}${assigned} · ${stage}`;
    return entry;
  }));
}

function describeTick() {
  const frame = trace[tick];
  if (!frame) return;
  const floor = floorPlan(frame.layout);
  byId("tick").textContent = String(frame.tick).padStart(2, "0");
  scrub.value = tick;
  byId("trace-limit").textContent = `${tick} / ${trace.length - 1}`;
  const droppedOff = frame.outcome === "running" && frame.tick === frame.delivery_tick;
  const pickedUp = frame.order && frame.tick === frame.pickup_tick;
  const packed = frame.tick === frame.pack_tick;
  const replenished = frame.replenished && !trace[tick - 1]?.replenished;
  const parked = frame.script_parked && !trace[tick - 1]?.script_parked;
  const event = [frame.action, frame.blocked && "Blocked move", frame.exposure && "Forklift exposure",
    conflictLabels[frame.conflict],
    frame.primary_denied && "Order AMR denied",
    frame.scripted_denied && "Replenishment AMR denied",
    replenished && "Bay replenished",
    parked && "Replenishment AMR parked",
    pickedUp && `Picked up ${frame.order}`,
    packed && `Packed ${frame.order}`,
    frame.charged > 0 && `Charged +${number(frame.charged)}`,
    droppedOff && "Parcel delivered · return to base",
    frame.fleet && frame.outcome === "running" && frame.fleet.some((robot) => robot.delivery_tick === tick) && "One order staged",
    outcomeLabel(frame)].filter(Boolean).join(" · ");
  byId("event").textContent = event || (frame.fleet && tick ? "Both AMR requests resolved" : "Episode start");
  eventReadout.dataset.tone = completed(frame) || droppedOff ? "success"
    : frame.blocked || frame.exposure || frame.conflict || ["collision", "depleted"].includes(frame.outcome) ? "warning" : "";
  byId("step-reward").textContent = tick ? signed(Object.values(frame.rewards).reduce((sum, value) => sum + value, 0)) : "—";
  for (const output of document.querySelectorAll("[data-term]")) {
    output.textContent = tick ? signed(frame.rewards[output.dataset.term] ?? 0) : "—";
  }
  const location = ([column, row]) => `column ${String.fromCharCode(65 + column)}, row ${row + 1}`;
  const forklift = frame.forklift ? ` Forklift at ${location(frame.forklift)}.` : "";
  const aisleStatus = byId("aisle-status");
  aisleStatus.hidden = !frame.scripted_robot;
  byId("scripted-robot-key").hidden = !frame.scripted_robot;
  byId("second-robot-key").hidden = !frame.fleet;
  byId("forklift-map-key").hidden = Boolean(frame.scripted_robot || frame.fleet);
  byId("primary-robot-key").textContent = frame.fleet ? "AMR 1" : frame.scripted_robot ? "Order AMR" : "Robot";
  byId("fleet-first-status").hidden = byId("fleet-second-status").hidden = !frame.fleet;
  describeShift(frame.shift);
  let scripted = "";
  if (frame.scripted_robot) {
    const stage = frame.script_parked ? "Parked" : frame.replenished ? "Returning to parking"
      : tick <= frame.release_tick ? `Waiting to depart after tick ${frame.release_tick}` : "Carrying replenishment tote";
    const request = frame.script_action ? ` · Requested ${frame.script_action.toLowerCase()}` : "";
    aisleStatus.textContent = `${stage}${request} · Denials ${frame.primary_denials} order / ${frame.scripted_denials} replenishment · Stall ticks ${frame.stall_ticks}`;
    scripted = ` Replenishment AMR at ${location(frame.scripted_robot)}. ${aisleStatus.textContent}.`;
  }
  const orderStatus = byId("order-status");
  orderStatus.hidden = !frame.order;
  let order = "";
  if (frame.order) {
    const [bay, point] = floor.pick_bays[frame.order];
    const stock = Object.entries(frame.stock).map(([item, count]) => `${floor.pick_bays[item][0]} ${item} ×${count}`);
    const cargo = frame.cargo && frame.pack_tick != null ? `Carton ${frame.cargo} packed` : `Tote ${frame.cargo ?? "empty"}`;
    orderStatus.textContent = `Order ${frame.order} at bay ${bay} · ${cargo} · Stock ${stock.join(", ")}`;
    order = ` Pick bay ${bay} at ${location(point)}. ${orderStatus.textContent}.`;
  }
  const batteryStatus = byId("battery-status");
  batteryStatus.hidden = frame.charge == null;
  let battery = "";
  if (frame.charge != null) {
    batteryStatus.textContent = `Battery ${number(frame.charge)} / ${number(frame.charge_capacity)} · Charging ticks ${frame.charge_ticks}`;
    battery = ` Charging dock at ${location(floor.charger)}. ${batteryStatus.textContent}.`;
  }
  const packing = frame.pack_tick === undefined ? "" :
    ` Packing station at ${location(floor.packing_station)}. Outbound staging at ${location(floor.dock)}.`;
  const robots = frame.fleet ? describeFleet(frame, location) : `Robot at ${location(frame.robot)}.`;
  map.setAttribute("aria-label", `${floor.name} floor. Tick ${frame.tick}. ${robots}${forklift}${scripted}${order}${battery}${packing}`);
}

function suspendPlaybackFrames() {
  cancelAnimationFrame(playbackFrame);
  playbackFrame = 0;
  animationStart = null;
}

function queuePlaybackFrame() {
  if (playing && playbackVisible && !document.hidden && !playbackFrame) {
    playbackFrame = requestAnimationFrame(animate);
  }
}

function stopPlayback() {
  playing = false;
  suspendPlaybackFrames();
  play.textContent = "Play trace";
  play.dataset.playing = "false";
}

function setTrace(frames, label, autoplay, duration = 270) {
  stopPlayback();
  if (!frames?.length) return;
  trace = frames;
  headings = vehicleHeadings(frames);
  tick = 0;
  stepProgress = 0;
  traceDuration = duration;
  scrub.max = frames.length - 1;
  scrub.disabled = frames.length < 2;
  play.disabled = frames.length < 2;
  byId("trace-title").textContent = label;
  describeTick();
  paintMap(0);
  if (autoplay) startPlayback();
}

function inspectGridTrace({ episode, frames }) {
  following = false;
  queuedTrace = null;
  setTrace(frames, trainingTraceLabel(episode), false);
  const heading = byId("floor-heading");
  heading.focus({ preventScroll: true });
  heading.scrollIntoView({ block: "start" });
}

function terminalFeedback() {
  const frame = trace[tick];
  return tick === trace.length - 1 && (completed(frame) || ["collision", "depleted"].includes(frame?.outcome)) && !motion.matches;
}

function paintCurrentMap() {
  if (stepProgress && tick < trace.length - 1 && !motion.matches) {
    const eased = stepProgress ** 2 * (3 - 2 * stepProgress);
    paintMap(tick + 1, eased);
  } else {
    paintMap(tick, 1, playing && terminalFeedback() ? stepProgress : 1);
  }
}

function finishPlayback() {
  stopPlayback();
  paintMap(tick);
  if (following && queuedTrace) {
    const nextTrace = queuedTrace;
    queuedTrace = null;
    setTrace(nextTrace.frames, nextTrace.label, true, 110);
  }
}

function previewMission(environment, roundTrip) {
  following = false;
  queuedTrace = null;
  if (hasShift(environment)) {
    setTrace(world.fulfillment.preview, "Dispatch preview · burst workload · carton first", false);
    return;
  }
  if (hasFleet(environment)) {
    setTrace(world.fleet.preview, "Joint reference preview · AMR 1 carton · both low charge", false);
    return;
  }
  if (hasSharedAisles(environment)) {
    const choice = byId("aisle-preview");
    const scenario = choice.value;
    const charge = byId("charge-preview").value;
    const preview = world.shared_aisles.previews[scenario];
    byId("charge-preview-setting").hidden = scenario !== "carton";
    if (scenario === "carton") {
      previewFrames.add(preview[charge]);
      setTrace(preview[charge], `Shared aisles · carton route · ${charge} starting charge`, false);
    } else {
      setTrace(preview, `Shared aisles · ${choice.selectedOptions[0].text}`, false);
    }
    return;
  }
  if (hasBattery(environment)) {
    const charge = byId("charge-preview").value;
    const layout = hasLayouts(environment) ? byId("preview-floor").value : "original";
    const demos = hasPacking(environment) ? world.floor_plans[layout].demos : world.charging_demos;
    const label = hasPacking(environment) ? "Pack and stage preview" : "Shortest-path preview";
    const suffix = hasLayouts(environment) ? layoutSuffix({ layout }) : "";
    previewFrames.add(demos[charge]);
    setTrace(demos[charge], `${label}${suffix} · ${charge} starting charge`, false);
    return;
  }
  const stocked = environment === "stocked_racks";
  const frames = stocked ? world.stocked_racks_demo : roundTrip ? world.round_trip_demo : world.demo;
  const mission = stocked ? "pick and deliver" : roundTrip ? "dock and back" : "dock only";
  previewFrames.add(frames);
  setTrace(frames, `Shortest-path preview · ${mission} · no traffic`, false);
}

function animate(timestamp) {
  playbackFrame = 0;
  if (!playing) return;
  const settling = terminalFeedback();
  const duration = settling ? feedbackDuration : traceDuration;
  animationStart ??= timestamp - stepProgress * duration;
  stepProgress = Math.min(1, (timestamp - animationStart) / duration);
  if (stepProgress === 1) {
    stepProgress = 0;
    if (tick === trace.length - 1) {
      finishPlayback();
      return;
    }
    tick += 1;
    animationStart = timestamp;
    describeTick();
    if (tick === trace.length - 1 && !terminalFeedback()) {
      finishPlayback();
      return;
    }
    paintCurrentMap();
  } else if (!motion.matches) {
    paintCurrentMap();
  }
  queuePlaybackFrame();
}

function startPlayback() {
  if (trace.length < 2) return;
  if (tick === trace.length - 1) {
    tick = 0;
    stepProgress = 0;
    describeTick();
    paintMap(0);
  }
  playing = true;
  play.textContent = "Pause trace";
  play.dataset.playing = "true";
  queuePlaybackFrame();
}

function scheduleBatch(delay = 130) {
  clearTimeout(trainingTimer);
  if (status === "Training") trainingTimer = setTimeout(advance, delay);
}

async function advance() {
  if (status !== "Training" || pending) return;
  pending = true;
  refreshControls();
  try {
    const result = await request("advance", { run_id: runId, cursor: history.length });
    for (const episode of result.episodes) {
      history.push(episode);
      const recent = history.slice(-25);
      averages.push(recent.reduce((sum, item) => sum + item.reward, 0) / recent.length);
    }
    if (result.frames) {
      const latest = history.at(-1);
      const firstTrace = latestTrace === null;
      latestTrace = { frames: result.frames, label: trainingTraceLabel(latest) };
      if (firstTrace || (following && !playing)) setTrace(latestTrace.frames, latestTrace.label, following, 110);
      else if (following) queuedTrace = latestTrace;
      episodeGrid.record(latest, result.frames, result.complete);
    }
    if (result.episodes.length) clearEvaluation();
    if (result.complete) status = "Complete";
    refreshMetrics();
  } catch (error) {
    status = "Paused";
    showError(`Training paused. ${error.message}`);
  } finally {
    pending = false;
    refreshControls();
    scheduleBatch();
  }
}

setup.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (pending || status === "Training") return;
  const hyperparameters = Object.fromEntries(
    Array.from(hyperparameterFields.querySelectorAll("input"), (input) => [input.name, input.valueAsNumber]),
  );
  const config = {
    episodes: byId("episodes").valueAsNumber,
    seed: byId("seed").valueAsNumber,
    environment: byId("environment").value,
    algorithm: byId("algorithm").value,
    traffic: byId("traffic").value,
    round_trip: byId("mission").value === "return",
    profile: byId("profile").value,
    exposure_cost: byId("profile").value === "balanced" ? byId("exposure").valueAsNumber : 0,
    ...hyperparameters,
  };
  if (hasLayouts(config.environment)) config.layout_training = byId("layout-training").value;
  else if (config.environment === "charging_dock" || config.environment === "pack_and_stage") {
    config.warm_start = byId("training-start").value === "warm";
  }
  const previousStatus = status;
  pending = true;
  status = "Starting";
  refreshControls();
  showError("");
  try {
    const result = await request("start", config);
    runId = result.run_id;
    runConfig = result.config;
    if (hasFleet(config.environment)) configureFleetCases(config.environment);
    byId("reference").textContent = hasShift(config.environment) ? "Play dispatch reference" : "Play fastest route";
    history.length = 0;
    averages.length = 0;
    total = runConfig.target_episodes ?? config.episodes;
    following = false;
    latestTrace = null;
    queuedTrace = null;
    clearEvaluation();
    previewMission(config.environment, config.round_trip);
    status = "Training";
    episodeGrid.reset(total);
    refreshMetrics();
  } catch (error) {
    status = previousStatus;
    showError(error.message);
  } finally {
    pending = false;
    refreshControls();
    scheduleBatch(0);
  }
});

byId("pause").addEventListener("click", () => {
  status = status === "Training" ? "Paused" : "Training";
  if (status === "Training") {
    showError("");
  }
  refreshControls();
  scheduleBatch(0);
});

byId("algorithm").addEventListener("change", () => {
  if (hasFleet(byId("environment").value)) fleetAlgorithm = byId("algorithm").value;
  showHyperparameters();
});
byId("environment").addEventListener("change", () => {
  updateEnvironmentSettings();
  previewMission(byId("environment").value, byId("mission").value === "return");
});
byId("training-start").addEventListener("change", () => {
  byId("training-start-note").hidden = byId("training-start").value !== "warm";
});
byId("charge-preview").addEventListener("change", () => previewMission(byId("environment").value, false));
byId("preview-floor").addEventListener("change", () => previewMission(byId("environment").value, false));
byId("aisle-preview").addEventListener("change", () => previewMission(byId("environment").value, false));
byId("evaluation-floor").addEventListener("change", clearEvaluation);
byId("fleet-case").addEventListener("change", clearEvaluation);
byId("fleet-policy-mode").addEventListener("change", clearEvaluation);
byId("mission").addEventListener("change", () => {
  if (!runId) previewMission(byId("environment").value, byId("mission").value === "return");
});
byId("reset-hyperparameters").addEventListener("click", () => {
  hyperparameterEdits.delete(byId("algorithm").value);
  showHyperparameters();
});
hyperparameterSettings.addEventListener("invalid", () => {
  byId("advanced-settings").open = true;
}, true);

byId("profile").addEventListener("change", (event) => {
  byId("profile-note").textContent = profileDescriptions[event.target.value];
  refreshControls();
});

function clearEvaluation() {
  byId("policy-evaluation").hidden = true;
  byId("reference").hidden = true;
  referenceTrace = null;
}

function configureFleetCases(environment) {
  const menu = byId("fleet-case");
  const shift = hasShift(environment);
  const cases = shift ? world.fulfillment.cases : world.fleet.cases;
  menu.replaceChildren(...cases.map(([first, second, third], index) => new Option(
    shift ? `${workloadLabels[first]} · ${second.toLowerCase()} first` : `AMR 1 ${first.toLowerCase()} · charge ${second} / ${third}`,
    index,
  )));
  menu.selectedIndex = shift ? 2 : 0;
}

byId("reference").addEventListener("click", () => {
  if (!referenceTrace) return;
  following = false;
  queuedTrace = null;
  const suffix = hasLayouts(runConfig.environment) ? layoutSuffix(referenceTrace[0]) : "";
  const label = hasShift(runConfig.environment) ? "Centralized dispatch reference"
    : hasFleet(runConfig.environment) ? "Fastest joint route" : "Fastest collision-free route";
  setTrace(referenceTrace, `${label}${suffix} · ${referenceTrace.length - 1} ticks`, !motion.matches);
});

byId("replay").addEventListener("click", async () => {
  pending = true;
  refreshControls();
  showError("");
  try {
    const replay = await request("replay", {
      run_id: runId,
      ...(hasLayouts(runConfig.environment) && { layout: byId("evaluation-floor").value }),
      ...(hasFleet(runConfig.environment) && {
        fleet_case: Number(byId("fleet-case").value), policy_mode: byId("fleet-policy-mode").value,
      }),
    });
    following = false;
    queuedTrace = null;
    const result = replay.result;
    const missions = replay.evaluation;
    const successes = missions.filter(completed);
    const fastest = successes.filter((mission) => mission.steps === mission.optimal_steps);
    const shared = result.release_tick != null;
    const scope = shared ? "orders, starting charges, and release times"
      : result.battery_case ? "orders and starting charges"
      : result.order ? "stocked-rack orders" : result.phase == null ? "the static scenario" : "forklift starting phases";
    const evaluation = byId("policy-evaluation");
    const depletions = missions.filter((mission) => mission.outcome === "depleted").length;
    const batterySummary = result.battery_case ? ` Battery depletions ${depletions}/${missions.length}.` : "";
    const floor = result.layout ? world.floor_plans[result.layout] : null;
    const provenance = replay.seen_in_training ? "seen in training" : "unseen in training";
    const floorSummary = floor ? `${floor.name} (${provenance}). ` : "";
    const parked = shared ? ` Replenishment AMR parked in ${missions.filter((mission) => mission.script_parked).length}/${missions.length}.` : "";
    if (hasShift(runConfig.environment)) {
      const group = missions.filter((mission) => mission.workload === result.workload);
      const mean = (field) => number(group.reduce((total, mission) => total + mission[field], 0) / group.length, 2);
      const mode = byId("fleet-policy-mode").value === "sampled" ? "Sampled" : "Highest-probability";
      evaluation.textContent = `${mode} · ${workloadLabels[result.workload]} workload · ${group.length} trials. Mean ${mean("throughput")} orders per 100 ticks, ${mean("backlog")} orders in end backlog, ${mean("queue_wait_ticks")} order queue ticks. Replay staged ${result.orders_completed}/${result.released}. Dispatch reference staged ${result.reference_orders}/${result.released}.`;
    } else if (hasFleet(runConfig.environment)) {
      const sum = (field) => missions.reduce((total, mission) => total + mission[field], 0);
      const mode = byId("fleet-policy-mode").value === "sampled" ? "Sampled" : "Highest-probability";
      evaluation.textContent = `${mode} policy completed both orders in ${successes.length}/${missions.length} trials. ${fastest.length}/${missions.length} matched the minimum time. Staged ${sum("orders_completed")}/${2 * missions.length} orders. Mean stationary ticks per AMR ${number(sum("first_waits") / missions.length)} / ${number(sum("second_waits") / missions.length)}. Denied moves ${sum("first_denials")} / ${sum("second_denials")}. Stall ticks ${sum("stall_ticks")}. Replay ${result.steps} ticks · joint reference ${result.optimal_steps} ticks.`;
    } else {
      evaluation.textContent = `${floorSummary}Completed ${successes.length}/${missions.length} across ${scope}. ${fastest.length}/${missions.length} matched the minimum time.${batterySummary}${parked} The replay took ${result.steps} ticks. The fastest completion takes ${result.optimal_steps}.`;
    }
    evaluation.hidden = false;
    referenceTrace = replay.reference;
    byId("reference").hidden = false;
    setTrace(replay.frames, `Policy replay after episode ${number(result.episode, 0)} · ${outcomeLabel(result)}${layoutSuffix(result)}`, !motion.matches);
  } catch (error) {
    showError(error.message);
  } finally {
    pending = false;
    refreshControls();
  }
});

play.addEventListener("click", () => {
  if (playing) {
    following = false;
    queuedTrace = null;
    stopPlayback();
    paintCurrentMap();
  } else {
    startPlayback();
  }
});

byId("follow").addEventListener("click", () => {
  if (!latestTrace) return;
  following = !motion.matches;
  queuedTrace = null;
  setTrace(latestTrace.frames, latestTrace.label, following, 110);
});

motion.addEventListener("change", () => {
  if (!motion.matches) return;
  following = false;
  queuedTrace = null;
  stopPlayback();
  stepProgress = 0;
  paintMap(tick);
});

scrub.addEventListener("input", () => {
  following = false;
  queuedTrace = null;
  stopPlayback();
  tick = Number(scrub.value);
  stepProgress = 0;
  describeTick();
  paintMap(tick);
});

document.addEventListener("visibilitychange", () => {
  if (document.hidden) suspendPlaybackFrames();
  else queuePlaybackFrame();
});

new IntersectionObserver(([entry]) => {
  playbackVisible = entry.isIntersecting;
  if (playbackVisible) queuePlaybackFrame();
  else suspendPlaybackFrames();
}).observe(map.closest(".floor-panel"));

byId("export").addEventListener("click", () => {
  const fields = ["episode", "outcome", "reward", "steps", "delivery_tick", "phase", "energy", "exposures", "blocked", "waits", "epsilon"];
  if (runConfig.environment !== "navigation") fields.push("order", "pickup_tick");
  if (hasBattery(runConfig.environment)) {
    fields.push("battery_case", "initial_charge", "end_charge", "charge_ticks", "charge_added");
  }
  if (hasPacking(runConfig.environment)) fields.push("pack_tick");
  if (hasLayouts(runConfig.environment)) fields.push("layout");
  if (hasSharedAisles(runConfig.environment)) {
    fields.push("release_tick", "primary_denials", "scripted_denials", "stall_ticks", "replenished", "script_parked");
  }
  if (hasFleet(runConfig.environment)) {
    fields.push("orders_completed", "first_denials", "second_denials", "first_waits", "second_waits", "stall_ticks");
    if (hasShift(runConfig.environment)) {
      fields.push("workload", "first_item", "released", "backlog", "unassigned", "throughput",
        "queue_wait_ticks", "mean_cycle_ticks", "peak_queue", "packing_ticks", "depletions");
    } else {
      fields.push("battery_case", "pack_tick", "second_order", "second_battery_case",
        "second_pickup_tick", "second_pack_tick", "second_delivery_tick");
    }
  }
  const terms = ["Delivery", "Time", "Energy", "Exposure", "Blocked", "Failure"];
  const configKeys = Object.keys(runConfig);
  const headings = [...fields, ...terms.map((term) => `reward_${term.toLowerCase()}`), ...configKeys];
  const rows = history.map((result) => [
    ...fields.map((field) => result[field]), ...terms.map((term) => result.breakdown[term]), ...Object.values(runConfig),
  ].join(","));
  const file = new Blob([[headings.join(","), ...rows].join("\r\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(file);
  const link = document.createElement("a");
  link.href = url;
  link.download = `warehouse-${runConfig.algorithm}-seed-${runConfig.seed}.csv`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

new ResizeObserver(paintChart).observe(chart);
new ResizeObserver(() => {
  resizeMap();
  paintCurrentMap();
}).observe(map);

Promise.all([request("warehouse"), request("hyperparameters")]).then(([data, schema]) => {
  world = data;
  hyperparameterSchema = schema;
  for (const [layout, floor] of Object.entries(world.floor_plans)) {
    byId("preview-floor").add(new Option(floor.name, layout));
    byId("evaluation-floor").add(new Option(
      floor.held_out ? `${floor.name} (held out)` : floor.name, layout, floor.held_out, floor.held_out,
    ));
  }
  updateEnvironmentSettings();
  byId("advanced-settings").hidden = false;
  resizeMap();
  status = "Ready";
  previewMission(byId("environment").value, byId("mission").value === "return");
  refreshMetrics();
  refreshControls();
}).catch((error) => {
  status = "Disconnected";
  refreshControls();
  const recovery = window.warehouseRequest ? "Check your connection and reload the page." : "Reload the page after starting the local Python server.";
  showError(`Could not load the warehouse. ${recovery} ${error.message}`);
});
