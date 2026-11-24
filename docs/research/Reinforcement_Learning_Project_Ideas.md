# Reinforcement-learning project directions

Research checked on 10 November 2026. These options examine where reinforcement learning could inform operational decisions. Verified facts describe upstream environments. Proposed designs describe experiments for future evaluation. Effort estimates assume a small Python prototype. Installation and training were not tested.

## 1. Warehouse navigation — initial recommendation

**Verified facts.** Gymnasium supplies a common environment interface and tools for defining observations, actions and rewards; it is not a ready-made warehouse simulator ([custom-environment documentation](https://gymnasium.farama.org/introduction/create_custom_env/)). MiniGrid supplies configurable grid environments, discrete actions and dictionary observations containing a symbolic image, direction and mission. Its default observations are partially observable; the default observation should not be treated as a complete Markov state for tabular learning ([MiniGrid](https://minigrid.farama.org/), [observation wrappers](https://minigrid.farama.org/api/wrappers/)).

**Proposed design.** Build a small, fixed-layout warehouse grid with static shelves, one robot and one destination. State: robot cell and destination cell, encoded as a finite index. Actions: four cardinal moves, including a defined response to blocked moves. Reward: +20 for arrival, −1 per step and an additional −4 for an invalid move; cap episode length. Compare tabular SARSA and Q-learning; optionally add DQN with the same discrete actions and a suitable state encoding. Evaluate against a random policy and greedy Manhattan routing with collision checks; include breadth-first search as a shortest-path reference for the known static layout. The research question should examine learning efficiency and robustness rather than assume improvement over a shortest-path solver. If using MiniGrid instead, use full observability and a compact state encoding including direction before applying tabular methods.

**Estimated effort: low–medium.** A custom environment needs transition and termination checks but offers the clearest, smallest MVP.

## 2. Inventory replenishment

**Verified facts.** OR-Gym provides inventory-management environments with backlog and lost-sales variants. Its implementation uses numerical vector observations and bounded order-quantity `Box` actions. The original package uses legacy `gym`; do not assume direct compatibility with current Gymnasium learners ([environment source](https://github.com/hubbs5/or-gym/blob/master/or_gym/envs/supply_chain/inventory_management.py), [package configuration](https://github.com/hubbs5/or-gym/blob/master/setup.py)).

**Proposed design.** Restrict the task to one retailer and one supplier. State: on-hand stock, outstanding orders, lead-time position and period. Actions: choose an order from a small enumerated set. Reward: sales revenue minus ordering, holding and shortage costs. Use DQN after converting the action interface to `Discrete`; use SARSA/Q-learning only after also binning the state. Compare with a fixed reorder-point policy under held-out demand sequences.

**Estimated effort: medium.** Allow for legacy API adaptation and validating the simplified configuration. This is an available legacy option, not a verified claim of active maintenance.

## 3. Traffic-signal control

**Verified facts.** SUMO-RL connects RL agents to the SUMO simulator. Its default observation includes the active phase, minimum-green status, incoming-lane densities and queues. Actions select a discrete green phase; the default reward reflects changes in accumulated waiting time. Setup requires SUMO and associated environment configuration; multi-intersection operation adds a multi-agent interface ([official repository and installation instructions](https://github.com/LucasAlegre/sumo-rl)).

**Proposed design.** Begin with one intersection. State: phase, elapsed-green indicator and lane queues. Actions: choose the next permitted green phase, respecting transition constraints. Reward: negative total waiting time per decision interval. Compare DQN and PPO with fixed-time signals across unseen arrival rates.

**Estimated effort: medium–high.** Simulator installation, network/route configuration and simulation runtime exceed the warehouse MVP.

## 4. Energy/EV charging

**Verified facts.** SustainGym includes an EV-charging environment with continuous `Box` charging actions and dictionary observations covering charging demand, departure information, time and carbon information. Its setup includes ACN-Sim/acnportal, optimization dependencies and solver configuration ([environment source](https://github.com/chrisyeh96/sustaingym/blob/main/sustaingym/envs/evcharging/env.py), [installation and examples](https://github.com/chrisyeh96/sustaingym)).

**Proposed design.** Use a small charging site. State: remaining energy requests, departure times, current loading and carbon signal. Actions: normalized per-charger rates. Reward: delivered energy value minus carbon cost and unmet-departure penalties, with network limits enforced by the environment. Compare continuous-action PPO and SAC against immediate charging.

**Estimated effort: high.** Dependency setup, charging constraints and reward scaling need particular care.

## Experiment design

Choose learners and simple baselines that answer a specific question about the task. Compare them under common conditions, then hold a suitable learner fixed while testing the reward against operational metrics. Use the observed behaviour to guide any search over hyperparameters, exploration schedules or state representations. Evaluate the selected configuration independently.

Use multiple training seeds and a separate evaluation environment; random seeds can materially affect RL results. Keep evaluation rewards and episode limits consistent across agents, especially when comparing reward-shaping variants ([Stable-Baselines3 evaluation guidance](https://stable-baselines3.readthedocs.io/en/master/guide/rl_tips.html)).

Report task success, episode return, operational cost or path length, training interactions and variability. Choose held-out scenarios that match the policy's represented information; a tabular policy indexed only by position and destination does not encode changes to the map. None of these directions establishes originality or guarantees that RL will outperform its baseline.
