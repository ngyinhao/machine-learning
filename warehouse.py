from collections import deque
from copy import copy
from dataclasses import dataclass
from functools import cache
from random import Random

from agents import ActorCritic, DQN, PPO, Reinforce, TabularTD


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
PATROL = ((4, 4), (4, 5), (4, 6), (4, 7), (5, 7), (5, 6), (5, 5), (5, 4))
ACTIONS = ("Up", "Right", "Down", "Left", "Wait")
MOVES = ((0, -1), (1, 0), (0, 1), (-1, 0), (0, 0))
HORIZON = 100
GAMMA = 0.98
EXPLORATION_DEFAULTS = {"epsilon_min": 0.05, "decay_fraction": 0.8}
TABULAR_DEFAULTS = {
    "q_learning": {"alpha": 1.0, "gamma": 0.85, "epsilon_min": 0.02, "decay_fraction": 0.85, "initial_q": 100.0},
    "sarsa": {"alpha": 0.25, "gamma": GAMMA, **EXPLORATION_DEFAULTS, "initial_q": 0.0},
}
SUCCESS_OUTCOMES = ("delivered", "returned")
PROFILES = {
    "sparse": (0.0, 0.0, 0.0, 0.0),
    "efficiency": (0.2, 0.05, 0.0, 0.0),
    "balanced": (0.2, 0.05, 2.0, 1.0),
}


def walkable(cell):
    column, row = cell
    return 0 <= row < len(LAYOUT) and 0 <= column < len(LAYOUT[row]) and LAYOUT[row][column] != "#"


VALID_ACTIONS = {
    (column, row): tuple(
        action for action, (horizontal, vertical) in enumerate(MOVES)
        if walkable((column + horizontal, row + vertical))
    )
    for row, cells in enumerate(LAYOUT)
    for column, marker in enumerate(cells)
    if marker != "#"
}


@dataclass(frozen=True)
class Transition:
    action: int
    blocked: bool
    exposure: bool
    energy: float
    outcome: str


