# Episode Grid Timing Check

## Playback during delayed DQN batches

The dashboard smoke check runs DQN for 65 episodes with 50-episode groups and holds the next request after episode 50. It advances the browser clock beyond one full playback cycle and checks that the recorded maps keep advancing while training stays at episode 50. The previous playback held at 0% throughout the delay. The check also verifies the grid and training pause controls and that the final group stops at its ending positions.

## Earlier checkpoint-driven playback

On November 18, 2026, two local headless Chrome runs checked whether the episode grid kept pace with training. Each run used Q-learning, seed 42, the operational reward profile, an exposure cost of 2 per tick, and 325 episodes. The grid used the default 100-episode groups with one trace every 10 episodes and up to ten simultaneous maps. The second run enabled forklift patrol and added a 160 ms delay before each 10-episode request to exercise slower training updates.

| Run | First group playback | Finish after the next training checkpoint |
| --- | ---: | ---: |
| No traffic | 1,526 ms | 78, 78, 77 ms |
| Forklift patrol with added delay | 3,159 ms | 91, 88, 86 ms |

The check measured from when the dashboard received each checkpoint to when the preceding group reached its final playback position. All six handoffs met the one-second target. The check also verified the partial final group, full-trace scrubbing, playback and training pauses, configurable map counts, and reduced motion on a narrow viewport.
