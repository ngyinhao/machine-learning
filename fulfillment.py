from collections import deque
from dataclasses import asdict, dataclass
from functools import cache
from itertools import product

from fleet import FLEET_CHARGERS, FleetObservation, FleetRun
from warehouse import (
    ACTIONS, CHARGE_RATE, DOCK, ENERGY_SCALE, IDLE_ENERGY, LAYOUT, MOVE_ENERGY, PACKING_STATION,
    PICK_BAYS, PROFILES, WAIT, legal_moves, move_target, resolve_aisle_moves,
)


SHIFT_TICKS = 80
PACK_TICKS = 3
CAPACITY = 420
QUEUE_BAYS = ((6, 5), (7, 4))
CELLS = (*LAYOUT[:4], "#.##..#..#", *LAYOUT[5:])
AISLES = legal_moves(CELLS)
RELEASES = {"paced": (0, 0, 28, 40, 58, 72), "burst": tuple(tick for tick in range(0, 48, 8) for _ in range(2))}
CASES = tuple(product(RELEASES, PICK_BAYS))


@cache
def distances(target):
    costs = {target: 0}
    queue = deque([target])
    while queue:
        point = queue.popleft()
        for action in AISLES[point]:
            neighbor = move_target(point, action)
            if neighbor not in costs:
                costs[neighbor] = costs[point] + 1
                queue.append(neighbor)
    return costs


@dataclass
class Order:
    id: int
    item: str
    release_tick: int
    robot: int | None = None
    assigned_tick: int | None = None
    pickup_tick: int | None = None
    queue_tick: int | None = None
    pack_start_tick: int | None = None
    pack_tick: int | None = None
    delivery_tick: int | None = None
    stranded_tick: int | None = None
    queue_wait: int = 0


@dataclass
class ShiftRobot:
    position: tuple
    charge: int = CAPACITY
    job: int | None = None
    depleted: bool = False
    action: int | None = None
    denials: int = 0
    waits: int = 0


@dataclass(frozen=True)
class ShiftEvent:
    energy: float
    delivered: int
    depleted: int
    active: int


