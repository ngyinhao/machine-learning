"use strict";

const byId = (id) => document.getElementById(id);
const settings = byId("settings");
const setup = byId("setup");
const hyperparameterFields = byId("hyperparameter-fields");
const hyperparameterSettings = byId("hyperparameter-settings");
const hyperparameterEdits = new Map();
const map = byId("map");
const mapContext = map.getContext("2d");
const floorLayer = document.createElement("canvas");
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
const feedbackDuration = 440;
const history = [];
const averages = [];
const outcomeLabels = { delivered: "Delivered", returned: "Returned to base", collision: "Collision", timeout: "Step limit" };
const completed = (result) => result?.outcome === "delivered" || result?.outcome === "returned";
const gridHeadings = new WeakMap();
const episodeGrid = new EpisodeGrid({
  paint: paintGridTrace,
  inspect: inspectGridTrace,
  describe: (episode) => ({
    title: `Episode ${number(episode.episode, 0)}`,
    summary: `${outcomeLabels[episode.outcome]} · Return ${signed(episode.reward)}`,
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
let world;
let hyperparameterSchema;
let runId;
let runConfig;
let referenceTrace;
let total = byId("episodes").valueAsNumber;
let status = "Loading";
let pending = false;
let trainingTimer;
let trace = [];
let robotHeadings = [];
let forkliftHeadings = [];
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

function refreshControls() {
  const running = status === "Training";
  const paused = status === "Paused";
  settings.disabled = !world || pending || running;
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

function buildFloorLayer() {
  if (!world) return;
  const size = Math.max(1, Math.round(map.getBoundingClientRect().width * Math.min(devicePixelRatio || 1, 2)));
  map.width = map.height = floorLayer.width = floorLayer.height = size;
  const scale = size / mapSize;
  mapContext.setTransform(scale, 0, 0, scale, 0, 0);
  const context = floorLayer.getContext("2d");
  context.setTransform(scale, 0, 0, scale, 0, 0);
  context.fillStyle = "#19241f";
  context.fillRect(0, 0, mapSize, mapSize);
  context.font = "650 11px ui-monospace, monospace";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillStyle = "#b0c2b3";
  for (const row of world.layout.keys()) {
    const [horizontal, vertical] = cellCenter([row, row]);
    context.fillText(String.fromCharCode(65 + row), horizontal, 16);
    context.fillText(String(row + 1).padStart(2, "0"), 15, vertical);
  }
  for (const [row, cells] of world.layout.entries()) {
    for (const [column, marker] of [...cells].entries()) {
      const left = mapInset + column * cellSize;
      const top = mapInset + row * cellSize;
      const wall = marker === "#" && (row === 0 || row === world.layout.length - 1 || column === 0 || column === cells.length - 1);
      context.fillStyle = wall ? "#23312a" : row === 5 ? "#34453b" : "#2b3a32";
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
  context.strokeRect(mapInset - 0.5, mapInset - 0.5, cellSize * world.layout[0].length + 1, cellSize * world.layout.length + 1);
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

function drawRobot(context, pose, carryingParcel, arrived) {
  context.save();
  context.translate(...pose.position);
  context.rotate(pose.angle);
  context.fillStyle = "#131f18";
  context.beginPath();
  context.roundRect(-14, -12, 29, 26, 6);
  context.fill();
  context.fillStyle = mapLime;
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
  paintTrace(mapContext, trace, robotHeadings, forkliftHeadings, targetTick, fraction, feedbackProgress);
}

function paintGridTrace(context, frames, position) {
  if (!gridHeadings.has(frames)) {
    gridHeadings.set(frames, { robot: traceHeadings(frames, "robot"), forklift: traceHeadings(frames, "forklift") });
  }
  const headings = gridHeadings.get(frames);
  const scale = context.canvas.width / mapSize;
  context.setTransform(scale, 0, 0, scale, 0, 0);
  const targetTick = Math.ceil(position);
  const fraction = position % 1 || 1;
  paintTrace(context, frames, headings.robot, headings.forklift, targetTick, fraction);
}

function paintTrace(context, frames, robotDirections, forkliftDirections, targetTick, fraction, feedbackProgress = 1) {
  const frame = frames[fraction === 1 ? targetTick : Math.max(0, targetTick - 1)];
  const robot = vehiclePose(frames, targetTick, fraction, "robot", robotDirections);
  const forklift = frames[targetTick].forklift && vehiclePose(frames, targetTick, fraction, "forklift", forkliftDirections);
  context.drawImage(floorLayer, 0, 0, mapSize, mapSize);
  context.lineCap = "round";
  context.lineJoin = "round";
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
  if (frames === world.demo || frames === world.round_trip_demo) {
    context.beginPath();
    context.moveTo(...robot.position);
    for (let index = targetTick; index < frames.length; index += 1) context.lineTo(...cellCenter(frames[index].robot));
    context.setLineDash([3, 6]);
    context.strokeStyle = "#a0b26e";
    context.lineWidth = 2;
    context.stroke();
    context.setLineDash([]);
  }
  if (targetTick) {
    context.beginPath();
    context.moveTo(...cellCenter(frames[0].robot));
    for (let index = 1; index < targetTick; index += 1) context.lineTo(...cellCenter(frames[index].robot));
    context.lineTo(...robot.position);
    context.strokeStyle = "#afc56a";
    context.lineWidth = 3;
    context.stroke();
  }
  const arrived = completed(frame) || frame.tick === frame.delivery_tick;
  const collision = frame.outcome === "collision";
  const [horizontal, vertical] = robot.position;
  if (arrived || collision || frame.exposure || frame.blocked) {
    const color = collision ? "#ff8c7c" : arrived ? mapLime : mapOrange;
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
  drawRobot(context, robot, frame.delivery_tick == null, arrived);
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
  const success = recent.filter(completed).length / recent.length;
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
  byId("outcome").textContent = count ? outcomeLabels[latest.outcome] : "—";
  byId("outcome").dataset.tone = completed(latest) ? "success" : latest ? "active" : "";
  byId("steps").textContent = count ? latest.steps : "—";
  byId("energy").textContent = count ? number(latest.energy, 2) : "—";
  byId("exposures").textContent = count ? latest.exposures : "—";
  paintChart();
}

function describeTick() {
  const frame = trace[tick];
  if (!frame) return;
  byId("tick").textContent = String(frame.tick).padStart(2, "0");
  scrub.value = tick;
  byId("trace-limit").textContent = `${tick} / ${trace.length - 1}`;
  const droppedOff = frame.outcome === "running" && frame.tick === frame.delivery_tick;
  const event = [frame.action, frame.blocked && "Blocked move", frame.exposure && "Forklift exposure",
    droppedOff && "Parcel delivered · return to base",
    outcomeLabels[frame.outcome]].filter(Boolean).join(" · ");
  byId("event").textContent = event || "Episode start";
  eventReadout.dataset.tone = completed(frame) || droppedOff ? "success"
    : frame.blocked || frame.exposure || frame.outcome === "collision" ? "warning" : "";
  byId("step-reward").textContent = tick ? signed(Object.values(frame.rewards).reduce((sum, value) => sum + value, 0)) : "—";
  for (const output of document.querySelectorAll("[data-term]")) {
    output.textContent = tick ? signed(frame.rewards[output.dataset.term] ?? 0) : "—";
  }
  const location = ([column, row]) => `column ${String.fromCharCode(65 + column)}, row ${row + 1}`;
  const forklift = frame.forklift ? ` Forklift at ${location(frame.forklift)}.` : "";
  map.setAttribute("aria-label", `Tick ${frame.tick}. Robot at ${location(frame.robot)}.${forklift}`);
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
  robotHeadings = traceHeadings(frames, "robot");
  forkliftHeadings = traceHeadings(frames, "forklift");
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
  setTrace(frames, `Training episode ${number(episode.episode, 0)} · ${outcomeLabels[episode.outcome]}`, false);
  const heading = byId("floor-heading");
  heading.focus({ preventScroll: true });
  heading.scrollIntoView({ block: "start" });
}

function terminalFeedback() {
  const frame = trace[tick];
  return tick === trace.length - 1 && (completed(frame) || frame?.outcome === "collision") && !motion.matches;
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

function previewMission(roundTrip) {
  setTrace(roundTrip ? world.round_trip_demo : world.demo,
    `Shortest-path preview · ${roundTrip ? "dock and back" : "dock only"} · no traffic`, false);
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
      latestTrace = { frames: result.frames, label: `Training episode ${number(latest.episode, 0)} · ${outcomeLabels[latest.outcome]}` };
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
    algorithm: byId("algorithm").value,
    traffic: byId("traffic").value,
    round_trip: byId("mission").value === "return",
    profile: byId("profile").value,
    exposure_cost: byId("profile").value === "balanced" ? byId("exposure").valueAsNumber : 0,
    ...hyperparameters,
  };
  const previousStatus = status;
  pending = true;
  status = "Starting";
  refreshControls();
  showError("");
  try {
    const result = await request("start", config);
    runId = result.run_id;
    runConfig = result.config;
    history.length = 0;
    averages.length = 0;
    total = config.episodes;
    following = false;
    latestTrace = null;
    queuedTrace = null;
    clearEvaluation();
    previewMission(config.round_trip);
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

byId("algorithm").addEventListener("change", showHyperparameters);
byId("mission").addEventListener("change", () => {
  if (!runId) previewMission(byId("mission").value === "return");
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

byId("reference").addEventListener("click", () => {
  if (!referenceTrace) return;
  following = false;
  queuedTrace = null;
  setTrace(referenceTrace, `Fastest collision-free route · ${referenceTrace.length - 1} ticks`, !motion.matches);
});

byId("replay").addEventListener("click", async () => {
  pending = true;
  refreshControls();
  showError("");
  try {
    const replay = await request("replay", { run_id: runId });
    following = false;
    queuedTrace = null;
    const result = replay.result;
    const missions = replay.evaluation;
    const successes = missions.filter(completed);
    const fastest = successes.filter((mission) => mission.steps === mission.optimal_steps);
    const scope = result.phase == null ? "static scenario" : "forklift starting phases";
    const evaluation = byId("policy-evaluation");
    evaluation.textContent = `Completed ${successes.length}/${missions.length} across ${scope}. ${fastest.length}/${missions.length} matched the minimum time. The replay took ${result.steps} ticks. The fastest completion takes ${result.optimal_steps}.`;
    evaluation.hidden = false;
    referenceTrace = replay.reference;
    byId("reference").hidden = false;
    setTrace(replay.frames, `Policy replay after episode ${number(result.episode, 0)} · ${outcomeLabels[result.outcome]}`, !motion.matches);
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
  buildFloorLayer();
  paintCurrentMap();
}).observe(map);

Promise.all([request("warehouse"), request("hyperparameters")]).then(([data, schema]) => {
  world = data;
  hyperparameterSchema = schema;
  showHyperparameters();
  byId("advanced-settings").hidden = false;
  buildFloorLayer();
  status = "Ready";
  previewMission(byId("mission").value === "return");
  refreshMetrics();
  refreshControls();
}).catch((error) => {
  status = "Disconnected";
  refreshControls();
  const recovery = window.warehouseRequest ? "Check your connection and reload the page." : "Reload the page after starting the local Python server.";
  showError(`Could not load the warehouse. ${recovery} ${error.message}`);
});
