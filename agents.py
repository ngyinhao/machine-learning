from collections import defaultdict, deque
from copy import deepcopy
from math import exp
from operator import mul
from random import Random


class Agent:
    uses_epsilon = False
    select_before_update = False

    def start_episode(self, episode, learn):
        pass

    def observe(self, state, action, reward, next_state, next_action):
        pass

    def finish_episode(self, reward):
        pass


def greedy(values, random_source, actions=None):
    if actions is None:
        actions = range(len(values))
    best = max(values[action] for action in actions)
    return random_source.choice([action for action in actions if values[action] == best])


class TabularTD(Agent):
    uses_epsilon = True
    select_before_update = True

    def __init__(self, actions, gamma, on_policy, alpha, initial_q, valid_actions):
        self.initial = (initial_q,) * actions
        self.values = defaultdict(lambda: list(self.initial))
        self.gamma = gamma
        self.on_policy = on_policy
        self.alpha = alpha
        self.valid_actions = valid_actions

    @staticmethod
    def key(state):
        position, phase, _, returning = state
        return position, phase, returning

    def select(self, state, epsilon, random_source, learn):
        actions = self.valid_actions[state[0]]
        if random_source.random() < epsilon:
            return random_source.choice(actions)
        values = self.values.get(self.key(state), self.initial)
        best = max(values[action] for action in actions)
        return random_source.choice([action for action in actions if values[action] == best])

    def observe(self, state, action, reward, next_state, next_action):
        target = reward
        if next_state is not None:
            future = self.values[self.key(next_state)]
            estimate = future[next_action] if self.on_policy else max(
                future[option] for option in self.valid_actions[next_state[0]]
            )
            target += self.gamma * estimate
        current = self.values[self.key(state)]
        current[action] += self.alpha * (target - current[action])


def activate(value):
    return value if value > 0 else 0.01 * value


class QNetwork:
    def __init__(self, width, height, phases, horizon, actions, random_source):
        hidden = 16
        self.width = width
        self.cells = width * height
        self.phases = phases
        self.horizon = horizon
        self.inputs = [self._weights(hidden, 0.5, random_source) for _ in range(self.cells + phases + 3)]
        self.hidden = [self._weights(hidden + 1, 0.35, random_source) for _ in range(hidden)]
        self.output = [self._weights(hidden + 1, 0.25, random_source) for _ in range(actions)]
        self.inputs.append(self._weights(hidden, 0.5, random_source))

    @staticmethod
    def _weights(count, scale, random_source):
        return [random_source.uniform(-scale, scale) for _ in range(count)]

    def _forward(self, state):
        (column, row), phase, remaining, returning = state
        active_inputs = (
            (row * self.width + column, 1.0),
            (self.cells + phase + 1, 1.0),
            (self.cells + self.phases + 1, remaining / self.horizon),
            (self.cells + self.phases + 2, 1.0),
            (self.cells + self.phases + 3, float(returning)),
        )
        first = [
            activate(sum(weight * value for weight, (_, value) in zip(weights, active_inputs)))
            for weights in zip(*(self.inputs[index] for index, _ in active_inputs))
        ]
        first.append(1.0)
        second = [activate(sum(map(mul, weights, first))) for weights in self.hidden]
        second.append(1.0)
        values = [sum(map(mul, weights, second)) for weights in self.output]
        return active_inputs, first, second, values

    def values(self, state):
        return self._forward(state)[-1]

    def train(self, state, action, target):
        active_inputs, first, second, values = self._forward(state)
        output_error = max(-1.0, min(1.0, values[action] - target))
        output_weights = self.output[action]
        second_errors = [
            output_error * weight * (1.0 if activation > 0 else 0.01)
            for weight, activation in zip(output_weights[:-1], second)
        ]
        first_errors = [
            sum(map(mul, weights, second_errors)) * (1.0 if activation > 0 else 0.01)
            for weights, activation in zip(zip(*self.hidden), first[:-1])
        ]

        self._update(output_weights, second, output_error)
        for weights, error in zip(self.hidden, second_errors):
            self._update(weights, first, error)
        for index, value in active_inputs:
            self._update(self.inputs[index], first_errors, value)

    @staticmethod
    def _update(weights, features, error):
        step = 0.015 * error
        for index, value in enumerate(features):
            weights[index] -= step * value


