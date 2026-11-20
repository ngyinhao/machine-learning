"use strict";

const WarehouseMap = (() => {
  const size = 500;
  const inset = 30;
  const palette = {
    floor: "#19241f", aisle: "#304239", tile: "#26362e", rack: "#788d7e",
    pale: "#d5e2d6", lime: "#e5f787", returning: "#b9d6a3", reference: "#b6d5e8",
    preview: "#899c76", amber: "#ffac73", red: "#ff8c7c", parcel: "#eee2b8", home: "#9bc9c4",
    wall: "#46514d", joint: "#35413c", outer: "#586660", lip: "#303d37", edge: "#84938a",
  };
  const routes = {
    outbound: [palette.lime, 3, []],
    returning: [palette.returning, 2.6, [3, 6]],
    patrol: [palette.amber, 1.8, [6, 6]],
    reference: [palette.reference, 3, [12, 6]],
    preview: [palette.preview, 2, [2, 6]],
    exposure: [palette.amber, 2.5, [1, 5]],
  };
  const moves = { Up: [0, -1], Right: [1, 0], Down: [0, 1], Left: [-1, 0] };
  const sameCell = (first, second) => first && second && first.every((coordinate, axis) => coordinate === second[axis]);
  const direction = (before, after) => Math.atan2(after[1] - before[1], after[0] - before[0]);

  function stroke(context, points, color, width, dash = []) {
    if (points.length < 2) return;
    context.beginPath();
    context.moveTo(...points[0]);
    for (const point of points.slice(1)) context.lineTo(...point);
    context.strokeStyle = color;
    context.lineWidth = width;
    context.lineCap = "round";
    context.lineJoin = "round";
    context.setLineDash(dash);
    context.stroke();
    context.setLineDash([]);
  }

  function box(context, left, top, width, height, radius, fill, outline) {
    context.beginPath();
    context.roundRect(left, top, width, height, radius);
    if (fill) {
      context.fillStyle = fill;
      context.fill();
    }
    if (outline) {
      context.strokeStyle = outline;
      context.lineWidth = 1.6;
      context.stroke();
    }
  }

  function wall(context, left, top, span, thickness) {
    const lip = thickness * .16;
    context.save();
    context.translate(left, top);
    context.beginPath();
    context.rect(0, 0, span, span);
    context.rect(thickness, thickness, span - thickness * 2, span - thickness * 2);
    context.fillStyle = palette.wall;
    context.fill("evenodd");
    for (let side = 0; side < 4; side += 1) {
      for (let joint = 1; joint < 5; joint += 1) {
        const offset = span * joint / 5;
        stroke(context, [[offset, 1], [offset, thickness - lip]], palette.joint, 1.4);
      }
      context.translate(span, 0);
      context.rotate(Math.PI / 2);
    }
    context.lineWidth = 1;
    context.strokeStyle = palette.outer;
    context.strokeRect(.5, .5, span - 1, span - 1);
    const bevel = thickness - lip / 2;
    context.lineWidth = lip;
    context.strokeStyle = palette.lip;
    context.strokeRect(bevel, bevel, span - bevel * 2, span - bevel * 2);
    const inner = thickness - .8;
    context.lineWidth = 1.6;
    context.strokeStyle = palette.edge;
    context.strokeRect(inner, inner, span - inner * 2, span - inner * 2);
    context.restore();
  }

  function glyph(context, name, position, scale = 1, angle = 0, compact = false) {
    context.save();
    context.translate(...position);
    context.rotate(angle);
    context.scale(scale, scale);
    switch (name) {
      case "loaded":
      case "unloaded":
        box(context, -10, -13, 17, 26, 3, palette.floor);
        box(context, -13, -10, 26, 20, [4, 8, 8, 4], palette.lime, palette.floor);
        stroke(context, [[6, -4], [10, 0], [6, 4]], palette.floor, 2);
        box(context, -9, -5.5, 10, 11, 1, name === "loaded" ? palette.parcel : null, palette.floor);
        if (!compact && name === "loaded") stroke(context, [[-4, -5], [-4, 4]], palette.floor, 1.4);
        break;
      case "forklift":
        box(context, -13, -9, 19, 18, 2, palette.amber, palette.floor);
        box(context, -7, -5, 8, 10, 1, palette.floor);
        stroke(context, [[5, -10], [5, 10]], palette.amber, 2.6);
        stroke(context, [[6, -6], [14, -6]], palette.amber, 2.8);
        stroke(context, [[6, 6], [14, 6]], palette.amber, 2.8);
        break;
      case "parcel":
        box(context, -7, -7, 14, 14, 1, palette.parcel, palette.floor);
        stroke(context, [[0, -6], [0, 5]], palette.floor, 1.5);
        break;
      case "home":
        box(context, -12, -12, 24, 24, 4, null, palette.home);
        stroke(context, [[-7, -1], [0, -7], [7, -1]], palette.home, 2);
        stroke(context, [[-5, -1], [-5, 6], [5, 6], [5, -1]], palette.home, 1.6);
        break;
      case "dock":
        stroke(context, [[-10, -10], [-10, 10], [10, 10], [10, -10]], palette.lime, 2);
        stroke(context, [[-4, 5], [4, 5]], palette.lime, 1.8);
        break;
      case "shelf":
        box(context, -12, -11, 24, 22, 1, palette.rack);
        for (const row of [-8, 2]) {
          box(context, -9, row, 18, 6, 1, palette.floor);
          stroke(context, [[0, row], [0, row + 6]], palette.rack, 2);
        }
        break;
      case "wall":
        context.beginPath();
        context.rect(-13, -13, 26, 26);
        context.clip();
        wall(context, -13, -13, 60, 9);
        break;
      case "wait":
      case "blocked":
      case "delivery":
      case "returned":
      case "collision":
      case "timeout":
        badge(context, name);
        break;
      default:
        stroke(context, [[-14, 0], [14, 0]], ...routes[name]);
    }
    context.restore();
  }

  function badge(context, name) {
    const success = name === "delivery" || name === "returned";
    const color = name === "collision" ? palette.red : success ? palette.lime
      : name === "wait" ? palette.pale : palette.amber;
    if (name === "returned") {
      context.beginPath();
      context.moveTo(-8, -2);
      context.lineTo(0, -9);
      context.lineTo(8, -2);
      context.lineTo(6, -2);
      context.lineTo(6, 7);
      context.lineTo(-6, 7);
      context.lineTo(-6, -2);
      context.closePath();
      context.fillStyle = palette.floor;
      context.fill();
      context.strokeStyle = color;
      context.lineWidth = 1.6;
      context.stroke();
    } else {
      box(context, -8, -8, 16, 16, name === "blocked" || name === "delivery" ? 2 : 8, palette.floor, color);
    }
    switch (name) {
      case "wait":
        stroke(context, [[-2, -3.5], [-2, 3.5]], color, 1.8);
        stroke(context, [[2, -3.5], [2, 3.5]], color, 1.8);
        break;
      case "blocked":
        stroke(context, [[-4, 0], [4, 0]], color, 2);
        break;
      case "collision":
        stroke(context, [[-3, -3], [3, 3]], color, 1.8);
        stroke(context, [[3, -3], [-3, 3]], color, 1.8);
        break;
      case "timeout":
        stroke(context, [[0, -4], [0, 0], [3, 1.5]], color, 1.8);
        break;
      default:
        stroke(context, [[-4, 0], [-1.5, 3], [4, -3]], color, 1.8);
    }
  }

  return class WarehouseMap {
    constructor(world) {
      this.world = world;
      this.cellSize = (size - inset * 2) / world.layout.length;
      this.layer = document.createElement("canvas");
      this.thumbnail = document.createElement("canvas");
      this.traces = new WeakMap();
      this.patrolPath = [...world.patrol, world.patrol[0]].map((point) => this.center(point));
      this.buildLayer(this.thumbnail, 250, true);
    }

    center(point) {
      return point.map((coordinate) => inset + (coordinate + .5) * this.cellSize);
    }

    resize(canvas) {
      const pixels = Math.round(canvas.clientWidth * Math.min(devicePixelRatio || 1, 2));
      if (!pixels || (pixels === canvas.width && this.layer.width === pixels && this.layer.height === pixels)) return;
      canvas.width = canvas.height = pixels;
      this.buildLayer(this.layer, pixels, false);
    }

    buildLayer(canvas, pixels, compact) {
      const { layout, start, dock } = this.world;
      const cell = this.cellSize;
      canvas.width = canvas.height = pixels;
      const context = canvas.getContext("2d");
      context.setTransform(pixels / size, 0, 0, pixels / size, 0, 0);
      context.fillStyle = palette.floor;
      context.fillRect(0, 0, size, size);
      wall(context, inset, inset, cell * layout.length, cell);
      context.font = "650 13px ui-monospace, monospace";
      context.textAlign = "center";
      context.textBaseline = "middle";
      for (const [row, tiles] of layout.entries()) {
        if (!compact) {
          const [labelX, labelY] = this.center([row, row]);
          context.fillStyle = palette.pale;
          context.fillText(String.fromCharCode(65 + row), labelX, 16);
          context.fillText(String(row + 1).padStart(2, "0"), 15, labelY);
        }
        for (const [column, tile] of [...tiles].entries()) {
          const perimeter = row === 0 || column === 0 || row === layout.length - 1 || column === tiles.length - 1;
          if (perimeter) continue;
          const point = this.center([column, row]);
          context.fillStyle = row === start[1] && row === dock[1] ? palette.aisle : palette.tile;
          context.fillRect(point[0] - cell / 2 + .5, point[1] - cell / 2 + .5, cell - 1, cell - 1);
          if (tile === "#") glyph(context, "shelf", point, cell / 35);
          if (tile === "S") glyph(context, "home", point, cell / 33);
          if (tile === "D") glyph(context, "dock", point, cell / 33);
        }
      }
    }

    drawLegend(canvas) {
      const context = canvas.getContext("2d");
      context.clearRect(0, 0, canvas.width, canvas.height);
      glyph(context, canvas.dataset.mapKey, [canvas.width / 2, canvas.height / 2], canvas.width / 34);
    }

    prepare(frames) {
      if (this.traces.has(frames)) return this.traces.get(frames);
      const headings = (vehicle, initial) => {
        let angle = initial;
        return frames.map((frame, index) => {
          const before = frames[index - 1]?.[vehicle];
          const after = frame[vehicle];
          if (before && after && !sameCell(before, after)) angle = direction(before, after);
          return angle;
        });
      };
      const { patrol } = this.world;
      const phase = patrol.findIndex((point) => sameCell(point, frames[0].forklift));
      const forkliftAngle = phase < 0 ? 0 : direction(patrol[(phase + patrol.length - 1) % patrol.length], patrol[phase]);
      const trace = {
        points: frames.map((frame) => this.center(frame.robot)),
        robot: headings("robot", 0),
        forklift: headings("forklift", forkliftAngle),
      };
      this.traces.set(frames, trace);
      return trace;
    }

    pose(frames, tick, fraction, vehicle, headings) {
      const previous = Math.max(0, tick - 1);
      const destination = frames[tick][vehicle];
      const origin = frames[previous][vehicle] ?? destination;
      const position = this.center(destination.map((coordinate, axis) => origin[axis] + (coordinate - origin[axis]) * fraction));
      const turn = headings[tick] - headings[previous];
      const angle = headings[previous] + Math.atan2(Math.sin(turn), Math.cos(turn)) * fraction;
      return { position, angle };
    }

    draw(context, frames, position, mode = "episode", compact = false, feedback = 1) {
      const target = Math.ceil(position);
      const fraction = position % 1 || 1;
      const settled = Math.floor(position);
      const frame = frames[settled];
      const trace = this.prepare(frames);
      const robot = this.pose(frames, target, fraction, "robot", trace.robot);
      const forklift = frames[target].forklift && this.pose(frames, target, fraction, "forklift", trace.forklift);
      const layer = compact ? this.thumbnail : this.layer;
      const scale = context.canvas.width / size;
      const vehicleScale = this.cellSize / (compact ? 29 : 32);
      context.setTransform(scale, 0, 0, scale, 0, 0);
      context.drawImage(layer, 0, 0, size, size);

      if (forklift) stroke(context, this.patrolPath, ...routes.patrol);
      this.drawRoute(context, trace.points, settled, frame.delivery_tick, robot.position, mode);
      const eventPoint = this.center(frame.robot);
      if (frame.exposure && frame.forklift) {
        stroke(context, [eventPoint, this.center(frame.forklift)], ...routes.exposure);
      }
      const overlap = frame.outcome === "collision" && sameCell(frame.robot, frame.forklift);
      if (forklift) {
        const point = overlap ? [forklift.position[0] + 10, forklift.position[1]] : forklift.position;
        glyph(context, "forklift", point, vehicleScale * (overlap ? .57 : 1), forklift.angle, compact);
      }
      const robotPoint = overlap ? [robot.position[0] - 10, robot.position[1]] : robot.position;
      glyph(context, frame.delivery_tick == null ? "loaded" : "unloaded", robotPoint,
        vehicleScale * (overlap ? .57 : 1), robot.angle, compact);
      if (frame.delivery_tick != null) {
        const [dockX, dockY] = this.center(this.world.dock);
        glyph(context, "parcel", [dockX, dockY + this.cellSize * .31], this.cellSize / 62);
      }
      this.drawEvent(context, frame, frames[settled - 1], eventPoint, compact, feedback);
    }

    drawRoute(context, points, settled, delivered, position, mode) {
      if (mode === "preview" || mode === "reference") {
        const faint = mode === "reference" ? ["#627b86", 2, routes.reference[2]] : routes.preview;
        stroke(context, [position, ...points.slice(settled + 1)], ...faint);
      }
      const returning = delivered != null && settled >= delivered;
      const route = points.slice(0, (returning ? delivered : settled) + 1);
      if (!returning) route.push(position);
      stroke(context, route, ...routes[mode === "reference" ? "reference" : "outbound"]);
      if (returning) {
        const leg = [...points.slice(delivered, settled + 1), position].map(([x, y]) => [x + 3, y + 5]);
        stroke(context, leg, ...routes[mode === "reference" ? "reference" : "returning"]);
      }
    }

    drawEvent(context, frame, previous, [x, y], compact, feedback) {
      const docked = frame.delivery_tick === frame.tick;
      const badgeScale = compact ? 1.2 : 1;
      if (frame.outcome === "collision") {
        const swapped = sameCell(previous?.robot, frame.forklift) && sameCell(previous?.forklift, frame.robot);
        const [contactX, contactY] = swapped
          ? this.center(frame.robot.map((coordinate, axis) => (coordinate + frame.forklift[axis]) / 2))
          : [x, y];
        if (swapped) {
          const halfEdge = this.cellSize / 2;
          const edge = frame.robot[0] === frame.forklift[0]
            ? [[contactX - halfEdge, contactY], [contactX + halfEdge, contactY]]
            : [[contactX, contactY - halfEdge], [contactX, contactY + halfEdge]];
          stroke(context, edge, palette.red, 3);
        } else {
          box(context, x - 20, y - 19, 40, 38, 4, null, palette.red);
        }
        glyph(context, "collision", swapped ? [contactX, contactY] : [x + 17, y - 17], badgeScale);
      } else if (frame.outcome === "timeout") {
        glyph(context, "timeout", [x + 16, y - 16], badgeScale);
      } else if (docked || frame.outcome === "delivered" || frame.outcome === "returned") {
        glyph(context, docked ? "delivery" : "returned", [x + 16, y - 16], badgeScale);
      } else if (frame.action === "Wait") {
        glyph(context, "wait", [x + 16, y - 16], badgeScale);
      }
      if (frame.blocked && moves[frame.action]) {
        const [dx, dy] = moves[frame.action];
        const badgePoint = [x + dx * this.cellSize, y + dy * this.cellSize];
        stroke(context, [[x + dx * 17, y + dy * 17], badgePoint], palette.amber, 1.8, [2, 4]);
        glyph(context, "blocked", badgePoint, badgeScale);
      }
      if (feedback < 1) {
        context.globalAlpha = .45 * (1 - feedback);
        const spread = 23 + feedback * 7;
        box(context, x - spread, y - spread, spread * 2, spread * 2, 6, null,
          frame.outcome === "collision" ? palette.red : palette.lime);
        context.globalAlpha = 1;
      }
    }
  };
})();
