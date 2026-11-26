# Warehouse environment implementation log

Manual review is the gate between phases. Each handoff records the scenario, verification results and manual checks. Continue when the reviewer approves the current phase.

| Phase | Deliverable | Manual check | Review status |
| --- | --- | --- | --- |
| V0 | Reproduce the existing navigation baseline | Confirm the original delivery and patrol replay are available | Verified as the V1 comparison control |
| V1 | Stocked pick bays and order-specific pickup | Inspect one order through pickup, stock decrement and delivery | Approved to advance on 20 November 2026 |
| V2 | Charging dock and battery state | Compare a full-charge departure with a low-charge case that requires waiting at the dock | Approved to advance on 20 November 2026 |
| V3 | Packing and outbound staging | Verify the order moves from pickup to packing to outbound staging | Approved to advance on 20 November 2026 |
| V4 | Multiple maps and held-out layout evaluation | Switch maps and inspect results on an unseen layout using frozen weights | Approved to advance on 20 November 2026 |
| V5 | Scripted second robot and shared-aisle conflicts | Watch the robots resolve a shared-cell request and a head-on swap | Approved to advance on 20 November 2026 |
| V6 | Two learning robots and a centralized routing comparison | Inspect both robots' decisions and compare independent PPO, multi-agent PPO and the planner | Approved to advance on 24 November 2026 |
| V7 | Recurring orders and a packing queue | Check throughput, waiting time and unfinished orders | Verified on 24 November 2026. Awaiting manual review. |
| V8 | Site-based map and calibration against measured traces | Compare simulation traces with held-out site observations | Queued. Requires an approved site plan and measured traces. |

## V0 · Navigation control

Run on 20 November 2026 from `origin/main` at `f05a308`. Q-learning used the repository defaults, 1,500 training episodes, seed 42, the one-way mission and both the sparse and operational reward profiles. The operational exposure cost was 0.15 per adjacent tick.

| Evaluation | Frozen-policy completions | Minimum-time matches | Observations |
| --- | --- | --- | --- |
| Static floor | 1/1 per profile | 1/1 per profile | 7 ticks and zero exposures |
| Forklift patrol | 8/8 per profile | 8/8 per profile | 7.25 mean ticks and 1.5 mean exposure ticks across the eight start phases |

Both profiles produced the same evaluation metrics in this run. The static round-trip planner took 14 ticks.

## V1 · Stocked racks and pickup

Keep the 10 × 10 V0 map and the five existing actions. Add pick bay A for a small carton and pick bay B for a refill pack. Stock one unit per bay and assign one order per episode. Waiting at the requested bay picks up the matching item in one tick. The dock completes the order when the robot arrives carrying that item. Use the static, one-way mission for the first Q-learning comparison.

### Results

Used Q-learning with the default learning rate 1.0, discount 0.85, optimistic initial Q-value 100, minimum ε 0.02 and ε decay over 85% of training. Ran 1,500 episodes for each of seeds 42, 43 and 44 on the static map with the operational reward. The order sampler used its own seeded stream. A frozen evaluation ran each of the two order types once for every fitted policy.

| Order | Pickup tick | Frozen-policy completions | Minimum-time matches | Energy per delivery |
| --- | --- | --- | --- | --- |
| Carton at A | 5 | 3/3 | 3/3 at 14 ticks | 13.2 simulation units |
| Refill pack at B | 10 | 3/3 | 3/3 at 14 ticks | 13.2 simulation units |

The planner found 13 movement ticks plus one pickup tick for each order. This check covers two known orders on the static map. Generalization to a new layout enters the evaluation at V4.

The scenario checks verified that an empty tote at the dock earns zero delivery credit, waiting at the wrong bay leaves stock intact, repeated waits cannot duplicate a pickup, and the completed order receives one delivery credit. Local and hosted browser smoke checks passed for both environments and exercised the V1 pickup readout, frozen replay, fastest route and CSV export.

### Manual review

