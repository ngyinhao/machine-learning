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
