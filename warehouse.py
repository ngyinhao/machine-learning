from collections import deque
from copy import copy
from dataclasses import dataclass
from functools import cache
from random import Random

from agents import ActorCritic, DQN, ExploreThenCommit, Reinforce, TabularTD


LAYOUT = (
    "##########",
    "#........#",
    "#........#",
    "#.######.#",
    "#.##..##.#",
    "#S......D#",
    "#.##..##.#",
    "#.##..##.#",
    "#........#",
    "##########",
)
START = (1, 5)
DOCK = (8, 5)
CHARGER = START
PACKING_STATION = (7, 5)
ENERGY_SCALE = 10
MOVE_ENERGY = 10
IDLE_ENERGY = 2
BATTERY_CAPACITY = 140
PACKING_BATTERY_CAPACITY = 160
CHARGE_RATE = 10
BATTERY_STARTS = {"low": 120, "full": BATTERY_CAPACITY}
PICK_BAYS = {
    "CARTON": ("A", (2, 2)),
    "REFILL": ("B", (7, 8)),
}
PATROL = ((4, 4), (4, 5), (4, 6), (4, 7), (5, 7), (5, 6), (5, 5), (5, 4))
ACTIONS = ("Up", "Right", "Down", "Left", "Wait")
MOVES = ((0, -1), (1, 0), (0, 1), (-1, 0), (0, 0))
WAIT = ACTIONS.index("Wait")
HORIZON = 100
GAMMA = 0.98
EXPLORATION_DEFAULTS = {"epsilon_min": 0.05, "decay_fraction": 0.8}
TABULAR_DEFAULTS = {
    "q_learning": {"alpha": 1.0, "gamma": 0.85, "epsilon_min": 0.02, "decay_fraction": 0.85, "initial_q": 100.0},
    "sarsa": {"alpha": 0.25, "gamma": GAMMA, **EXPLORATION_DEFAULTS, "initial_q": 0.0},
}
SUCCESS_OUTCOMES = ("delivered", "returned")
FAILURE_OUTCOMES = ("collision", "depleted", "timeout")
PROFILES = {
    "sparse": (0.0, 0.0, 0.0, 0.0),
    "efficiency": (0.2, 0.05, 0.0, 0.0),
    "balanced": (0.2, 0.05, 2.0, 1.0),
}
ORIGINAL_LAYOUT = "original"
TRAINING_LAYOUTS = (ORIGINAL_LAYOUT, "parallel")
HELD_OUT_LAYOUT = "cross_aisle"
LAYOUT_PROGRESS_LIMIT = 25
SCRIPT_RELEASE_TICKS = (7, 10)
REPLENISHMENT_ROUTE = ((4, 4), (4, 5), (5, 5), (5, 6), (5, 6), (5, 5), (4, 5), (4, 4))
REPLENISHMENT_STEP = 4


@dataclass(frozen=True)
class FloorPlan:
    name: str
    cells: tuple
    start: tuple
    dock: tuple
    packing_station: tuple
    pick_bays: dict


FLOOR_PLANS = {
    ORIGINAL_LAYOUT: FloorPlan("Original", LAYOUT, START, DOCK, PACKING_STATION, PICK_BAYS),
    "parallel": FloorPlan(
        "Parallel aisles",
        (
            "##########", "#........#", "#.##.##..#", "#.##.##..#", "#.##.##..#",
            "#S.......#", "#.##.##..#", "#.##.##..#", "#.......D#", "##########",
        ),
        (1, 5), (8, 8), (7, 8), {"CARTON": ("A", (1, 3)), "REFILL": ("B", (7, 3))},
    ),
    HELD_OUT_LAYOUT: FloorPlan(
        "Offset cross-aisle",
        (
            "##########", "#........#", "#.###.##.#", "#.###.##.#", "#........#",
            "#.##.###.#", "#S##.###.#", "#.##.###.#", "#.......D#", "##########",
        ),
        (1, 6), (8, 8), (7, 8), {"CARTON": ("A", (4, 4)), "REFILL": ("B", (6, 4))},
    ),
}


def walkable(cell, layout=LAYOUT):
    column, row = cell
    return 0 <= row < len(layout) and 0 <= column < len(layout[row]) and layout[row][column] != "#"


