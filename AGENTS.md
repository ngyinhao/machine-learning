# Project Agent Instructions

## Documentation Layout

- Use `docs/README.md` as the documentation index. Keep the research report and its export assets in `docs/report/` and research and experiment notes in `docs/research/`.

## Dashboard Development

- Keep `main` ready for release. In a Git checkout, do implementation work on a feature branch in a separate worktree. Run each preview on its own port with `python app.py --port 0`.
- Run the dashboard smoke check before proposing changes for `main`. See [the worktree and merge workflow](docs/README.md#worktrees-and-merges).
- When a dashboard change reaches GitHub `main`, build the hosted dashboard from that merged revision, deploy it to the existing private ChatGPT Site, and verify the live deployment. Treat both updates as one release. Follow [the hosted dashboard release steps](docs/README.md#release-the-hosted-dashboard).

## Report Checkpoint

- At the start of every development task, identify which report sections or results the work could affect. Before closing the task, decide whether to update the draft, record experiment notes, build the report, or leave it as is. Briefly state the decision in the handoff.
- Edit `docs/report/Warehouse_RL_Lab_Report.md` as the source of truth for report content. Keep figure assets in `docs/report/figures/` and link them from the Markdown.
- Update the Markdown report when a change affects the research question, warehouse environment, agent or reward design, baselines, training setup, evaluation protocol, results, or conclusions. Explain the reasons for selecting methods, changing rewards, and choosing tuning ranges. Describe the dashboard as a way to visualize and interpret the results.
- At experiment milestones, record what changed, why, the run configuration, and the observed results. Flag figures, tables, or claims that need a fresh run.
- Treat DOCX as a generated export. Apply content edits to the Markdown and regenerate from the repository root with `pandoc --defaults=docs/report/pandoc-report.yaml`.
- Before publishing the research report, verify the results against the implementation, refresh affected tables and figures, and check the generated Word document's layout and table of contents.

## Branch Push Checkpoint

- At the final handoff, check whether the task's feature branch has unpublished work, including uncommitted task changes or commits that have yet to be pushed.
- When the task is complete and required checks have passed, name the branch and ask whether to push it. If the task changes still need a commit, ask whether to commit and push them. Use any authorization the user has already given.
- Skip the push question if work or required checks are still pending, a required check failed, there is nothing new to publish, or the user asked to keep the work local.