1. Open the worktree preview started by `python app.py --port 0`. Select **V1 · Stocked racks** and scrub the shortest-path preview to tick **5**. The tote should show `CARTON`, stock at A should drop to zero and the completion reward should be zero.
2. Scrub to tick **14**. The robot should deliver at the dock, empty its tote and receive `+100` completion reward.
3. Train with the default 1,500 episodes and seed 42. Select **Replay trained policy** and confirm both orders complete. Download the CSV and inspect the `order` and `pickup_tick` fields.
4. Select **V0 · Navigation** and check that the original mission and traffic options are available.

The working Markdown report records V1 in Appendix C as a follow-up pilot.

## V2 · Charging dock and battery

The home cell (1, 5) doubles as a charging dock. V2 keeps the stocked-rack workflow and adds battery charge to the Q-learning state. Charge and operating energy are measured in synthetic units. The full case starts at 14 units and the low case starts at 12. Movement draws 1 unit. Idle and blocked actions draw 0.2 units. During a dock wait, the charger covers idle use and adds up to 1 net unit, capped at 14. Charging gives no completion reward. Battery depletion away from the charger ends the run and takes precedence over delivery.

The same-order planner finds a 14-tick route from full charge and a 16-tick route from low charge. The latter uses two charging waits. Both arrive with 0.8 units left. These settings make charging necessary from the low start while preserving a feasible route for every order. Training samples the starting charge from a seeded stream independent of the order sampler. Frozen evaluation covers all four order and charge combinations.

### Results

On 20 November 2026, both training modes used the V1 Q-learning defaults, the operational reward and seeds 42, 43 and 44. Warm start spent the first half of its episode budget on V1 and copied the item- and tote-specific Q-values into the matching V2 battery states. It then learned from V2 transitions. The dashboard curve and exported episode rows cover V2. The CSV records the pretraining episode and tick counts alongside the V2 data.

| Method | Episodes per seed | Total training ticks per seed | Frozen-policy completions | Minimum-time matches |
| --- | --- | --- | --- | --- |
| From scratch | 3,000 on V2 | 61,063–61,416 | 0/12 | 0/12 |
| Warm start from V1 | 1,500 on V1 and 1,500 on V2 | 84,308–84,805 | 12/12 | 12/12 |
| Extended scratch run | 4,200 on V2 | 86,696–86,746 | 0/12 | 0/12 |

The warm-start policies completed the full case in 14 ticks and the low case in 16 ticks for both items. During exploratory V2 training they completed 891 of 4,500 episodes. The extended scratch run used the Python training API and exceeded the warm-start interaction count for each paired seed. Across its 12 replays, 11 depleted the battery and one reached the step limit. The pilot tests one layout and two starting charges.

Local and hosted browser smoke checks passed across V0, V1 and V2. The V2 smoke check exercised both previews, both training starts, policy replay, the matched reference and CSV export. Scenario checks verified the charger cap, off-dock waiting, failure when a low-charge robot tries to deliver without charging, and depletion taking precedence over delivery.

This checkpoint uses the original V1 worktree base, `f05a308`. The replay redesign on `origin/main` at `a826bf2` changes the map renderer and dashboard controls. Integration needs a fresh browser smoke check.

### Manual review

1. Open the worktree preview and select **V2 · Charging dock**. With **Low charge** selected, scrub to tick **2** and check that the robot stays on the dock, charge rises from **12** to **14**, and the completion reward stays at zero. At tick **16**, check delivery and **0.8** units of remaining charge.
2. Switch **Preview starting charge** to **Full charge** and scrub to tick **14**. Check delivery with **zero** charging ticks.
3. To reproduce the pilot, set **Episodes** to **3,000**, keep **Warm start from V1** and seed **42**, then train and replay. The curve covers the **1,500** V2 episodes. Check **4/4** completions and **4/4** minimum-time matches.

Appendix C of the Markdown report records the environment and training comparison. Refresh the Word export after review.

## V3 · Packing and outbound staging

The staffed packing station is at (7, 5) and the former delivery dock at (8, 5) serves as outbound staging. After collecting the requested item, the robot waits one tick at the station to exchange the open tote for a packed shipping carton. The observation records whether packing has completed. The only completion credit comes from moving the packed carton into staging. The original map, movement actions and charging rules apply.

