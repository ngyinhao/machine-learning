"use strict";

const byId = (id) => document.getElementById(id);
const settings = byId("settings");
const setup = byId("setup");
const hyperparameterFields = byId("hyperparameter-fields");
const hyperparameterSettings = byId("hyperparameter-settings");
const hyperparameterEdits = new Map();
const map = byId("map");
const mapContext = map.getContext("2d");
const chart = byId("chart");
const scrub = byId("scrub");
const play = byId("play");
const eventReadout = document.querySelector(".event-readout");
const motion = matchMedia("(prefers-reduced-motion: reduce)");
const feedbackDuration = 440;
const history = [];
const averages = [];
const outcomeLabels = { delivered: "Delivered", returned: "Returned to base", collision: "Collision", timeout: "Step limit" };
const outcomeIcons = { delivered: "parcel-check", returned: "home-check", collision: "failure", timeout: "clock" };
const completed = (result) => result?.outcome === "delivered" || result?.outcome === "returned";
const episodeGrid = new EpisodeGrid({
  paint: (context, frames, position) => warehouseMap.draw(context, frames, position, "episode", true),
  inspect: inspectGridTrace,
  setLabel: setLabeledIcon,
  describe: (episode) => ({
    title: `Episode ${number(episode.episode, 0)}`,
    summary: `${outcomeLabels[episode.outcome]} · Return ${signed(episode.reward)}`,
    icon: outcomeIcons[episode.outcome],
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
let warehouseMap;
let hyperparameterSchema;
let runId;
let runConfig;
let referenceTrace;
let total = byId("episodes").valueAsNumber;
let status = "Loading";
let pending = false;
let trainingTimer;
let trace = [];
let traceMode = "episode";
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

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const use = document.createElementNS(svg.namespaceURI, "use");
  svg.classList.add("ui-icon");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("viewBox", "0 0 24 24");
  use.setAttribute("href", `#icon-${name}`);
  svg.append(use);
  return svg;
}

function setLabeledIcon(container, label, name) {
  const text = container.querySelector("[data-label]");
  const symbol = container.querySelector("use");
  if (text.textContent !== label) text.textContent = label;
  const href = name ? `#icon-${name}` : "";
  if (symbol.getAttribute("href") !== href) symbol.setAttribute("href", href);
  symbol.parentElement.classList.toggle("is-hidden", !name);
}

for (const placeholder of document.querySelectorAll("[data-icon]")) {
  placeholder.replaceWith(icon(placeholder.dataset.icon));
}

function showError(message) {
  byId("error").querySelector("[data-label]").textContent = message;
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
  setLabeledIcon(byId("start"), runId ? "Start new run" : "Start training", "play");
  byId("pause").disabled = (!running && !paused) || (paused && pending);
  setLabeledIcon(byId("pause"), paused ? "Resume training" : "Pause training", paused ? "play" : "pause");
  byId("replay").disabled = pending || running || !history.length;
  byId("export").disabled = !history.length;
  byId("follow").disabled = !latestTrace;
  const tone = running ? "active" : status === "Complete" ? "success" : "";
  const statusIcon = ({ Training: "dot", Starting: "dot", Paused: "pause",
    Complete: "check", Disconnected: "alert", Loading: "clock" })[status];
  for (const id of ["status", "curve-status"]) {
    setLabeledIcon(byId(id), status, statusIcon);
    byId(id).dataset.tone = tone;
  }
  const emptyMessage = emptyChartMessages[status === "Starting" ? "Training" : status];
  if (!history.length && emptyMessage) {
    const [title, note] = emptyMessage;
    const heading = byId("chart-empty-heading");
    if (heading.querySelector("[data-label]").textContent !== title) {
      setLabeledIcon(heading, title, statusIcon ?? "chart");
      byId("chart-empty-note").textContent = note;
    }
    byId("chart-setup-link").hidden = status !== "Ready" && !paused;
  }
}

function paintMap(targetTick, fraction = 1, feedbackProgress = 1) {
  if (!trace.length) return;
  warehouseMap.draw(mapContext, trace, targetTick - 1 + fraction, traceMode, false, feedbackProgress);
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
  setLabeledIcon(byId("outcome"), count ? outcomeLabels[latest.outcome] : "—", outcomeIcons[latest?.outcome]);
  byId("outcome").dataset.tone = completed(latest) ? "success" : latest?.outcome === "collision" ? "failure" : latest ? "active" : "";
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
  scrub.setAttribute("aria-valuetext", `Tick ${frame.tick} of ${trace.at(-1).tick}`);
  byId("trace-limit").textContent = `${tick} / ${trace.length - 1}`;
  const droppedOff = frame.outcome === "running" && frame.tick === frame.delivery_tick;
  const action = frame.action === "Wait" ? "Wait" : frame.action ? `Move ${frame.action.toLowerCase()}` : "Episode start";
  const events = [[action, frame.action === "Wait" ? "pause" : frame.action?.toLowerCase() ?? "play"],
    [frame.blocked && "Blocked move", "blocked", "warning"],
    [frame.exposure && "Forklift exposure", "exposure", "warning"],
    [droppedOff && "Parcel dropped off", "parcel-check", "success"],
    [outcomeLabels[frame.outcome], outcomeIcons[frame.outcome], completed(frame) ? "success" : "failure"],
  ].filter(([label]) => label);
  byId("event").replaceChildren(...events.map(([label, symbol, tone = ""]) => {
    const chip = document.createElement("span");
    chip.className = "event-chip";
    chip.dataset.tone = tone;
    chip.append(icon(symbol), label);
    return chip;
  }));
  eventReadout.dataset.tone = completed(frame) || droppedOff ? "success" : outcomeIcons[frame.outcome] ? "failure"
    : frame.blocked || frame.exposure ? "warning" : "";
  byId("step-reward").textContent = tick ? signed(Object.values(frame.rewards).reduce((sum, value) => sum + value, 0)) : "—";
  for (const output of document.querySelectorAll("[data-term]")) {
    output.textContent = tick ? signed(frame.rewards[output.dataset.term] ?? 0) : "—";
  }
  const location = ([column, row]) => `column ${String.fromCharCode(65 + column)}, row ${row + 1}`;
  const forklift = frame.forklift ? ` Forklift at ${location(frame.forklift)}.` : "";
  const cargo = frame.delivery_tick == null ? "Carrying the parcel." : "Parcel at the dock.";
  map.setAttribute("aria-label", `Tick ${frame.tick}. Robot at ${location(frame.robot)}.${forklift} ${cargo} ${events.map(([label]) => label).join(". ")}.`);
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
  setLabeledIcon(play, "Play trace", "play");
}

function setTrace(frames, label, autoplay, duration = 270, mode = "episode") {
  stopPlayback();
  if (!frames?.length) return;
  trace = frames;
  traceMode = mode;
  tick = 0;
  stepProgress = 0;
  traceDuration = duration;
  scrub.max = frames.length - 1;
  scrub.disabled = frames.length < 2;
  play.disabled = frames.length < 2;
  byId("trace-title").textContent = label;
  const patrol = frames.some((frame) => frame.forklift);
  byId("map-key-patrol").hidden = !patrol;
  byId("map-key-exposure").hidden = !patrol;
  byId("map-key-return").hidden = mode === "reference" || !frames.some((frame) => frame.delivery_tick != null && frame.tick > frame.delivery_tick);
  byId("map-key-outbound").hidden = mode === "reference";
  byId("map-key-reference").hidden = mode !== "reference";
  byId("map-key-preview").hidden = mode !== "preview";
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
    `Shortest-path preview · ${roundTrip ? "dock and back" : "dock only"} · no traffic`, false, 270, "preview");
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
  setLabeledIcon(play, "Pause trace", "pause");
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
  episodeGrid.clearSelection();
  setTrace(referenceTrace, `Fastest collision-free route · ${referenceTrace.length - 1} ticks`, !motion.matches, 270, "reference");
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
    episodeGrid.clearSelection();
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
  episodeGrid.clearSelection();
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
  warehouseMap?.resize(map);
  paintCurrentMap();
}).observe(map);

Promise.all([request("warehouse"), request("hyperparameters")]).then(([data, schema]) => {
  world = data;
  warehouseMap = new WarehouseMap(data);
  warehouseMap.resize(map);
  for (const key of document.querySelectorAll("[data-map-key]")) warehouseMap.drawLegend(key);
  hyperparameterSchema = schema;
  showHyperparameters();
  byId("advanced-settings").hidden = false;
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