class FulfillmentWarehouse:
    def __init__(self, workload, first_item):
        if (workload, first_item) not in CASES:
            raise ValueError("Choose a supported fulfillment workload.")
        other_item = next(item for item in PICK_BAYS if item != first_item)
        self.schedule = tuple((tick, (first_item, other_item)[index % 2])
                              for index, tick in enumerate(RELEASES[workload]))
        self.workload = workload
        self.first_item = first_item
        self.robots = tuple(ShiftRobot(charger) for charger in FLEET_CHARGERS)
        self.orders = []
        self.pending = deque()
        self.stock = dict.fromkeys(PICK_BAYS, 0)
        self.reserved = dict.fromkeys(PICK_BAYS, 0)
        self.queue = deque()
        self.packing_id = None
        self.service_left = 0
        self.tick = self.stall_ticks = self.peak_queue = self.packing_ticks = 0
        self.outcome = "running"
        self.conflict = None
        self.denied = (False, False)
        self._release_and_dispatch()

    def order_for(self, robot):
        return self.orders[robot.job - 1] if robot.job is not None else None

    def _release_and_dispatch(self):
        for index in range(len(self.orders), len(self.schedule)):
            release, item = self.schedule[index]
            if release != self.tick:
                break
            self.orders.append(Order(index + 1, item, release))
            self.pending.append(index + 1)
            self.stock[item] += 1
        for index, robot in enumerate(self.robots):
            if self.pending and robot.job is None and not robot.depleted and robot.position == FLEET_CHARGERS[index]:
                order = self.orders[self.pending.popleft() - 1]
                robot.job = order.id
                order.robot = index + 1
                order.assigned_tick = self.tick
                self.reserved[order.item] += 1

    def _trip_charge(self, index, order):
        home, bay = FLEET_CHARGERS[index], QUEUE_BAYS[index]
        pick = PICK_BAYS[order.item][1]
        moves = distances(pick)[home] + distances(bay)[pick] + 2 + distances(home)[DOCK]
        return min(CAPACITY, moves * MOVE_ENERGY + (PACK_TICKS + 1) * IDLE_ENERGY + 30)

    def _goal(self, index):
        robot = self.robots[index]
        order = self.order_for(robot)
        home = FLEET_CHARGERS[index]
        if robot.depleted or self.packing_id is not None and self.packing_id == robot.job:
            return robot.position
        if order is None or order.delivery_tick is not None:
            return home
        if order.pickup_tick is None:
            if robot.position == home and robot.charge < self._trip_charge(index, order):
                return home
            return PICK_BAYS[order.item][1]
        if order.pack_tick is not None:
            return DOCK
        if self.queue and self.queue[0] == order.id and self.packing_id is None:
            return PACKING_STATION
        return QUEUE_BAYS[index]

    def _remaining_steps(self, index, order, target, distance):
        if order is None or order.delivery_tick is not None:
            return distance
        robot = self.robots[index]
        returning = distances(FLEET_CHARGERS[index])[DOCK]
        if self.packing_id == order.id:
            return self.service_left + 1 + returning
        if order.pack_tick is not None:
            return distance + returning
        bay = QUEUE_BAYS[index]
        if order.pickup_tick is not None:
            approach = int(target != PACKING_STATION)
            return distance + approach + PACK_TICKS + 1 + returning
        pick = PICK_BAYS[order.item][1]
        if robot.position == FLEET_CHARGERS[index]:
            deficit = max(0, self._trip_charge(index, order) - robot.charge)
            distance = distances(pick)[robot.position] + (deficit + CHARGE_RATE - 1) // CHARGE_RATE
        return distance + 1 + distances(bay)[pick] + 1 + PACK_TICKS + 1 + returning

    def observe(self):
        observations = []
        for index, robot in enumerate(self.robots):
            peer = self.robots[1 - index]
            target = self._goal(index)
            if robot.depleted:
                observations.append(FleetObservation((WAIT,), (), (1.0, 0, 0, 0, 0, 0, 0, 0), 0))
                continue
            must_wait = robot.position == target
            gate_closed = target != PACKING_STATION and (self.packing_id is not None or bool(self.queue))
            actions = (WAIT,) if must_wait else tuple(
                action for action in AISLES[robot.position]
                if not gate_closed or move_target(robot.position, action) != PACKING_STATION or action == WAIT
            )
            if target == PACKING_STATION:
                actions = tuple(action for action in actions
                                if action == WAIT or move_target(robot.position, action) == PACKING_STATION)
            costs = distances(target)
            distance = costs[robot.position]
            peer_distances = distances(peer.position)
            near = peer_distances[robot.position] <= 2
            features = tuple(
                (progress, float(action == WAIT), float(destination == peer.position), float(near and action == WAIT),
                 float(near) * progress, float(near and peer_distances[destination] == 1),
                 float(must_wait))
                for action in actions
                for destination in (move_target(robot.position, action),)
                for progress in (distance - costs[destination],)
            )
            order = self.order_for(robot)
            value = (
                1.0, 1.0, distance / 25, robot.charge / CAPACITY,
                float(order is not None and order.pickup_tick is not None),
                float(order is not None and order.pack_tick is not None),
                (SHIFT_TICKS - self.tick) / SHIFT_TICKS, float(near),
            )
            observations.append(FleetObservation(actions, features, value, self._remaining_steps(index, order, target, distance)))
        return tuple(observations)

    def targets(self, actions):
        return tuple(move_target(robot.position, action) if robot.charge >= MOVE_ENERGY else robot.position
                     for robot, action in zip(self.robots, actions))

    def step(self, actions, observations=None):
        if self.outcome != "running":
            raise RuntimeError("Start another fulfillment shift after termination.")
        observations = self.observe() if observations is None else observations
        if len(actions) != 2 or any(type(action) is not int or action not in observation.actions
                                    for action, observation in zip(actions, observations)):
            raise ValueError("Choose one allowed action per AMR.")
        origins = tuple(robot.position for robot in self.robots)
        targets = self.targets(actions)
        decision = resolve_aisle_moves(*origins, *targets)
        self.conflict = decision.conflict
        self.denied = (decision.primary_denied, decision.scripted_denied)
        existing_packing = self.packing_id
        active = energy = depleted = delivered = 0
        self.tick += 1
        for order_id in self.queue:
            self.orders[order_id - 1].queue_wait += 1
        for index, (robot, action, target, denied) in enumerate(zip(self.robots, actions, targets, self.denied)):
            robot.action = action
            if robot.depleted:
                continue
            active += robot.job is not None
            robot.denials += denied
            destination = robot.position if denied else target
            stayed = destination == robot.position
            robot.waits += stayed and robot.job is not None
            spend = IDLE_ENERGY if stayed else MOVE_ENERGY
            charging = action == WAIT and robot.position == FLEET_CHARGERS[index]
            if charging:
                robot.charge = min(CAPACITY, robot.charge + CHARGE_RATE)
            else:
                energy += min(spend, robot.charge)
                robot.charge = max(0, robot.charge - spend)
            robot.position = destination
            if robot.charge == 0 and robot.position != FLEET_CHARGERS[index]:
                robot.depleted = True
                depleted += 1
                order = self.order_for(robot)
                if order is not None and order.delivery_tick is None:
                    order.stranded_tick = self.tick
                if robot.job in self.queue:
                    self.queue.remove(robot.job)
                if self.packing_id is not None and self.packing_id == robot.job:
                    self.packing_id, self.service_left = None, 0
                continue
            delivered += self._service(index, action, existing_packing)
        self.stall_ticks += bool(self.conflict and origins == tuple(robot.position for robot in self.robots))
        self.peak_queue = max(self.peak_queue, len(self.queue))
        self._release_and_dispatch()
        if self.tick == SHIFT_TICKS:
            self.outcome = "delivered" if all(order.delivery_tick is not None for order in self.orders) else "shift_ended"
        return ShiftEvent(energy / ENERGY_SCALE, delivered, depleted, active)

    def _service(self, index, action, existing_packing):
        robot = self.robots[index]
        order = self.order_for(robot)
        if order is None:
            return 0
        if order.delivery_tick is not None:
            if robot.position == FLEET_CHARGERS[index]:
                robot.job = None
        elif order.pickup_tick is None:
            if robot.position == PICK_BAYS[order.item][1] and action == WAIT:
                order.pickup_tick = self.tick
                self.stock[order.item] -= 1
                self.reserved[order.item] -= 1
        elif order.pack_tick is not None:
            if robot.position == DOCK:
                order.delivery_tick = self.tick
                return 1
        elif existing_packing == order.id:
            self.service_left -= 1
            self.packing_ticks += 1
            if not self.service_left:
                order.pack_tick = self.tick
                self.packing_id = None
        elif self.queue and self.queue[0] == order.id and self.packing_id is None and robot.position == PACKING_STATION:
            self.packing_id, self.service_left = self.queue.popleft(), PACK_TICKS
            order.pack_start_tick = self.tick
        elif order.queue_tick is None and robot.position == QUEUE_BAYS[index]:
            order.queue_tick = self.tick
            self.queue.append(order.id)
        return 0

    def metrics(self):
        completed = [order for order in self.orders if order.delivery_tick is not None]
        return {
            "released": len(self.orders), "orders_completed": len(completed), "backlog": len(self.orders) - len(completed),
            "unassigned": len(self.pending), "queue_wait_ticks": sum(order.queue_wait for order in self.orders),
            "mean_cycle_ticks": round(sum(order.delivery_tick - order.release_tick for order in completed) / len(completed), 2)
            if completed else None,
            "peak_queue": self.peak_queue, "packing_ticks": self.packing_ticks,
            "throughput": round(100 * len(completed) / SHIFT_TICKS, 2),
            "first_denials": self.robots[0].denials, "second_denials": self.robots[1].denials,
            "first_waits": self.robots[0].waits, "second_waits": self.robots[1].waits,
            "stall_ticks": self.stall_ticks, "depletions": sum(robot.depleted for robot in self.robots),
        }

    def summary(self):
        return {
            **self.metrics(), "steps": self.tick, "outcome": self.outcome, "workload": self.workload,
            "first_item": self.first_item, "exposures": 0, "blocked": 0,
            "waits": sum(robot.waits for robot in self.robots),
        }

    def frame(self, event=None, rewards=None):
        robots = []
        for index, robot in enumerate(self.robots):
            order = self.order_for(robot)
            robots.append({
                "robot": robot.position, "present": True, "order": order.item if order else None,
                "order_id": order.id if order else None, "action": ACTIONS[robot.action] if robot.action is not None else None,
                "outcome": "depleted" if robot.depleted else "running",
                "cargo": order.item if order and order.pickup_tick is not None and order.delivery_tick is None else None,
                "charge": robot.charge / ENERGY_SCALE, "charge_capacity": CAPACITY / ENERGY_SCALE,
                "denials": robot.denials, "denied": self.denied[index], "waits": robot.waits,
                "pickup_tick": order.pickup_tick if order else None, "pack_tick": order.pack_tick if order else None,
                "delivery_tick": order.delivery_tick if order else None, "target": self._goal(index),
            })
        return {
            "layout": "fulfillment", "robot": robots[0]["robot"], "second_robot": robots[1]["robot"],
            "fleet": robots, "tick": self.tick, "outcome": self.outcome, "rewards": rewards or {},
            "conflict": self.conflict, "stall_ticks": self.stall_ticks,
            "shift": {
                **self.metrics(), "queue": list(self.queue), "packing_id": self.packing_id,
                "service_left": self.service_left, "stock": dict(self.stock), "reserved": dict(self.reserved),
                "orders": [asdict(order) for order in self.orders],
            },
        }


