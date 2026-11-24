# Warehouse algorithm comparison

## November 20, 2026 release verification

The newest remote implementation checked on November 20 was `f652239` on `codex/dashboard-publish`. The rerun used Python 3.14.6 on Windows. The release replaces Explore-Then-Commit in the dashboard with PPO. It also gives DQN a static wall-action mask and training-only potential shaping. The historical runs below used the original methods.

The one-way screen paired seeds 42–44 across the six supported learners, with 600 episodes per seed and traffic mode and an operational exposure cost of 2. Q-learning and SARSA used the original tabular settings explicitly. PPO completed 24 of 24 patrol replays in 20.67 mean ticks with zero exposure. It completed 75 of 75 sampled patrol episodes in the final 25 episodes per seed. Actor–Critic also completed 24 of 24 greedy replays, with five of 75 late sampled completions. Updated DQN completed 23 of 24 patrol replays with one collision and no timeouts. The 23 successful runs averaged 16.48 ticks. Q-learning remained the fastest method with full completion at 9.71 mean ticks.

### DQN round-trip component ablation

The wall-action mask limits actions to traversable neighbours and Wait during both action selection and target calculation. The shaping term adds `γΦ(next) − Φ(current)` before scaling the learning reward by 100. `Φ` is −10 times the remaining Manhattan distance through the mission goals and zero for all terminal successors. Masking tests whether wasting actions on walls accounts for the learning failures. Shaping tests whether geometric progress can provide feedback before the terminal reward. The four combinations hold the environment, logged operational reward, network, episode budget, and training seeds fixed.

Every condition used 1,500 training episodes per seed, seeds 42–44, the patrol round trip, `balanced` with exposure cost 0.15, γ = 0.98, ε floor 0.05 and decay fraction 0.80. Each frozen policy was replayed in all eight starting phases.

| Mask | Shape | Completed by seed | Total completed | Collision | Timeout | Mean successful ticks | Minimum-time matches |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| Off | Off | 0, 0, 0 | 0/24 | 0 | 24 | — | 0/24 |
| On | Off | 0, 0, 0 | 0/24 | 0 | 24 | — | 0/24 |
| Off | On | 0, 0, 8 | 8/24 | 3 | 13 | 37.50 | 0/24 |
| On | On | 8, 7, 8 | 23/24 | 1 | 0 | 27.43 | 1/24 |

For a mask-off run, use `range(len(ACTIONS))` at every cell instead of `VALID_ACTIONS` in the DQN factory. For a shaping-off run, pass a potential that returns `0.0` for every state. Keep the terminal handling and reward reporting as implemented in `f652239`. The combined run reproduces the default seed-42 example on phase 6, with dock arrival at tick 19 and return at tick 27 against a 15-tick reference.

The five-condition Q-learning reward ablation and the four-configuration tuning verification on both five-seed groups were rerun on `f652239`. They reproduced the report tables. The tuned light-clearance configuration matched minimum time in 36/40 fresh-seed replays and 37/40 historical verification replays. The DQN regression test and local Edge dashboard smoke check passed. The smoke check exercised Q-learning and PPO training and replays and confirmed that DQN grid playback continues during a deliberately delayed training batch.

## November 18, 2026 experiment

This comparison adds neural Q-learning, direct policy gradients, and Actor–Critic to the tabular baselines. Explore-Then-Commit measures what a policy can gain from map-derived route candidates. The experiment holds the map, transition logic, and reward profile fixed. The tabular agents mask blocked moves using the static map. DQN and the two policy learners consider all five actions.

## Configuration

- Train each method on the one-way delivery mission for 600 episodes with each of seeds 42, 43, and 44 in both traffic scenarios. Use the operational reward with an exposure cost of 2. The comparison used Python 3.14.6. Each seed generates the same phase sequence across methods. Episode length varies, so the training budgets match in episodes and can differ in transition count.
- Evaluate the frozen policy once per seed on the static map and once per seed on each of the eight scripted patrol starting phases. Replay chooses the largest Q-value or policy preference, with seeded tie-breaking. Explore-Then-Commit follows its best route.
- Q-learning and SARSA use a step size of 0.25. Q-learning, SARSA, and DQN use ε-greedy actions with ε starting at 1, declining linearly, and stopping at 0.05. The navigation learners use a discount factor of 0.98. DQN, REINFORCE, and Actor–Critic divide rewards by 100 internally. The reported metrics use the original reward scale.
- DQN has two 16-unit leaky ReLU hidden layers and a linear output for each action. It uses a Huber loss and SGD with a step size of 0.015. It stores up to 5,000 transitions, trains after a warm-up of 128 transitions with four sampled SGD updates every four steps, and copies the target network every 250 transitions.
- REINFORCE and Actor–Critic use softmax policies indexed by position, patrol phase, and mission stage. REINFORCE uses a policy step size of 0.12 and updates its running scalar baseline with a step size of 0.05. Actor–Critic uses step sizes of 0.25 for the actor and 0.2 for the tabular critic.
- Explore-Then-Commit cycles through the direct, upper-aisle, and lower-aisle routes for 50 episodes each. It picks the route with the highest mean undiscounted episode return and follows it for the remaining 450 episodes.