The best packing route for either item takes 15 moves and two service waits, drawing 15.4 synthetic energy units. V3 raises full charge from 14 to 16 units to keep both orders feasible. Low charge starts at 14, so the robot needs two charging ticks. The minimum times are 17 ticks from full charge and 19 ticks from low charge. Both routes arrive with 0.6 units remaining.

### Results

On 20 November 2026, Q-learning used the V1 defaults, the operational reward and seeds 42, 43 and 44. Each frozen policy was evaluated on both orders at both starting charges. The warm start used half the episode budget for packing practice with the same stations and reward, with battery limits disabled. The learner then copied the resulting action values into the corresponding battery states and continued training with battery limits enabled.

| Method | Episodes per seed | Total training ticks per seed | Frozen completions | Minimum-time matches |
| --- | --- | --- | --- | --- |
| From scratch | 3,000 on V3 | 69,347–69,826 | 0/12 | 0/12 |
| Shorter warm start | 750 practice and 750 on V3 | 50,880–51,314 | 7/12 | 7/12 |
| Warm start, review configuration | 1,500 practice and 1,500 on V3 | 98,050–98,534 | 12/12 | 12/12 |
| Extended scratch run | 4,400 on V3 | 102,995–103,328 | 0/12 | 0/12 |

The 3,000-episode warm start completed 740 of 4,500 exploratory V3 episodes. The extended scratch run used the Python training API and exceeded the warm-start interaction count for each seed. Its frozen policy depleted the battery in all 12 evaluations. These runs use two known orders and one static map.

Local and hosted browser smoke checks passed for V0 through V3 on the phase branch. The V3 check covered the pack and stage sequence, starting charge previews, warm-start budget, frozen replay and CSV export with `pack_tick`. Scenario checks verified that an empty tote cannot be packed, visiting staging with an unpacked item earns no completion credit, and waiting twice does not create a second carton. Frozen V0 through V2 evaluations reproduced the earlier routes. Integration with the replay redesign on `origin/main` at `a826bf2` remains pending.

### Manual review

1. Select **V3 · Pack and stage** and **Full charge**. At tick **14**, the robot visits outbound staging with the unpacked item. Check that completion reward is **0**.
2. At tick **16**, check **Packed CARTON** at the packing station and completion reward **0**. At tick **17**, check **Staged for shipment** and completion reward **+100**.
3. Switch to **Low charge** and confirm the preview completes at tick **19** with two charging ticks. The carton preview routes back to the charger after pickup.
4. Set **Episodes** to **3,000**, keep **Warm start with packing practice** and seed **42**, then train and replay. Check **4/4** completions and **4/4** minimum-time matches. The curve and CSV rows cover 1,500 V3 episodes, and the export records the packing tick and pretraining budget.

Appendix C of the Markdown report records the V3 pilot. Refresh the Word export after review.

## V4 · Multiple layouts and held-out evaluation

V4 carries the V3 workflow and battery limits into three 10 × 10 synthetic floors. The original floor is the single-layout training control. Mixed training samples the original floor and the parallel-aisle floor with equal probability using a dedicated seeded stream. The offset cross-aisle is reserved for frozen evaluation. Each floor defines its own rack obstacles, pick bays, charging start, packing station and outbound staging. The forklift stays in the V0 navigation scenario.

The same DQN learns in both conditions. Per-action inputs indicate legal moves and progress toward the current station using shortest walkable distances. Further inputs describe pickup and packing progress, charge, estimated ability to complete or recharge, distance to the current station and remaining time. The distance estimate directs the robot toward its charger when the next service sequence exceeds its remaining charge and recharging there is feasible. These inputs let both policies use the geometry of whichever test floor is loaded. The network receives neither coordinates nor a floor ID. Training masks illegal moves, follows the distance guide on 80% of exploratory choices when the estimate is feasible, and adds a training-only progress term. The term doubles the difference between the current estimate and the discounted next estimate. Each estimate is capped at 25 ticks and set to zero at the end of the episode. Frozen replays use greedy network values over legal moves. The dashboard and CSV report the operational reward before shaping.

### Protocol and results

