from copy import copy
from dataclasses import dataclass, replace
from functools import cache
from heapq import heappop, heappush
from itertools import count, product
from random import Random

from agents import FleetPPO
from warehouse import (
    ACTIONS, BATTERY_STARTS, CHARGE_RATE, ENERGY_SCALE, GAMMA, HORIZON, MOVE_ENERGY,
    ORIGINAL_LAYOUT, PICK_BAYS, REPLENISHMENT_ROUTE, START, VALID_ACTIONS, WAIT, Warehouse,
    distances_to, move_target, resolve_aisle_moves, score,
)


FLEET_ALGORITHMS = ("ippo", "mappo")
FLEET_CHARGERS = (START, REPLENISHMENT_ROUTE[0])
FLEET_CAPACITY = 210
FLEET_CASES = tuple(product(PICK_BAYS, BATTERY_STARTS, BATTERY_STARTS))
ROLLOUT_EPISODES = 10


def available_actions(robot):
    return VALID_ACTIONS[robot.position] if robot.outcome == "running" else (WAIT,)


@dataclass(frozen=True)
class FleetObservation:
    actions: tuple
    action_features: tuple
    value_features: tuple
    remaining_steps: int


class FleetWarehouse:
    def __init__(self, first_order, first_charge, second_charge):
        if (first_order, first_charge, second_charge) not in FLEET_CASES:
            raise ValueError("Choose a supported fleet scenario.")
        second_order = next(item for item in PICK_BAYS if item != first_order)
        self.robots = tuple(
            self._robot(home, order, charge)
            for home, order, charge in zip(FLEET_CHARGERS, (first_order, second_order), (first_charge, second_charge))
        )
        self.tick = 0
        self.outcome = "running"
        self.denials = (0, 0)
        self.waits = (0, 0)
        self.stall_ticks = 0
        self.conflict = None
        self.denied = (False, False)

    @staticmethod
    def _robot(home, order, charge):
        robot = Warehouse("none", order=order, battery_case=charge, packing=True)
        robot.position = home
        robot.floor = replace(robot.floor, start=home)
        robot.initial_charge += FLEET_CAPACITY - robot.battery_capacity
        robot.charge = robot.initial_charge
        robot.battery_capacity = FLEET_CAPACITY
        return robot

    def copy(self):
        successor = copy(self)
        successor.robots = tuple(copy(robot) for robot in self.robots)
        return successor

    def key(self):
        return tuple(
            None if robot.outcome == "delivered" else (robot.position, robot.cargo is not None,
                                                        robot.pack_tick is not None, robot.charge)
            for robot in self.robots
        )

    def observe(self):
        observations = []
        for robot, peer in (self.robots, self.robots[::-1]):
            if robot.outcome != "running":
                observations.append(FleetObservation((WAIT,), (), (1.0, 0, 0, 0, 0, 0, 0, 0), 0))
                continue
            base = robot.layout_observation()
            peer_present = peer.outcome == "running"
            distances = distances_to(ORIGINAL_LAYOUT, peer.position) if peer_present else {}
            near = distances.get(robot.position, 5) <= 2
            features = []
            for action in base.actions:
                target = move_target(robot.position, action)
                progress = base.features[action]
                occupied = peer_present and target == peer.position
                features.append((
                    progress, float(action == WAIT), float(occupied), float(near and action == WAIT),
                    float(near) * progress, float(near and distances.get(target, 5) == 1),
                    float(action == WAIT and base.guide == WAIT),
                ))
            value_features = (
                1.0, 1.0, base.remaining_steps / 25, robot.charge / FLEET_CAPACITY,
                float(robot.cargo is not None), float(robot.pack_tick is not None),
                (HORIZON - self.tick) / HORIZON, float(near),
            )
            observations.append(FleetObservation(base.actions, tuple(features), value_features, base.remaining_steps))
        return tuple(observations)

    def step(self, actions):
        if self.outcome != "running":
            raise RuntimeError("Start another fleet episode after termination.")
        if len(actions) != 2 or any(type(action) is not int or action not in available_actions(robot)
                                    for robot, action in zip(self.robots, actions)):
            raise ValueError("Choose one legal action per robot.")
        active = tuple(robot.outcome == "running" for robot in self.robots)
        positions = tuple(robot.position for robot in self.robots)
        self.conflict = None
        self.denied = (False, False)
        if all(active):
            targets = tuple(move_target(robot.position, action) if robot.charge >= MOVE_ENERGY else robot.position
                            for robot, action in zip(self.robots, actions))
            decision = resolve_aisle_moves(*positions, *targets)
            self.conflict = decision.conflict
            self.denied = (decision.primary_denied, decision.scripted_denied)
        events = tuple(robot._step(action, denied=denied) if running else None
                       for robot, action, denied, running in zip(self.robots, actions, self.denied, active))
        self.tick += 1
        self.denials = tuple(total + denied for total, denied in zip(self.denials, self.denied))
        self.waits = tuple(total + (running and robot.position == before)
                           for total, running, robot, before in zip(self.waits, active, self.robots, positions))
        self.stall_ticks += bool(self.conflict and positions == tuple(robot.position for robot in self.robots))
        outcomes = tuple(robot.outcome for robot in self.robots)
        if outcomes == ("delivered", "delivered"):
            self.outcome = "delivered"
        elif "depleted" in outcomes:
            self.outcome = "depleted"
        elif self.tick == HORIZON:
            self.outcome = "timeout"
        return events

    def frame(self, events=(None, None), rewards=None):
        frames = [robot.frame(event) for robot, event in zip(self.robots, events)]
        for index, (robot, frame) in enumerate(zip(self.robots, frames)):
            frame["present"] = robot.delivery_tick is None or robot.delivery_tick == self.tick
            frame["denied"] = self.denied[index]
            frame["denials"] = self.denials[index]
            frame["waits"] = self.waits[index]
        stock = {robot.order: int(robot.pickup_tick is None) for robot in self.robots}
        return {
            "layout": ORIGINAL_LAYOUT, "robot": frames[0]["robot"], "second_robot": frames[1]["robot"],
            "tick": self.tick, "fleet": frames, "outcome": self.outcome, "stock": stock,
            "conflict": self.conflict, "stall_ticks": self.stall_ticks, "rewards": rewards or {},
        }

    def summary(self):
        first, second = self.robots
        return {
            "outcome": self.outcome, "steps": self.tick, "exposures": 0, "blocked": 0, "waits": sum(self.waits),
            "orders_completed": sum(robot.outcome == "delivered" for robot in self.robots),
            "order": first.order, "second_order": second.order,
            "battery_case": first.battery_case, "second_battery_case": second.battery_case,
            "pickup_tick": first.pickup_tick, "second_pickup_tick": second.pickup_tick,
            "pack_tick": first.pack_tick, "second_pack_tick": second.pack_tick,
            "delivery_tick": first.delivery_tick, "second_delivery_tick": second.delivery_tick,
            "first_denials": self.denials[0], "second_denials": self.denials[1],
            "first_waits": self.waits[0], "second_waits": self.waits[1], "stall_ticks": self.stall_ticks,
        }


