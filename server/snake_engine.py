# Author: Claude Opus 4.6
# Date: 2026-03-16 23:30
# PURPOSE: Core snake game engines for Arena. 2-player SnakeGame + 4-player SnakeGame4P
#   (Battle Royale & 2v2 Teams). Used by server heartbeat and batch runner.
# SRP/DRY check: Pass — game engine logic only, no DB or API calls
"""Core snake game engines for 2-player and 4-player competitive snake."""

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
    def __init__(self, width=20, height=20, max_turns=350, food_count=8):
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
            # Both dead (head-on or simultaneous crash) — longer snake wins
            self.game_over = True
            self.winner = self._winner_by_length()
        elif not alive[0]:
            self.game_over = True
            self.winner = 1
        elif not alive[1]:
            self.game_over = True
            self.winner = 0
        elif self.turn >= self.max_turns:
            # Time's up — longer snake wins
            self.game_over = True
            self.winner = self._winner_by_length()

        if self.game_over:
            self.history.append(self.get_full_state())

        return not self.game_over

    def _winner_by_length(self) -> Optional[int]:
        """Determine winner by snake length (apples eaten). None if tied."""
        l0, l1 = len(self.snakes[0].body), len(self.snakes[1].body)
        if l0 > l1: return 0
        elif l1 > l0: return 1
        return None

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