On 20 November 2026, each condition used 1,500 episodes per seed, seeds 42–44, the operational reward, discount 0.98, an exploration decay fraction of 0.8 and a minimum exploration probability of 0.05. Order and charge streams are paired across conditions. Each frozen policy runs both orders at both starting charges on each of the three floors. A breadth-first search over the executable simulator states supplies the minimum-time reference for the same floor, order and starting charge.

| Reference floor | Carton, full / low | Refill, full / low |
| --- | --- | --- |
| Original | 17 / 19 ticks | 17 / 19 ticks |
| Parallel aisles | 16 / 17 ticks | 16 / 17 ticks |
| Offset cross-aisle | 15 / 15 ticks | 17 / 19 ticks |

| Seed | Original-only training ticks | Mixed training ticks | Mixed episodes on original / parallel | Held-out completions, original / mixed | Held-out minimum-time matches, original / mixed |
| --- | ---: | ---: | ---: | ---: | ---: |
| 42 | 58,129 | 52,476 | 735 / 765 | 2/4 / 4/4 | 2/4 / 4/4 |
| 43 | 42,783 | 41,648 | 730 / 770 | 4/4 / 4/4 | 0/4 / 2/4 |
| 44 | 41,540 | 45,430 | 743 / 757 | 2/4 / 4/4 | 2/4 / 4/4 |

| Evaluation floor | Original-only completions | Original-only minimum-time matches | Mixed completions | Mixed minimum-time matches |
| --- | ---: | ---: | ---: | ---: |
| Original | 12/12 | 11/12 | 12/12 | 10/12 |
| Parallel aisles | 6/12 | 6/12 | 12/12 | 12/12 |
| Offset cross-aisle, held out in both conditions | 8/12 | 4/12 | 12/12 | 10/12 |

All four original-only failures on the held-out floor depleted the battery. The two slower mixed-policy completions on that floor came from seed 43 on the carton order and took 31 and 41 ticks against a 15-tick reference. On the original floor, the mixed seed-42 policy took 85 and 91 ticks to complete the refill order. Original-only training completed 2,769 of 4,500 exploratory episodes. Mixed training completed 2,729 of 4,500. The comparison matches episode counts and reports the unequal simulator tick counts. It measures transfer to one synthetic held-out floor with access to its geometry and station distances. Additional held-out layouts and a guide-only control would be needed to attribute the results more broadly to the learner.

### Verification

The planner and the distance guide each completed all 12 floor, order and charge combinations at the recorded reference times. The checks covered legal movement, service order, positive charge at completion, charging after a zero-charge arrival and withholding guide actions when the estimate is infeasible. Before-and-after snapshots confirmed that frozen evaluation left the network, target network, replay buffer, random states used during training and training history unchanged. Only the configured training floors appeared in the episode records. Seed-42 static runs for V0 through V3 reproduced their previous frozen reference times.

Local and hosted Edge smoke checks passed for V0 through V4. The browser checks cover preview floor switching, map rendering in the mixed episode grid, both training modes, matched references, evaluation provenance and CSV export. This checkpoint stays on `codex/warehouse-environment-phases`. Integration with the replay redesign on `origin/main` remains pending.

### Manual review

1. In the worktree preview, select **V4 · Multiple layouts** and **Low charge**. Switch **Preview floor** between **Original**, **Parallel aisles** and **Offset cross-aisle**. The carton reference takes 19, 17 and 15 ticks respectively. On the offset cross-aisle the robot starts at column B, row 7, then packs at H9 and stages at I9.
2. With **Original and parallel aisles**, train for **1,500** episodes using seed **42** and the default operational reward. Check that the episode grid shows the floor for each trace and the CSV contains both training floors.
3. Set **Evaluation floor** to **Offset cross-aisle (held out)**. Select **Replay trained policy**. Expect **4/4** completions and **4/4** minimum-time matches. **Play fastest route** should show the representative low-charge refill run taking 19 ticks on the offset cross-aisle.
4. Repeat with **Original only**, keeping the other settings. Expect **2/4** held-out completions and **2/4** minimum-time matches. The representative refill replay depletes the battery. The 19-tick reference still completes.