def fleet_rewards(events, outcome, profile, exposure_cost):
    terms = dict.fromkeys(("Delivery", "Time", "Energy", "Exposure", "Blocked", "Failure"), 0.0)
    for event in events:
        if event is not None:
            for term, value in score(event, profile, exposure_cost).items():
                terms[term] += value
    terms["Delivery"] *= 0.5
    terms["Failure"] = -100.0 if outcome in ("timeout", "depleted") else 0.0
    return terms


@cache
def fleet_route(first_order, first_charge, second_charge):
    def bound(state):
        return max(item.remaining_steps for item in state.observe())

    initial = FleetWarehouse(first_order, first_charge, second_charge)
    sequence = count()
    queue = [(bound(initial), 0, next(sequence), initial, ())]
    visited = {initial.key(): 0}
    while queue:
        _, _, _, warehouse, route = heappop(queue)
        if warehouse.outcome == "delivered":
            return route
        if visited[warehouse.key()] != warehouse.tick:
            continue
        for actions in product(*(available_actions(robot) for robot in warehouse.robots)):
            successor = warehouse.copy()
            successor.step(actions)
            if successor.outcome not in ("running", "delivered"):
                continue
            key = successor.key()
            if successor.tick >= visited.get(key, HORIZON + 1):
                continue
            visited[key] = successor.tick
            priority = successor.tick + bound(successor)
            heappush(queue, (priority, -successor.tick, next(sequence), successor, (*route, actions)))
    raise ValueError("No joint route completes both orders.")


