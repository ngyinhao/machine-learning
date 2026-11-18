# Reward Design for Warehouse Robot Navigation with Discrete Actions

Working draft based on the assignment specification and report template.

## 1. Introduction and Problem Statement

The project studies how reward design affects a delivery robot that navigates a simulated warehouse. The robot has five actions. It must reach a delivery dock and, in the round-trip mission, return to its home base while limiting delay, energy use, and exposure to a moving forklift.

## 3. Environment and Exploratory Analysis

The simulator uses a fixed 10 × 10 floor plan and one robot carrying a parcel. The robot can move one cell in any of four directions or wait. Each action consumes one tick. An attempt to enter a shelf or leave the floor leaves the robot in its current cell. Arrival at the dock delivers the parcel automatically. In the round-trip mission the episode then continues until the robot returns to the starting cell. A collision or reaching the 100-tick limit without completing the mission is a failure.

The forklift follows an eight-cell loop, advancing one cell per tick. A dedicated seeded random stream selects its starting phase for each episode. The robot and forklift move simultaneously. Ending a tick in the same cell or exchanging cells counts as a collision. Ending in orthogonally adjacent cells without a collision counts as one exposure tick. The simulator tracks robot position, patrol phase, remaining time, and the mission leg. The dock and shelves stay fixed.

## 4. Methodology and System Design

The Python simulator records delivery, failure, elapsed time, energy use, blocked moves, and forklift exposure by transition. A reward profile converts those events into a training reward. All profiles award 100 once on mission completion and subtract 100 on collision or horizon expiry. The efficiency profile adds a cost of 0.2 per tick and 0.05 per energy unit. The operational profile also subtracts 1 per blocked attempt and applies a configurable exposure cost. Valid movement uses one synthetic energy unit. Waiting and blocked attempts each use 0.2 units.

The dashboard starts a training run and animates recorded robot and forklift positions. The learning curve plots one dot per episode return, a rolling mean over up to 25 episodes, and a dashed zero-return reference. The trace shows each transition's reward terms. The Advanced hyperparameters panel lets users set the learning rate, discount factor, minimum exploration, exploration decay fraction, and initial Q-value for Q-learning and SARSA before starting a run. DQN exposes minimum exploration and exploration decay fraction. The training CSV records the values applied to that run alongside episode outcomes, costs, and metrics.

The demonstration is hosted privately on ChatGPT Sites. A browser worker runs the Python simulator and agents, with one training session per tab. Closing or reloading the tab clears that session, so users export the CSV to retain the results.

The episode grid compares up to ten recorded training traces. By default, it samples every tenth episode and groups traces in 100-episode blocks. The latest recorded block plays on a shared timeline and repeats while the next block is still training. The final block plays once. Each trace remains available for per-step inspection. This display uses traces from training episodes, including exploratory actions.

## 5. Part A — Identifying and Selecting Promising Models

The comparison covers value-based, policy-based, and hybrid learning. All navigation learners use the same simulator and reward profile. Q-learning and SARSA use the static map to exclude blocked actions. DQN, REINFORCE, and Actor–Critic can attempt all five actions. The tabular and policy learners index their estimates by position, patrol phase, and mission stage. DQN also receives normalized remaining time.

- **Value-based** methods include tabular Q-learning, SARSA, and a Deep Q-Network (DQN). Q-learning and DQN bootstrap from the best estimated next action. SARSA bootstraps from the action actually selected. DQN uses experience replay and a periodically copied target network.
- **Policy-based** REINFORCE updates a softmax policy after each episode using discounted returns and a scalar running baseline.
- **Hybrid** Actor–Critic uses a softmax actor and a tabular critic. The critic learns to predict state value and supplies a one-step temporal-difference error to update the actor.
- **Route baseline** Explore-Then-Commit tries the seven-step direct route and two 13-step detours, then commits to the route with the highest observed mean return. Its candidate routes come from the static map, which gives it prior structure unavailable to the navigation learners.

### Three-seed comparison

Each method trained on the one-way delivery mission for 600 episodes per traffic scenario with seeds 42, 43, and 44, the operational reward, and an exposure cost of 2. Paired runs used the same sequence of starting patrol phases. After training, each policy ran frozen on the static map once per seed and on all eight starting phases of the scripted patrol per seed. The replays use greedy action selection or the committed route. The patrol phases were also available during training.

| Method | Static deliveries | Patrol deliveries | Patrol collisions | Patrol timeouts | Mean patrol return |
| --- | ---: | ---: | ---: | ---: | ---: |
| Q-learning | 3/3 | 24/24 | 0 | 0 | 97.13 |
| SARSA | 3/3 | 24/24 | 0 | 0 | 95.76 |
| DQN | 2/3 | 6/24 | 10 | 8 | −67.36 |
| REINFORCE | 3/3 | 0/24 | 0 | 24 | −142.28 |
| Actor–Critic | 3/3 | 24/24 | 0 | 0 | 93.67 |
| Explore-Then-Commit | 3/3 | 24/24 | 0 | 0 | 96.75 |

Q-learning, SARSA, Actor–Critic, and Explore-Then-Commit completed all 24 patrol replays. Q-learning had the highest mean patrol return and averaged 9.71 steps per delivery. Explore-Then-Commit took 13 steps with zero exposure. During the last 25 training episodes per seed, the stochastic Actor–Critic delivered in 5 of 75 patrol episodes, compared with 24 of 24 under greedy replay. The action filter for the tabular methods and the preset routes for Explore-Then-Commit affect the comparison. The results cover a single layout and patrol pattern. Run settings, operational metrics, and reproduction steps are in the [experiment record](../research/Warehouse_Algorithm_Comparison.md).

## 6. Part B — Refining the Model

### Dock and home-base return

Staged sweeps selected Q-learning with 1,500 episodes, a learning rate of 1, a discount factor of 0.85, an exploration floor of 0.02, a decay fraction of 0.85, and optimistic initial Q-values of 100. The selected operational reward uses an exposure cost of 0.15. The patrol-aware reference uses breadth-first search through robot positions, patrol phases, and the outbound and return legs to find the minimum collision-free completion time.

The learned policy completed all 24 validation replays at the minimum time. Across five independent verification training seeds and all eight starting phases, it completed **40/40 round trips without a collision** and matched the fastest route in **37/40**. Completion averaged 14.50 ticks, or 0.125 extra ticks above the phase-specific minimum. A higher exposure cost of 2 reduced mean exposure from 3.40 to 2.50 ticks and increased mean travel time to 14.70 ticks. These results cover one fixed warehouse and patrol pattern. The [experiment record](../research/Warehouse_Algorithm_Comparison.md#home-base-round-trip) gives the configurations, selection rule, and reproduction steps.

The broader reward study will hold the learner configuration fixed across reward profiles and compare completion, collisions, timeouts, exposure, travel time, and energy use on shared scenarios. Fresh layouts and patrol patterns will test generalization. Battery limits, soft deadlines, and potential-based shaping are planned extensions.