Appendix C of the Markdown report records the V4 experiment. The Word export is deferred until after review.

## V5 · Shared aisles and a scripted replenishment AMR

Use the original packing floor, with the existing pick, charge, pack and staging rules. The learning AMR fills the shipment order. A second AMR starts with a replenishment tote at its parking cell (4, 4), crosses the center aisle, spends a tick unloading at the buffer bay (5, 6) and returns to parking. The scripted job records the tote handoff separately from order stock and completion credit. It leaves parking after tick 7 or 10, sampled by an independent seeded stream. The episode ends with the shipment outcome. The scripted AMR's parked status records whether it finished its own job by then.

Both AMRs request movement from the same pre-tick state. The simulator resolves both requests before committing either move. The replenishment AMR has priority when both request the same free cell. Both stay put on a head-on swap. A following move into an occupied cell succeeds only if the occupant vacates it on that tick. The scripted AMR retries denied moves. A denied shipment AMR move draws idle energy and earns no pickup, packing or charging service. Denials are counted per robot, and a stall is a conflict tick when neither moves. These counters are separate from wall blocks and forklift exposure.

V5 retains the V4 DQN, distance features, movement mask, guided exploration and training-only progress shaping. It adds two five-element inputs showing, for each action, whether the announced replenishment request would cause each AMR to be denied. When the distance guide would cause a denial, it prefers to wait if that clears the conflict, then considers the best-progress action that clears both requests. The learned policy can still request any move permitted by the floor. The resolver applies during training, frozen evaluation and breadth-first reference search.

### Protocol and results

On 20 November 2026, V5 trained for 1,500 episodes per seed on seeds 42–44, using the operational reward and the V4 DQN defaults (discount 0.98, exploration floor 0.05, decay fraction 0.8). The control reused the V4 original-only protocol and froze its policy before evaluating it on V5. It received the V4 observation during evaluation. Each fitted policy faced the same two items, two starting charges and two release times, for eight frozen trials per seed. Both conditions used the same conflict resolver. The planner completed every case with zero denials, taking 17 ticks at full charge or 19 from low charge.

| Seed | V4 control training ticks | V5 training ticks | V5 episodes released after tick 7 / 10 | Frozen completions V4 / V5 | Minimum-time matches V4 / V5 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 42 | 58,129 | 50,604 | 731 / 769 | 8 / 8 | 8 / 6 |
| 43 | 42,783 | 42,909 | 722 / 778 | 8 / 8 | 6 / 5 |
| 44 | 41,540 | 43,755 | 783 / 717 | 6 / 8 | 6 / 8 |

| Frozen metric | V4 control | V5 with traffic inputs |
| --- | ---: | ---: |
| Shipment completions | 22/24 | 24/24 |
| Minimum-time matches | 20/24 | 19/24 |
| Battery depletions | 2 | 0 |
| Order AMR denials | 6 | 7 |
| Replenishment AMR denials | 5 | 10 |
| Stall ticks | 5 | 10 |
| Replenishment AMR parked by episode end | 24/24 | 24/24 |

V5 completed 2,886 of 4,500 exploratory training episodes, with 1,026 order AMR denials, 1,100 scripted AMR denials and 1,417 stall ticks. Four frozen carton trials took 33–35 ticks, 16 ticks beyond their references. The fifth slower V5 trial spent one extra tick. The pilot compares exposure to traffic during training together with the new inputs and guided exploration. It matches episode budgets and reports the unequal tick budgets. The results cover one floor, one scripted route and two known release times. This comparison does not isolate the contribution of the added inputs.

### Verification and manual review

The resolver was checked on all 26,296 joint legal requests from distinct cells on the original floor. No accepted pair shared a destination or swapped cells. All eight matched reference traces delivered the order and returned the scripted AMR to parking. Frozen evaluation left the network, target, replay memory, training RNGs checked and episode history unchanged. The local and hosted dashboard smoke checks exercise both AMRs, all three conflict previews, the episode grid, matched replay and CSV export.

