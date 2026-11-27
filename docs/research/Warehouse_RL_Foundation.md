# Warehouse RL Lab Foundation

## Central research question

How can machine learning help autonomous mobile robots fulfill orders reliably and efficiently as warehouse workflows become more complex?

Warehouse RL Lab starts with a single autonomous mobile robot (AMR) completing a delivery. Each phase adds a warehouse capability so an experiment can test what the robot learns as the job changes. An order succeeds when the correct item reaches its required destination after all required services. Compare efficiency among policies that achieve reliable completion.

## Phase design

Each phase starts from the preceding phase’s environment rules and defines the changes needed for its research question. Keep earlier phases selectable as controls. Define layout, workflow, fleet size, reward weights, and learning algorithm explicitly in each experiment configuration.

Each episode resets robot positions, charge, stock, and orders according to the selected scenario. Policy transfer is an explicit training choice. When comparing a warm start with training from scratch, include pretraining in the interaction budget and evaluate both policies on the same target scenarios.

## Shared AMR agent

The AMR agent uses the robot’s observations to choose Up, Right, Down, Left, or Wait. Moving uses one synthetic energy unit. Waiting or requesting a move that is blocked or denied uses 0.2 units. A wait at a station can perform a service when the workflow permits it.

Use one agent instance per learning robot. In fleet phases, each instance acts from its own observations. The simulator manages inventory, order status, station access, and movement conflicts. A scripted robot or dispatcher follows the phase’s operating rules.

## Algorithm support

The shared agent is designed to support **Q-learning, SARSA, Deep Q-Network (DQN), REINFORCE, Actor–Critic, and Proximal Policy Optimization (PPO)**. Select the algorithm independently of the phase and give each algorithm the information required by the experiment. Algorithms may encode those observations differently.

The two learning-robot phases, V6 and V7, also support **Independent PPO (IPPO)** and **Multi-Agent PPO (MAPPO)**. Compare them using the same observations for the acting policies and the same team objective. IPPO trains critics from each robot’s local observations. MAPPO can use joint information in its critic during training.

## Rewards and evaluation

Give completion credit once per valid order. Define each phase’s failure conditions and configure weights for its operating costs, including time, energy, and blocked or denied moves where applicable. Record reward weights for each run. Report environment rewards and operational outcomes separately from any progress shaping used during training.

Use **valid order completion** as the first measure of reliability. Record failure reasons, elapsed ticks, and energy per completed order. In fleet phases, also record denied moves and stalls. For continuous fulfillment, measure orders staged per 100 ticks, packing queue time, and released orders still unfinished at the end of the shift.

Evaluate frozen policies on matched scenarios using seeds separate from training. When comparing learners, hold the environment, reward, and simulator tick budget fixed. Report robot decisions separately when fleet sizes differ. Use a routing or dispatch reference under the same operating rules, and distinguish a minimum-time reference from a dispatch heuristic.

## Shared battery settings

From V2 onward, use a battery capacity of **50 synthetic energy units per AMR**. Start standard comparisons at full charge. Use lower starting charge in dedicated charging trials and verify that each normal evaluation case has a feasible route. Waiting at the charger adds up to one net unit per tick, capped at capacity. Report charge in units and as a percentage, such as **37 / 50 units (74%)**.

## V0 Navigation

| Component | Design |
| --- | --- |
| **Agent** | One AMR starts loaded and carries the parcel from home to the delivery dock. |
| **Environment** | A static 10 × 10 floor with rack obstacles, a home cell, and a delivery dock. An episode allows up to 100 ticks. |
| **State** | Robot position, destination, remaining ticks, and delivery status. |
| **Action** | Move or wait. Entering the dock unloads the parcel and completes the delivery. |
| **Reward** | Credit the delivery once. Apply the configured operating costs and timeout penalty. |
| **Policy** | Learn to reach the dock. Compare completion time and energy with a shortest-path reference on the same floor. |

## V1 Stocked racks

| Component | Design |
| --- | --- |
| **Agent** | The AMR starts empty and must collect the requested item before delivering it. |
| **Environment** | Keep V0’s floor and dock. Add two stocked pick bays, one for cartons and one for refill packs. Assign one order per episode. |
| **State** | Add the requested item, tote contents, bay stock, and pickup status. |
| **Action** | Wait at the requested bay to load one unit into an empty tote. Enter the dock with the matching item to complete the order. |
| **Reward** | Award completion credit only for delivery of the requested item. |
| **Policy** | Route to the requested bay, pick the item, then route to the dock. Evaluate both item assignments against the corresponding shortest valid route. |

## V2 Charging dock

| Component | Design |
| --- | --- |
| **Agent** | The AMR fulfills the V1 order while managing its charge. |
| **Environment** | Keep V1’s workflow and add a charger at home. An AMR that depletes its battery away from the charger fails the episode. |
| **State** | Add starting charge, current charge, charging time, and depletion status. |
| **Action** | Wait at the charger to recharge. Pickup and delivery follow V1. |
| **Reward** | Credit valid delivery. Apply the configured depletion penalty and operating costs. |
| **Policy** | Decide whether to charge before departure. Compare full-charge cases with low-charge cases that require charging, using a battery-aware reference. |