class Warehouse:
    def __init__(self, traffic, phase=0, *, round_trip=False):
        if traffic not in ("none", "patrol"):
            raise ValueError("Choose a supported traffic scenario.")
        self.position = START
        self.phase = phase % len(PATROL) if traffic == "patrol" else -1
        self.tick = 0
        self.outcome = "running"
        self.round_trip = round_trip
        self.delivery_tick = None

    @property
    def forklift(self):
        return PATROL[self.phase] if self.phase >= 0 else None

    @property
    def state(self):
        return self.position, self.phase, HORIZON - self.tick, self.delivery_tick is not None

    def frame(self, event=None, rewards=None):
        return {
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

    def step(self, action):
        if self.outcome != "running":
            raise RuntimeError("Start another episode after termination.")
        if type(action) is not int or not 0 <= action < len(MOVES):
            raise ValueError("Invalid movement action.")

        previous_position, previous_forklift = self.position, self.forklift
        horizontal, vertical = MOVES[action]
        candidate = (self.position[0] + horizontal, self.position[1] + vertical)
        blocked = not walkable(candidate)
        if not blocked:
            self.position = candidate
        if previous_forklift is not None:
            self.phase = (self.phase + 1) % len(PATROL)
        self.tick += 1
        forklift = self.forklift
        collision = forklift is not None and (
            self.position == forklift or (self.position == previous_forklift and previous_position == forklift)
        )
        if collision:
            self.outcome = "collision"
        elif self.position == DOCK and self.delivery_tick is None:
            self.delivery_tick = self.tick
            if not self.round_trip:
                self.outcome = "delivered"
        elif self.position == START and self.delivery_tick is not None:
            self.outcome = "returned"
        if self.outcome == "running" and self.tick == HORIZON:
            self.outcome = "timeout"

        exposure = forklift is not None and not collision and (
            abs(self.position[0] - forklift[0]) + abs(self.position[1] - forklift[1]) == 1
        )
        energy = 0.2 if blocked or action == 4 else 1.0
        return Transition(action, blocked, exposure, energy, self.outcome)


def score(event, profile, exposure_cost):
    time_cost, energy_cost, default_exposure, blocked_cost = PROFILES[profile]
    exposure_weight = exposure_cost if profile == "balanced" else default_exposure
    return {
        "Delivery": 100.0 if event.outcome in SUCCESS_OUTCOMES else 0.0,
        "Time": -time_cost,
        "Energy": -energy_cost * event.energy,
        "Exposure": -exposure_weight if event.exposure else 0.0,
        "Blocked": -blocked_cost if event.blocked else 0.0,
        "Failure": -100.0 if event.outcome in ("collision", "timeout") else 0.0,
    }


@cache
def fastest_route(traffic, phase, round_trip):
    initial = Warehouse(traffic, phase, round_trip=round_trip)
    queue = deque([(initial, ())])
    visited = {(initial.position, initial.phase, False)}
    while queue:
        environment, route = queue.popleft()
        for action in VALID_ACTIONS[environment.position]:
            successor = copy(environment)
            event = successor.step(action)
            if event.outcome in SUCCESS_OUTCOMES:
                return (*route, action)
            key = (successor.position, successor.phase, successor.delivery_tick is not None)
            if event.outcome == "running" and key not in visited:
                visited.add(key)
                queue.append((successor, (*route, action)))
    raise ValueError("No collision-free route completes this mission.")


def reference_trace(traffic, phase, round_trip, profile, exposure_cost):
    environment = Warehouse(traffic, phase, round_trip=round_trip)
    frames = [environment.frame()]
    for action in fastest_route(traffic, phase, round_trip):
        event = environment.step(action)
        frames.append(environment.frame(event, score(event, profile, exposure_cost)))
    return frames


def demo_route(round_trip=False):
    return reference_trace("none", 0, round_trip, "balanced", 2.0)


def dqn_potential(state, round_trip):
    position, _, _, returning = state
    goal = START if returning else DOCK
    distance = sum(abs(source - target) for source, target in zip(position, goal))
    if round_trip and not returning:
        distance += sum(abs(dock - home) for dock, home in zip(DOCK, START))
    return -10 * distance


AGENTS = {
    "q_learning": TabularTD,
    "sarsa": TabularTD,
    "dqn": lambda seed, round_trip: DQN(
        len(LAYOUT[0]), len(LAYOUT), len(PATROL), HORIZON, len(ACTIONS), GAMMA, seed,
        VALID_ACTIONS, lambda state: dqn_potential(state, round_trip),
    ),
    "reinforce": lambda seed, _round_trip: Reinforce(len(ACTIONS), GAMMA),
    "actor_critic": lambda seed, _round_trip: ActorCritic(len(ACTIONS), GAMMA),
    "ppo": lambda seed, _round_trip: PPO(len(ACTIONS), GAMMA, seed),
}


class TrainingRun:
    def __init__(self, *, episodes, seed, traffic, profile, exposure_cost, algorithm, round_trip=False,
                 alpha=None, gamma=None, epsilon_min=None, decay_fraction=None, initial_q=None):
        self.total = episodes
        self.seed = seed
        self.traffic = traffic
        self.profile = profile
        self.exposure_cost = exposure_cost
        self.algorithm = algorithm
        self.round_trip = round_trip
        self.random = Random(seed)
        self.scenarios = Random(seed ^ 0xF04C)
        defaults = TABULAR_DEFAULTS.get(algorithm, EXPLORATION_DEFAULTS)
        self.epsilon_min = defaults["epsilon_min"] if epsilon_min is None else epsilon_min
        self.decay_fraction = defaults["decay_fraction"] if decay_fraction is None else decay_fraction
        if algorithm in TABULAR_DEFAULTS:
            self.agent = AGENTS[algorithm](
                len(ACTIONS), defaults["gamma"] if gamma is None else gamma, algorithm == "sarsa",
                defaults["alpha"] if alpha is None else alpha,
                defaults["initial_q"] if initial_q is None else initial_q, VALID_ACTIONS,
            )
        else:
            self.agent = AGENTS[algorithm](seed, round_trip)
        self.history = []

    def _episode(self, environment, random_source, epsilon, learn, trace, episode):
        totals = dict.fromkeys(("Delivery", "Time", "Energy", "Exposure", "Blocked", "Failure"), 0.0)
        frames = [environment.frame()] if trace else None
        self.agent.start_episode(episode, learn)
        action = self.agent.select(environment.state, epsilon, random_source, learn)
        energy = exposures = blocked = waits = 0
        while environment.outcome == "running":
            state = environment.state
            event = environment.step(action)
            rewards = score(event, self.profile, self.exposure_cost)
            energy += event.energy
            exposures += event.exposure
            blocked += event.blocked
            waits += action == 4
            for name, value in rewards.items():
                totals[name] += value
            if trace:
                frames.append(environment.frame(event, rewards))

            next_state = environment.state if environment.outcome == "running" else None
            next_action = None
            if next_state is not None and self.agent.select_before_update:
                next_action = self.agent.select(next_state, epsilon, random_source, learn)
            if learn:
                self.agent.observe(state, action, sum(rewards.values()), next_state, next_action)
            if next_state is not None and not self.agent.select_before_update:
                next_action = self.agent.select(next_state, epsilon, random_source, learn)
            action = next_action

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
            environment = Warehouse(self.traffic, phase, round_trip=self.round_trip)
            result, frames = self._episode(environment, self.random, epsilon, True, index == count - 1, episode)
            result.update(episode=episode, epsilon=round(epsilon, 3) if epsilon is not None else None,
                          phase=phase if self.traffic == "patrol" else None)
            self.history.append(result)
            batch.append(result)
        return {"episodes": batch, "frames": frames, "complete": len(self.history) == self.total}

    def replay(self, *, phase=None, trace=True):
        random_source = Random(self.seed ^ 0x5EED)
        default_phase = random_source.randrange(len(PATROL))
        start_phase = 0 if self.traffic == "none" else default_phase if phase is None else phase % len(PATROL)
        environment = Warehouse(self.traffic, start_phase, round_trip=self.round_trip)
        result, frames = self._episode(environment, random_source, 0.0, False, trace, len(self.history))
        result["episode"] = len(self.history)
        result["phase"] = start_phase if self.traffic == "patrol" else None
        result["optimal_steps"] = len(fastest_route(self.traffic, start_phase, self.round_trip))
        return {"result": result, "frames": frames}

    def evaluate(self):
        phases = range(len(PATROL)) if self.traffic == "patrol" else (0,)
        return [self.replay(phase=phase, trace=False)["result"] for phase in phases]

    def reference(self, phase):
        return reference_trace(self.traffic, phase, self.round_trip, self.profile, self.exposure_cost)
