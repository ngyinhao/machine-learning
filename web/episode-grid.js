"use strict";

class EpisodeGrid {
  constructor({ paint, inspect, describe, setLabel, motion }) {
    this.paint = paint;
    this.inspect = inspect;
    this.describe = describe;
    this.setLabel = setLabel;
    this.motion = motion;
    this.range = document.getElementById("monitor-range");
    this.status = document.getElementById("monitor-status");
    this.progress = document.getElementById("monitor-progress");
    this.control = document.getElementById("monitor-play");
    this.cards = document.getElementById("monitor-cards");
    this.template = document.getElementById("monitor-card");
    this.tiles = [];
    this.control.addEventListener("click", () => this.toggle());
    this.motion.addEventListener("change", () => {
      this.live = !this.motion.matches;
      this.showLatest();
    });
  }

  reset(total) {
    this.stop();
    this.total = total;
    this.batchSize = Number(document.getElementById("monitor-batch").value);
    this.interval = Number(document.getElementById("monitor-interval").value);
    this.limit = Number(document.getElementById("monitor-limit").value);
    this.live = !this.motion.matches;
    this.complete = false;
    this.group = null;
    this.latest = null;
    this.selected = null;
    this.samples = [];
    this.trained = 0;
    this.batchStart = 0;
    this.startedAt = this.lastUpdate = performance.now();
    this.pausedAt = null;
    this.cards.hidden = true;
    this.progress.value = 0;
    this.range.textContent = "Waiting for the first recorded group.";
    this.refresh();
  }

  setTrainingPaused(paused) {
    if (paused && this.pausedAt === null) {
      this.pausedAt = performance.now();
    } else if (!paused && this.pausedAt != null) {
      const now = performance.now();
      this.startedAt += now - this.pausedAt;
      this.lastUpdate = now;
      this.pausedAt = null;
    }
    if (this.total) this.refresh();
  }

  record(episode, frames, complete) {
    const now = performance.now();
    const chunkDuration = (this.pausedAt ?? now) - this.lastUpdate;
    this.lastUpdate = now;
    this.trained = episode.episode;
    this.complete = complete;
    const end = Math.min(this.total, this.batchStart + this.batchSize);
    const boundary = this.trained === end;
    if (boundary || (this.trained - this.batchStart) % this.interval === 0) {
      this.samples.push({ episode, frames });
    }

    if (!boundary) {
      if (this.live && this.group && this.group === this.latest) {
        this.moveTo(this.trainingProgress(), Math.min(150, Math.max(0, chunkDuration)));
      }
      this.refresh();
      return;
    }

    const count = Math.min(this.limit, this.samples.length);
    const samples = Array.from({ length: count }, (_, index) =>
      this.samples[Math.ceil((index + 1) * this.samples.length / count) - 1]);
    this.latest = {
      start: this.batchStart + 1,
      end,
      samples,
      ticks: Math.max(...samples.map(({ frames }) => frames.length - 1)),
      duration: Math.max(350, (this.pausedAt ?? now) - this.startedAt),
    };
    this.samples = [];
    this.batchStart = end;
    this.startedAt = now;
    if (this.pausedAt !== null) this.pausedAt = now;

    if (this.live && this.group && !document.hidden) {
      this.moveTo(1, 75);
      this.handoff = setTimeout(() => this.showLatest(), 220);
    } else if (this.live || !this.group || this.motion.matches) {
      this.showLatest();
    }
    this.refresh();
  }

  trainingProgress() {
    const nextEnd = Math.min(this.group.end + this.batchSize, this.total);
    return (this.trained - this.group.end) / (nextEnd - this.group.end);
  }

