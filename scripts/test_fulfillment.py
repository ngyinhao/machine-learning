from copy import deepcopy
from unittest import TestCase

from fulfillment import CASES, PACK_TICKS, QUEUE_BAYS, SHIFT_TICKS, FulfillmentRun, fulfillment_reference
from warehouse import PICK_BAYS


class FulfillmentChecks(TestCase):
    def test_reference_reserves_stock_and_services_orders_once(self):
        for case in CASES:
            with self.subTest(case=case):
                frames = fulfillment_reference(case)
                self.assertEqual(len(frames), SHIFT_TICKS + 1)
                for frame in frames:
                    shift = frame["shift"]
                    orders = shift["orders"]
                    self.assertNotEqual(frame["robot"], frame["second_robot"])
                    self.assertEqual(shift["released"], shift["orders_completed"] + shift["backlog"])
                    self.assertEqual(shift["unassigned"], sum(order["robot"] is None for order in orders))
                    self.assertEqual(len({order["id"] for order in orders}), len(orders))
                    self.assertTrue(all(order["release_tick"] <= frame["tick"] for order in orders))
                    for item in PICK_BAYS:
                        units = [order for order in orders if order["item"] == item and order["pickup_tick"] is None]
                        self.assertEqual(shift["stock"][item], len(units))
                        self.assertEqual(shift["reserved"][item], sum(unit["robot"] is not None for unit in units))
                    for order_id in shift["queue"]:
                        order = orders[order_id - 1]
                        self.assertEqual(frame["fleet"][order["robot"] - 1]["robot"], QUEUE_BAYS[order["robot"] - 1])

                end = frames[-1]["shift"]
                completed = [order for order in end["orders"] if order["delivery_tick"] is not None]
                self.assertEqual(end["orders_completed"], 4)
                self.assertEqual(end["backlog"], 8 if case[0] == "burst" else 2)
                self.assertEqual(sum(frame["rewards"].get("Delivery", 0) for frame in frames), 50 * len(completed))
                for order in completed:
                    self.assertLess(order["pickup_tick"], order["queue_tick"])
                    self.assertLess(order["queue_tick"], order["pack_start_tick"])
                    self.assertEqual(order["pack_tick"] - order["pack_start_tick"], PACK_TICKS)
                    self.assertLess(order["pack_tick"], order["delivery_tick"])

    def test_fifo_tie_and_repeated_frozen_evaluation(self):
        frames = fulfillment_reference(("burst", "CARTON"))
        self.assertEqual(frames[14]["shift"]["queue"], [1, 2])
        self.assertEqual(frames[15]["shift"]["packing_id"], 1)
        self.assertEqual(frames[19]["shift"]["packing_id"], 2)

        for algorithm in ("ippo", "mappo"):
            with self.subTest(algorithm=algorithm):
                run = FulfillmentRun(
                    episodes=25, seed=42, profile="balanced", exposure_cost=0.15,
                    algorithm=algorithm, environment="continuous_fulfillment", traffic="none",
                )
                run.advance(25)
                before = deepcopy((vars(run.policy), run.history, run.random.getstate(), run.scenarios.getstate()))
                sampled = run.evaluate(sampled=True)
                self.assertEqual(len(sampled), 16)
                self.assertEqual(sampled, run.evaluate(sampled=True))
                self.assertEqual(len(run.evaluate()), 4)
                for frame in run.replay(("burst", "CARTON"), sample=0)["frames"]:
                    shift = frame["shift"]
                    for order_id in shift["queue"]:
                        order = shift["orders"][order_id - 1]
                        index = order["robot"] - 1
                        self.assertEqual(frame["fleet"][index]["robot"], QUEUE_BAYS[index])
                    self.assertEqual(shift["service_left"] > 0, shift["packing_id"] is not None)
                self.assertEqual(before, (vars(run.policy), run.history, run.random.getstate(), run.scenarios.getstate()))