1. Open **V5 · Shared aisles**. Select **Same-cell request** and scrub to tick **8**. The blue replenishment AMR enters E6. The order AMR stays at D6. Expect one order AMR denial and zero stall ticks.
2. Select **Head-on swap** and scrub to tick **9**. The robots stay at E6 and F6. Expect one denial per robot and one stall tick. Scrub to tick **10** to see both move clear.
3. Select **Occupied aisle cell**. At tick **9** the order AMR must hold at F6 and the replenishment AMR waits at E6. At tick **10**, both advance one cell.
4. Select **Carton order route** with **Low charge**. The replenishment AMR unloads at tick **14**, parks at **17**, and the order AMR stages the carton at tick **19**.
5. Train for **1,500** episodes with seed **42** and the default settings, then replay. Expect **8/8** shipments, **6/8** minimum-time matches and **8/8** replenishment trips parked. The representative replay and its matched reference each take 19 ticks. The CSV records the release tick, both denial totals and the stall count.

Appendix C of the Markdown report records V5. The Word export is deferred until after review. Integration with the replay redesign on `origin/main` remains pending.

## V6 · Two learning AMRs

Two independently acting AMRs share the original rack layout, packing station and outbound staging cell. Each gets one of the two stocked items. The two possible order assignments and the independent charge presets make eight scenarios. AMR 1 starts at the original charger and AMR 2 starts at a charger in the former replenishment parking cell. Full and low charge are 21 and 19 simulation units so both assignments have a feasible route. The existing move, idle and recharge rates apply. A robot exits through staging after handing off its packed order, freeing the cell for the other robot on the following tick. The episode finishes when both orders are staged, either robot depletes its charge, or 100 ticks elapse.

Both actions are requested from the same pre-tick state. V5's joint conflict resolver applies with AMR 2 receiving priority when both request the same empty cell. It prevents swaps and permits following into a cell that its occupant vacates on the same tick. Each staged order earns the team 50 points once. The operational profile sums time and energy costs across active robots and applies one 100-point failure penalty to a failed episode. The dashboard shows the chosen action, order state, battery, denied moves and stationary ticks for each robot. Stationary ticks include charging and service waits, plus denied moves.

### Training and comparison

The comparison uses compact PPO actors and linear critics that run in the local and browser simulators. Each robot has its own masked softmax actor. Both methods use the same action features for route progress, the option to wait and nearby peer occupancy. The initial weights favor moving toward the current order or charging waypoint. IPPO fits one value model per robot using its own features. MAPPO fits a shared value model using the concatenated features from both robots. Both methods train on the same team reward and use local actor inputs at replay time.

On 20 November 2026, each method trained for 1,500 episodes on each of seeds 42–44. Paired runs sampled the same eight scenario combinations with a dedicated seeded stream. Each update used up to 10 episodes, three passes, a PPO clip interval of 0.8–1.2, discount 0.98 and GAE parameter 0.95. The actor and critic update rates were 0.002 and 0.005, with the critic step divided by its feature count. The training reward adds twice the difference between the current and discounted next estimates of total remaining robot ticks, then scales the reward by 100. The displayed return uses the operational reward.

The centralized reference uses joint A* to choose both actions under the same motion, charge and service rules. It minimizes the tick when both orders have been staged. All eight scenarios attained the lower bound from the slower robot's optimal solo route. The reference needs **17 ticks** with the carton assigned to AMR 1. When the carton is assigned to AMR 2, the reference needs **21 ticks** from full charge or **22 ticks** from low charge.

| Seed | IPPO training ticks | MAPPO training ticks | IPPO sampled completions | MAPPO sampled completions |
| ---: | ---: | ---: | ---: | ---: |
| 42 | 37,068 | 38,082 | 27/32 | 27/32 |
| 43 | 37,335 | 37,226 | 29/32 | 28/32 |
| 44 | 38,840 | 37,946 | 30/32 | 31/32 |

Frozen sampled evaluation ran four seeded action draws per scenario for each training seed. The initial actor used the same evaluation draws to measure the effect of the route-aware initialization. Greedy evaluation used the highest-probability action once per scenario. Both protocols froze weights and used the same joint routing reference.