## Observations

| Method | Traffic | Deliveries in final 25 per seed | Replay deliveries | Collisions | Timeouts | Mean return | Mean energy | Mean exposure | Mean delivery steps |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Q-learning | None | 75/75 | 3/3 | 0 | 0 | 98.25 | 7 | 0 | 7 |
| SARSA | None | 75/75 | 3/3 | 0 | 0 | 98.25 | 7 | 0 | 7 |
| DQN | None | 71/75 | 2/3 | 0 | 1 | −8.85 | 15.60 | 0 | 13 |
| REINFORCE | None | 75/75 | 3/3 | 0 | 0 | 98.25 | 7 | 0 | 7 |
| Actor–Critic | None | 75/75 | 3/3 | 0 | 0 | 98.25 | 7 | 0 | 7 |
| Explore-Then-Commit | None | 75/75 | 3/3 | 0 | 0 | 98.25 | 7 | 0 | 7 |
| Q-learning | Patrol | 74/75 | 24/24 | 0 | 0 | 97.13 | 8.47 | 0.25 | 9.71 |
| SARSA | Patrol | 75/75 | 24/24 | 0 | 0 | 95.76 | 15.08 | 0 | 17.42 |
| DQN | Patrol | 26/75 | 6/24 | 10 | 8 | −67.36 | 28.50 | 1.08 | 7 |
| REINFORCE | Patrol | 6/75 | 0/24 | 0 | 24 | −142.28 | 63.07 | 0 | — |
| Actor–Critic | Patrol | 5/75 | 24/24 | 0 | 0 | 93.67 | 16.51 | 0.38 | 19.21 |
| Explore-Then-Commit | Patrol | 75/75 | 24/24 | 0 | 0 | 96.75 | 13 | 0 | 13 |

Return, energy, and exposure include every replay outcome. Delivery steps include successful replays only. Patrol deliveries by seed were `[6, 0, 0]` for DQN and `[0, 0, 0]` for REINFORCE. Each of the four other methods delivered in all eight patrol phases for each seed.

Refresh these tables if the agent defaults, warehouse, or reward implementation changes. Generalization claims require held-out layouts or traffic patterns. For a follow-up on policy reliability, evaluate stochastic policies alongside greedy replay and compare learning curves at equal transition counts.

### November 18, 2026 tabular rerun

The tabular spot-check found 24/24 patrol deliveries for both Q-learning and SARSA after the static move filter was introduced. The full one-way comparison above reproduces those counts and adds the results for the other methods under the same episode budget and reward profile.

## Learner tuning record

The one-way comparison records the pre-tuning configurations and outcomes. The following values describe the original tabular settings. The dashboard now uses the round-trip Q-learning settings documented below.

| Setting | Starting value | Reason to vary it |
| --- | ---: | --- |
| Learning rate (α) | 0.25 | Test whether stronger updates learn useful routes sooner or whether smaller updates give more consistent performance across seeds. |
| Discount factor (γ) | 0.98 | Test how much valuing later outcomes affects route choices that trade immediate costs for eventual delivery or forklift clearance. |
| Minimum exploration (ε) | 0.05 | Test how much random exploration is useful late in training, after the learner has found viable routes. |
| Exploration decay fraction | 0.80 | Test how quickly the learner should move from trying actions to relying on its learned policy. |
| Initial Q-value | 0 | Test whether optimistic estimates encourage trials of less visited actions after the learner finds a viable route. |

For a hyperparameter sweep, use a common environment, reward, and training budget for every setting. Log both episodes and transitions. Include the defaults, specify the candidate values and selection rule before running them, and compare settings across paired seeds. For the reward study, use one learner configuration and vary the reward profile or exposure cost. An exposure penalty changes what the robot is rewarded for, so compare reward variants using the same operational metrics.