def move_target(position, action):
    horizontal, vertical = MOVES[action]
    return position[0] + horizontal, position[1] + vertical


def legal_moves(layout):
    return {
        (column, row): tuple(
            action for action, (horizontal, vertical) in enumerate(MOVES)
            if walkable((column + horizontal, row + vertical), layout)
        )
        for row, cells in enumerate(layout)
        for column, marker in enumerate(cells)
        if marker != "#"
    }


FLOOR_ACTIONS = {layout: legal_moves(plan.cells) for layout, plan in FLOOR_PLANS.items()}
VALID_ACTIONS = FLOOR_ACTIONS[ORIGINAL_LAYOUT]


@cache
def distances_to(layout, target):
    distances = {target: 0}
    queue = deque([target])
    while queue:
        cell = queue.popleft()
        for action in FLOOR_ACTIONS[layout][cell]:
            horizontal, vertical = MOVES[action]
            neighbor = cell[0] + horizontal, cell[1] + vertical
            if neighbor not in distances:
                distances[neighbor] = distances[cell] + 1
                queue.append(neighbor)
    return distances


def shortest_route(*, crossing_row=None):
    queue = deque([(START, ())])
    visited = {START}
    while queue:
        cell, route = queue.popleft()
        if cell == DOCK:
            return route
        for action, (horizontal, vertical) in enumerate(MOVES[:4]):
            neighbor = (cell[0] + horizontal, cell[1] + vertical)
            if crossing_row is not None and neighbor[0] == 4 and neighbor[1] != crossing_row:
                continue
            if walkable(neighbor) and neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, (*route, action)))
    raise ValueError("The dock is unreachable.")


@dataclass(frozen=True)
class Transition:
    action: int
    blocked: bool
    exposure: bool
    energy: float
    outcome: str
    charged: int = 0


@dataclass(frozen=True)
class LayoutObservation:
    features: tuple
    actions: tuple
    guide: int | None
    remaining_steps: int


