# Author: Claude Opus 4.6
# Date: 2026-03-16 16:00
# PURPOSE: Chess960 (Fischer Random) engine for arena autoresearch.
#   Full legal move generation, check/checkmate/stalemate detection,
#   en passant, pawn promotion, 50-move rule. No castling (v1).
#   Board: 8x8 int array. Positive = white, negative = black.
#   1=Pawn, 2=Knight, 3=Bishop, 4=Rook, 5=Queen, 6=King.
#   Row 0 = rank 8 (black back rank), Row 7 = rank 1 (white back rank).
# SRP/DRY check: Pass — no existing chess engine in codebase

from typing import List, Dict, Optional, Tuple

# ═══════════════════════════════════════════════════════════════════════════
#   Constants
# ═══════════════════════════════════════════════════════════════════════════

EMPTY = 0
PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = 1, 2, 3, 4, 5, 6

PIECE_VALUES = {PAWN: 1, KNIGHT: 3, BISHOP: 3, ROOK: 5, QUEEN: 9, KING: 0}
PIECE_NAMES = {PAWN: 'P', KNIGHT: 'N', BISHOP: 'B', ROOK: 'R', QUEEN: 'Q', KING: 'K'}
PROMO_CHARS = {QUEEN: 'q', ROOK: 'r', BISHOP: 'b', KNIGHT: 'n'}
CHAR_TO_PROMO = {'q': QUEEN, 'r': ROOK, 'b': BISHOP, 'n': KNIGHT}

KNIGHT_DIRS = [(-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)]
BISHOP_DIRS = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
ROOK_DIRS = [(-1, 0), (1, 0), (0, -1), (0, 1)]
QUEEN_DIRS = BISHOP_DIRS + ROOK_DIRS
KING_DIRS = QUEEN_DIRS

FILES = 'abcdefgh'

# Knight placement table: 10 ways to place 2 knights in 5 remaining squares
_KNIGHT_COMBOS = [
    (0, 1), (0, 2), (0, 3), (0, 4), (1, 2),
    (1, 3), (1, 4), (2, 3), (2, 4), (3, 4),
]


# ═══════════════════════════════════════════════════════════════════════════
#   Coordinate helpers
# ═══════════════════════════════════════════════════════════════════════════

def _sq_to_alg(row: int, col: int) -> str:
    """Convert (row, col) to algebraic notation like 'e2'."""
    return FILES[col] + str(8 - row)


def _alg_to_sq(s: str) -> Tuple[int, int]:
    """Convert algebraic notation like 'e2' to (row, col)."""
    return (8 - int(s[1]), FILES.index(s[0]))


# ═══════════════════════════════════════════════════════════════════════════
#   Fischer Random position generation (960 positions)
# ═══════════════════════════════════════════════════════════════════════════

def _generate_fischer_random(position_id: int) -> List[int]:
    """Generate a back-rank piece arrangement from position number 0-959.

    Uses the Scharnagl numbering system:
    1. Light-square bishop (4 choices: cols 1,3,5,7)
    2. Dark-square bishop  (4 choices: cols 0,2,4,6)
    3. Queen on one of 6 remaining squares
    4. Two knights on 2 of 5 remaining squares (10 combos)
    5. Remaining 3 squares: Rook, King, Rook (king always between rooks)

    Position 518 = standard chess: RNBQKBNR
    """
    n = position_id % 960
    rank = [EMPTY] * 8

    # Light-square bishop
    b1 = n % 4
    n //= 4
    rank[1 + b1 * 2] = BISHOP

    # Dark-square bishop
    b2 = n % 4
    n //= 4
    rank[b2 * 2] = BISHOP

    # Queen on one of 6 remaining empty squares
    empty = [i for i in range(8) if rank[i] == EMPTY]
    q_idx = n % 6
    n //= 6
    rank[empty[q_idx]] = QUEEN

    # Two knights on 2 of 5 remaining empty squares
    empty = [i for i in range(8) if rank[i] == EMPTY]
    k1, k2 = _KNIGHT_COMBOS[n]
    rank[empty[k1]] = KNIGHT
    rank[empty[k2]] = KNIGHT

    # Remaining 3 squares: R, K, R (left to right ensures king between rooks)
    empty = [i for i in range(8) if rank[i] == EMPTY]
    rank[empty[0]] = ROOK
    rank[empty[1]] = KING
    rank[empty[2]] = ROOK

    return rank