Select settings on validation runs, then evaluate the chosen settings on fresh training seeds. Generalization across new warehouse layouts or patrol patterns requires separate experiments. The distinct tuning and test seeds follow [Eimer, Lindauer, and Raileanu (2023)](https://proceedings.mlr.press/v202/eimer23a.html).

### Home-base round trip

On November 18, 2026, the round-trip experiment required a parcel drop at the dock followed by a return to the start within 100 ticks. The simulator distinguishes the outbound and return legs, and awards the successful-mission reward once at the base. Tabular Q-learning and SARSA share estimates across remaining-time values to reduce the number of combinations to learn. This approximation can miss choices that depend on the deadline. They filter moves into known shelves and retain the wait action.

Staged sweeps used validation seeds `7`, `19`, and `42` with all eight forklift starting phases per trained policy. They explored episode budgets from 600 to 1,800, α from 0.25 to 1, γ from 0.80 to 0.98, exploration floors from 0.02 to 0.12, decay fractions from 0.25 to 0.95, and initial Q-values of 0 and 100. A separate reward sensitivity sweep varied the exposure cost from 0 to 2. Candidates were ranked by completed missions, matches to the minimum collision-free travel time, and mean extra ticks. The final neighborhood sweep fixed α at 1, the initial estimate at 100, the floor at 0.02, and the decay fraction at 0.85. It crossed 1,200, 1,500, and 1,800 episodes with γ in `{0.80, 0.85, 0.90}` and exposure cost in `{0.15, 0.25, 0.50}`.

The selected Q-learning configuration used 1,500 episodes, α = 1, γ = 0.85, ε floor = 0.02, decay fraction = 0.85, initial Q = 100, and the operational reward with exposure cost 0.15. It matched the minimum time in 24/24 validation replays. The table uses independent training seeds `103`, `211`, `307`, `409`, and `503`, with all eight starting phases per seed. Each policy was frozen with exploration disabled. All rows completed 40 of 40 replays with zero collisions and zero timeouts. Metrics summarize these deterministic scenarios across five independently trained policies.

| Configuration | Fastest replays | Mean ticks | Mean extra ticks | Mean exposure ticks |
| --- | ---: | ---: | ---: | ---: |
| Selected Q-learning | 37/40 | 14.50 | 0.125 | 3.40 |
| Selected settings with initial Q = 0 | 4/40 | 17.15 | 2.775 | 1.83 |
| Selected settings with exposure cost = 2 | 27/40 | 14.70 | 0.325 | 2.50 |

The selected policy matched the 14–15 tick minimum in `8, 8, 8, 7, 6` phases per test seed. The three slower routes used one, two, and two extra ticks. The shortest-route reference searches robot position, forklift phase, and mission leg using the simulator's collision and timing rules. The agent learns from episode transitions alone. The higher exposure cost reduced proximity to the forklift at a small travel-time cost. Refresh the results if the layout, patrol, reward settings, or training defaults change.

Run the following from the project root to reproduce the verification rows.

```python
from statistics import mean
from warehouse import TrainingRun

for initial_q, exposure_cost in ((100, 0.15), (0, 0.15), (100, 2)):
    results = []
    for seed in (103, 211, 307, 409, 503):
        run = TrainingRun(
            episodes=1500, seed=seed, traffic="patrol", profile="balanced",
            exposure_cost=exposure_cost, algorithm="q_learning", round_trip=True,
            alpha=1, gamma=0.85, epsilon_min=0.02, decay_fraction=0.85, initial_q=initial_q,
        )
        run.advance(run.total)
        results.extend(run.evaluate())
    completed = [row for row in results if row["outcome"] == "returned"]
    gaps = [row["steps"] - row["optimal_steps"] for row in completed]
    print(initial_q, exposure_cost, len(completed), gaps.count(0), mean(gaps))
```

### What to record for each tuning batch

- Date, run IDs, code revision, and artifact paths for the training CSV and frozen-policy evaluation.
- Hypothesis, candidate values, baseline settings, algorithm, environment, reward, seeds, and training budget.
- Validation and test scenarios, evaluation policy, selection rule, per-seed outcomes, and observed trade-offs.
- Settings selected or rejected, the evidence for that decision, and any report claims, figures, or tables to refresh.

## Reproduce the runs

Run this from the project root to repeat the comparison. The training and replay rows contain the reward breakdown and operational metrics.

```python
from itertools import product
from warehouse import AGENTS, TrainingRun

for algorithm, traffic, seed in product(AGENTS, ("none", "patrol"), (42, 43, 44)):
    baseline = {"alpha": 0.25, "gamma": 0.98, "epsilon_min": 0.05,
                "decay_fraction": 0.8, "initial_q": 0} if algorithm in ("q_learning", "sarsa") else {}
    run = TrainingRun(
        episodes=600, seed=seed, traffic=traffic, profile="balanced",
        exposure_cost=2, algorithm=algorithm, round_trip=False, **baseline,
    )
    while len(run.history) < run.total:
        run.advance(10)
    training = run.history[-25:]
    replays = run.evaluate()
    print(algorithm, traffic, seed, training, replays)
```

## Method references

- Mnih et al. (2015). [Human-level control through deep reinforcement learning](https://doi.org/10.1038/nature14236).
- Williams (1992). [Simple statistical gradient-following algorithms for connectionist reinforcement learning](https://doi.org/10.1007/BF00992696).
- Konda and Tsitsiklis (1999). [Actor-Critic Algorithms](https://papers.nips.cc/paper/1999/hash/6449f44a102fde848669bdd9eb6b76fa-Abstract.html).
- Garivier, Lattimore, and Kaufmann (2016). [On Explore-Then-Commit Strategies](https://papers.nips.cc/paper_files/paper/2016/hash/ef575e8837d065a1683c022d2077d342-Abstract.html).
