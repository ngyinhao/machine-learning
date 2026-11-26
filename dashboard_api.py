import math
from uuid import uuid4

from fleet import FLEET_ALGORITHMS, FLEET_CASES, FLEET_CHARGERS, FleetRun, fleet_reference
from fulfillment import CASES as SHIFT_CASES, CELLS as SHIFT_CELLS, QUEUE_BAYS, FulfillmentRun, fulfillment_reference
from warehouse import (
    AGENTS, BATTERY_CAPACITY, BATTERY_STARTS, CHARGER, DOCK, ENERGY_SCALE, EXPLORATION_DEFAULTS,
    FLOOR_PLANS, HELD_OUT_LAYOUT, LAYOUT, PACKING_STATION, PATROL, PICK_BAYS, PROFILES, REPLENISHMENT_ROUTE,
    REPLENISHMENT_STEP, START, TABULAR_DEFAULTS, TrainingRun, demo_route, shared_aisle_previews,
)


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
        "pick_bays": PICK_BAYS, "stocked_racks_demo": demo_route(order="CARTON"),
        "charger": CHARGER, "battery_capacity": BATTERY_CAPACITY / ENERGY_SCALE,
        "charging_demos": {case: demo_route(order="CARTON", battery_case=case) for case in BATTERY_STARTS},
        "packing_station": PACKING_STATION,
        "packing_demos": {
            case: demo_route(order="CARTON", battery_case=case, packing=True) for case in BATTERY_STARTS
        },
        "floor_plans": {
            layout: {
                "name": floor.name, "cells": floor.cells, "charger": floor.start, "dock": floor.dock,
                "packing_station": floor.packing_station, "pick_bays": floor.pick_bays,
                "held_out": layout == HELD_OUT_LAYOUT,
                "demos": {
                    case: demo_route(order="CARTON", battery_case=case, packing=True, layout=layout)
                    for case in BATTERY_STARTS
                },
            }
            for layout, floor in FLOOR_PLANS.items()
        },
        "shared_aisles": {
            "parking": REPLENISHMENT_ROUTE[0], "replenishment_bay": REPLENISHMENT_ROUTE[REPLENISHMENT_STEP],
            "previews": shared_aisle_previews(),
        },
        "fleet": {"chargers": FLEET_CHARGERS, "cases": FLEET_CASES, "preview": fleet_reference(*FLEET_CASES[0])},
        "fulfillment": {
            "queue_bays": QUEUE_BAYS, "cases": SHIFT_CASES,
            "floor": {
                "name": "Fulfillment floor", "cells": SHIFT_CELLS, "dock": DOCK, "charger": CHARGER,
                "packing_station": PACKING_STATION, "pick_bays": PICK_BAYS,
            },
            "preview": fulfillment_reference(SHIFT_CASES[2]),
        },
    }


def training_config(payload):
    episodes = payload.get("episodes")
    seed = payload.get("seed")
    traffic = payload.get("traffic")
    profile = payload.get("profile")
    algorithm = payload.get("algorithm")
    exposure_cost = payload.get("exposure_cost")
    round_trip = payload.get("round_trip", False)
    environment = payload.get("environment", "navigation")
    if not isinstance(environment, str):
        raise ValueError("Choose a supported warehouse environment.")
    if type(episodes) is not int or not 25 <= episodes <= 3000:
        raise ValueError("Enter an episode count from 25 to 3,000.")
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValueError("Enter a seed from 0 to 4,294,967,295.")
    allowed_algorithms = FLEET_ALGORITHMS if environment in (FleetRun.environment, FulfillmentRun.environment) else AGENTS
    if traffic not in ("none", "patrol") or not isinstance(algorithm, str) or algorithm not in allowed_algorithms:
        raise ValueError("Choose a supported algorithm and traffic scenario.")
    if not isinstance(profile, str) or profile not in PROFILES:
        raise ValueError("Choose a supported reward profile.")
    if type(exposure_cost) not in (int, float) or not 0 <= exposure_cost <= 20 or not math.isfinite(exposure_cost):
        raise ValueError("Enter an exposure cost from 0 to 20.")
    if type(round_trip) is not bool:
        raise ValueError("Choose a supported mission.")
    config = {
        "episodes": episodes, "seed": seed, "traffic": traffic, "profile": profile,
        "algorithm": algorithm, "exposure_cost": exposure_cost, "round_trip": round_trip, "environment": environment,
    }
    if environment in ("charging_dock", "pack_and_stage") or "warm_start" in payload:
        config["warm_start"] = payload.get("warm_start", False)
    if environment == "multiple_layouts" or "layout_training" in payload:
        config["layout_training"] = payload.get("layout_training", "original")
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
            run_type = {FleetRun.environment: FleetRun, FulfillmentRun.environment: FulfillmentRun}.get(
                config["environment"], TrainingRun,
            )
            self.run = run_type(**config)
            self.run_id = uuid4().hex
            self.last_batch = None
            if config["environment"] in ("charging_dock", "pack_and_stage"):
                config.update(
                    target_episodes=self.run.total,
                    pretraining_episodes=self.run.pretraining_episodes,
                    pretraining_ticks=self.run.pretraining_ticks,
                )
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
            if isinstance(self.run, FleetRun):
                mode = payload.get("policy_mode", "sampled")
                case_index = payload.get("fleet_case", 0)
                cases = self.run.cases
                if mode not in ("sampled", "greedy") or type(case_index) is not int or not 0 <= case_index < len(cases):
                    raise ValueError("Choose a supported fleet replay scenario and policy mode.")
                case = cases[case_index]
                sampled = mode == "sampled"
                reference = (fulfillment_reference(case, self.run.profile, self.run.exposure_cost)
                             if isinstance(self.run, FulfillmentRun)
                             else fleet_reference(*case, self.run.profile, self.run.exposure_cost))
                return {
                    **self.run.replay(case, sample=0 if sampled else None),
                    "evaluation": self.run.evaluate(sampled=sampled),
                    "reference": reference,
                }
            layout = payload.get("layout", "original")
            replay = self.run.replay(layout=layout)
            result = replay["result"]
            phase = result["phase"] or 0
            reference = self.run.reference(phase, result.get("order"), result.get("battery_case"),
                                           layout=layout, release_tick=result.get("release_tick"))
            return {
                **replay, "evaluation": self.run.evaluate(layout), "reference": reference,
                "seen_in_training": any(row.get("layout", "original") == layout for row in self.run.history),
            }
        raise ValueError("Action not found.")
