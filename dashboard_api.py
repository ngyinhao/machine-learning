import math
from uuid import uuid4

from warehouse import AGENTS, DOCK, EXPLORATION_DEFAULTS, LAYOUT, PATROL, PROFILES, START, TABULAR_DEFAULTS, TrainingRun, demo_route


HYPERPARAMETER_FIELDS = {
    "alpha": ("Learning rate (α)", 0, 1, "How strongly each update changes an action value."),
    "gamma": ("Discount factor (γ)", 0, 1, "How much future rewards count."),
    "epsilon_min": ("Minimum exploration (ε)", 0, 1, "The lowest probability of choosing a random action."),
    "decay_fraction": ("Exploration decay fraction", 0, 1, "Fraction of the run used to reduce exploration from 1 toward 0, stopping at minimum ε."),
    "initial_q": ("Initial Q-value", -1000, 1000, "Starting value for each state–action pair before learning."),
}


def training_hyperparameters():
    return {
        algorithm: [
            {"name": name, "label": label, "description": description, "min": lower, "max": upper,
             "default": defaults[name]}
            for name, (label, lower, upper, description) in HYPERPARAMETER_FIELDS.items()
            if name in defaults
        ]
        for algorithm, defaults in {**TABULAR_DEFAULTS, "dqn": EXPLORATION_DEFAULTS}.items()
    }


def warehouse_payload():
    return {
        "layout": LAYOUT, "start": START, "dock": DOCK, "patrol": PATROL,
        "demo": demo_route(), "round_trip_demo": demo_route(round_trip=True),
    }


def training_config(payload):
    episodes = payload.get("episodes")
    seed = payload.get("seed")
    traffic = payload.get("traffic")
    profile = payload.get("profile")
    algorithm = payload.get("algorithm")
    exposure_cost = payload.get("exposure_cost")
    round_trip = payload.get("round_trip", False)
    if type(episodes) is not int or not 25 <= episodes <= 3000:
        raise ValueError("Enter an episode count from 25 to 3,000.")
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValueError("Enter a seed from 0 to 4,294,967,295.")
    if traffic not in ("none", "patrol") or not isinstance(algorithm, str) or algorithm not in AGENTS:
        raise ValueError("Choose a supported algorithm and traffic scenario.")
    if not isinstance(profile, str) or profile not in PROFILES:
        raise ValueError("Choose a supported reward profile.")
    if type(exposure_cost) not in (int, float) or not 0 <= exposure_cost <= 20 or not math.isfinite(exposure_cost):
        raise ValueError("Enter an exposure cost from 0 to 20.")
    if type(round_trip) is not bool:
        raise ValueError("Choose a supported mission.")
    config = {
        "episodes": episodes, "seed": seed, "traffic": traffic, "profile": profile,
        "algorithm": algorithm, "exposure_cost": exposure_cost, "round_trip": round_trip,
    }
    for field in training_hyperparameters().get(algorithm, ()):
        name = field["name"]
        value = payload.get(name, field["default"])
        if type(value) not in (int, float) or not field["min"] <= value <= field["max"]:
            raise ValueError(f'Enter {field["label"].lower()} from {field["min"]} to {field["max"]}.')
        config[name] = value
    return config


class DashboardSession:
    def __init__(self):
        self.run = None
        self.run_id = None
        self.last_batch = None

    def dispatch(self, action, payload):
        if action == "start":
            config = training_config(payload)
            self.run = TrainingRun(**config)
            self.run_id = uuid4().hex
            self.last_batch = None
            return {"run_id": self.run_id, "config": config}
        if self.run is None or payload.get("run_id") != self.run_id:
            raise LookupError("Unknown run")
        if action == "advance":
            cursor = payload.get("cursor")
            if self.last_batch is not None and cursor == self.last_batch[0]:
                return self.last_batch[1]
            if type(cursor) is not int or cursor != len(self.run.history):
                raise ValueError("Training progress is out of sync. Start a new run.")
            result = self.run.advance(10)
            self.last_batch = (cursor, result)
            return result
        if action == "replay":
            replay = self.run.replay()
            phase = replay["result"]["phase"] or 0
            return {**replay, "evaluation": self.run.evaluate(), "reference": self.run.reference(phase)}
        raise ValueError("Action not found.")