class Warehouse:
    def __init__(self, traffic, phase=0, *, round_trip=False, order=None, battery_case=None, packing=False,
                 layout=ORIGINAL_LAYOUT):
        if traffic not in ("none", "patrol"):
            raise ValueError("Choose a supported traffic scenario.")
        if not isinstance(layout, str) or layout not in FLOOR_PLANS:
            raise ValueError("Choose a supported floor plan.")
        if layout != ORIGINAL_LAYOUT and traffic == "patrol":
            raise ValueError("The forklift patrol uses the original floor plan.")
        self.layout = layout
        self.floor = FLOOR_PLANS[layout]
        if order is not None and order not in self.floor.pick_bays:
            raise ValueError("Choose an item stocked at a pick bay.")
        if battery_case is not None and battery_case not in BATTERY_STARTS:
            raise ValueError("Choose a supported starting charge.")
        if packing and order is None:
            raise ValueError("Packing requires a stocked-rack order.")
        self.position = self.floor.start
        self.phase = phase % len(PATROL) if traffic == "patrol" else -1
        self.tick = 0
        self.outcome = "running"
        self.round_trip = round_trip
        self.delivery_tick = None
        self.order = order
        self.cargo = None
        self.pickup_tick = None
        self.packing = packing
        self.pack_tick = None
        self.battery_case = battery_case
        self.battery_capacity = PACKING_BATTERY_CAPACITY if packing else BATTERY_CAPACITY
        self.initial_charge = None if battery_case is None else (
            BATTERY_STARTS[battery_case] + self.battery_capacity - BATTERY_CAPACITY
        )
        self.charge = self.initial_charge
        self.charge_ticks = 0
        self.charge_added = 0

    @property
    def forklift(self):
        return PATROL[self.phase] if self.phase >= 0 else None

    @property
    def state(self):
        navigation = self.position, self.phase, HORIZON - self.tick, self.delivery_tick is not None
        if self.order is not None:
            navigation += (self.order, self.cargo)
        if self.packing:
            navigation += (self.pack_tick is not None,)
        if self.charge is not None:
            navigation += (self.charge,)
        return navigation

    def layout_observation(self):
        pick = self.floor.pick_bays[self.order][1]
        pack = self.floor.packing_station
        stage = self.floor.dock
        waypoints = (pick, pack, stage) if self.cargo is None else (pack, stage) if self.pack_tick is None else (stage,)
        target = waypoints[0]
        distances = distances_to(self.layout, target)
        moves = distances[self.position]
        moves += sum(distances_to(self.layout, end)[start] for start, end in zip(waypoints, waypoints[1:]))
        services = len(waypoints) - 1
        demand = moves * MOVE_ENERGY + services * IDLE_ENERGY
        needs_charge = self.charge <= demand
        remaining_steps = moves + services
        feasible = True
        if needs_charge:
            charger = self.floor.start
            to_charger = distances_to(self.layout, charger)[self.position]
            detour = distances[charger] - distances[self.position]
            charger_demand = demand + detour * MOVE_ENERGY
            arrival_charge = self.charge - to_charger * MOVE_ENERGY
            feasible = arrival_charge >= 0 and charger_demand < self.battery_capacity
            deficit = charger_demand - arrival_charge
            remaining_steps += to_charger + detour + max(0, deficit // CHARGE_RATE + 1)
            target = charger
            distances = distances_to(self.layout, target)
        actions = FLOOR_ACTIONS[self.layout][self.position]
        progress = [0.0] * len(ACTIONS)
        distance = distances[self.position]
        for action in actions:
            horizontal, vertical = MOVES[action]
            neighbor = self.position[0] + horizontal, self.position[1] + vertical
            progress[action] = distance - distances[neighbor]
        if self.position == target:
            progress[WAIT] = 1.0
        features = (
            *progress, *(float(action in actions) for action in range(len(ACTIONS))),
            float(needs_charge), float(feasible), float(self.cargo is not None), float(self.pack_tick is not None),
            self.charge / self.battery_capacity, distance / 20, (HORIZON - self.tick) / HORIZON, 1.0,
        )
        guide = max(actions, key=progress.__getitem__) if feasible else None
        remaining_steps = min(remaining_steps, LAYOUT_PROGRESS_LIMIT) if feasible else LAYOUT_PROGRESS_LIMIT
        return LayoutObservation(features, actions, guide, remaining_steps)

    def frame(self, event=None, rewards=None):
        frame = {
            "layout": self.layout,
            "robot": self.position,
            "forklift": self.forklift,
            "tick": self.tick,
            "delivery_tick": self.delivery_tick,
            "outcome": self.outcome,
            "action": ACTIONS[event.action] if event else None,
            "exposure": event.exposure if event else False,
            "blocked": event.blocked if event else False,
            "rewards": rewards or {},
        }
        if self.order is not None:
            frame.update(
                order=self.order, cargo=self.cargo, pickup_tick=self.pickup_tick,
                stock={item: int(item != self.order or self.pickup_tick is None) for item in self.floor.pick_bays},
            )
        if self.charge is not None:
            frame.update(
                charge=self.charge / ENERGY_SCALE,
                charge_capacity=self.battery_capacity / ENERGY_SCALE,
                charged=event.charged / ENERGY_SCALE if event else 0,
                charge_ticks=self.charge_ticks,
            )
        if self.packing:
            frame["pack_tick"] = self.pack_tick
        return frame

    def step(self, action):
        if self.outcome != "running":
            raise RuntimeError("Start another episode after termination.")
        if type(action) is not int or not 0 <= action < len(MOVES):
            raise ValueError("Invalid movement action.")
        return self._step(action)

    def _step(self, action, *, denied=False):
        previous_position, previous_forklift = self.position, self.forklift
        candidate = move_target(self.position, action)
        blocked = action not in FLOOR_ACTIONS[self.layout][self.position]
        energy = IDLE_ENERGY if blocked or denied or action == WAIT else MOVE_ENERGY
        charging = self.charge is not None and previous_position == self.floor.start and action == WAIT
        powered = self.charge is None or charging or self.charge >= energy
        if not blocked and not denied and powered:
            self.position = candidate
        charged = 0
        if charging:
            charged = min(CHARGE_RATE, self.battery_capacity - self.charge)
            self.charge += charged
            self.charge_ticks += charged > 0
            self.charge_added += charged
        elif self.charge is not None:
            energy = min(self.charge, energy)
            self.charge -= energy
        if previous_forklift is not None:
            self.phase = (self.phase + 1) % len(PATROL)
        self.tick += 1
        forklift = self.forklift
        collision = forklift is not None and (
            self.position == forklift or (self.position == previous_forklift and previous_position == forklift)
        )
        if collision:
            self.outcome = "collision"
        elif not powered or (self.charge == 0 and self.position != self.floor.start):
            self.outcome = "depleted"
        elif (self.position == self.floor.dock and self.delivery_tick is None
              and (self.order is None or self.cargo == self.order)
              and (not self.packing or self.pack_tick is not None)):
            self.delivery_tick = self.tick
            self.cargo = None
            if not self.round_trip:
                self.outcome = "delivered"
        elif self.position == self.floor.start and self.delivery_tick is not None:
            self.outcome = "returned"
        elif (self.order is not None and self.pickup_tick is None
              and action == WAIT and self.position == self.floor.pick_bays[self.order][1]):
            self.cargo = self.order
            self.pickup_tick = self.tick
        elif (self.packing and self.pack_tick is None and self.cargo == self.order
              and action == WAIT and self.position == self.floor.packing_station):
            self.pack_tick = self.tick
        if self.outcome == "running" and self.tick == HORIZON:
            self.outcome = "timeout"

        exposure = forklift is not None and not collision and (
            abs(self.position[0] - forklift[0]) + abs(self.position[1] - forklift[1]) == 1
        )
        return Transition(action, blocked, exposure, energy / ENERGY_SCALE, self.outcome, charged)


@dataclass(frozen=True)
class AisleDecision:
    conflict: str | None = None
    primary_denied: bool = False
    scripted_denied: bool = False


def resolve_aisle_moves(primary, scripted, primary_target, scripted_target):
    if primary_target == scripted and scripted_target == primary:
        return AisleDecision("swap", True, True)
    if primary_target == scripted_target:
        if scripted_target == scripted:
            return AisleDecision("occupied", primary_denied=True)
        if primary_target == primary:
            return AisleDecision("occupied", scripted_denied=True)
        return AisleDecision("same_cell", primary_denied=True)
    return AisleDecision()


class SharedWarehouse(Warehouse):
    def __init__(self, order, battery_case, release_tick):
        if type(release_tick) is not int or release_tick not in SCRIPT_RELEASE_TICKS:
            raise ValueError("Choose a supported replenishment release tick.")
        if battery_case is None:
            raise ValueError("Shared aisles requires a starting charge.")
        super().__init__("none", order=order, battery_case=battery_case, packing=True)
        self.release_tick = release_tick
        self.script_index = 0
        self.script_action = None
        self.decision = AisleDecision()
        self.primary_denials = self.scripted_denials = self.stall_ticks = 0

    @property
    def scripted_robot(self):
        return REPLENISHMENT_ROUTE[self.script_index]

    @property
    def replenished(self):
        return self.script_index >= REPLENISHMENT_STEP

    @property
    def script_parked(self):
        return self.script_index == len(REPLENISHMENT_ROUTE) - 1

    @property
    def state(self):
        return (*super().state, self.script_index, max(0, self.release_tick - self.tick))

    def _next_script_index(self):
        return self.script_index + int(self.tick >= self.release_tick and not self.script_parked)

    def _decision(self, action, scripted_target):
        can_move = self.charge >= MOVE_ENERGY and action in VALID_ACTIONS[self.position]
        primary_target = move_target(self.position, action) if can_move else self.position
        return resolve_aisle_moves(self.position, self.scripted_robot, primary_target, scripted_target)

    def layout_observation(self):
        observation = super().layout_observation()
        scripted_target = REPLENISHMENT_ROUTE[self._next_script_index()]
        decisions = [self._decision(action, scripted_target) for action in range(len(ACTIONS))]
        guide = observation.guide
        if guide is not None and (decisions[guide].primary_denied or decisions[guide].scripted_denied):
            clear = [action for action in observation.actions
                     if not decisions[action].primary_denied and not decisions[action].scripted_denied]
            if clear:
                guide = WAIT if WAIT in clear else max(clear, key=observation.features.__getitem__)
        return LayoutObservation(
            (*observation.features, *(float(decision.primary_denied) for decision in decisions),
             *(float(decision.scripted_denied) for decision in decisions)),
            observation.actions, guide, observation.remaining_steps,
        )

    def _step(self, action):
        primary, scripted = self.position, self.scripted_robot
        next_index = self._next_script_index()
        scripted_target = REPLENISHMENT_ROUTE[next_index]
        offset = (scripted_target[0] - scripted[0], scripted_target[1] - scripted[1])
        self.script_action = ACTIONS[MOVES.index(offset)]
        self.decision = self._decision(action, scripted_target)
        event = super()._step(action, denied=self.decision.primary_denied)
        if not self.decision.scripted_denied:
            self.script_index = next_index
        self.primary_denials += self.decision.primary_denied
        self.scripted_denials += self.decision.scripted_denied
        self.stall_ticks += bool(self.decision.conflict and self.position == primary and self.scripted_robot == scripted)
        return event

    def frame(self, event=None, rewards=None):
        return {
            **super().frame(event, rewards),
            **self.traffic_summary(),
            "scripted_robot": self.scripted_robot,
            "script_action": self.script_action,
            "conflict": self.decision.conflict,
            "primary_denied": self.decision.primary_denied,
            "scripted_denied": self.decision.scripted_denied,
        }

    def traffic_summary(self):
        return {
            "release_tick": self.release_tick, "primary_denials": self.primary_denials,
            "scripted_denials": self.scripted_denials, "stall_ticks": self.stall_ticks,
            "replenished": self.replenished, "script_parked": self.script_parked,
        }


def create_warehouse(traffic, phase, round_trip, order, battery_case, *, packing, layout, release_tick):
    if release_tick is not None:
        if (traffic, round_trip, packing, layout) != ("none", False, True, ORIGINAL_LAYOUT):
            raise ValueError("Shared aisles uses the original packing floor and replenishment traffic.")
        return SharedWarehouse(order, battery_case, release_tick)
    return Warehouse(traffic, phase, round_trip=round_trip, order=order, battery_case=battery_case,
                     packing=packing, layout=layout)


def score(event, profile, exposure_cost):
    time_cost, energy_cost, default_exposure, blocked_cost = PROFILES[profile]
    exposure_weight = exposure_cost if profile == "balanced" else default_exposure
    return {
        "Delivery": 100.0 if event.outcome in SUCCESS_OUTCOMES else 0.0,
        "Time": -time_cost,
        "Energy": -energy_cost * event.energy,
        "Exposure": -exposure_weight if event.exposure else 0.0,
        "Blocked": -blocked_cost if event.blocked else 0.0,
        "Failure": -100.0 if event.outcome in FAILURE_OUTCOMES else 0.0,
    }


@cache
def fastest_route(traffic, phase, round_trip, order=None, battery_case=None, *, packing=False, layout=ORIGINAL_LAYOUT,
                  release_tick=None):
    initial = create_warehouse(traffic, phase, round_trip, order, battery_case,
                               packing=packing, layout=layout, release_tick=release_tick)
    queue = deque([(initial, ())])
    visited = {initial.state[:2] + initial.state[3:]}
    while queue:
        environment, route = queue.popleft()
        for action in FLOOR_ACTIONS[layout][environment.position]:
            successor = copy(environment)
            event = successor.step(action)
            if event.outcome in SUCCESS_OUTCOMES:
                return (*route, action)
            state = successor.state
            key = state[:2] + state[3:]
            if event.outcome == "running" and key not in visited:
                visited.add(key)
                queue.append((successor, (*route, action)))
    raise ValueError("No feasible route completes this mission.")


def reference_trace(traffic, phase, round_trip, profile, exposure_cost, order=None, battery_case=None, *,
                    packing=False, layout=ORIGINAL_LAYOUT, release_tick=None):
    environment = create_warehouse(traffic, phase, round_trip, order, battery_case,
                                   packing=packing, layout=layout, release_tick=release_tick)
    frames = [environment.frame()]
    for action in fastest_route(traffic, phase, round_trip, order, battery_case, packing=packing, layout=layout,
                                release_tick=release_tick):
        event = environment.step(action)
        frames.append(environment.frame(event, score(event, profile, exposure_cost)))
    return frames


def demo_route(round_trip=False, order=None, battery_case=None, *, packing=False, layout=ORIGINAL_LAYOUT):
    return reference_trace("none", 0, round_trip, "balanced", 2.0, order, battery_case, packing=packing, layout=layout)


def shared_aisle_previews():
    previews = {
        "carton": {
            case: reference_trace("none", 0, False, "balanced", 0, "CARTON", case, packing=True,
                                  release_tick=SCRIPT_RELEASE_TICKS[-1])
            for case in BATTERY_STARTS
        },
    }
    first_release = SCRIPT_RELEASE_TICKS[0]
    right = ACTIONS.index("Right")
    left = ACTIONS.index("Left")
    requests = {
        "same_cell": [right] * 2 + [WAIT] * (first_release - 2) + [right, right],
        "swap": [right] * 4 + [WAIT] * (first_release - 3) + [left, right],
        "occupied": [right] * 4 + [WAIT] * (first_release - 2) + [right, WAIT],
    }
    for name, actions in requests.items():
        environment = SharedWarehouse("CARTON", "full", first_release)
        frames = [environment.frame()]
        for action in actions:
            event = environment.step(action)
            frames.append(environment.frame(event, score(event, "balanced", 0)))
        previews[name] = frames
    return previews


def route_options(round_trip):
    routes = tuple(shortest_route(crossing_row=row) for row in (None, 2, 8))
    if round_trip:
        return tuple(route + tuple((action + 2) % 4 for action in reversed(route)) for route in routes)
    return routes


AGENTS = {
    "q_learning": TabularTD,
    "sarsa": TabularTD,
    "dqn": lambda episodes, seed, round_trip: DQN(
        len(LAYOUT[0]), len(LAYOUT), len(PATROL), HORIZON, len(ACTIONS), GAMMA, seed
    ),
    "reinforce": lambda episodes, seed, round_trip: Reinforce(len(ACTIONS), GAMMA),
    "actor_critic": lambda episodes, seed, round_trip: ActorCritic(len(ACTIONS), GAMMA),
    "etc": lambda episodes, seed, round_trip: ExploreThenCommit(route_options(round_trip), episodes, HORIZON),
}


class TrainingRun:
    def __init__(self, *, episodes, seed, traffic, profile, exposure_cost, algorithm, round_trip=False,
                 environment="navigation", warm_start=False, alpha=None, gamma=None, epsilon_min=None,
                 decay_fraction=None, initial_q=None, packing_practice=False, layout_training="original"):
        if environment not in ("navigation", "stocked_racks", "charging_dock", "pack_and_stage", "multiple_layouts",
                               "shared_aisles"):
            raise ValueError("Choose a supported warehouse environment.")
        self.multiple_layouts = environment == "multiple_layouts"
        self.shared_aisles = environment == "shared_aisles"
        self.uses_layout_observation = self.multiple_layouts or self.shared_aisles
        required_algorithm = "dqn" if self.uses_layout_observation else "q_learning"
        if environment != "navigation" and (algorithm, traffic, round_trip) != (required_algorithm, "none", False):
            raise ValueError(f"This environment uses {required_algorithm} and a one-way mission without a forklift.")
        if layout_training not in ("original", "mixed") or (layout_training == "mixed" and not self.multiple_layouts):
            raise ValueError("Mixed-layout training is available in Multiple layouts.")
        self.packing = environment == "pack_and_stage" or self.uses_layout_observation
        if packing_practice and environment != "pack_and_stage":
            raise ValueError("Packing practice applies to the Pack and stage environment.")
        battery_enabled = (self.packing or environment == "charging_dock") and not packing_practice
        if type(warm_start) is not bool or (warm_start and (not battery_enabled or self.uses_layout_observation)):
            raise ValueError("Warm start is available for charging and packing runs with a battery.")
        self.pretraining_episodes = episodes // 2 if warm_start else 0
        self.pretraining_ticks = 0
        self.total = episodes - self.pretraining_episodes
        self.seed = seed
        self.traffic = traffic
        self.profile = profile
        self.exposure_cost = exposure_cost
        self.algorithm = algorithm
        self.round_trip = round_trip
        self.random = Random(seed)
        self.scenarios = Random(seed ^ 0xF04C)
        self.order_choices = tuple(PICK_BAYS) if environment != "navigation" else (None,)
        self.orders = Random(seed ^ 0xA11D)
        self.battery_choices = tuple(BATTERY_STARTS) if battery_enabled else (None,)
        self.batteries = Random(seed ^ 0xBA77)
        self.layouts = Random(seed ^ 0xF100)
        self.releases = Random(seed ^ 0xA152)
        self.release_choices = SCRIPT_RELEASE_TICKS if self.shared_aisles else (None,)
        self.training_layouts = TRAINING_LAYOUTS if layout_training == "mixed" else (ORIGINAL_LAYOUT,)
        defaults = TABULAR_DEFAULTS.get(algorithm, EXPLORATION_DEFAULTS)
        self.epsilon_min = defaults["epsilon_min"] if epsilon_min is None else epsilon_min
        self.decay_fraction = defaults["decay_fraction"] if decay_fraction is None else decay_fraction
        if self.uses_layout_observation:
            sample = self._warehouse(0, self.order_choices[0], "full", ORIGINAL_LAYOUT, self.release_choices[0])
            self.agent = DQN(0, 0, 0, HORIZON, len(ACTIONS), GAMMA, seed,
                             feature_count=len(sample.layout_observation().features))
        elif algorithm in TABULAR_DEFAULTS:
            self.agent = AGENTS[algorithm](
                len(ACTIONS), defaults["gamma"] if gamma is None else gamma, algorithm == "sarsa",
                defaults["alpha"] if alpha is None else alpha,
                defaults["initial_q"] if initial_q is None else initial_q, VALID_ACTIONS,
            )
        else:
            self.agent = AGENTS[algorithm](episodes, seed, round_trip)
        self.history = []
        if self.pretraining_episodes:
            warmup = TrainingRun(
                episodes=self.pretraining_episodes, seed=seed, traffic=traffic, profile=profile,
                exposure_cost=exposure_cost, algorithm=algorithm,
                environment="pack_and_stage" if self.packing else "stocked_racks", packing_practice=self.packing,
                alpha=alpha, gamma=gamma, epsilon_min=epsilon_min, decay_fraction=decay_fraction, initial_q=initial_q,
            )
            warmup.advance(warmup.total)
            self.pretraining_ticks = sum(result["steps"] for result in warmup.history)
            self.agent.values.update({
                (*key, charge): values.copy()
                for key, values in warmup.agent.values.items()
                for charge in range((PACKING_BATTERY_CAPACITY if self.packing else BATTERY_CAPACITY) + 1)
            })

    def _warehouse(self, phase, order, battery_case, layout, release_tick):
        return create_warehouse(self.traffic, phase, self.round_trip, order, battery_case,
                                packing=self.packing, layout=layout, release_tick=release_tick)

    def _episode(self, environment, random_source, epsilon, learn, trace, episode):
        totals = dict.fromkeys(("Delivery", "Time", "Energy", "Exposure", "Blocked", "Failure"), 0.0)
        frames = [environment.frame()] if trace else None
        self.agent.start_episode(episode, learn)
        observation = environment.layout_observation if self.uses_layout_observation else lambda: environment.state
        state = observation()
        action = self.agent.select(state, epsilon, random_source, learn)
        energy = exposures = blocked = waits = 0
        while environment.outcome == "running":
            event = environment.step(action)
            rewards = score(event, self.profile, self.exposure_cost)
            energy += event.energy
            exposures += event.exposure
            blocked += event.blocked
            waits += action == WAIT
            for name, value in rewards.items():
                totals[name] += value
            if trace:
                frames.append(environment.frame(event, rewards))

            next_state = observation() if environment.outcome == "running" else None
            next_action = None
            if next_state is not None and self.agent.select_before_update:
                next_action = self.agent.select(next_state, epsilon, random_source, learn)
            if learn:
                reward = sum(rewards.values())
                if self.uses_layout_observation:
                    future = next_state.remaining_steps if next_state is not None else 0
                    reward += 2 * (state.remaining_steps - GAMMA * future)
                self.agent.observe(state, action, reward, next_state, next_action)
            if next_state is not None and not self.agent.select_before_update:
                next_action = self.agent.select(next_state, epsilon, random_source, learn)
            action = next_action
            state = next_state

        reward = sum(totals.values())
        if learn:
            self.agent.finish_episode(reward)
        summary = {
            "outcome": environment.outcome,
            "reward": round(reward, 3),
            "steps": environment.tick,
            "delivery_tick": environment.delivery_tick,
            "energy": round(energy, 2),
            "exposures": exposures,
            "blocked": blocked,
            "waits": waits,
            "breakdown": {name: round(value, 3) for name, value in totals.items()},
        }
        if environment.order is not None:
            summary.update(order=environment.order, pickup_tick=environment.pickup_tick)
        if environment.packing:
            summary["pack_tick"] = environment.pack_tick
        if self.multiple_layouts:
            summary["layout"] = environment.layout
        if self.shared_aisles:
            summary.update(environment.traffic_summary())
        if environment.charge is not None:
            summary.update(
                battery_case=environment.battery_case,
                initial_charge=environment.initial_charge / ENERGY_SCALE,
                end_charge=environment.charge / ENERGY_SCALE,
                charge_ticks=environment.charge_ticks,
                charge_added=environment.charge_added / ENERGY_SCALE,
            )
        return summary, frames

    def advance(self, batch_size):
        batch = []
        count = min(batch_size, self.total - len(self.history))
        frames = None
        for index in range(count):
            episode = len(self.history) + 1
            epsilon = None
            if self.agent.uses_epsilon:
                progress = (episode - 1) / max(1, (self.total - 1) * self.decay_fraction)
                epsilon = max(self.epsilon_min, 1 - progress)
            phase = self.scenarios.randrange(len(PATROL))
            order = self.orders.choice(self.order_choices)
            battery_case = self.batteries.choice(self.battery_choices)
            layout = self.layouts.choice(self.training_layouts)
            release_tick = self.releases.choice(self.release_choices)
            environment = self._warehouse(phase, order, battery_case, layout, release_tick)
            result, frames = self._episode(environment, self.random, epsilon, True, index == count - 1, episode)
            result.update(episode=episode, epsilon=round(epsilon, 3) if epsilon is not None else None,
                          phase=phase if self.traffic == "patrol" else None)
            self.history.append(result)
            batch.append(result)
        return {"episodes": batch, "frames": frames, "complete": len(self.history) == self.total}

    def replay(self, *, phase=None, order=None, battery_case=None, trace=True, layout=ORIGINAL_LAYOUT, release_tick=None):
        if layout != ORIGINAL_LAYOUT and not self.multiple_layouts:
            raise ValueError("This run uses the original floor plan.")
        random_source = Random(self.seed ^ 0x5EED)
        default_phase = random_source.randrange(len(PATROL))
        start_phase = 0 if self.traffic == "none" else default_phase if phase is None else phase % len(PATROL)
        if order is None:
            order = Random(self.seed ^ 0xBA5E).choice(self.order_choices)
        elif order not in self.order_choices:
            raise ValueError("This order is unavailable in the selected environment.")
        if battery_case is None:
            battery_case = self.battery_choices[0]
        elif battery_case not in self.battery_choices:
            raise ValueError("This starting charge is unavailable in the selected environment.")
        if release_tick is None:
            release_tick = self.release_choices[-1]
        if release_tick not in self.release_choices:
            raise ValueError("This replenishment release is unavailable in the selected environment.")
        environment = self._warehouse(start_phase, order, battery_case, layout, release_tick)
        result, frames = self._episode(environment, random_source, 0.0, False, trace, len(self.history))
        result["episode"] = len(self.history)
        result["phase"] = start_phase if self.traffic == "patrol" else None
        result["optimal_steps"] = len(fastest_route(self.traffic, start_phase, self.round_trip, order, battery_case,
                                                   packing=self.packing, layout=layout, release_tick=release_tick))
        return {"result": result, "frames": frames}

    def evaluate(self, layout=ORIGINAL_LAYOUT):
        phases = range(len(PATROL)) if self.traffic == "patrol" else (0,)
        return [self.replay(phase=phase, order=order, battery_case=battery_case, trace=False, layout=layout,
                            release_tick=release_tick)["result"]
                for phase in phases for order in self.order_choices for battery_case in self.battery_choices
                for release_tick in self.release_choices]

    def reference(self, phase, order=None, battery_case=None, *, layout=ORIGINAL_LAYOUT, release_tick=None):
        if release_tick is None:
            release_tick = self.release_choices[-1]
        if release_tick not in self.release_choices:
            raise ValueError("This replenishment release is unavailable in the selected environment.")
        return reference_trace(self.traffic, phase, self.round_trip, self.profile, self.exposure_cost, order, battery_case,
                               packing=self.packing, layout=layout, release_tick=release_tick)