class DQN(Agent):
    uses_epsilon = True

    def __init__(self, width, height, phases, horizon, actions, gamma, seed, valid_actions, potential):
        self.random = Random(seed)
        self.network = QNetwork(width, height, phases, horizon, actions, self.random)
        self.target = deepcopy(self.network)
        self.replay = deque(maxlen=5000)
        self.transitions = 0
        self.gamma = gamma
        self.valid_actions = valid_actions
        self.potential = potential

    def select(self, state, epsilon, random_source, learn):
        actions = self.valid_actions[state[0]]
        if random_source.random() < epsilon:
            return random_source.choice(actions)
        return greedy(self.network.values(state), random_source, actions)

    def observe(self, state, action, reward, next_state, next_action):
        next_potential = self.potential(next_state) if next_state is not None else 0.0
        shaping_reward = self.gamma * next_potential - self.potential(state)
        self.replay.append((state, action, (reward + shaping_reward) / 100.0, next_state))
        self.transitions += 1
        if len(self.replay) >= 128 and self.transitions % 4 == 0:
            for sample_state, sample_action, sample_reward, sample_next in self.random.sample(self.replay, 4):
                target = sample_reward
                if sample_next is not None:
                    future = self.target.values(sample_next)
                    target += self.gamma * max(future[option] for option in self.valid_actions[sample_next[0]])
                self.network.train(sample_state, sample_action, target)
        if self.transitions % 250 == 0:
            self.target = deepcopy(self.network)


class SoftmaxPolicy(Agent):
    def __init__(self, actions, gamma):
        self.actions = range(actions)
        self.initial = (0.0,) * actions
        self.preferences = defaultdict(lambda: list(self.initial))
        self.gamma = gamma

    @staticmethod
    def key(state):
        position, phase, _, returning = state
        return position, phase, returning

    def probabilities(self, state):
        logits = self.preferences.get(self.key(state), self.initial)
        peak = max(logits)
        weights = [exp(logit - peak) for logit in logits]
        total = sum(weights)
        return [weight / total for weight in weights]

    def select(self, state, epsilon, random_source, learn):
        if learn:
            return random_source.choices(self.actions, self.probabilities(state))[0]
        return greedy(self.preferences.get(self.key(state), self.initial), random_source)

    def _improve(self, state, action, probabilities, step):
        logits = self.preferences[self.key(state)]
        for index, probability in enumerate(probabilities):
            logits[index] += step * ((index == action) - probability)


class Reinforce(SoftmaxPolicy):
    def __init__(self, actions, gamma):
        super().__init__(actions, gamma)
        self.trajectory = []
        self.baseline = 0.0

    def observe(self, state, action, reward, next_state, next_action):
        self.trajectory.append((state, action, self.probabilities(state), reward / 100.0))

    def finish_episode(self, reward):
        discounted = 0.0
        for index in range(len(self.trajectory) - 1, -1, -1):
            state, action, probabilities, step_reward = self.trajectory[index]
            discounted = step_reward + self.gamma * discounted
            step = 0.12 * self.gamma**index * (discounted - self.baseline)
            self._improve(state, action, probabilities, step)
        self.baseline += 0.05 * (discounted - self.baseline)
        self.trajectory.clear()


class ActorCritic(SoftmaxPolicy):
    def __init__(self, actions, gamma):
        super().__init__(actions, gamma)
        self.critic = defaultdict(float)
        self.discount = 1.0

    def start_episode(self, episode, learn):
        if learn:
            self.discount = 1.0

    def observe(self, state, action, reward, next_state, next_action):
        key = self.key(state)
        future = self.critic.get(self.key(next_state), 0.0) if next_state is not None else 0.0
        error = reward / 100.0 + self.gamma * future - self.critic[key]
        self.critic[key] += 0.2 * error
        self._improve(state, action, self.probabilities(state), 0.25 * self.discount * error)
        self.discount *= self.gamma


class PPO(SoftmaxPolicy):
    def __init__(self, actions, gamma, seed):
        super().__init__(actions, gamma)
        self.critic = defaultdict(float)
        self.trajectory = []
        self.random = Random(seed)

    def observe(self, state, action, reward, next_state, next_action):
        self.trajectory.append((state, action, self.probabilities(state)[action], reward / 100.0))

    def finish_episode(self, reward):
        samples = []
        advantage = next_value = 0.0
        for state, action, old_probability, step_reward in reversed(self.trajectory):
            value = self.critic.get(self.key(state), 0.0)
            delta = step_reward + self.gamma * next_value - value
            advantage = delta + self.gamma * 0.95 * advantage
            samples.append((state, action, old_probability, advantage, value + advantage))
            next_value = value
        self.trajectory.clear()

        for _ in range(4):
            self.random.shuffle(samples)
            for state, action, old_probability, advantage, target in samples:
                probabilities = self.probabilities(state)
                ratio = probabilities[action] / old_probability
                if (advantage > 0 and ratio <= 1.2) or (advantage < 0 and ratio >= 0.8):
                    self._improve(state, action, probabilities, 0.25 * ratio * advantage)
                key = self.key(state)
                self.critic[key] += 0.2 * (target - self.critic[key])