## V3 Pack and stage

| Component | Design |
| --- | --- |
| **Agent** | The AMR picks the requested item, brings it to packing, and stages the packed order. |
| **Environment** | Add a staffed packing station to V2. The former delivery dock serves as outbound staging. Packing takes one service tick. |
| **State** | Add packing status and service timestamps. |
| **Action** | Wait at packing with the picked item to have it packed. Enter outbound staging with the packed carton to complete the order. |
| **Reward** | Credit staging of the packed order. |
| **Policy** | Choose the next waypoint from the order’s progress and remaining charge. Compare routes against a reference that follows the same service sequence. |

## V4 Multiple layouts

| Component | Design |
| --- | --- |
| **Agent** | The AMR performs the V3 workflow using the selected floor’s rack and station locations. |
| **Environment** | Add a parallel-aisle layout and reserve an offset cross-aisle layout for evaluation. Apply the V3 workflow and battery rules on each floor. |
| **State** | Add layout information that lets the policy identify walkable cells and locate the next service point. |
| **Action** | Use the selected layout to determine legal moves and station access. |
| **Reward** | Apply the V3 reward rules on every floor. |
| **Policy** | Compare policies trained on the original floor alone and on a mix of training floors. Evaluate both on the same held-out floor. |

## V5 Shared aisles

| Component | Design |
| --- | --- |
| **Agent** | One learning AMR fulfills the order while a second AMR runs a scripted replenishment route. |
| **Environment** | Keep V4’s workflow and layout capability. Add a replenishment route, buffer bay, and parking cell. Use the original layout for the first traffic comparison and validate routes and stations on additional floors before using them. |
| **State** | Add the replenishment robot’s position and route progress. Record conflicts, denied moves, and stalls. |
| **Action** | Both robots request movement on the same tick. The replenishment robot has priority for an empty cell requested by both. A head-on swap stops both. A robot may follow into a cell that the other vacates on that tick. |
| **Reward** | Credit the fulfilled order. A denied move consumes time and idle energy. |
| **Policy** | Learn when to advance, wait, or reroute around the replenishment robot. Compare the effect of traffic on a matched floor and order set. |

## V6 Two learning robots

| Component | Design |
| --- | --- |
| **Agent** | Replace the scripted robot with a second learning AMR. Each robot fulfills one assigned order. |
| **Environment** | Keep V5’s conflict rules and validated layouts. Give each robot its own charger. Both use the shared packing station and staging cell. End the episode when both orders are staged, either robot depletes its charge, or the time limit is reached. |
| **State** | Track each robot’s position, assigned order, load, charge, service progress, and nearby robot occupancy. |
| **Action** | Each robot acts once per tick. Apply the V5 resolver with the second robot taking the former scripted robot’s priority. A robot leaves the shared floor after staging its order. |
| **Reward** | Give the team credit for each staged order. Sum configured operating costs across active robots. |
| **Policy** | Compare independent and centralized-critic training with local action selection during evaluation. Use a joint routing reference and track both order completion and stalls. |

## V7 Continuous fulfillment

| Component | Design |
| --- | --- |
| **Agent** | Two AMRs repeatedly take orders from a dispatcher and return to their chargers after staging. |
| **Environment** | Extend V6 with recurring order releases and one packing slot served by a first-in, first-out queue. Start with an 80-tick shift and compare a paced workload of six orders with a burst workload of twelve. Packing takes three service ticks. A depleted AMR stays in its cell, and the shift continues to its tick limit. |
| **State** | Add order release times, inventory reservations, assignments, queue position, service remaining, and end-of-shift backlog. |
| **Action** | Reserve one stock unit when assigning an order. A robot waits in a marked bay until it reaches the head of the queue and the packing slot is free. After staging, the robot returns to charge and can accept another order. |
| **Reward** | Credit each staged order once. Apply configured operating costs and depletion penalties. |
| **Policy** | Compare learned movement policies under the same dispatcher, queue, workloads, and validated layouts. Report throughput, queue wait, and backlog against a dispatch reference. |

## V8 Site-based simulation

| Component | Design |
| --- | --- |
| **Agent** | Start from the V7 fleet workflow and use the fleet size and assignments specified for the site. |
| **Environment** | Use an approved or measured floor plan. Calibrate travel, pickup, packing, and charging times from site observations. |
| **State** | Track robot, order, and station state using the site layout and available measurements. |
| **Action** | Apply the site’s permitted routes, movements, and service rules. |
| **Reward** | Keep valid order completion as the objective. Set operating costs for the site-specific experiment. |
| **Policy** | Compare learned policies with a reference under the same site rules. Use separate held-out observations to assess how well the simulator reproduces route times, station waits, and throughput. |

## Confirmation for conflicts

Before acting on a request or making a change that conflicts with this foundation, identify the conflicting requirement and the proposed change, then ask the user to confirm how to proceed. Wait for explicit confirmation before doing the conflicting work. Apply the same rule when resolving an existing discrepancy would require an exception or a change to the foundation.
