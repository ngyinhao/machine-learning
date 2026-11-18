from unittest import TestCase

from warehouse import DOCK, PATROL, START, TrainingRun


class DQNDeliveryTest(TestCase):
    def test_dashboard_default_round_trip_greedy_replay(self):
        run = TrainingRun(
            episodes=1500, seed=42, traffic="patrol", profile="balanced",
            exposure_cost=0.15, algorithm="dqn", round_trip=True,
        )
        run.advance(run.total)

        replay = run.replay()
        self.assertEqual(replay["result"]["outcome"], "returned")
        delivery_tick = replay["result"]["delivery_tick"]
        self.assertEqual(replay["frames"][delivery_tick]["robot"], DOCK)
        self.assertEqual(replay["frames"][-1]["robot"], START)
        self.assertEqual([result["outcome"] for result in run.evaluate()], ["returned"] * len(PATROL))
