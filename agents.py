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


def greedy(values, random_source):
    best = max(values)
    return random_source.choice([action for action, value in enumerate(values) if value == best])


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
        position, phase, _, returning, *mission = state
        return position, phase, returning, *mission

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
    def __init__(self, width, height, phases, horizon, actions, random_source, *, feature_count=None):
        hidden = 16
        self.width = width
        self.cells = width * height
        self.phases = phases
        self.horizon = horizon
        self.feature_count = feature_count
        inputs = feature_count if feature_count is not None else self.cells + phases + 3
        self.inputs = [self._weights(hidden, 0.5, random_source) for _ in range(inputs)]
        self.hidden = [self._weights(hidden + 1, 0.35, random_source) for _ in range(hidden)]
        self.output = [self._weights(hidden + 1, 0.25, random_source) for _ in range(actions)]
        if feature_count is None:
            self.inputs.append(self._weights(hidden, 0.5, random_source))

    @staticmethod
    def _weights(count, scale, random_source):
        return [random_source.uniform(-scale, scale) for _ in range(count)]

    def _active_inputs(self, state):
        if self.feature_count is not None:
            return tuple(enumerate(state.features))
        (column, row), phase, remaining, returning = state
        return (
            (row * self.width + column, 1.0),
            (self.cells + phase + 1, 1.0),
            (self.cells + self.phases + 1, remaining / self.horizon),
            (self.cells + self.phases + 2, 1.0),
            (self.cells + self.phases + 3, float(returning)),
        )

    def _forward(self, state):
        active_inputs = self._active_inputs(state)
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

    def __init__(self, width, height, phases, horizon, actions, gamma, seed, *, feature_count=None):
        self.random = Random(seed)
        self.network = QNetwork(width, height, phases, horizon, actions, self.random, feature_count=feature_count)
        self.target = deepcopy(self.network)
        self.replay = deque(maxlen=5000)
        self.transitions = 0
        self.gamma = gamma
        self.actions = actions
        self.layout_aware = feature_count is not None

    def allowed(self, state):
        return state.actions if self.layout_aware else range(self.actions)

    def select(self, state, epsilon, random_source, learn):
        actions = self.allowed(state)
        if random_source.random() < epsilon:
            if self.layout_aware and state.guide is not None and random_source.random() < 0.8:
                return state.guide
            return random_source.choice(actions)
        values = self.network.values(state)
        best = max(values[action] for action in actions)
        return random_source.choice([action for action in actions if values[action] == best])

    def observe(self, state, action, reward, next_state, next_action):
        self.replay.append((state, action, reward / 100.0, next_state))
        self.transitions += 1
        if len(self.replay) >= 128 and self.transitions % 4 == 0:
            for sample_state, sample_action, sample_reward, sample_next in self.random.sample(self.replay, 4):
                target = sample_reward
                if sample_next is not None:
                    values = self.target.values(sample_next)
                    target += self.gamma * max(values[action] for action in self.allowed(sample_next))
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


class FleetPPO:
    def __init__(self, *, centralized):
        self.centralized = centralized
        self.actors = [[2.4, -1.5, -0.8, 0.0, 0.0, 0.0, 0.0] for _ in range(2)]
        self.critics = [[0.0] * 16] if centralized else [[0.0] * 8 for _ in range(2)]

    @staticmethod
    def probabilities(weights, observation):
        logits = [sum(map(mul, weights, features)) for features in observation.action_features]
        peak = max(logits)
        probabilities = [exp(logit - peak) for logit in logits]
        total = sum(probabilities)
        return [probability / total for probability in probabilities]

    def select(self, observations, random_source):
        actions = []
        old_probabilities = []
        for weights, observation in zip(self.actors, observations):
            if not observation.action_features:
                actions.append(observation.actions[0])
                old_probabilities.append(1.0)
                continue
            probabilities = self.probabilities(weights, observation)
            index = (random_source.choices(range(len(probabilities)), probabilities)[0] if random_source
                     else max(range(len(probabilities)), key=probabilities.__getitem__))
            actions.append(observation.actions[index])
            old_probabilities.append(probabilities[index])
        return tuple(actions), tuple(old_probabilities)

    def update(self, rollout, random_source):
        actor_samples = [[], []]
        critic_samples = [[] for _ in self.critics]
        for trajectory in rollout:
            next_values = [0.0] * len(self.critics)
            advantages = [0.0] * len(self.critics)
            for observations, actions, previous_probabilities, reward in reversed(trajectory):
                inputs = tuple(observation.value_features for observation in observations)
                if self.centralized:
                    inputs = (inputs[0] + inputs[1],)
                values = [sum(map(mul, weights, features)) for weights, features in zip(self.critics, inputs)]
                for index, features in enumerate(inputs):
                    delta = reward + 0.98 * next_values[index] - values[index]
                    advantages[index] = delta + 0.98 * 0.95 * advantages[index]
                    critic_samples[index].append((features, values[index] + advantages[index]))
                for index, (observation, action, probability) in enumerate(
                        zip(observations, actions, previous_probabilities)):
                    if observation.action_features:
                        advantage = advantages[0 if self.centralized else index]
                        actor_samples[index].append((observation, observation.actions.index(action), probability, advantage))
                next_values = values
        for weights, samples in zip(self.actors, actor_samples):
            self._update_actor(weights, samples, random_source)
        for weights, samples in zip(self.critics, critic_samples):
            for _ in range(3):
                random_source.shuffle(samples)
                for features, target in samples:
                    error = target - sum(map(mul, weights, features))
                    for index, feature in enumerate(features):
                        weights[index] += 0.005 * error * feature / len(weights)

    def _update_actor(self, weights, samples, random_source):
        mean = sum(sample[-1] for sample in samples) / len(samples)
        deviation = (sum((sample[-1] - mean)**2 for sample in samples) / len(samples) + 1e-8)**0.5
        for _ in range(3):
            random_source.shuffle(samples)
            for observation, action, old_probability, raw_advantage in samples:
                probabilities = self.probabilities(weights, observation)
                advantage = (raw_advantage - mean) / deviation
                ratio = probabilities[action] / old_probability
                if (advantage > 0 and ratio > 1.2) or (advantage < 0 and ratio < 0.8):
                    continue
                for index, features in enumerate(zip(*observation.action_features)):
                    gradient = features[action] - sum(map(mul, probabilities, features))
                    weights[index] += 0.002 * ratio * advantage * gradient


class ExploreThenCommit(Agent):
    def __init__(self, routes, episodes, horizon):
        self.routes = routes
        self.horizon = horizon
        self.exploration_episodes = len(routes) * max(1, episodes // (4 * len(routes)))
        self.counts = [0] * len(routes)
        self.totals = [0.0] * len(routes)
        self.training_route = 0

    def _best_route(self):
        tried = [index for index, count in enumerate(self.counts) if count]
        return max(tried, key=lambda index: self.totals[index] / self.counts[index], default=0)

    def start_episode(self, episode, learn):
        if learn:
            if episode <= self.exploration_episodes:
                self.training_route = (episode - 1) % len(self.routes)
            else:
                self.training_route = self._best_route()

    def select(self, state, epsilon, random_source, learn):
        route = self.training_route if learn else self._best_route()
        return self.routes[route][self.horizon - state[2]]

    def finish_episode(self, reward):
        if sum(self.counts) < self.exploration_episodes:
            self.counts[self.training_route] += 1
            self.totals[self.training_route] += reward