| Frozen policy | Completed both orders | Individual orders staged | Minimum-time matches | Mean stationary ticks, AMR 1 / 2 | Stall ticks |
| --- | ---: | ---: | ---: | ---: | ---: |
| Initial actor, sampled | 74/96 | 157/192 | 18/96 | 6.47 / 8.73 | 359 |
| IPPO, sampled | 86/96 | 180/192 | 33/96 | 3.58 / 4.11 | 107 |
| MAPPO, sampled | 86/96 | 180/192 | 32/96 | 4.03 / 4.52 | 141 |
| IPPO, greedy | 12/24 | 24/48 | 0/24 | 19.0 / 21.5 | 414 |
| MAPPO, greedy | 12/24 | 24/48 | 0/24 | 19.0 / 21.5 | 414 |

Sampled IPPO logged 105 and 93 denials for AMRs 1 and 2. Sampled MAPPO logged 129 and 133. Every failed frozen trial ended in battery depletion. Both greedy policies repeatedly attempted swaps with the carton assigned to AMR 1. The fixed resolver prevented contact while the robots continued spending idle energy. Under sampling, both methods increased completion and reduced stalls relative to the initialized actor. This pilot used one floor and the same scenario combinations during training and evaluation. It gives no clear advantage to the centralized critic and motivates separate checks for persistent conflicts before interpreting completion as robust coordination.

### Verification and manual review

Simulator checks verified distinct robot occupancy, head-on denial and recovery, separate stock consumption, one staging reward per order, reference optimality across all eight cases and batch-size reproducibility. Frozen evaluation preserved actor and critic weights, random states and training history. Local and hosted Edge smoke checks passed for V0 through V6 and covered both PPO methods, both replay behaviors, the episode grid and CSV export.

1. Select **V6 · Two learning robots**. In the default reference preview, scrub to tick **15**. AMR 2 stages the refill for **+50**. At tick **16** it has exited through staging. At tick **17**, AMR 1 stages the carton for **+50** and the episode ends.
2. Train **Independent PPO** for **1,500 episodes** with seed **42**. Keep the first replay scenario and choose **Sample actions**. Expect **27/32** trials completing both orders, with **10/32** matching the joint reference. The displayed replay and its reference take **17 ticks** each.
3. Change **Frozen policy behavior** to **Choose highest-probability action** and replay. Expect **4/8** complete trials. Scrub the failed carton-first trace to inspect repeated denials. Play the joint reference for the same starting conditions.
4. Repeat with **Multi-agent PPO**. With seed 42 the sampled evaluation also completes **27/32**, while the accumulated stall count is **57** for MAPPO and **39** for IPPO. The CSV records both orders, staging ticks, stationary ticks and denials.

Appendix C of the Markdown report records V6. The Word export and integration with `origin/main` remain pending.

## V7 · Continuous fulfillment and the packing queue

V7 runs an 80-tick shift with two AMRs and recurring orders. The paced workload releases six orders at ticks 0, 0, 28, 40, 58 and 72. The burst workload releases two every eight ticks from tick 0 through 40, for twelve orders. Items alternate between carton and refill, with either item first. Each release puts one unit in the corresponding rack. An AMR at its charger reserves the oldest unassigned order and one unit of its item. Pickup consumes the reservation and the unit. At staging, the packed shipment earns 50 points once. The AMR then returns to charge and can take another order. A depleted AMR remains in its cell and a stranded shipment remains in the backlog.

The original floor gains one passable holding bay beside packing. The two marked waiting cells feed one FIFO packing slot. AMR 1 breaks ties when both join on the same tick. Only the head order can enter when the slot is available, and an admitted order gets three stationary packing ticks. The movement resolver from V6 still governs contested cells, swaps and following. The synthetic battery capacity is 42 units. Dispatch holds the robot at the charger until it has enough charge for the nominal pick, pack, stage and return trip plus a three-unit allowance. Departures are still subject to the V6 movement and idle costs and the one-unit net charge per wait.

### Protocol

