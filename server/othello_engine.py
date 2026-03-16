# Author: Claude Opus 4.6
# Date: 2026-03-16 20:00
# PURPOSE: Othello (Reversi) engine for arena autoresearch.
#   8x8 board, standard rules: place to flip, pass if no moves, game ends when
#   both pass or board full. 1=black (first), -1=white. No RNG needed.
# SRP/DRY check: Pass — no existing Othello engine in codebase

from typing import List, Dict, Optional, Tuple

EMPTY = 0
BLACK = 1   # goes first
WHITE = -1

DIRECTIONS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


class OthelloGame:
    """Full Othello engine for 2-player arena matches."""

    def __init__(self, max_turns: int = 128):
        self.board: List[List[int]] = []
        self.turn: int = BLACK  # 1=black goes first
        self.ply: int = 0
        self.max_turns: int = max_turns
        self.game_over: bool = False
        self.winner: Optional[str] = None  # 'black', 'white', 'draw'
        self.result_reason: Optional[str] = None
        self.last_move: Optional[List[int]] = None
        self.consecutive_passes: int = 0
        self.history: List[Dict] = []
        self.prev_moves: List[List] = [[], []]  # [black_memory, white_memory]

    def setup(self):
        """Initialize board with standard Othello starting position."""
        self.board = [[EMPTY] * 8 for _ in range(8)]
        self.board[3][3] = WHITE
        self.board[3][4] = BLACK
        self.board[4][3] = BLACK
        self.board[4][4] = WHITE
        self.turn = BLACK
        self.ply = 0
        self.game_over = False
        self.winner = None
        self.result_reason = None
        self.last_move = None
        self.consecutive_passes = 0
        self.history = []
        self.prev_moves = [[], []]

    def _get_flips(self, row: int, col: int, color: int) -> List[Tuple[int, int]]:
        """Get all pieces that would be flipped by placing color at (row, col)."""
        if self.board[row][col] != EMPTY:
            return []
        flips = []
        opp = -color
        for dr, dc in DIRECTIONS:
            r, c = row + dr, col + dc
            line = []
            while 0 <= r < 8 and 0 <= c < 8 and self.board[r][c] == opp:
                line.append((r, c))
                r, c = r + dr, c + dc
            if line and 0 <= r < 8 and 0 <= c < 8 and self.board[r][c] == color:
                flips.extend(line)
        return flips

    def get_legal_moves(self, color: Optional[int] = None) -> List[List[int]]:
        """Get all legal moves for the given color (default: current turn)."""
        if color is None:
            color = self.turn
        moves = []
        for r in range(8):
            for c in range(8):
                if self._get_flips(r, c, color):
                    moves.append([r, c])
        return moves

    def count_pieces(self) -> Dict[str, int]:
        """Count pieces on the board."""
        black = sum(1 for r in self.board for p in r if p == BLACK)
        white = sum(1 for r in self.board for p in r if p == WHITE)
        return {'black': black, 'white': white, 'empty': 64 - black - white}

    def _material_score(self, color: str) -> int:
        counts = self.count_pieces()
        return counts.get(color, 0)

    def get_state(self, color: int) -> Dict:
        """Get state dict for an agent to make a move."""
        player_idx = 0 if color == BLACK else 1
        is_my_turn = color == self.turn
        legal = self.get_legal_moves(color) if is_my_turn else []

        return {
            'board': [row[:] for row in self.board],
            'my_color': color,
            'legal_moves': legal,
            'opponent_last_move': self.last_move,
            'turn': self.ply,
            'scores': self.count_pieces(),
            'prev_moves': self.prev_moves[player_idx],
        }

    def get_full_state(self) -> Dict:
        """Get full state for history/replay."""
        counts = self.count_pieces()
        return {
            'turn': self.ply,
            'board': [row[:] for row in self.board],
            'last_move': self.last_move,
            'current_player': self.turn,
            'scores': [counts['black'], counts['white']],
            'game_over': self.game_over,
            'winner': self.winner,
        }

    def step(self, move) -> bool:
        """Execute a move ([row, col] or None for pass). Returns True if game continues."""
        if self.game_over:
            return False

        self.history.append(self.get_full_state())

        if move is None:
            # Pass
            self.consecutive_passes += 1
            self.last_move = None
        else:
            row, col = move[0], move[1]
            flips = self._get_flips(row, col, self.turn)
            if not flips:
                # Illegal move = forfeit
                self.game_over = True
                self.winner = 'white' if self.turn == BLACK else 'black'
                self.result_reason = 'illegal_move'
                self.history.append(self.get_full_state())
                return False

            self.board[row][col] = self.turn
            for fr, fc in flips:
                self.board[fr][fc] = self.turn
            self.consecutive_passes = 0
            self.last_move = [row, col]

        self.ply += 1
        self.turn = -self.turn

        # Check game-end conditions
        if self.consecutive_passes >= 2:
            self._end_by_score('both_pass')
        elif self.ply >= self.max_turns:
            self._end_by_score('max-turns')
        else:
            # Check if board is full
            counts = self.count_pieces()
            if counts['empty'] == 0:
                self._end_by_score('board_full')

        if self.game_over:
            self.history.append(self.get_full_state())

        return not self.game_over

    def _end_by_score(self, reason: str):
        """End game and determine winner by piece count."""
        self.game_over = True
        self.result_reason = reason
        counts = self.count_pieces()
        if counts['black'] > counts['white']:
            self.winner = 'black'
        elif counts['white'] > counts['black']:
            self.winner = 'white'
        else:
            self.winner = 'draw'

    def run(self, black_fn, white_fn) -> Dict:
        """Run a complete game. Each agent receives get_state(color) and returns
        [row, col] or None to pass. Returns {winner, turns, scores, history}."""
        self.setup()
        agents = {BLACK: black_fn, WHITE: white_fn}

        while not self.game_over:
            color = self.turn
            state = self.get_state(color)
            legal = state['legal_moves']

            if not legal:
                # Must pass
                self.step(None)
                continue

            try:
                move = agents[color](state)
                if move is None or not isinstance(move, (list, tuple)) or len(move) != 2:
                    # Invalid return = forfeit
                    self.game_over = True
                    self.winner = 'white' if color == BLACK else 'black'
                    self.result_reason = 'invalid_move'
                    self.history.append(self.get_full_state())
                    break
                move_list = [int(move[0]), int(move[1])]
                if move_list not in legal:
                    self.game_over = True
                    self.winner = 'white' if color == BLACK else 'black'
                    self.result_reason = 'illegal_move'
                    self.history.append(self.get_full_state())
                    break
            except Exception:
                self.game_over = True
                self.winner = 'white' if color == BLACK else 'black'
                self.result_reason = 'crash'
                self.history.append(self.get_full_state())
                break

            self.step(move_list)

        winner_idx = None
        if self.winner == 'black':
            winner_idx = 0
        elif self.winner == 'white':
            winner_idx = 1

        counts = self.count_pieces()
        return {
            'winner': winner_idx,
            'turns': self.ply,
            'scores': [counts['black'], counts['white']],
            'history': self.history,
            'result_reason': self.result_reason,
        }
