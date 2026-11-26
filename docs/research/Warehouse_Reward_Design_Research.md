# Warehouse reward-design theory

Verified 2026-11-12; scope: up/down/left/right/wait.

Separate three reward roles. Sparse success reward records task completion. Task costs price elapsed time, energy, or collisions. Adding safety/energy task rewards intentionally changes the objective relative to success alone; an unchanged optimal policy in one instance does not establish a general invariance guarantee. Optional shaping supplies guidance after the base objective is fixed. These are design recommendations informed by constrained RL's distinction between rewards and auxiliary costs, and reward-specification research. [3,4]

Ng, Harada, and Russell's Theorem 1 gives the policy-preserving additive transformation:

`F(s,a,s')=gamma*Phi(s')-Phi(s)`

Use `R'=R+F` in the same MDP: identical states, actions, transition dynamics, termination semantics, and discount `gamma`. In a continuing discounted problem (`gamma<1`), bounded `Phi` makes the limiting boundary term vanish; finite state spaces imply boundedness. For a trajectory ending at time `T`, telescoping gives the shaping contribution `-Phi(s_initial)+gamma^T*Phi(s_T)`. Therefore, for finite episodic comparisons, set terminal `Phi=0` for every genuine terminal outcome, including failure, or supply an equivalent correct terminal boundary correction. Otherwise the residual can depend on the reached terminal state or episode length and change preferences. With `gamma=1`, boundedness alone is insufficient: termination/properness and finite returns matter. A finite deadline can be represented through a time-augmented state. These boundary statements follow directly from the telescoping identity and the paper's absorbing-state assumptions. The theorem preserves optimal policies; it does not guarantee that finite training finds them. [1]

Gymnasium distinguishes task termination from external truncation. Success, failure, and an intrinsic finite-horizon deadline are `terminated`; an external sampling cutoff is `truncated`. For an intrinsic horizon, remaining time must appear in the observation to preserve the Markov property: identical physical configurations can require different decisions at different remaining times. More generally, observations should expose the state information needed to predict transitions and rewards. Bootstrap value targets after external truncation, using the actual final observation; do not bootstrap after true termination. Accordingly, do not zero the potential at a sampling cutoff that is not a terminal state of the underlying MDP. [1,2]

A weighted collision penalty expresses a tradeoff, not a hard safety guarantee. Sufficient expected gain elsewhere can outweigh a finite penalty. Achiam, Held, Tamar, and Abbeel instead formalize CMDPs with explicit expected-cost limits; their fixed-penalty experiments demonstrate sensitivity to penalty coefficients. An expected-cost constraint generally permits some unsafe trajectories, rather than guaranteeing safety on every trajectory. Practical CPO also uses approximations and can produce infeasible iterates. Thus neither a penalty nor this algorithm alone establishes collision impossibility. A hard safety claim requires separately specified admissibility/enforcement conditions and assumptions about dynamics. [3]

For evaluation, keep dynamics and test scenarios fixed across reward variants, use shared held-out scenarios and multiple training seeds, and compare operational metrics: completion rate, completion time, collisions per episode, probability of any collision, energy use, and waiting. Report failure/timeouts alongside timing metrics so selective successes cannot hide poor completion. Do not rank variants by their differently scaled training returns. This evaluation recommendation follows Leike et al.'s separation of observed reward from intended performance: their gridworld agents can optimize visible reward while missing intended behavior. Include shaping ablations against the same base task reward to isolate learning guidance from objective changes. [4]

Primary sources:

1. Ng, Harada, Russell (1999), *Policy invariance under reward transformations: Theory and application to reward shaping*, §§2–3, Theorem 1 and Corollary 2: https://people.eecs.berkeley.edu/~russell/papers/icml99-shaping.pdf
2. Farama Foundation, *Gymnasium: Handling Time Limits*, “Termination,” “Truncation,” and “Solution”: https://gymnasium.farama.org/v1.2.3/tutorials/gymnasium_basics/handling_time_limits/
3. Achiam, Held, Tamar, Abbeel (2017), *Constrained Policy Optimization*, §§4, 6.2, 8.3: https://proceedings.mlr.press/v70/achiam17a/achiam17a.pdf
4. Leike et al. (2017), *AI Safety Gridworlds*, §§1–3, especially reward versus performance: https://arxiv.org/html/1711.09883

## Round-trip reward experiments, November 20, 2026

The original report introduced time and energy costs together. This experiment varies them independently, then checks whether increasing the exposure cost improves clearance with the dashboard’s Q-learning defaults. The experiments use revision `f05a308`, the existing warehouse layout and patrol, and 1,500 training episodes per run. Each frozen policy is replayed once from each of the eight patrol phases. The five seeds in each comparison share their training phase sequences across reward conditions.

### Time and energy costs

The four conditions cross time cost of 0 or 0.20 per tick with energy cost of 0 or 0.05 per synthetic energy unit. Completion still earns 100 and collision or timeout costs 100. Exposure and blocked-action costs are zero. Training seeds are 101, 223, 347, 467 and 599. Every row completed all 40 frozen replays with zero collisions and timeouts. The training transitions column is the mean per seed.

