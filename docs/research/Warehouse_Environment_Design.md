# Warehouse navigation environment and reward study

Design proposal dated 12 November 2026. All dimensions, coefficients, scenarios and experiment counts below are proposed starting points, not established results or calibrated real-world costs.

## Research purpose

Study how reward design changes a robot's trade-offs between successful delivery, time, energy and exposure to moving obstacles while keeping its actions simple. A working title is **Reward Design for Safe and Efficient Warehouse Navigation with Simple Discrete Actions**. “Safe” describes a measured simulation objective, not a real-world safety certification.

Research questions:

1. How does adding operational costs to a delivery reward affect completion, energy use, delay and near misses?
2. Does potential-based progress shaping improve learning efficiency without changing the intended operational objective?
3. How sensitive is behavior to the safety and energy weights, including under unseen traffic and battery conditions?

## Environment

Use a custom Gymnasium grid environment. Gymnasium supplies the interface and a four-direction GridWorld tutorial, rather than a complete warehouse simulator [1].

Start with a fixed 10 by 10 layout, one learning robot, static shelves, an accessible delivery dock and two alternative corridors. The robot starts carrying one parcel. Entering the dock completes delivery automatically; there is no separate picking, steering or unloading action.

The five actions are `up`, `down`, `left`, `right` and `wait`. Every action advances one simulation tick. A blocked move leaves the robot in place but still costs time and idle energy. A valid move consumes one energy unit; waiting or attempting a blocked move consumes 0.2 units. These units are synthetic.

For a traffic extension, add one scripted forklift. Define simultaneous robot/forklift movement explicitly: sharing the destination cell or swapping cells constitutes a collision. Expose the forklift's position and its route phase/direction. Independent random pauses may introduce uncertainty; a hidden persistent traffic mode would need to be observed or treated as partial observability.

The full observation should include robot position, destination, battery charge, current time or remaining horizon, due time, and moving-obstacle information. Include any traffic-density parameter if it changes by episode and is needed to identify the dynamics. Keep the fixed map constant, or provide its representation when testing different maps. Position alone is insufficient once decisions depend on battery, timing or traffic. Gymnasium documents the need to expose remaining time for a finite-horizon Markov environment [2].

Proposed episode limits:

- Delivery, collision or battery depletion terminates the task.
- A delivery due time of 40 ticks is a soft deadline: later delivery remains possible but incurs delay costs.
- A 100-tick task horizon ends an unsuccessful episode. This horizon is part of the task and is observed.
- A separate external training cutoff, if used, is a truncation rather than a task failure; preserve the correct learning bootstrap [2].

For the first implementation, omit traffic and battery, verify navigation, then add one feature at a time. Add a charger only as a later extension: `wait` on the charger automatically replenishes charge, consumes time and earns no standalone positive reward.

Validate reset scenarios before using them for agent comparisons: the destination must be reachable and the initial battery must permit at least one feasible delivery plan, including charging only if that extension is present. Label deliberately infeasible stress tests separately from the normal success benchmark.

## Design sequence for the report

Once the environment dynamics, observations, and actions are specified, use this order to explain the design decisions.

1. **Define success and evaluation metrics.** Specify what counts as mission completion. Measure completion, travel time, energy use, forklift exposure, collisions, and timeouts so the report can assess operational outcomes directly.
2. **Specify an initial reward.** Start with signals for successful completion and failed termination. Add time, energy, and exposure costs to represent the trade-offs the study is intended to test. Record the reason for each term.
3. **Sanity-check the incentives on example trajectories.** Compare an efficient completed route, a longer route that avoids the forklift, waiting until timeout, and an early collision. Inspect the reward components and both discounted and undiscounted returns to see whether they express the intended trade-offs. Check that completing a feasible long delivery is preferable to waiting out the episode.
4. **Choose a reference and a learning algorithm.** Use a shortest-feasible-route planner as a reference where its assumptions fit. Consider tabular Q-learning for a small discrete state space and DQN if a larger observation space warrants function approximation.

Describe the objective, reward, and any completed trajectory checks in **Methodology and System Design**. Explain the reference and algorithm choices in **Learner Selection**. Hold the reward and evaluation protocol fixed for learner comparisons, then hold learner settings fixed when comparing reward variants.

## Reward layers

Separate **the operational objective**, which defines desired behavior, from **learning guidance**, which helps the agent discover it.

### Operational objective

Proposed starting reward:

`r_task = 100 × delivered − 0.2 − 0.05 × energy_used − 2 × near_miss − 1 × blocked_move − 0.5 × overdue − 100 × failed`

All indicators refer to the current transition and are either zero or one. `energy_used` is the actual movement/idle consumption for that transition. Near-miss and blocked-move events may co-occur; their costs add.

| Component | Exact proposed trigger | Intended behavior |
| --- | --- | --- |
| Delivery benefit | First arrival at the destination with the parcel | Complete the assigned task; then terminate |
| Time cost | Every transition, including waiting and terminal transitions | Avoid unnecessary delay and indefinite waiting |
| Energy cost | Actual move or idle consumption | Prefer economical behavior when time and safety allow |
| Near-miss cost | No collision, but the post-transition Manhattan distance to a forklift is one cell | Maintain clearance; this is an exposure proxy |
| Blocked-move cost | Attempt to enter a shelf or leave the grid | Discourage repeatedly issuing ineffective moves |
| Overdue cost | Each transition ending after tick 40, including late delivery | Trade a safe delay against punctuality |
| Failure cost | Collision, battery depletion or unsuccessful task-horizon expiry | Penalize unsuccessful termination once |

