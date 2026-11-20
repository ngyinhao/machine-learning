# Project Agent Instructions

## Documentation Layout

- Use `docs/README.md` as the documentation index. Store project documentation under `docs/`, with assignment and report materials in `docs/assignment/` and research and experiment notes in `docs/research/`.

## Dashboard Development

- Keep `main` ready for release. In a Git checkout, do implementation work on a feature branch in a separate worktree. Run each preview on its own port with `python app.py --port 0`.
- Run the dashboard smoke check before proposing changes for `main`. See [the worktree and merge workflow](docs/README.md#worktrees-and-merges).
- When a dashboard change reaches GitHub `main`, build the hosted dashboard from that merged revision, deploy it to the existing private ChatGPT Site, and verify the live deployment. Treat both updates as one release. Follow [the hosted dashboard release steps](docs/README.md#release-the-hosted-dashboard).

## Report Checkpoint

- At the start of every development task, identify which report sections or results the work could affect. Before closing the task, decide whether to update the draft, record experiment notes, build the report, or leave it as is. Briefly state the decision in the handoff.
- Update the draft when a change affects the problem statement, warehouse environment, agent or reward design, baselines, training setup, evaluation protocol, results, or conclusions. If the draft is missing and there is material ready to write, start it using `docs/assignment/BMDS2114_Machine_Learning_Report_Template.docx` and `docs/assignment/Assignment specification (v1).md`.
- At experiment milestones, record what changed, why, the run configuration, and the observed results. Flag figures, tables, or claims that need a fresh run.
- Build or export the report when requested or when preparing the submission. Verify the results against the final implementation, refresh affected tables and figures, and align the conclusions with the verified results.