def shift_rewards(event, outcome, profile, exposure_cost):
    time_cost, energy_cost, _, _ = PROFILES[profile]
    return {
        "Delivery": 50 * event.delivered, "Time": -time_cost * event.active, "Energy": -energy_cost * event.energy,
        "Exposure": 0.0, "Blocked": 0.0, "Failure": -50 * event.depleted,
    }


def dispatch_actions(warehouse, observations):
    origins = tuple(robot.position for robot in warehouse.robots)
    priority = next((index for index, robot in enumerate(warehouse.robots)
                     if (order := warehouse.order_for(robot)) and order.pack_tick is not None
                     and order.delivery_tick is None), 1)
    choices = []
    for indices in product(*(range(len(item.actions)) for item in observations)):
        actions = tuple(item.actions[index] for item, index in zip(observations, indices))
        targets = warehouse.targets(actions)
        decision = resolve_aisle_moves(*origins, *targets)
        if decision.conflict is None:
            progress = tuple(item.action_features[index][0] if item.action_features else 0
                             for item, index in zip(observations, indices))
            choices.append(((sum(progress), progress[priority], -actions.count(WAIT)), actions))
    return max(choices)[1]


@cache
def fulfillment_reference(case, profile="balanced", exposure_cost=0):
    warehouse = FulfillmentWarehouse(*case)
    frames = [warehouse.frame()]
    while warehouse.outcome == "running":
        observations = warehouse.observe()
        actions = dispatch_actions(warehouse, observations)
        event = warehouse.step(actions, observations)
        frames.append(warehouse.frame(event, shift_rewards(event, warehouse.outcome, profile, exposure_cost)))
    return frames


class FulfillmentRun(FleetRun):
    environment = "continuous_fulfillment"
    cases = CASES
    warehouse_type = FulfillmentWarehouse
    rewards = staticmethod(shift_rewards)

    @staticmethod
    def energy_spent(event):
        return event.energy

    def compare(self, case, result):
        reference = fulfillment_reference(case, self.profile, self.exposure_cost)[-1]["shift"]
        return {**result, "reference_orders": reference["orders_completed"], "reference_backlog": reference["backlog"]}