| Q-learning settings | Reward | Fastest replays | Mean ticks | Mean energy | Mean waits | Training transitions |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Report baseline | Sparse | 2/40 | 23.900 | 19.700 | 5.250 | 93,931 |
| Report baseline | Time only | 0/40 | 19.300 | 17.060 | 2.800 | 58,837 |
| Report baseline | Energy only | 0/40 | 22.700 | 16.580 | 7.650 | 79,104 |
| Report baseline | Efficiency | 1/40 | 18.900 | 16.100 | 3.500 | 59,175 |
| Dashboard defaults | Sparse | 40/40 | 14.375 | 14.075 | 0.375 | 51,460 |
| Dashboard defaults | Time only | 40/40 | 14.375 | 14.075 | 0.375 | 51,972 |
| Dashboard defaults | Energy only | 39/40 | 14.400 | 14.080 | 0.400 | 52,872 |
| Dashboard defaults | Efficiency | 36/40 | 14.475 | 14.095 | 0.475 | 52,914 |

At the report settings, time cost alone cut mean time by 4.60 ticks from sparse, and energy cost alone lowered mean energy by 3.12 units while increasing waits by 2.40 ticks. With both costs active, time and energy both improved on sparse. At the dashboard defaults, sparse already matched the fastest collision-free route in all 40 replays. The measured benefit of the extra time and energy terms depends on the learner settings and training budget. Several learner settings change between the two groups, so the comparison estimates the effect of the bundle and cannot isolate discounting.

### Exposure cost

The sweep uses the Operational profile at the dashboard Q-learning defaults. Time, energy, and blocked-action coefficients stay fixed. All rows completed 40 of 40 frozen replays with zero collisions and timeouts. The sweep uses the same five training seeds as the ablation. The confirmation repeats the current weight and two higher weights with training seeds 613, 743, 857, 947 and 1009.

| Seed set | Exposure cost per adjacent tick | Fastest replays | Mean ticks | Mean exposure | Max exposure | Replays with zero exposure |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Sweep | 0.15 | 38/40 | 14.475 | 3.50 | 6 | 5/40 |
| Sweep | 0.50 | 32/40 | 14.625 | 3.10 | 6 | 9/40 |
| Sweep | 1.00 | 26/40 | 14.850 | 2.30 | 6 | 16/40 |
| Sweep | 2.00 | 28/40 | 14.725 | 2.35 | 6 | 16/40 |
| Sweep | 4.00 | 14/40 | 15.525 | 1.75 | 4 | 20/40 |
| Confirmation | 0.15 | 36/40 | 14.525 | 3.50 | 6 | 5/40 |
| Confirmation | 2.00 | 26/40 | 14.850 | 2.15 | 6 | 17/40 |
| Confirmation | 4.00 | 13/40 | 15.825 | 1.45 | 4 | 23/40 |

On confirmation seeds, increasing the cost from 0.15 to 2 lowered mean exposure by 39% and added 0.325 ticks per trip. A cost of 4 lowered mean exposure by 59% and added 1.300 ticks. Weight 2 is a candidate when average clearance matters and travel time remains important. Weight 4 is a candidate when a lower worst observed exposure matters. Compare these settings on held-out patrol schedules or layouts before choosing a new default. A clearance requirement would also need an explicit threshold and a metric such as the fraction of replays exceeding it.

### Return on example routes

For patrol phase 6 at operational exposure cost 2, the fastest reference and the upper detour both deliver and return. The other trajectories use 100 Wait actions at home and three Right actions from home. The discounted column weights the first tick by 1 and subsequent ticks by powers of the dashboard’s Q-learning discount of 0.85.

| Route | Outcome | Ticks | Exposure ticks | Displayed return | Discounted return |
| --- | --- | ---: | ---: | ---: | ---: |
| Fastest reference | Returned | 15 | 4 | 88.290 | 5.383 |
| Upper detour | Returned | 26 | 0 | 93.500 | 0.077 |
| Wait at home | Timeout | 100 | 0 | −121.000 | −1.400 |
| Three Right moves | Collision | 3 | 0 | −100.750 | −72.893 |

The displayed return ranks the upper detour above the fastest route. The discounted objective ranks the fastest route higher because it places more weight on earlier completion. Both returns favour taking the detour over waiting at home. Check both returns when testing a proposed reward revision.

### Reproduction

Use `TrainingRun` with `algorithm="q_learning"`, `round_trip=True`, `traffic="patrol"`, and `episodes=1500`. For the report baseline pass `alpha=0.25`, `gamma=0.98`, `epsilon_min=0.05`, `decay_fraction=0.80` and `initial_q=0`. The dashboard defaults are `alpha=1.0`, `gamma=0.85`, `epsilon_min=0.02`, `decay_fraction=0.85` and `initial_q=100`.

For the ablation, add a temporary profile in the experiment process with `PROFILES["ablation"] = (time_cost, energy_cost, 0.0, 0.0)` and pass `profile="ablation", exposure_cost=0`. For the exposure comparisons, pass `profile="balanced"` and the row’s `exposure_cost`. Create a fresh run per condition and seed, call `run.advance(run.total)`, then collect `run.evaluate()`. Count a fastest match when a replay succeeds and `steps == optimal_steps`. Sum `steps` in `run.history` for training transitions. Report operational metrics directly because return depends on the selected weights.

These runs extend the questions in report Sections 4.2, 6.1 and 8. Update the report after testing the clearance trade-off under additional traffic conditions.
