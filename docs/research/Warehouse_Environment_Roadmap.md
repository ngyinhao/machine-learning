# Warehouse environment and training roadmap

Research proposal dated 20 November 2026. This extends the [warehouse environment and experiment plan](Warehouse_Environment_Design.md) from navigation to order handling and fleet coordination.

The first question is whether a policy can complete a warehouse order when the required item and its storage location change. Later stages test whether the policy handles charging, unfamiliar floor plans and shared aisles. Start with one autonomous mobile robot (AMR) serving worker-assisted pick-to-tote orders. The worker places the item in the tote at the rack. The simulator models that handoff as a timed event, so the robot keeps its five movement and wait actions. Locus Robotics describes this type of picking workflow at Premier Yarns. [Premier Yarns deployment](https://locusrobotics.com/customers/premier-yarns-carolina-handling/).

## Environment progression

Each version builds on the previous one. Keep earlier versions selectable so a change can be tested on the same map and order set. Treat the floor plan, enabled workflow and training method as separate choices.

| Version | Features introduced | What to verify before advancing |
| --- | --- | --- |
| V0 · Navigation control | Use the current 10 × 10 grid. One robot starts with a parcel and delivers at the dock. Keep the existing static and forklift patrol scenarios as controls. | Reproduce the existing route and reward comparisons on the original scenarios. |
| V1 · Pick from stocked racks | Add two rack-side pick bays with item stock and an assigned order. The robot starts empty and must collect the correct item before delivering it. | An empty or incorrect tote earns no delivery credit. Only the correct pick removes one stock unit, and only the first valid delivery completes the order. |
| V2 · Charging bay | Put a charging dock at the start. Add battery charge that drops during travel and recovers while waiting at the dock. | Include a full-charge case and a low-charge case where waiting to charge makes the route possible. Check the feasibility of each reset and log charging time and depletion. |
| V3 · Pack and stage | Add a staffed packing station. After the item is packed into a shipping carton, the robot moves the carton to outbound staging at the former delivery dock. | Staging completes the order only after packing. Check the sequence and log time spent travelling and packing. |
| V4 · Multiple layouts | Add a parallel-aisle layout and reserve a layout with a different cross-aisle arrangement for testing. Use the same pick, charge and pack rules on all layouts. | Freeze policy weights before testing on the reserved layout. Verify that the loaded route, station positions and feasible battery plan come from the selected map. |
| V5 · Shared aisles | Add a second, scripted AMR with its own job and parking cell. Introduce simultaneous movement and a fixed rule for resolving conflicts. | Test same-cell requests, swaps and blocked following moves. Log denied moves and stalls, even when the controller prevents contact. |
| V6 · Two learning robots | Replace the scripted robot with a second learning agent. Both robots get one assigned order and keep the V5 map and movement rules. | Compare learning approaches on the same paired jobs. Count each order once and track whether one robot consistently waits longer. |
| V7 · Continuous fulfillment | Release new orders during an episode. Give the packing station one service slot and a marked waiting area. | Check that jobs and stock are reserved once, orders can queue safely, and released but unfinished orders appear in the backlog. |
| V8 · Site-based simulation | Use a measured or approved floor plan when available. Calibrate travel, pickup, packing and charging times from measured traces. | Replay a separate set of site observations and compare route times, station waits and throughput before making claims about the facility. |

A charging bay represents a real docking location. The start-at-charger scenario exercises the decision to top up before departure. ABB describes automated charging in its AMR charging systems. The proposed packing and staging sequence follows an outbound option documented in Dynamics 365. The prototype uses a fixed one-tick packing service at V3 and synthetic battery rates at V2. [ABB mobile-robot charging systems](https://www.abb.com/global/en/areas/robotics/products/mobile-robots/technology) · [Microsoft outbound container packing](https://learn.microsoft.com/en-us/dynamics365/supply-chain/warehousing/packing-containers).

## V1 floor plan and state

```text
##########
#........#
#.A......#
#.######.#
#.##..##.#
#S......D#
#.##..##.#
#.##..##.#
#......B.#
##########
```

`S` is the start, `D` is the delivery dock, `A` and `B` are reachable pick bays adjacent to racks, and `#` marks rack or wall cells. Use two sample stock-keeping units (SKUs), such as a small carton at A and a refill pack at B. At reset, stock both racks and use the scenario seed to choose an order for one unit. The policy observes the requested item or its pick bay, its tote contents, its position and the remaining ticks. The simulator also records rack stock and the order status.

`Wait` at the assigned bay with an empty tote transfers one unit and takes one tick. Entering D with the requested unit unloads it and completes the order. Entering D before pickup simply advances the simulation. Start the first tests on the static floor. A breadth-first search over the current [`warehouse.py`](../../warehouse.py) grid verified travel of 4 + 9 moves via A and 9 + 4 moves via B. With the proposed pickup tick, the static planner target is **14 ticks through either bay**. That is a geometry check for the proposed map and service rule.

## Training and comparisons

- **V1–V2 · Single robot.** Use tabular Q-learning on the unchanged grid with an observation key that includes the target, order progress and, once added, discrete battery charge. Use a planner that routes to the pick bay and then the dock, with battery-aware search at V2. Keep the delivery reward tied to valid order completion so collecting items and charging cannot independently earn delivery credit.
- **V3–V5 · Layout-aware single robot.** Compare DQN or PPO using map features alongside the current goal and mission state. Train on the original geometry, then on a mix of the original and parallel-aisle layouts. Compare both policies on the same reserved layout. Add the scripted AMR after that comparison so layout generalization and traffic adaptation each have a dedicated test.
- **V6–V7 · Fleet learning.** Start with independent PPO (IPPO) as the learning baseline, then test multi-agent PPO (MAPPO). Keep robot policy inputs and the shared team objective consistent. Each robot acts from its observation, and MAPPO's critic can use fleet state during training. Pair both with a centralized routing reference using time reservations. Rolling-Horizon Collision Resolution (RHCR) is an option when orders keep arriving. Hold the order dispatcher and movement rules fixed so the comparison measures coordination. [MAPPO paper](https://proceedings.neurips.cc/paper_files/paper/2022/hash/9c1535a02f0ce079433344e14d910597-Abstract.html) · [Cooperative benchmark with IPPO, MAPPO and warehouse tasks](https://datasets-benchmarks-proceedings.neurips.cc/paper/2021/hash/a8baa56554f96369ab93e4f3bb068c22-Abstract-round1.html) · [RHCR warehouse routing study](https://cdn.aaai.org/ojs/17344/17344-13-20838-1-2-20210518.pdf).
- **Curriculum experiment.** Once the final observation format is fixed, compare training from scratch on the target scenario with training that starts on easier scenarios and advances to the target. Match the total simulator tick budget, including pretraining, and record robot decisions separately when fleet sizes differ. Evaluate frozen policies on the same held-out layouts and order seeds.

The published RWARE benchmark found a larger advantage for MAPPO over IPPO on its four-robot tasks than on its two-robot task. That motivates comparing both methods on the two-robot lab scenario before adding fleet size as another experimental variable. [Papoudakis et al., Table 3](https://datasets-benchmarks-proceedings.neurips.cc/paper/2021/file/a8baa56554f96369ab93e4f3bb068c22-Paper-round1.pdf).

Track valid order completion, elapsed ticks and energy per completed order alongside failure counts. For recurring orders, add completed orders per 1,000 simulator ticks, backlog at the horizon, 95th-percentile completion time among delivered orders, time waiting for stations and denied moves per robot. Keep training seeds separate from evaluation seeds. Compare algorithms on the same environment version, state inputs available to their acting policies and reward. Compare reward variants using the same operational metrics.

## Implementation and site data

[`warehouse.py`](../../warehouse.py) currently defines one layout, home, dock and patrol as module constants. The planner and DQN use those definitions, and [`dashboard_api.py`](../../dashboard_api.py) serves a single map with one robot in each replay frame. V1 can introduce a scenario configuration with walkable cells, station locations, inventory and reset rules. Have training, route references and playback read the selected scenario. Use semantic map inputs such as passable cells and station masks for a policy that will see multiple layouts. At V5, move to per-robot observations and a joint tick that resolves conflicts before committing any moves.

Expose battery charge and the charging bay at V2, and whether the order is packed and where to stage it at V3. For shared aisles, let each policy observe nearby robot occupancy. When orders queue at V7, expose whether the packing slot is busy and where to wait. Record order IDs, stock reservations and time remaining in service in simulator state so events and replays can be audited.

For an actual facility, request an anonymized plan with scale, aisle widths and directions, rack-access sides, station locations and permitted robot and pedestrian routes. Record order releases and samples of travel and service times separately from the floor plan. Until those are available, use a warehouse-inspired layout. The Moving AI warehouse grids supply public aisle geometry for comparison. RWARE can exercise coordination separately in a workflow where robots carry shelves to a workstation and return them. [Moving AI warehouse benchmark maps](https://www.movingai.com/benchmarks/mapf.html) · [RWARE simulator](https://github.com/semitable/robotic-warehouse).

The report sections on environment, methodology, learner selection, evaluation and future work should be revisited when a version is runnable and produces matched results. The existing report and Word export describe the current experiments.