def fleet_reference(first_order, first_charge, second_charge, profile="balanced", exposure_cost=0):
    warehouse = FleetWarehouse(first_order, first_charge, second_charge)
    frames = [warehouse.frame()]
    for actions in fleet_route(first_order, first_charge, second_charge):
        events = warehouse.step(actions)
        frames.append(warehouse.frame(events, fleet_rewards(events, warehouse.outcome, profile, exposure_cost)))
    return frames


class FleetRun:
    def __init__(self, *, episodes, seed, profile, exposure_cost, algorithm, environment,
                 traffic, round_trip=False, warm_start=False, layout_training="original"):
        if (environment, traffic, round_trip, warm_start, layout_training) != (
                self.environment, "none", False, False, "original") or algorithm not in FLEET_ALGORITHMS:
            raise ValueError("Fleet training uses IPPO or MAPPO without forklift traffic.")
        self.total = episodes
        self.seed = seed
        self.profile = profile
        self.exposure_cost = exposure_cost
        self.random = Random(seed)
        self.scenarios = Random(seed ^ 0xF1EE7)
        self.policy = FleetPPO(centralized=algorithm == "mappo")
        self.history = []
        self.rollout = []

    environment = "two_learning_robots"
    cases = FLEET_CASES
    warehouse_type = FleetWarehouse
    rewards = staticmethod(fleet_rewards)

    @staticmethod
    def energy_spent(events):
        return sum(event.energy for event in events if event is not None)

    def _episode(self, case, *, learn, trace, random_source=None):
        warehouse = self.warehouse_type(*case)
        frames = [warehouse.frame()] if trace else None
        totals = dict.fromkeys(("Delivery", "Time", "Energy", "Exposure", "Blocked", "Failure"), 0.0)
        trajectory = []
        energy = 0.0
        observations = warehouse.observe()
        while warehouse.outcome == "running":
            actions, old_probabilities = self.policy.select(observations, self.random if learn else random_source)
            events = warehouse.step(actions)
            rewards = self.rewards(events, warehouse.outcome, self.profile, self.exposure_cost)
            energy += self.energy_spent(events)
            for term, value in rewards.items():
                totals[term] += value
            if trace:
                frames.append(warehouse.frame(events, rewards))
            next_observations = warehouse.observe() if warehouse.outcome == "running" else None
            if learn:
                potential = sum(item.remaining_steps for item in observations)
                future = sum(item.remaining_steps for item in next_observations) if next_observations else 0
                training_reward = (sum(rewards.values()) + 2 * (potential - GAMMA * future)) / 100
                trajectory.append((observations, actions, old_probabilities, training_reward))
            observations = next_observations
        if learn:
            self.rollout.append(trajectory)
        return {
            **warehouse.summary(), "reward": round(sum(totals.values()), 3),
            "breakdown": {term: round(value, 3) for term, value in totals.items()},
            "energy": round(energy, 2), "episode": len(self.history) + int(learn), "epsilon": None,
        }, frames

    def advance(self, batch_size):
        remaining = min(batch_size, self.total - len(self.history))
        batch = []
        frames = None
        for index in range(remaining):
            result, frames = self._episode(self.scenarios.choice(self.cases), learn=True, trace=index == remaining - 1)
            self.history.append(result)
            batch.append(result)
            if len(self.rollout) == ROLLOUT_EPISODES or len(self.history) == self.total:
                self.policy.update(self.rollout, self.random)
                self.rollout.clear()
        return {"episodes": batch, "frames": frames, "complete": len(self.history) == self.total}

    def replay(self, case=FLEET_CASES[0], *, trace=True, sample=None):
        random_source = None if sample is None else Random(self.seed ^ (0xF202 + 97 * self.cases.index(case) + sample))
        result, frames = self._episode(case, learn=False, trace=trace, random_source=random_source)
        return {"result": self.compare(case, result), "frames": frames}

    def compare(self, case, result):
        result["optimal_steps"] = len(fleet_route(*case))
        return result

    def evaluate(self, *, sampled=False):
        samples = range(4) if sampled else (None,)
        return [self.replay(case, trace=False, sample=sample)["result"] for case in self.cases for sample in samples]