class SnakeGame4P:
    """4-player snake for Battle Royale and 2v2 Teams."""

    # Teams for 2v2: (0,2) vs (1,3)
    TEAMS = {0: 0, 2: 0, 1: 1, 3: 1}

    def __init__(self, width=30, height=30, max_turns=400, food_count=12, mode='royale'):
        self.width = width
        self.height = height
        self.max_turns = max_turns
        self.food_count = food_count
        self.mode = mode  # 'royale' or '2v2'
        self.turn = 0
        self.food: List[Tuple[int, int]] = []
        self.snakes: List[Snake] = []
        self.history: List[Dict] = []
        self.game_over = False
        self.winner = None  # int (player index), 'team0', 'team1', or None (draw)
        self.prev_moves: List[List] = [[], [], [], []]

    def setup(self):
        w, h = self.width, self.height
        self.snakes = [
            Snake([(4, 4), (3, 4), (2, 4)], 'RIGHT'),       # A: top-left
            Snake([(w - 5, 4), (w - 4, 4), (w - 3, 4)], 'LEFT'),  # B: top-right
            Snake([(4, h - 5), (3, h - 5), (2, h - 5)], 'RIGHT'),  # C: bottom-left
            Snake([(w - 5, h - 5), (w - 4, h - 5), (w - 3, h - 5)], 'LEFT'),  # D: bottom-right
        ]
        for _ in range(self.food_count):
            self._spawn_food()

    def _occupied(self):
        cells = set()
        for s in self.snakes:
            if s.alive:
                cells.update(s.body)
        cells.update(self.food)
        return cells

    def _spawn_food(self):
        occupied = self._occupied()
        free = [(x, y) for x in range(self.width) for y in range(self.height)
                if (x, y) not in occupied]
        if free:
            self.food.append(random.choice(free))

    def _are_allies(self, i, j):
        """Check if snakes i and j are allies (2v2 mode only)."""
        if self.mode != '2v2':
            return False
        return self.TEAMS[i] == self.TEAMS[j]

    def get_state(self, player_idx: int) -> Dict:
        me = self.snakes[player_idx]
        state = {
            'grid_size': (self.width, self.height),
            'my_snake': [list(p) for p in me.body],
            'my_direction': me.direction,
            'my_index': player_idx,
            'snakes': [],
            'food': [list(p) for p in self.food],
            'turn': self.turn,
            'prev_moves': self.prev_moves[player_idx],
        }
        for i, s in enumerate(self.snakes):
            state['snakes'].append({
                'body': [list(p) for p in s.body] if s.alive else [],
                'direction': s.direction if s.alive else None,
                'alive': s.alive,
                'is_ally': self._are_allies(player_idx, i),
            })
        if self.mode == '2v2':
            ally_idx = 2 if player_idx == 0 else (3 if player_idx == 1 else (0 if player_idx == 2 else 1))
            ally = self.snakes[ally_idx]
            state['ally_snake'] = [list(p) for p in ally.body] if ally.alive else []
            state['ally_direction'] = ally.direction if ally.alive else None
            enemies = [s for i, s in enumerate(self.snakes)
                       if not self._are_allies(player_idx, i) and i != player_idx]
            state['enemies'] = [{
                'body': [list(p) for p in e.body] if e.alive else [],
                'direction': e.direction if e.alive else None,
                'alive': e.alive,
            } for e in enemies]
        return state

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
            if not self.snakes[i].alive:
                valid_moves.append('UP')
            elif move not in DIRECTIONS:
                valid_moves.append(self.snakes[i].direction)
            else:
                valid_moves.append(move)

        for i, snake in enumerate(self.snakes):
            if snake.alive:
                snake.move(valid_moves[i])

        # Check collisions
        deaths = [False] * 4
        for i, snake in enumerate(self.snakes):
            if not snake.alive:
                continue
            hx, hy = snake.head
            # Wall collision
            if hx < 0 or hx >= self.width or hy < 0 or hy >= self.height:
                deaths[i] = True
                continue
            # Self collision
            if snake.head in set(snake.body[1:]):
                deaths[i] = True
                continue
            # Body collision with other snakes
            for j, other in enumerate(self.snakes):
                if i == j or not other.alive:
                    continue
                # 2v2: allies pass through each other
                if self._are_allies(i, j):
                    continue
                if snake.head in set(other.body[1:]):
                    deaths[i] = True
                    break

        # Head-on collisions
        for i in range(4):
            if not self.snakes[i].alive or deaths[i]:
                continue
            for j in range(i + 1, 4):
                if not self.snakes[j].alive or deaths[j]:
                    continue
                if self.snakes[i].head == self.snakes[j].head:
                    # 2v2: allies pass through on head-on
                    if self._are_allies(i, j):
                        continue
                    deaths[i] = True
                    deaths[j] = True

        for i, dead in enumerate(deaths):
            if dead:
                self.snakes[i].alive = False

        # Food consumption
        for snake in self.snakes:
            if snake.alive and snake.head in self.food:
                self.food.remove(snake.head)
                snake.grow()
                self._spawn_food()

        self.turn += 1

        # Check game over
        alive = [s.alive for s in self.snakes]
        alive_count = sum(alive)

        if self.mode == 'royale':
            if alive_count <= 1:
                self.game_over = True
                alive_indices = [i for i, a in enumerate(alive) if a]
                if alive_indices:
                    self.winner = alive_indices[0]
                else:
                    self.winner = self._winner_by_length_4p()
            elif self.turn >= self.max_turns:
                self.game_over = True
                self.winner = self._winner_by_length_4p()
        else:  # 2v2
            team0_alive = any(alive[i] for i in (0, 2))
            team1_alive = any(alive[i] for i in (1, 3))
            if not team0_alive and not team1_alive:
                self.game_over = True
                self.winner = self._winner_team_by_length()
            elif not team0_alive:
                self.game_over = True
                self.winner = 'team1'
            elif not team1_alive:
                self.game_over = True
                self.winner = 'team0'
            elif self.turn >= self.max_turns:
                self.game_over = True
                self.winner = self._winner_team_by_length()

        if self.game_over:
            self.history.append(self.get_full_state())

        return not self.game_over

    def _winner_by_length_4p(self):
        """Longest snake wins in royale. Returns player index or None if tied."""
        lengths = [(len(s.body), i) for i, s in enumerate(self.snakes)]
        lengths.sort(reverse=True)
        if lengths[0][0] > lengths[1][0]:
            return lengths[0][1]
        return None  # draw

    def _winner_team_by_length(self):
        """Team with more total length wins. Returns 'team0', 'team1', or None."""
        team0_len = sum(len(self.snakes[i].body) for i in (0, 2))
        team1_len = sum(len(self.snakes[i].body) for i in (1, 3))
        if team0_len > team1_len:
            return 'team0'
        elif team1_len > team0_len:
            return 'team1'
        return None

    def run(self, agent_fns: list) -> Dict:
        """Run a 4-player game. agent_fns is a list of 4 callables."""
        self.setup()
        while not self.game_over:
            moves = []
            for i, fn in enumerate(agent_fns):
                if self.snakes[i].alive:
                    state = self.get_state(i)
                    try:
                        move = fn(state)
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