Both methods reuse the V6 PPO actor architecture, optimizer settings and critic comparison. Masks enforce charging, service and queue access. The actor sees local progress toward the current job waypoint, relative peer occupancy and allowed actions. The observation for the value model includes charge, current waypoint distance, order progress, nearby occupancy and time left. The operational reward charges time and energy during the shift and applies a one-time 50-point penalty when a robot depletes. Training-only shaping uses the difference between the current and discounted next estimates of the robots' total remaining job ticks. Service and route estimates include the return to the chargers. Unfinished orders are measured in the backlog.

On 24 November 2026, IPPO and MAPPO each trained on 1,500 shifts per seed for seeds 42–44. The two methods shared the same seeded workload and item sequence and consumed 120,000 simulator ticks per seed. Each frozen sampled policy faced 24 shifts per workload across the three seeds (two item sequences and four action draws per seed). Highest-probability replay used one shift per item sequence and seed. The comparison includes the common initial actor and a deterministic centralized reference. That reference chooses a conflict-free joint action with the most immediate waypoint progress and favors the robot carrying a packed carton when breaking progress ties. It uses the same dispatch, queue, battery and movement rules. This reference is a greedy heuristic, so it does not establish maximum achievable throughput.

### Results

The table reports means per 80-tick shift except for throughput, which is normalized to 100 ticks. Queue ticks sum time spent waiting for packing across admitted and outstanding orders. Time awaiting assignment is part of end backlog and is excluded from queue ticks.

| Frozen policy or reference | Workload | Staged per shift | Orders per 100 ticks | End backlog | Order queue ticks | Stall ticks |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Initial actor, sampled | Paced | 2.17 | 2.71 | 3.83 | 5.21 | 28.00 |
| Initial actor, sampled | Burst | 2.46 | 3.07 | 9.54 | 5.96 | 28.29 |
| IPPO, sampled | Paced | 3.50 | 4.38 | 2.50 | 7.42 | 6.38 |
| IPPO, sampled | Burst | 3.58 | 4.48 | 8.42 | 6.58 | 6.58 |
| MAPPO, sampled | Paced | 3.63 | 4.53 | 2.38 | 8.17 | 5.33 |
| MAPPO, sampled | Burst | 3.54 | 4.43 | 8.46 | 7.17 | 8.04 |
| Dispatch reference | Paced | 4.00 | 5.00 | 2.00 | 8.50 | 0.00 |
| Dispatch reference | Burst | 4.00 | 5.00 | 8.00 | 8.50 | 0.00 |

Sampled IPPO staged 170 orders and sampled MAPPO staged 172 across 48 shifts each. The initial actor staged 111. Both trained policies reduced stalls and staged similar totals. Their total queue ticks rose as more orders reached packing. Highest-probability replay averaged 1.50 staged orders per shift for both methods and about 48 stall ticks. Across the four reference cases there were zero battery depletions, compared with 19 for sampled IPPO and 25 for sampled MAPPO. These are results for one synthetic floor, two known release schedules and a fixed assignment rule. They do not estimate site throughput.

Simulator tests checked reservation counts, physical queue occupancy, one staging credit per order, FIFO ties, the three-tick service duration and frozen evaluation. Local and hosted browser smoke checks passed for V0 through V7.

### Manual review

1. Select **V7 · Continuous fulfillment** and scrub the default burst preview to tick **14**. Both orders are in the queue in the order **#1, #2**. At tick **15**, **#1** has three ticks of service left and **#2** is waiting in its marked bay.
2. At tick **19**, **#1** stages and earns **+50** while **#2** enters packing. At tick **80**, check **12 released, 4 staged and 8 in backlog**. Expand **Released orders** to inspect the status of each order.
3. Train **Independent PPO** or **Multi-agent PPO** with **1,500 episodes** and seed **42**. Keep the default **Burst · carton first** scenario and **Sample actions**. The displayed replay and the matched dispatch reference each stage **4 of 12** orders for either method. Across the eight burst evaluations per method, the sampled policies average **4.53 orders per 100 ticks**. The CSV records throughput, queue ticks, packing service, depletion and end backlog.

Appendix C of the Markdown report records the V7 pilot. The Word export and integration with `origin/main` remain pending.
