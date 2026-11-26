# Warehouse RL Lab

A research project on how reinforcement learning rewards affect travel time, energy use, and forklift exposure in simulated warehouse deliveries. The dashboard visualizes training outcomes and route decisions.

## Documentation

- **Research report** — [Markdown source](report/Warehouse_RL_Lab_Report.md) and [Word export](report/Warehouse_RL_Lab_Report_Pandoc.docx).
- **Product and dashboard** — [product brief](PRODUCT.md) and [dashboard design](DESIGN.md).
- **Research and experiments** — [project ideas](research/Reinforcement_Learning_Project_Ideas.md), [warehouse environment and experiment plan](research/Warehouse_Environment_Design.md), [reward-design research](research/Warehouse_Reward_Design_Research.md), [algorithm comparison](research/Warehouse_Algorithm_Comparison.md), and [learner tuning record](research/Warehouse_Algorithm_Comparison.md#learner-tuning-record).
- **Warehouse expansion** — [environment and training roadmap](research/Warehouse_Environment_Roadmap.md) and [phase implementation, results and review checks](research/Warehouse_Phase_Log.md).
- **Dashboard verification** — [episode grid timing check](research/Episode_Grid_Timing.md).

## Export the report

Edit `docs/report/Warehouse_RL_Lab_Report.md` and keep its linked figures in `docs/report/figures/`. Pandoc uses `docs/report/Warehouse_RL_Report_Reference.docx` for Word formatting. With Pandoc on `PATH`, run this from the repository root.

```sh
pandoc --defaults=docs/report/pandoc-report.yaml
```

The command generates `docs/report/Warehouse_RL_Lab_Report_Pandoc.docx`. In Word, refresh the table of contents after rebuilding to update page numbers.

## Hosted dashboard

Open [Warehouse RL Lab on ChatGPT Sites](https://warehouse-rl-lab.teamngnew-6178.chatgpt.site). The same Python training engine runs in a browser worker. Each tab has its own training run. Download the CSV before closing or reloading the tab.

Run `python scripts/build_hosted_dashboard.py` to build the assets into `sites/warehouse-rl-lab/dist`. The hosted URL serves the published version until a new version is deployed.

## Run a local preview

From the project root, run `python app.py` and open `http://127.0.0.1:8765` in a browser. Python 3.10 or newer is required. The dashboard and agents use the Python standard library and browser-native graphics, so there are no packages to install.

The server loads the dashboard files at startup. After updating the checkout, save any training results you need, stop that checkout’s server with `Ctrl+C`, and start it again. If you don’t know which process owns the port, use `python app.py --port 0` and open the free address it prints.

## Worktrees and merges

Use the published Site for the demo. Start each task from the shared `main` branch in its own checkout. Run these commands from the Git repository.

```sh
git fetch origin
git worktree add -b feature/dashboard-change ../machine-learning-dashboard-change origin/main
cd ../machine-learning-dashboard-change
python app.py --port 0
```

Use the printed address for that worktree. Each process has its own training state. To run the same browser check as CI from the worktree, run the following commands in your Python environment:

```sh
python -m pip install -r scripts/dashboard-check-requirements.txt
python -m playwright install chromium
python scripts/check_dashboard.py
python scripts/check_dashboard.py --hosted
```

Each check starts a separate server on a free port and exercises warehouse environments V0 through V7. The navigation checks include Q-learning and PPO training and replay, and the episode grid during a delayed DQN batch. The checks shut down their servers when finished. On Windows with Microsoft Edge installed, add `--channel msedge` to both checks and skip the Chromium download.

Push feature branches and open pull requests to `main`. GitHub Actions runs the `Dashboard smoke` job on those pull requests. The branch protection rule requires that check to pass on an up-to-date branch before merging, including for repository admins.

## Release the hosted dashboard

When a dashboard change is merged to GitHub `main`, publish it to the existing Warehouse RL Lab Site as part of the same release. GitHub Actions runs the smoke checks. Publication goes through ChatGPT Sites.

1. Fetch the merged `main` revision and check it out in a clean worktree. Record its commit SHA, then run `python scripts/build_hosted_dashboard.py` from that checkout.
2. Use the generated `sites/warehouse-rl-lab/dist` assets to update the existing Site's source repository. Save and deploy that version through ChatGPT Sites with the existing access settings.
3. Verify that the deployment succeeded. Record the GitHub commit, the live Site version, and the URL in the release handoff.

## Watch a training run

1. Select an **Environment** from V0 to V7 and play its route or dispatch preview. In **V4 · Multiple layouts**, use **Preview floor** to compare the Original, Parallel aisles, and Offset cross-aisle maps.
2. Choose an algorithm, mission, traffic scenario, and reward profile. The default configuration trains Q-learning to deliver to the dock and return home under the forklift patrol. Start training to see sampled episodes and the learning curve.
3. Pause training to inspect a checkpoint. Play or scrub the route trace to see per-step reward terms. **Show latest** loads the most recent recorded training trace. **Replay trained policy** evaluates one frozen-policy episode for each forklift starting phase, or one episode on the static floor, and plays a representative trace. **Play fastest route** animates the minimum-time collision-free reference for the replayed phase.
4. Open **View episode grid** to watch up to ten recorded training episodes together. By default, it samples every 10 episodes and shows a new group every 100. The grid plays the latest recorded group over roughly the time it took to train and repeats it if the next group is still training. The final group plays once. Use **Pause grid** to hold a view, or select a map to inspect and scrub its original trace. **Grid settings** apply when starting a new run.
5. Download the training CSV to compare runs. It includes the run settings, per-episode outcomes and metrics, and reward totals by component.

The completion rate and mean return show the latest 25 training episodes, or all available episodes if fewer have completed. Episode return is the undiscounted sum of recorded rewards. The replay comparison reports how many frozen-policy episodes completed and matched the minimum time. The animated replay uses a fixed scenario phase derived from the seed.

## Training methods

- **Value-based** learners include tabular Q-learning, SARSA, and a Deep Q-Network (DQN). All three use the displayed ε-greedy exploration schedule.
- **Policy-based** REINFORCE learns a probability distribution over actions from completed episodes.
- **Hybrid** methods include Actor–Critic and Proximal Policy Optimization (PPO). Both learn a policy and a value estimate and sample from the learned action probabilities during training. PPO applies multiple updates per episode using a clipped policy objective.

The dashboard shows `N/A` and the CSV leaves ε blank for methods without ε-greedy exploration.

## Warehouse simulator

- A fixed 10 × 10 grid, an automatic delivery dock, an optional return leg to the starting cell, a 100-tick task horizon, and four movement directions plus wait.
- An optional scripted forklift with a seed-controlled starting phase. Same-cell and swap collisions end the episode. Adjacent noncollision positions count as exposure. The scenario sequence uses a dedicated random stream so paired runs with the same seed see the same starting phases.
- Delivery/failure, efficiency, and operational reward profiles. The operational profile exposes the per-tick forklift exposure penalty.
- Synthetic movement and idle energy costs. Battery depletion, soft deadlines, potential-based shaping, and evaluation on different layouts are subsequent milestones.

The local dashboard keeps one active training run in server memory. Download the CSV before replacing that run or shutting down the server.

`warehouse.py` owns transitions, reward calculation, and episode execution. `agents.py` implements the training methods. `dashboard_api.py` manages training sessions for both the local and hosted dashboards. The `web` folder contains the interactive floor plan and charts.