Define event precedence before coding: collision or battery depletion overrides delivery. Apply the failure cost once even if multiple failure conditions occur. At the horizon, count successful arrival as delivery if no higher-priority failure occurred. Do not stack a second timeout penalty.

These coefficients need calibration. For example, the added lateness cost means the late time cost becomes 0.7 per tick; it is intentionally additional. Energy consumption is a battery-use proxy, not a validated electricity-price or carbon model.

Do not add a positive reward merely for charging, visiting new cells, or moving toward the goal. Such bonuses could compete with completing delivery. Recharging helps only when it enables delivery; it is not itself the objective.

### Optional learning guidance

Investigate potential-based progress shaping separately:

`r_train = r_task + λ × (γ × Φ(next_state) − Φ(current_state))`

Use the learner's discount factor `γ` and a fixed potential `Φ`. One proposed potential is negative normalized shortest navigable distance to the delivery dock, computed around static shelves. This is a static progress heuristic, not an oracle for dynamic traffic or energy feasibility. Set the potential to zero at every true terminal state, including failures.

The policy-invariance result applies under its assumptions to potential-based transformations of the same MDP; it does not say that arbitrary safety/energy penalties preserve a delivery-only objective. Those task terms intentionally redefine the objective [3]. See the companion theory note for terminal-boundary qualifications.

Avoid a plain positive “closer to goal” bonus: it can discourage a necessary detour or reward repeated approach/retreat cycles if reverse motion is not treated consistently.

## Why the environment supports meaningful trade-offs

Construct scenarios where changing the reward can change a sensible choice:

- A short aisle passes near a moving forklift; a longer aisle provides clearance.
- Waiting allows the crossing to clear while using less battery than a detour.
- A low starting battery makes an otherwise acceptable detour infeasible.
- An approaching due time increases the cost of waiting.

If every reward term merely favors the shortest path, adding terms gives little evidence about trade-offs. Keep conditions in the observation so the agent can distinguish these situations.

The inline illustration uses three invented successful routes: an 8-tick shortcut consuming 8 units with 3 exposure ticks; a 12-tick detour consuming 12 units with no exposure; and waiting 6 ticks followed by the 8-move route, consuming 9.2 units over 14 ticks with no exposure. These are hypothetical route summaries, not simulator rollouts. It shows undiscounted task scores without lateness, collision or shaping.

## Constraints and unintended behavior

A finite weighted penalty permits trade-offs; it cannot enforce an absolute no-collision rule. If a rule must be inviolable, encode a simulator restriction or a separately specified safety mechanism, then evaluate that mechanism's interventions. A collision-blocking mechanism changes the learning problem and must be common to compared agents. Constrained-RL formulations separate rewards and cost constraints, but an empirical result still requires careful interpretation [4].

Check explicitly for:

- Remaining near the destination to collect guidance instead of completing delivery.
- Repeatedly approaching and leaving the dock.
- Charging indefinitely or entering a charge/discharge loop.
- Deliberately terminating to avoid accumulated costs in a difficult episode.
- Choosing a dangerous shortcut because its time savings outweigh the safety weight.

Distinguish an exploitable reward bug from an intended trade-off that reflects an unsuitable coefficient. Check discounted returns as well as undiscounted operational metrics; discounting can change the value of delayed delivery and failure.

## Experiment plan

Keep dynamics, observations, action space, training interaction budget and evaluation scenarios fixed within a reward comparison. Use the same RL learner for the primary reward study:

1. Delivery and failure events only.
2. Add time and energy costs.
3. Add near-miss, blocked-move and overdue costs.
4. Add potential-based shaping to the unchanged objective in experiment 3.

Compare the complete task reward with one-component-removed variants for an ablation. Sweep safety and energy weights separately before considering a combined sweep. Removing shaping should leave the intended task objective unchanged; removing a task cost changes that objective.

Use tabular Q-learning and SARSA for a deliberately small, discretized state space. The battery, time and traffic extensions multiply the state count; assess coverage before scaling them up. For the expanded observation, DQN and PPO are candidate comparisons with the same five discrete actions [5]. First freeze the reward to compare algorithms, then freeze the learner to compare reward variants.

Use random, static shortest-path, and traffic-aware rule-based policies as references. Static shortest path is a distance reference, not an optimal solver for the full timed, battery-dependent task.

Proposed evaluation: five independent training seeds, plus 100 held-out episodes per trained policy under shared scenario seeds. Report variation across training seeds rather than treating every episode as an independent trained model. Select weights/checkpoints on validation scenarios; reserve test scenarios for final evaluation.

Report delivery success, collision rate, exposure ticks, on-time delivery, completion time, energy consumption, invalid actions and interactions needed to reach a predefined success target. Show time/energy on successful episodes alongside failure rates to avoid rewarding a policy that succeeds only on easy cases. Compare policies using a common task score and raw metrics, not their differently shaped training returns. Separate evaluation and multiple runs follow established RL evaluation guidance [5].

## Sources

1. Gymnasium, creating a custom environment: https://gymnasium.farama.org/introduction/create_custom_env/
2. Gymnasium, handling time limits: https://gymnasium.farama.org/tutorials/gymnasium_basics/handling_time_limits/
3. Ng, Harada and Russell, policy invariance under reward transformations: https://people.eecs.berkeley.edu/~russell/papers/icml99-shaping.pdf
4. Achiam et al., Constrained Policy Optimization: https://arxiv.org/abs/1705.10528
5. Stable-Baselines3, RL tips and tricks: https://stable-baselines3.readthedocs.io/en/master/guide/rl_tips.html