# ═══════════════════════════════════════════════════════════════════════════
#   Chess960Game
# ═══════════════════════════════════════════════════════════════════════════

class Chess960Game:
    """Full Chess960 game engine. Supports everything except castling (v1)."""

    def __init__(self, position_id: int = 518, max_turns: int = 400):
        self.position_id = position_id
        self.max_turns = max_turns  # half-moves (200 full moves)
        self.board: List[List[int]] = []
        self.white_to_move: bool = True
        self.en_passant: Optional[Tuple[int, int]] = None
        self.halfmove_clock: int = 0
        self.turn: int = 0
        self.game_over: bool = False
        self.winner: Optional[str] = None  # 'white', 'black', 'draw'
        self.result_reason: Optional[str] = None
        self.captured: Dict[str, List[int]] = {'white': [], 'black': []}
        self.history: List[Dict] = []
        self.last_move: Optional[str] = None
        self.prev_moves: List[List] = [[], []]  # [white_memory, black_memory]

    def setup(self):
        """Initialize board with Fischer Random position."""
        self.board = [[EMPTY] * 8 for _ in range(8)]
        self.white_to_move = True
        self.en_passant = None
        self.halfmove_clock = 0
        self.turn = 0
        self.game_over = False
        self.winner = None
        self.result_reason = None
        self.captured = {'white': [], 'black': []}
        self.history = []
        self.last_move = None
        self.prev_moves = [[], []]

        # Pawns
        for col in range(8):
            self.board[1][col] = -PAWN   # black pawns rank 7
            self.board[6][col] = PAWN    # white pawns rank 2

        # Back rank pieces (same arrangement for both sides)
        back_rank = _generate_fischer_random(self.position_id)
        for col in range(8):
            self.board[7][col] = back_rank[col]      # white rank 1
            self.board[0][col] = -back_rank[col]     # black rank 8

    # ───────────────────────────────────────────────────────────────────
    #   Attack detection
    # ───────────────────────────────────────────────────────────────────

    def _is_square_attacked(self, row: int, col: int, by_color: str) -> bool:
        """Check if (row, col) is attacked by any piece of by_color."""
        sign = 1 if by_color == 'white' else -1

        # Knight
        for dr, dc in KNIGHT_DIRS:
            r, c = row + dr, col + dc
            if 0 <= r < 8 and 0 <= c < 8 and self.board[r][c] == sign * KNIGHT:
                return True

        # Pawn
        if by_color == 'white':
            for dc in (-1, 1):
                r, c = row + 1, col + dc
                if 0 <= r < 8 and 0 <= c < 8 and self.board[r][c] == PAWN:
                    return True
        else:
            for dc in (-1, 1):
                r, c = row - 1, col + dc
                if 0 <= r < 8 and 0 <= c < 8 and self.board[r][c] == -PAWN:
                    return True

        # King
        for dr, dc in KING_DIRS:
            r, c = row + dr, col + dc
            if 0 <= r < 8 and 0 <= c < 8 and self.board[r][c] == sign * KING:
                return True

        # Bishop / Queen (diagonals)
        for dr, dc in BISHOP_DIRS:
            r, c = row + dr, col + dc
            while 0 <= r < 8 and 0 <= c < 8:
                piece = self.board[r][c]
                if piece != EMPTY:
                    if piece == sign * BISHOP or piece == sign * QUEEN:
                        return True
                    break
                r, c = r + dr, c + dc

        # Rook / Queen (straights)
        for dr, dc in ROOK_DIRS:
            r, c = row + dr, col + dc
            while 0 <= r < 8 and 0 <= c < 8:
                piece = self.board[r][c]
                if piece != EMPTY:
                    if piece == sign * ROOK or piece == sign * QUEEN:
                        return True
                    break
                r, c = r + dr, c + dc

        return False

    def _is_in_check(self, color: str) -> bool:
        """Check if color's king is in check."""
        sign = 1 if color == 'white' else -1
        for r in range(8):
            for c in range(8):
                if self.board[r][c] == sign * KING:
                    opponent = 'black' if color == 'white' else 'white'
                    return self._is_square_attacked(r, c, opponent)
        return False

    # ───────────────────────────────────────────────────────────────────
    #   Pseudo-legal move generation
    # ───────────────────────────────────────────────────────────────────

    def _is_own(self, piece: int) -> bool:
        if self.white_to_move:
            return piece > 0
        return piece < 0

    def _is_enemy(self, piece: int) -> bool:
        if piece == EMPTY:
            return False
        if self.white_to_move:
            return piece < 0
        return piece > 0

    def _gen_pawn_moves(self, moves: list):
        if self.white_to_move:
            sign, direction, start_row, promo_row = 1, -1, 6, 0
        else:
            sign, direction, start_row, promo_row = -1, 1, 1, 7

        for row in range(8):
            for col in range(8):
                if self.board[row][col] != sign * PAWN:
                    continue

                nr = row + direction

                # Forward 1
                if 0 <= nr < 8 and self.board[nr][col] == EMPTY:
                    if nr == promo_row:
                        for promo in (QUEEN, ROOK, BISHOP, KNIGHT):
                            moves.append((row, col, nr, col, promo))
                    else:
                        moves.append((row, col, nr, col, 0))

                        # Forward 2 from start row
                        nr2 = row + 2 * direction
                        if row == start_row and self.board[nr2][col] == EMPTY:
                            moves.append((row, col, nr2, col, 0))

                # Diagonal captures + en passant
                for dc in (-1, 1):
                    nc = col + dc
                    if not (0 <= nc < 8 and 0 <= nr < 8):
                        continue

                    target = self.board[nr][nc]
                    is_capture = self._is_enemy(target)
                    is_ep = self.en_passant is not None and (nr, nc) == self.en_passant

                    if is_capture or is_ep:
                        if nr == promo_row:
                            for promo in (QUEEN, ROOK, BISHOP, KNIGHT):
                                moves.append((row, col, nr, nc, promo))
                        else:
                            moves.append((row, col, nr, nc, 0))

    def _gen_knight_moves(self, moves: list):
        sign = 1 if self.white_to_move else -1
        for row in range(8):
            for col in range(8):
                if self.board[row][col] != sign * KNIGHT:
                    continue
                for dr, dc in KNIGHT_DIRS:
                    nr, nc = row + dr, col + dc
                    if 0 <= nr < 8 and 0 <= nc < 8:
                        target = self.board[nr][nc]
                        if target == EMPTY or self._is_enemy(target):
                            moves.append((row, col, nr, nc, 0))

    def _gen_sliding_moves(self, moves: list, piece_type: int, directions: list):
        sign = 1 if self.white_to_move else -1
        for row in range(8):
            for col in range(8):
                if self.board[row][col] != sign * piece_type:
                    continue
                for dr, dc in directions:
                    nr, nc = row + dr, col + dc
                    while 0 <= nr < 8 and 0 <= nc < 8:
                        target = self.board[nr][nc]
                        if target == EMPTY:
                            moves.append((row, col, nr, nc, 0))
                        elif self._is_enemy(target):
                            moves.append((row, col, nr, nc, 0))
                            break
                        else:
                            break  # own piece
                        nr, nc = nr + dr, nc + dc

    def _gen_king_moves(self, moves: list):
        sign = 1 if self.white_to_move else -1
        for row in range(8):
            for col in range(8):
                if self.board[row][col] != sign * KING:
                    continue
                for dr, dc in KING_DIRS:
                    nr, nc = row + dr, col + dc
                    if 0 <= nr < 8 and 0 <= nc < 8:
                        target = self.board[nr][nc]
                        if target == EMPTY or self._is_enemy(target):
                            moves.append((row, col, nr, nc, 0))
                return  # only one king

    def _gen_pseudo_legal(self) -> List[tuple]:
        moves = []
        self._gen_pawn_moves(moves)
        self._gen_knight_moves(moves)
        self._gen_sliding_moves(moves, BISHOP, BISHOP_DIRS)
        self._gen_sliding_moves(moves, ROOK, ROOK_DIRS)
        self._gen_sliding_moves(moves, QUEEN, QUEEN_DIRS)
        self._gen_king_moves(moves)
        return moves

    # ───────────────────────────────────────────────────────────────────
    #   Legal move generation (filters out moves leaving king in check)
    # ───────────────────────────────────────────────────────────────────

    def _apply_move_raw(self, move: tuple):
        """Apply move to board in-place. For legality testing only."""
        fr, fc, tr, tc, promo = move
        piece = self.board[fr][fc]

        # En passant capture — remove the captured pawn
        if abs(piece) == PAWN and self.en_passant and (tr, tc) == self.en_passant:
            if piece > 0:
                self.board[tr + 1][tc] = EMPTY
            else:
                self.board[tr - 1][tc] = EMPTY

        self.board[tr][tc] = piece
        self.board[fr][fc] = EMPTY

        if promo:
            sign = 1 if piece > 0 else -1
            self.board[tr][tc] = sign * promo

    def gen_legal_moves(self) -> List[tuple]:
        """Generate all legal moves for the side to move."""
        color = 'white' if self.white_to_move else 'black'
        pseudo = self._gen_pseudo_legal()
        legal = []

        for move in pseudo:
            saved_board = [row[:] for row in self.board]
            saved_ep = self.en_passant

            self._apply_move_raw(move)
            if not self._is_in_check(color):
                legal.append(move)

            self.board = saved_board
            self.en_passant = saved_ep

        return legal

    def get_legal_move_strings(self) -> List[str]:
        """Get all legal moves as algebraic strings."""
        return [self._move_to_str(m) for m in self.gen_legal_moves()]

    # ───────────────────────────────────────────────────────────────────
    #   Move formatting
    # ───────────────────────────────────────────────────────────────────

    def _move_to_str(self, move: tuple) -> str:
        fr, fc, tr, tc, promo = move
        s = _sq_to_alg(fr, fc) + _sq_to_alg(tr, tc)
        if promo:
            s += PROMO_CHARS[promo]
        return s

    def _parse_move(self, move_str: str) -> Optional[tuple]:
        if len(move_str) < 4:
            return None
        try:
            fr, fc = _alg_to_sq(move_str[0:2])
            tr, tc = _alg_to_sq(move_str[2:4])
            promo = 0
            if len(move_str) == 5:
                promo = CHAR_TO_PROMO.get(move_str[4].lower(), 0)
            return (fr, fc, tr, tc, promo)
        except (ValueError, IndexError):
            return None

    # ───────────────────────────────────────────────────────────────────
    #   State accessors
    # ───────────────────────────────────────────────────────────────────

    def _material_score(self, color: str) -> int:
        sign = 1 if color == 'white' else -1
        total = 0
        for row in self.board:
            for piece in row:
                if piece != EMPTY and (piece > 0) == (sign > 0):
                    total += PIECE_VALUES[abs(piece)]
        return total

    def get_state(self, color: str) -> Dict:
        """Get state dict for an agent to make a move."""
        player_idx = 0 if color == 'white' else 1
        is_my_turn = (color == 'white') == self.white_to_move
        legal_strs = self.get_legal_move_strings() if is_my_turn else []

        return {
            'board': [row[:] for row in self.board],
            'my_color': color,
            'legal_moves': legal_strs,
            'opponent_last_move': self.last_move,
            'turn': self.turn,
            'halfmove_clock': self.halfmove_clock,
            'captured': {k: list(v) for k, v in self.captured.items()},
            'king_in_check': self._is_in_check(color),
            'prev_moves': self.prev_moves[player_idx],
        }

    def get_full_state(self) -> Dict:
        """Get full state for history/replay."""
        return {
            'turn': self.turn,
            'board': [row[:] for row in self.board],
            'last_move': self.last_move,
            'white_to_move': self.white_to_move,
            'scores': [self._material_score('white'), self._material_score('black')],
            'in_check': [self._is_in_check('white'), self._is_in_check('black')],
            'game_over': self.game_over,
            'winner': self.winner,
        }

    # ───────────────────────────────────────────────────────────────────
    #   Game execution
    # ───────────────────────────────────────────────────────────────────

    def step(self, move_str: str) -> bool:
        """Execute a move. Returns True if game continues."""
        if self.game_over:
            return False

        self.history.append(self.get_full_state())

        move = self._parse_move(move_str)
        if not move:
            self.game_over = True
            self.winner = 'black' if self.white_to_move else 'white'
            self.result_reason = 'invalid_move'
            self.history.append(self.get_full_state())
            return False

        fr, fc, tr, tc, promo = move
        piece = self.board[fr][fc]
        captured_piece = self.board[tr][tc]

        # En passant capture
        is_ep = (abs(piece) == PAWN and self.en_passant
                 and (tr, tc) == self.en_passant and captured_piece == EMPTY)
        if is_ep:
            capturer = 'white' if self.white_to_move else 'black'
            self.captured[capturer].append(PAWN)
            if piece > 0:
                self.board[tr + 1][tc] = EMPTY
            else:
                self.board[tr - 1][tc] = EMPTY
            self.halfmove_clock = 0
        elif captured_piece != EMPTY:
            capturer = 'white' if self.white_to_move else 'black'
            self.captured[capturer].append(abs(captured_piece))
            self.halfmove_clock = 0
        elif abs(piece) == PAWN:
            self.halfmove_clock = 0
        else:
            self.halfmove_clock += 1

        # Update en passant target
        if abs(piece) == PAWN and abs(tr - fr) == 2:
            self.en_passant = ((fr + tr) // 2, fc)
        else:
            self.en_passant = None

        # Execute move
        self.board[tr][tc] = piece
        self.board[fr][fc] = EMPTY

        # Promotion
        if promo:
            sign = 1 if piece > 0 else -1
            self.board[tr][tc] = sign * promo

        self.last_move = move_str
        self.turn += 1
        self.white_to_move = not self.white_to_move

        # Check game-end conditions
        opponent_legal = self.gen_legal_moves()
        if not opponent_legal:
            self.game_over = True
            current = 'white' if self.white_to_move else 'black'
            other = 'black' if self.white_to_move else 'white'
            if self._is_in_check(current):
                self.winner = other
                self.result_reason = 'checkmate'
            else:
                self.winner = 'draw'
                self.result_reason = 'stalemate'
        elif self.halfmove_clock >= 100:  # 50 full moves without capture/pawn move
            self.game_over = True
            self.winner = 'draw'
            self.result_reason = '50-move'
        elif self.turn >= self.max_turns:
            self.game_over = True
            self.winner = 'draw'
            self.result_reason = 'max-turns'

        if self.game_over:
            self.history.append(self.get_full_state())

        return not self.game_over

    def run(self, white_fn, black_fn) -> Dict:
        """Run a complete game between two agent functions.
        Each agent receives get_state(color) and returns a move string.
        Returns {winner: 0/1/None, turns, scores, history, result_reason}."""
        self.setup()
        agents = [white_fn, black_fn]

        while not self.game_over:
            color = 'white' if self.white_to_move else 'black'
            idx = 0 if self.white_to_move else 1
            state = self.get_state(color)

            if not state['legal_moves']:
                break  # game should already be over from previous step

            try:
                move = agents[idx](state)
                if not isinstance(move, str) or move not in state['legal_moves']:
                    self.game_over = True
                    self.winner = 'black' if color == 'white' else 'white'
                    self.result_reason = 'illegal_move'
                    self.history.append(self.get_full_state())
                    break
            except Exception:
                self.game_over = True
                self.winner = 'black' if color == 'white' else 'white'
                self.result_reason = 'crash'
                self.history.append(self.get_full_state())
                break

            self.step(move)

        winner_idx = None
        if self.winner == 'white':
            winner_idx = 0
        elif self.winner == 'black':
            winner_idx = 1

        return {
            'winner': winner_idx,
            'turns': self.turn,
            'scores': [self._material_score('white'), self._material_score('black')],
            'history': self.history,
            'result_reason': self.result_reason,
        }