  showLatest() {
    this.stop();
    if (!this.latest) return;
    this.group = this.latest;
    this.range.textContent = `Viewing episodes ${this.group.start.toLocaleString()}–${this.group.end.toLocaleString()}`;
    this.cards.hidden = false;
    this.cards.style.setProperty("--map-count", this.group.samples.length);
    this.group.samples.forEach((sample, index) => {
      const tile = this.tiles[index] ?? this.addTile();
      const label = this.describe(sample.episode);
      tile.sample = sample;
      tile.position = -1;
      tile.button.hidden = false;
      tile.button.firstElementChild.textContent = label.title;
      this.setLabel(tile.button.lastElementChild, label.summary, label.icon);
      tile.button.setAttribute("aria-label", `Inspect ${label.title}, ${label.summary}`);
      tile.button.setAttribute("aria-pressed", sample === this.selected);
    });
    for (const tile of this.tiles.slice(this.group.samples.length)) {
      tile.sample = null;
      tile.button.hidden = true;
      tile.button.setAttribute("aria-pressed", "false");
    }
    this.draw(this.live ? 0 : 1);
    if (this.live && this.complete) {
      this.moveTo(1, this.group.duration);
    } else if (this.live) {
      this.moveTo(this.trainingProgress(), 0);
    }
    this.refresh();
  }

  addTile() {
    const button = this.template.content.firstElementChild.cloneNode(true);
    const canvas = button.querySelector("canvas");
    const tile = { button, context: canvas.getContext("2d") };
    this.tiles.push(tile);
    this.cards.append(button);
    button.addEventListener("click", () => {
      this.clearSelection();
      this.selected = tile.sample;
      button.setAttribute("aria-pressed", "true");
      this.inspect(tile.sample);
    });
    return tile;
  }

  clearSelection() {
    if (!this.selected) return;
    this.selected = null;
    this.cards.querySelector('[aria-pressed="true"]')?.setAttribute("aria-pressed", "false");
  }

  draw(position) {
    this.position = position;
    this.progress.value = position;
    for (const tile of this.tiles) {
      if (tile.button.hidden) continue;
      const tick = Math.min(tile.sample.frames.length - 1, position * this.group.ticks);
      if (tile.position === tick) continue;
      tile.position = tick;
      this.paint(tile.context, tile.sample.frames, tick);
    }
  }

  moveTo(target, duration) {
    cancelAnimationFrame(this.frame);
    this.frame = 0;
    const from = this.position;
    if (!duration || target <= from || document.hidden) {
      this.draw(target);
      return;
    }
    const start = performance.now();
    const render = (now) => {
      const elapsed = Math.max(0, Math.min(1, (now - start) / duration));
      this.draw(from + (target - from) * elapsed);
      this.frame = elapsed < 1 ? requestAnimationFrame(render) : 0;
      if (!this.frame) this.refresh();
    };
    this.frame = requestAnimationFrame(render);
  }

  stop() {
    cancelAnimationFrame(this.frame);
    clearTimeout(this.handoff);
    this.frame = 0;
    this.handoff = 0;
  }

  toggle() {
    if (this.live && (!this.complete || this.frame || this.handoff)) {
      this.live = false;
      this.stop();
      this.refresh();
    } else {
      this.live = true;
      this.showLatest();
    }
  }

  refresh() {
    const watching = this.live && (!this.complete || this.frame || this.handoff);
    this.control.disabled = !this.group || this.motion.matches;
    let action = "Pause grid";
    if (this.motion.matches) action = "Autoplay off";
    else if (!watching && !this.complete) action = "Follow training";
    else if (!watching) action = this.group !== this.latest ? "Show latest group" : "Replay group";
    const icon = this.motion.matches || watching ? "pause"
      : action === "Replay group" ? "replay" : action === "Show latest group" ? "latest" : "play";
    this.setLabel(this.control, action, icon);

    const training = `Trained ${this.trained.toLocaleString()} of ${this.total.toLocaleString()} episodes`;
    let playback = "Following training";
    if (!this.group) playback = `Next group at ${Math.min(this.total, this.batchSize).toLocaleString()}`;
    else if (this.motion.matches) playback = "Showing final positions";
    else if (!this.live) playback = "Grid paused";
    else if (this.handoff) playback = "Switching groups";
    else if (this.complete) playback = this.frame ? "Playing final group" : "Playback complete";
    else if (this.pausedAt !== null) playback = "Training paused";
    this.status.textContent = `${training} · ${playback}`;
  }
}
