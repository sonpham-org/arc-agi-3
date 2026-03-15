"""Core snake game engine for 2-player competitive snake."""

import random
from typing import List, Tuple, Dict, Optional

DIRECTIONS = {
    'UP': (0, -1),
    'DOWN': (0, 1),
    'LEFT': (-1, 0),
    'RIGHT': (1, 0),
}

OPPOSITE = {'UP': 'DOWN', 'DOWN': 'UP', 'LEFT': 'RIGHT', 'RIGHT': 'LEFT'}


class Snake:
    def __init__(self, body: List[Tuple[int, int]], direction: str = 'RIGHT'):
        self.body = list(body)
        self.direction = direction
        self.alive = True
        self.grow_pending = 0

    @property
    def head(self):
        return self.body[0]

    def move(self, direction: str):
        if len(self.body) > 1 and OPPOSITE.get(direction) == self.direction:
            direction = self.direction
        self.direction = direction
        dx, dy = DIRECTIONS[direction]
        new_head = (self.body[0][0] + dx, self.body[0][1] + dy)
        self.body.insert(0, new_head)
        if self.grow_pending > 0:
            self.grow_pending -= 1
        else:
            self.body.pop()

    def grow(self, amount=1):
        self.grow_pending += amount


class SnakeGame:
    def __init__(self, width=20, height=20, max_turns=500, food_count=3):
        self.width = width
        self.height = height
        self.max_turns = max_turns
        self.food_count = food_count
        self.turn = 0
        self.food: List[Tuple[int, int]] = []
        self.snakes: List[Snake] = []
        self.history: List[Dict] = []
        self.game_over = False
        self.winner: Optional[int] = None
        self.prev_moves: List[List] = [[], []]  # Per-agent persistent memory

    def setup(self):
        s1 = Snake([(3, 3), (2, 3), (1, 3)], 'RIGHT')
        s2 = Snake([(self.width - 4, self.height - 4),
                     (self.width - 3, self.height - 4),
                     (self.width - 2, self.height - 4)], 'LEFT')
        self.snakes = [s1, s2]
        for _ in range(self.food_count):
            self._spawn_food()

    def _occupied(self):
        cells = set()
        for s in self.snakes:
            cells.update(s.body)
        cells.update(self.food)
        return cells

    def _spawn_food(self):
        occupied = self._occupied()
        free = [(x, y) for x in range(self.width) for y in range(self.height)
                if (x, y) not in occupied]
        if free:
            self.food.append(random.choice(free))

    def get_state(self, player_idx: int) -> Dict:
        me = self.snakes[player_idx]
        enemy = self.snakes[1 - player_idx]
        return {
            'grid_size': (self.width, self.height),
            'my_snake': [list(p) for p in me.body],
            'my_direction': me.direction,
            'enemy_snake': [list(p) for p in enemy.body] if enemy.alive else [],
            'enemy_direction': enemy.direction if enemy.alive else None,
            'food': [list(p) for p in self.food],
            'turn': self.turn,
            'prev_moves': self.prev_moves[player_idx],  # Agent's persistent memory
        }

    def get_full_state(self) -> Dict:
        return {
            'turn': self.turn,
            'snakes': [[list(p) for p in s.body] for s in self.snakes],
            'alive': [s.alive for s in self.snakes],
            'food': [list(p) for p in self.food],
            'scores': [len(s.body) for s in self.snakes],
        }

    def step(self, moves: List[str]) -> bool:
        if self.game_over:
            return False

        self.history.append(self.get_full_state())

        valid_moves = []
        for i, move in enumerate(moves):
            if move not in DIRECTIONS:
                move = self.snakes[i].direction
            valid_moves.append(move)

        for i, snake in enumerate(self.snakes):
            if snake.alive:
                snake.move(valid_moves[i])

        # Check collisions
        deaths = [False, False]
        for i, snake in enumerate(self.snakes):
            if not snake.alive:
                continue
            hx, hy = snake.head
            if hx < 0 or hx >= self.width or hy < 0 or hy >= self.height:
                deaths[i] = True
                continue
            body_set = set(snake.body[1:])
            if snake.head in body_set:
                deaths[i] = True
                continue
            other = self.snakes[1 - i]
            if other.alive:
                other_body = set(other.body[1:])
                if snake.head in other_body:
                    deaths[i] = True

        # Head-on collision
        if (self.snakes[0].alive and self.snakes[1].alive
                and not deaths[0] and not deaths[1]
                and self.snakes[0].head == self.snakes[1].head):
            deaths[0] = True
            deaths[1] = True

        for i, dead in enumerate(deaths):
            if dead:
                self.snakes[i].alive = False

        # Food consumption (only alive snakes)
        for snake in self.snakes:
            if snake.alive and snake.head in self.food:
                self.food.remove(snake.head)
                snake.grow()
                self._spawn_food()

        self.turn += 1

        alive = [s.alive for s in self.snakes]
        if not alive[0] and not alive[1]:
            self.game_over = True
            self.winner = None
        elif not alive[0]:
            self.game_over = True
            self.winner = 1
        elif not alive[1]:
            self.game_over = True
            self.winner = 0
        elif self.turn >= self.max_turns:
            self.game_over = True
            l0, l1 = len(self.snakes[0].body), len(self.snakes[1].body)
            if l0 > l1:
                self.winner = 0
            elif l1 > l0:
                self.winner = 1
            else:
                self.winner = None

        if self.game_over:
            self.history.append(self.get_full_state())

        return not self.game_over

    def run(self, agent0_fn, agent1_fn) -> Dict:
        self.setup()
        agents = [agent0_fn, agent1_fn]

        while not self.game_over:
            moves = []
            for i, agent_fn in enumerate(agents):
                if self.snakes[i].alive:
                    state = self.get_state(i)
                    try:
                        move = agent_fn(state)
                        if move not in DIRECTIONS:
                            move = self.snakes[i].direction
                    except Exception:
                        move = self.snakes[i].direction
                else:
                    move = 'UP'
                moves.append(move)
            self.step(moves)

        return {
            'winner': self.winner,
            'turns': self.turn,
            'scores': [len(s.body) for s in self.snakes],
            'history': self.history,
        }
