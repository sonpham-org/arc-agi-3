// Author: Claude Opus 4.6
// Date: 2026-03-16 03:00
// PURPOSE: ARC Arena — Agent vs Agent game engine, AI strategies, match runner,
//   and UI controller. Manages the three-column layout with side panels (agent
//   settings → observatory logs) and center panel (game selection → match canvas).
//   Supports Code mode (built-in AI) and Harness mode (LLM scaffolding settings).
//   Implements 9 games: Snake Battle, Tron, Connect Four, Fischer Random Chess,
//   Othello, Go 9x9, Gomoku, Artillery, Poker. Each has engine, AI, rendering, match runner.
//   Dispatcher pattern: ARENA_GAMES entries have run/render/preview functions.
//   Arena Observatory: per-agent observability overlay (Agent A obs LEFT, Agent B obs RIGHT).
//   Auto Research: mode switcher, per-game community/local research, leaderboard,
//   strategy discussion, program.md viewer/editor/voting, human vs AI play dialog.
// SRP/DRY check: Pass — self-contained arena module, no overlap with main app JS

/* ═══════════════════════════════════════════════════════════════════════════
   ARC3 Color Palette & Constants
   ═══════════════════════════════════════════════════════════════════════════ */

const ARC3 = [
  '#FFFFFF', '#CCCCCC', '#999999', '#666666', '#333333', '#000000',
  '#E53AA3', '#FF7BCC', '#F93C31', '#1E93FF', '#88D8F1', '#FFDC00',
  '#FF851B', '#921231', '#4FCC30', '#A356D6'
];

const C = {
  BG: 5, WALL: 3, FOOD: 11,
  A_HEAD: 9, A_BODY: 10,
  B_HEAD: 8, B_BODY: 12,
};

const DIR = { UP: 0, RIGHT: 1, DOWN: 2, LEFT: 3 };
const DIR_NAME = ['UP', 'RIGHT', 'DOWN', 'LEFT'];
const DX = [0, 1, 0, -1];
const DY = [-1, 0, 1, 0];
const OPPOSITE = [2, 3, 0, 1];

function mulberry32(seed) {
  let a = seed | 0;
  return function() {
    a |= 0; a = a + 0x6D2B79F5 | 0;
    let t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}


/* ═══════════════════════════════════════════════════════════════════════════
   Snake Game Engine
   ═══════════════════════════════════════════════════════════════════════════ */

class SnakeGame {
  constructor(config = {}) {
    this.W = config.width || 20;
    this.H = config.height || 20;
    this.maxTurns = config.maxTurns || 200;
    this.seed = config.seed || 42;
    this.rng = mulberry32(this.seed);
    this.turn = 0;
    this.over = false;
    this.winner = null;

    const midY = this.H >> 1;
    this.snakeA = {
      body: [[4, midY], [3, midY], [2, midY]],
      dir: DIR.RIGHT, alive: true, score: 0,
    };
    this.snakeB = {
      body: [[this.W - 5, midY], [this.W - 4, midY], [this.W - 3, midY]],
      dir: DIR.LEFT, alive: true, score: 0,
    };
    this.food = this._spawnFood();
  }

  _spawnFood() {
    const occupied = new Set();
    for (const [x, y] of this.snakeA.body) occupied.add(`${x},${y}`);
    for (const [x, y] of this.snakeB.body) occupied.add(`${x},${y}`);
    const cands = [];
    for (let y = 1; y < this.H - 1; y++)
      for (let x = 1; x < this.W - 1; x++)
        if (!occupied.has(`${x},${y}`)) cands.push([x, y]);
    if (!cands.length) return null;
    return cands[Math.floor(this.rng() * cands.length)];
  }

  getGrid() {
    const grid = Array.from({ length: this.H }, () => Array(this.W).fill(C.BG));
    for (let x = 0; x < this.W; x++) { grid[0][x] = C.WALL; grid[this.H - 1][x] = C.WALL; }
    for (let y = 0; y < this.H; y++) { grid[y][0] = C.WALL; grid[y][this.W - 1] = C.WALL; }
    if (this.food) grid[this.food[1]][this.food[0]] = C.FOOD;
    const drawSnake = (snake, headColor, bodyColor) => {
      if (!snake.alive) return;
      for (let i = snake.body.length - 1; i >= 1; i--)
        grid[snake.body[i][1]][snake.body[i][0]] = bodyColor;
      grid[snake.body[0][1]][snake.body[0][0]] = headColor;
    };
    drawSnake(this.snakeA, C.A_HEAD, C.A_BODY);
    drawSnake(this.snakeB, C.B_HEAD, C.B_BODY);
    return grid;
  }

  getAIState() {
    const snap = s => ({
      head: [...s.body[0]], body: s.body.map(p => [...p]),
      dir: s.dir, alive: s.alive, score: s.score, length: s.body.length,
    });
    return {
      width: this.W, height: this.H, turn: this.turn, maxTurns: this.maxTurns,
      food: this.food ? [...this.food] : null,
      snakeA: snap(this.snakeA), snakeB: snap(this.snakeB),
    };
  }

  step(moveA, moveB) {
    if (this.over) return;
    this.turn++;

    // Prevent 180-degree reversal
    if (moveA === OPPOSITE[this.snakeA.dir]) moveA = this.snakeA.dir;
    if (moveB === OPPOSITE[this.snakeB.dir]) moveB = this.snakeB.dir;
    this.snakeA.dir = moveA;
    this.snakeB.dir = moveB;

    const [ax, ay] = this.snakeA.body[0];
    const nax = ax + DX[moveA], nay = ay + DY[moveA];
    const [bx, by] = this.snakeB.body[0];
    const nbx = bx + DX[moveB], nby = by + DY[moveB];

    let aDead = false, bDead = false;

    // Wall collision
    if (nax <= 0 || nax >= this.W - 1 || nay <= 0 || nay >= this.H - 1) aDead = true;
    if (nbx <= 0 || nbx >= this.W - 1 || nby <= 0 || nby >= this.H - 1) bDead = true;

    // Head-on collision
    if (nax === nbx && nay === nby) { aDead = true; bDead = true; }

    // Body collisions (self + opponent)
    const inBody = (x, y, body) => body.some(([px, py]) => px === x && py === y);
    if (inBody(nax, nay, this.snakeA.body)) aDead = true;
    if (inBody(nax, nay, this.snakeB.body)) aDead = true;
    if (inBody(nbx, nby, this.snakeB.body)) bDead = true;
    if (inBody(nbx, nby, this.snakeA.body)) bDead = true;

    if (aDead) this.snakeA.alive = false;
    if (bDead) this.snakeB.alive = false;

    let ateA = false, ateB = false;
    if (this.snakeA.alive) {
      this.snakeA.body.unshift([nax, nay]);
      if (this.food && nax === this.food[0] && nay === this.food[1]) {
        ateA = true; this.snakeA.score++;
      } else this.snakeA.body.pop();
    }
    if (this.snakeB.alive) {
      this.snakeB.body.unshift([nbx, nby]);
      if (this.food && nbx === this.food[0] && nby === this.food[1]) {
        ateB = true; this.snakeB.score++;
      } else this.snakeB.body.pop();
    }
    if (ateA || ateB) this.food = this._spawnFood();

    // Determine winner
    if (!this.snakeA.alive && !this.snakeB.alive) { this.over = true; this.winner = 'draw'; }
    else if (!this.snakeA.alive) { this.over = true; this.winner = 'B'; }
    else if (!this.snakeB.alive) { this.over = true; this.winner = 'A'; }
    else if (this.turn >= this.maxTurns) {
      this.over = true;
      if (this.snakeA.score > this.snakeB.score) this.winner = 'A';
      else if (this.snakeB.score > this.snakeA.score) this.winner = 'B';
      else this.winner = 'draw';
    }
  }
}


/* ═══════════════════════════════════════════════════════════════════════════
   AI Strategies
   ═══════════════════════════════════════════════════════════════════════════ */

function manhattan(a, b) { return Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]); }

function isSafe(x, y, state, me, other) {
  if (x <= 0 || x >= state.width - 1 || y <= 0 || y >= state.height - 1) return false;
  for (const [bx, by] of me.body) if (bx === x && by === y) return false;
  for (const [bx, by] of other.body) if (bx === x && by === y) return false;
  return true;
}

function floodFill(startX, startY, state, me, other, limit) {
  let count = 0;
  const visited = new Set([`${startX},${startY}`]);
  const queue = [[startX, startY]];
  while (queue.length && count < limit) {
    const [cx, cy] = queue.shift();
    count++;
    for (let d = 0; d < 4; d++) {
      const nx = cx + DX[d], ny = cy + DY[d];
      const key = `${nx},${ny}`;
      if (!visited.has(key) && isSafe(nx, ny, state, me, other)) {
        visited.add(key); queue.push([nx, ny]);
      }
    }
  }
  return count;
}

function evaluateMoves(state, player) {
  const me = player === 'A' ? state.snakeA : state.snakeB;
  const other = player === 'A' ? state.snakeB : state.snakeA;
  const [hx, hy] = me.head;
  const moves = [];
  for (let d = 0; d < 4; d++) {
    const nx = hx + DX[d], ny = hy + DY[d];
    const safe = isSafe(nx, ny, state, me, other);
    const foodDist = state.food ? manhattan([nx, ny], state.food) : 999;
    const oppDist = manhattan([nx, ny], other.head);
    const space = safe ? floodFill(nx, ny, state, me, other, 40) : 0;
    moves.push({ dir: d, safe, foodDist, oppDist, space, nx, ny });
  }
  return { moves, me, other };
}

// Greedy: chase food, avoid walls
function greedyAI(state, player) {
  const { moves, me } = evaluateMoves(state, player);
  const lines = moves.map(m =>
    `  ${DIR_NAME[m.dir]}: ${m.safe ? `safe, food ${m.foodDist}` : 'BLOCKED'}`
  );
  const safe = moves.filter(m => m.safe);
  if (!safe.length) {
    return { move: me.dir, reasoning: lines.join('\n') + `\nTrapped! Going ${DIR_NAME[me.dir]}` };
  }
  safe.sort((a, b) => a.foodDist - b.foodDist);
  return {
    move: safe[0].dir,
    reasoning: lines.join('\n') + `\n=> ${DIR_NAME[safe[0].dir]} (nearest food)`,
  };
}

// Aggressive: hunt opponent when longer, feed when shorter
function aggressiveAI(state, player) {
  const { moves, me, other } = evaluateMoves(state, player);
  const lines = moves.map(m =>
    `  ${DIR_NAME[m.dir]}: ${m.safe ? `safe, food ${m.foodDist}, opp ${m.oppDist}` : 'BLOCKED'}`
  );
  const safe = moves.filter(m => m.safe);
  if (!safe.length) {
    return { move: me.dir, reasoning: lines.join('\n') + `\nTrapped!` };
  }
  const hunt = me.length > other.length;
  if (hunt) {
    safe.sort((a, b) => a.oppDist - b.oppDist);
    return {
      move: safe[0].dir,
      reasoning: `HUNT mode (len ${me.length} vs ${other.length})\n` +
        lines.join('\n') + `\n=> ${DIR_NAME[safe[0].dir]} (chase opponent)`,
    };
  }
  safe.sort((a, b) => a.foodDist - b.foodDist);
  return {
    move: safe[0].dir,
    reasoning: `FEED mode (len ${me.length} vs ${other.length})\n` +
      lines.join('\n') + `\n=> ${DIR_NAME[safe[0].dir]} (nearest food)`,
  };
}

// Cautious: prefer open space, avoid traps
function cautiousAI(state, player) {
  const { moves, me } = evaluateMoves(state, player);
  const lines = moves.map(m =>
    `  ${DIR_NAME[m.dir]}: ${m.safe ? `safe, food ${m.foodDist}, space ${m.space}` : 'BLOCKED'}`
  );
  const safe = moves.filter(m => m.safe);
  if (!safe.length) {
    return { move: me.dir, reasoning: lines.join('\n') + `\nTrapped!` };
  }
  safe.sort((a, b) => {
    if (b.space !== a.space) return b.space - a.space;
    return a.foodDist - b.foodDist;
  });
  return {
    move: safe[0].dir,
    reasoning: `CAUTIOUS (prefer space)\n` +
      lines.join('\n') + `\n=> ${DIR_NAME[safe[0].dir]} (space ${safe[0].space})`,
  };
}

const AI_STRATEGIES = {
  greedy:     { name: 'Greedy',     fn: greedyAI,     desc: 'Chases food directly',
                personality: { aggression: 20, caution: 40, greed: 90 } },
  aggressive: { name: 'Aggressive', fn: aggressiveAI, desc: 'Hunts when longer, feeds when shorter',
                personality: { aggression: 80, caution: 30, greed: 50 } },
  cautious:   { name: 'Cautious',   fn: cautiousAI,   desc: 'Prefers open spaces, avoids traps',
                personality: { aggression: 10, caution: 95, greed: 40 } },
};


/* ═══════════════════════════════════════════════════════════════════════════
   Chess960 (Fischer Random) Game Engine
   ═══════════════════════════════════════════════════════════════════════════ */

const KING = 1, QUEEN = 2, ROOK = 3, BISHOP = 4, KNIGHT = 5, PAWN = 6;
const PIECE_CHAR = { [KING]:'K',[QUEEN]:'Q',[ROOK]:'R',[BISHOP]:'B',[KNIGHT]:'N',[PAWN]:'' };
const PIECE_UNICODE = {
  1:'\u2654', 2:'\u2655', 3:'\u2656', 4:'\u2657', 5:'\u2658', 6:'\u2659',
  [-1]:'\u265A', [-2]:'\u265B', [-3]:'\u265C', [-4]:'\u265D', [-5]:'\u265E', [-6]:'\u265F',
};
const PIECE_VAL = { [KING]:20000,[QUEEN]:900,[ROOK]:500,[BISHOP]:330,[KNIGHT]:320,[PAWN]:100 };

// Piece-square tables (white perspective, index = row*8+col, row 0 = rank 8)
const PST_PAWN = [0,0,0,0,0,0,0,0,50,50,50,50,50,50,50,50,10,10,20,30,30,20,10,10,5,5,10,25,25,10,5,5,0,0,0,20,20,0,0,0,5,-5,-10,0,0,-10,-5,5,5,10,10,-20,-20,10,10,5,0,0,0,0,0,0,0,0];
const PST_KNIGHT = [-50,-40,-30,-30,-30,-30,-40,-50,-40,-20,0,0,0,0,-20,-40,-30,0,10,15,15,10,0,-30,-30,5,15,20,20,15,5,-30,-30,0,15,20,20,15,0,-30,-30,5,10,15,15,10,5,-30,-40,-20,0,5,5,0,-20,-40,-50,-40,-30,-30,-30,-30,-40,-50];
const PST_BISHOP = [-20,-10,-10,-10,-10,-10,-10,-20,-10,0,0,0,0,0,0,-10,-10,0,10,10,10,10,0,-10,-10,5,5,10,10,5,5,-10,-10,0,10,10,10,10,0,-10,-10,10,10,10,10,10,10,-10,-10,5,0,0,0,0,5,-10,-20,-10,-10,-10,-10,-10,-10,-20];
const PST_ROOK = [0,0,0,0,0,0,0,0,5,10,10,10,10,10,10,5,-5,0,0,0,0,0,0,-5,-5,0,0,0,0,0,0,-5,-5,0,0,0,0,0,0,-5,-5,0,0,0,0,0,0,-5,-5,0,0,0,0,0,0,-5,0,0,0,5,5,0,0,0];
const PST_QUEEN = [-20,-10,-10,-5,-5,-10,-10,-20,-10,0,0,0,0,0,0,-10,-10,0,5,5,5,5,0,-10,-5,0,5,5,5,5,0,-5,0,0,5,5,5,5,0,-5,-10,5,5,5,5,5,0,-10,-10,0,5,0,0,0,0,-10,-20,-10,-10,-5,-5,-10,-10,-20];
const PST_KING = [-30,-40,-40,-50,-50,-40,-40,-30,-30,-40,-40,-50,-50,-40,-40,-30,-30,-40,-40,-50,-50,-40,-40,-30,-30,-40,-40,-50,-50,-40,-40,-30,-20,-30,-30,-40,-40,-30,-30,-20,-10,-20,-20,-20,-20,-20,-20,-10,20,20,0,0,0,0,20,20,20,30,10,0,0,10,30,20];
const PST = { [PAWN]:PST_PAWN,[KNIGHT]:PST_KNIGHT,[BISHOP]:PST_BISHOP,[ROOK]:PST_ROOK,[QUEEN]:PST_QUEEN,[KING]:PST_KING };

const KNIGHT_OFFSETS = [[-2,-1],[-2,1],[-1,-2],[-1,2],[1,-2],[1,2],[2,-1],[2,1]];
const KING_OFFSETS = [[-1,-1],[-1,0],[-1,1],[0,-1],[0,1],[1,-1],[1,0],[1,1]];
const DIAG_DIRS = [[-1,-1],[-1,1],[1,-1],[1,1]];
const STRAIGHT_DIRS = [[-1,0],[1,0],[0,-1],[0,1]];

function sqName(r, c) { return String.fromCharCode(97 + c) + (8 - r); }

class ChessGame {
  constructor(config = {}) {
    this.board = Array.from({length: 8}, () => Array(8).fill(0));
    this.turn = 'w';
    this.ply = 0;
    this.maxPly = (config.maxMoves || 80) * 2;
    this.over = false;
    this.winner = null;
    this.lastMove = null;
    this.enPassant = null;
    this.halfmoveClock = 0;
    this._setupFischerRandom(config.seed || 42);
  }

  _setupFischerRandom(seed) {
    const rng = mulberry32(seed);
    const rank = Array(8).fill(0);
    // Bishops on opposite-colored squares
    const light = [0,2,4,6], dark = [1,3,5,7];
    rank[light[Math.floor(rng()*4)]] = BISHOP;
    rank[dark[Math.floor(rng()*4)]] = BISHOP;
    // Queen on a remaining square
    let rem = []; for (let i=0;i<8;i++) if(!rank[i]) rem.push(i);
    let idx = Math.floor(rng()*rem.length);
    rank[rem[idx]] = QUEEN; rem.splice(idx,1);
    // Two knights
    idx = Math.floor(rng()*rem.length); rank[rem[idx]] = KNIGHT; rem.splice(idx,1);
    idx = Math.floor(rng()*rem.length); rank[rem[idx]] = KNIGHT; rem.splice(idx,1);
    // Remaining 3: Rook, King, Rook (king between rooks)
    rank[rem[0]] = ROOK; rank[rem[1]] = KING; rank[rem[2]] = ROOK;
    // Place on board
    for (let c = 0; c < 8; c++) {
      this.board[7][c] = rank[c];       // white back rank
      this.board[6][c] = PAWN;           // white pawns
      this.board[0][c] = -rank[c];       // black back rank
      this.board[1][c] = -PAWN;          // black pawns
    }
  }

  getBoard() { return this.board.map(r => [...r]); }

  _pseudoLegalMoves() {
    const moves = [];
    const sign = this.turn === 'w' ? 1 : -1;
    for (let r = 0; r < 8; r++) {
      for (let c = 0; c < 8; c++) {
        const p = this.board[r][c];
        if (p * sign <= 0) continue;
        const t = Math.abs(p);
        if (t === PAWN) {
          const dir = sign > 0 ? -1 : 1;
          const startRow = sign > 0 ? 6 : 1;
          const promoRow = sign > 0 ? 0 : 7;
          const nr = r + dir;
          if (nr >= 0 && nr < 8 && this.board[nr][c] === 0) {
            if (nr === promoRow) moves.push({f:[r,c],t:[nr,c],pr:QUEEN});
            else {
              moves.push({f:[r,c],t:[nr,c],pr:null});
              if (r === startRow && this.board[r+2*dir][c] === 0)
                moves.push({f:[r,c],t:[r+2*dir,c],pr:null});
            }
          }
          for (const dc of [-1,1]) {
            const nc = c+dc;
            if (nc<0||nc>=8) continue;
            if (this.board[nr][nc]*sign < 0) {
              moves.push({f:[r,c],t:[nr,nc],pr:nr===promoRow?QUEEN:null});
            }
            if (this.enPassant && this.enPassant[0]===nr && this.enPassant[1]===nc) {
              moves.push({f:[r,c],t:[nr,nc],pr:null,ep:true});
            }
          }
        }
        if (t === KNIGHT) {
          for (const [dr,dc] of KNIGHT_OFFSETS) {
            const nr=r+dr,nc=c+dc;
            if (nr<0||nr>=8||nc<0||nc>=8||this.board[nr][nc]*sign>0) continue;
            moves.push({f:[r,c],t:[nr,nc],pr:null});
          }
        }
        if (t === BISHOP || t === QUEEN) {
          for (const [dr,dc] of DIAG_DIRS) this._slide(r,c,dr,dc,sign,moves);
        }
        if (t === ROOK || t === QUEEN) {
          for (const [dr,dc] of STRAIGHT_DIRS) this._slide(r,c,dr,dc,sign,moves);
        }
        if (t === KING) {
          for (const [dr,dc] of KING_OFFSETS) {
            const nr=r+dr,nc=c+dc;
            if (nr<0||nr>=8||nc<0||nc>=8||this.board[nr][nc]*sign>0) continue;
            moves.push({f:[r,c],t:[nr,nc],pr:null});
          }
        }
      }
    }
    return moves;
  }

  _slide(r,c,dr,dc,sign,moves) {
    let nr=r+dr,nc=c+dc;
    while (nr>=0&&nr<8&&nc>=0&&nc<8) {
      if (this.board[nr][nc]*sign > 0) break;
      moves.push({f:[r,c],t:[nr,nc],pr:null});
      if (this.board[nr][nc] !== 0) break;
      nr+=dr; nc+=dc;
    }
  }

  _isAttacked(r, c, byColor) {
    const s = byColor === 'w' ? 1 : -1;
    // Knights
    for (const [dr,dc] of KNIGHT_OFFSETS) {
      const nr=r+dr,nc=c+dc;
      if (nr>=0&&nr<8&&nc>=0&&nc<8&&this.board[nr][nc]===s*KNIGHT) return true;
    }
    // Pawns (attack FROM byColor's perspective)
    const pd = byColor === 'w' ? 1 : -1;
    for (const dc of [-1,1]) {
      const pr=r+pd,pc=c+dc;
      if (pr>=0&&pr<8&&pc>=0&&pc<8&&this.board[pr][pc]===s*PAWN) return true;
    }
    // King
    for (const [dr,dc] of KING_OFFSETS) {
      const nr=r+dr,nc=c+dc;
      if (nr>=0&&nr<8&&nc>=0&&nc<8&&this.board[nr][nc]===s*KING) return true;
    }
    // Diagonal (bishop/queen)
    for (const [dr,dc] of DIAG_DIRS) {
      let nr=r+dr,nc=c+dc;
      while (nr>=0&&nr<8&&nc>=0&&nc<8) {
        const p=this.board[nr][nc];
        if (p!==0) { if (p===s*BISHOP||p===s*QUEEN) return true; break; }
        nr+=dr;nc+=dc;
      }
    }
    // Straight (rook/queen)
    for (const [dr,dc] of STRAIGHT_DIRS) {
      let nr=r+dr,nc=c+dc;
      while (nr>=0&&nr<8&&nc>=0&&nc<8) {
        const p=this.board[nr][nc];
        if (p!==0) { if (p===s*ROOK||p===s*QUEEN) return true; break; }
        nr+=dr;nc+=dc;
      }
    }
    return false;
  }

  _isInCheck(color) {
    const kp = color === 'w' ? KING : -KING;
    for (let r=0;r<8;r++) for (let c=0;c<8;c++) if (this.board[r][c]===kp) {
      return this._isAttacked(r, c, color === 'w' ? 'b' : 'w');
    }
    return true;
  }

  makeMove(move) {
    const saved = {
      cap: this.board[move.t[0]][move.t[1]],
      ep: this.enPassant ? [...this.enPassant] : null,
      hc: this.halfmoveClock,
    };
    const [fr,fc] = move.f, [tr,tc] = move.t;
    const piece = this.board[fr][fc];
    const sgn = piece > 0 ? 1 : -1;
    const apt = Math.abs(piece);
    this.halfmoveClock = (apt === PAWN || this.board[tr][tc] !== 0) ? 0 : this.halfmoveClock + 1;
    if (move.ep) this.board[fr][tc] = 0;
    this.enPassant = (apt === PAWN && Math.abs(fr-tr) === 2) ? [(fr+tr)/2, fc] : null;
    this.board[tr][tc] = move.pr ? sgn * move.pr : piece;
    this.board[fr][fc] = 0;
    this.turn = this.turn === 'w' ? 'b' : 'w';
    this.ply++;
    return saved;
  }

  unmakeMove(move, saved) {
    const [fr,fc] = move.f, [tr,tc] = move.t;
    const piece = this.board[tr][tc];
    const sgn = piece > 0 ? 1 : -1;
    this.board[fr][fc] = move.pr ? sgn * PAWN : piece;
    this.board[tr][tc] = saved.cap;
    if (move.ep) this.board[fr][tc] = -sgn * PAWN;
    this.enPassant = saved.ep;
    this.halfmoveClock = saved.hc;
    this.turn = this.turn === 'w' ? 'b' : 'w';
    this.ply--;
  }

  getLegalMoves() {
    const pseudo = this._pseudoLegalMoves();
    const legal = [];
    const movingColor = this.turn;
    for (const m of pseudo) {
      const s = this.makeMove(m);
      if (!this._isInCheck(movingColor)) legal.push(m);
      this.unmakeMove(m, s);
    }
    return legal;
  }
}

function chessMoveNotation(board, move) {
  const piece = board[move.f[0]][move.f[1]];
  const t = Math.abs(piece);
  const cap = board[move.t[0]][move.t[1]] !== 0 || move.ep;
  const dest = sqName(move.t[0], move.t[1]);
  if (t === PAWN) {
    let n = cap ? sqName(move.f[0],move.f[1])[0]+'x'+dest : dest;
    if (move.pr) n += '=Q';
    return n;
  }
  return PIECE_CHAR[t] + (cap ? 'x' : '') + dest;
}


/* ═══════════════════════════════════════════════════════════════════════════
   Chess AI
   ═══════════════════════════════════════════════════════════════════════════ */

function chessEval(game) {
  let score = 0;
  for (let r = 0; r < 8; r++) for (let c = 0; c < 8; c++) {
    const p = game.board[r][c];
    if (p === 0) continue;
    const t = Math.abs(p), sgn = p > 0 ? 1 : -1;
    const pstIdx = sgn > 0 ? r*8+c : (7-r)*8+c;
    score += sgn * (PIECE_VAL[t] + (PST[t] ? PST[t][pstIdx] : 0));
  }
  return score;
}

function chessMinimax(game, depth, alpha, beta, maximizing) {
  if (depth === 0) return chessEval(game);
  const moves = game.getLegalMoves();
  if (moves.length === 0) {
    return game._isInCheck(game.turn) ? (maximizing ? -99999 : 99999) : 0;
  }
  // Order: captures first for better pruning
  moves.sort((a, b) => {
    const ca = game.board[a.t[0]][a.t[1]] !== 0 ? 1 : 0;
    const cb = game.board[b.t[0]][b.t[1]] !== 0 ? 1 : 0;
    return cb - ca;
  });
  if (maximizing) {
    let best = -Infinity;
    for (const m of moves) {
      const s = game.makeMove(m);
      best = Math.max(best, chessMinimax(game, depth-1, alpha, beta, false));
      game.unmakeMove(m, s);
      alpha = Math.max(alpha, best);
      if (beta <= alpha) break;
    }
    return best;
  } else {
    let best = Infinity;
    for (const m of moves) {
      const s = game.makeMove(m);
      best = Math.min(best, chessMinimax(game, depth-1, alpha, beta, true));
      game.unmakeMove(m, s);
      beta = Math.min(beta, best);
      if (beta <= alpha) break;
    }
    return best;
  }
}

function chessAI(game, depth) {
  const moves = game.getLegalMoves();
  if (!moves.length) return null;
  const maximizing = game.turn === 'w';
  const candidates = [];
  for (const m of moves) {
    const notation = chessMoveNotation(game.board, m);
    const s = game.makeMove(m);
    const score = chessMinimax(game, depth-1, -Infinity, Infinity, !maximizing);
    game.unmakeMove(m, s);
    candidates.push({ move: m, score, notation });
  }
  candidates.sort((a,b) => maximizing ? b.score-a.score : a.score-b.score);
  const best = candidates[0];
  const top = candidates.slice(0, 3);
  const lines = top.map((c,i) =>
    `  ${i+1}. ${c.notation}: ${c.score>0?'+':''}${c.score}`
  );
  return {
    move: best.move,
    notation: best.notation,
    reasoning: `Depth ${depth} search\n${lines.join('\n')}\n=> ${best.notation} (${best.score>0?'+':''}${best.score})`,
  };
}

function chessTacticianAI(game) { return chessAI(game, 3); }
function chessPositionalAI(game) { return chessAI(game, 2); }

const CHESS_STRATEGIES = {
  tactician:  { name: 'Tactician',  fn: chessTacticianAI, desc: 'Deep search (depth 3), finds combinations',
                personality: { aggression: 70, caution: 40, greed: 60 } },
  positional: { name: 'Positional', fn: chessPositionalAI, desc: 'Balanced search (depth 2), solid play',
                personality: { aggression: 30, caution: 70, greed: 40 } },
};


/* ═══════════════════════════════════════════════════════════════════════════
   Chess Rendering
   ═══════════════════════════════════════════════════════════════════════════ */

function renderChessFrame(ctx, frame, size) {
  const sq = size / 8;
  const board = frame.board;
  const lm = frame.lastMove; // [fr,fc,tr,tc] or null

  for (let r = 0; r < 8; r++) {
    for (let c = 0; c < 8; c++) {
      const isLight = (r + c) % 2 === 0;
      let highlight = lm && ((r===lm[0]&&c===lm[1])||(r===lm[2]&&c===lm[3]));
      ctx.fillStyle = highlight
        ? (isLight ? '#F6F669' : '#BACA2B')
        : (isLight ? ARC3[0] : ARC3[2]);
      ctx.fillRect(c*sq, r*sq, sq, sq);

      const piece = board[r][c];
      if (piece !== 0) {
        const ch = PIECE_UNICODE[piece];
        ctx.font = `${sq * 0.78}px serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        // Shadow for contrast
        ctx.fillStyle = 'rgba(0,0,0,0.25)';
        ctx.fillText(ch, c*sq+sq/2+1, r*sq+sq/2+1);
        // Piece
        ctx.fillStyle = piece > 0 ? '#FFFFFF' : '#111111';
        ctx.fillText(ch, c*sq+sq/2, r*sq+sq/2);
      }
    }
  }
  // File/rank labels
  ctx.font = `bold ${sq*0.18}px monospace`;
  ctx.textBaseline = 'bottom';
  for (let c = 0; c < 8; c++) {
    ctx.fillStyle = (7+c)%2===0 ? ARC3[2] : ARC3[0];
    ctx.textAlign = 'left';
    ctx.fillText(String.fromCharCode(97+c), c*sq+2, size-2);
  }
  ctx.textBaseline = 'top';
  for (let r = 0; r < 8; r++) {
    ctx.fillStyle = (r)%2===0 ? ARC3[2] : ARC3[0];
    ctx.textAlign = 'right';
    ctx.fillText(String(8-r), sq-2, r*sq+2);
  }
}

function renderChessPreview(canvas, config) {
  const game = new ChessGame(config);
  const board = game.getBoard();
  const size = 120;
  canvas.width = size; canvas.height = size;
  const ctx = canvas.getContext('2d');
  const sq = size / 8;
  for (let r = 0; r < 8; r++) for (let c = 0; c < 8; c++) {
    ctx.fillStyle = (r+c)%2===0 ? ARC3[0] : ARC3[2];
    ctx.fillRect(c*sq, r*sq, sq, sq);
    const p = board[r][c];
    if (p !== 0) {
      ctx.font = `${sq*0.75}px serif`;
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillStyle = p > 0 ? '#FFFFFF' : '#111111';
      ctx.fillText(PIECE_UNICODE[p], c*sq+sq/2, r*sq+sq/2);
    }
  }
}


/* ═══════════════════════════════════════════════════════════════════════════
   Chess Match Runner (turn-based: alternating white/black)
   ═══════════════════════════════════════════════════════════════════════════ */

function runChessMatch(config, strategyA, strategyB) {
  const game = new ChessGame(config);
  const fnW = CHESS_STRATEGIES[strategyA].fn;
  const fnB = CHESS_STRATEGIES[strategyB].fn;
  const history = [];

  history.push({
    turn: 0, board: game.getBoard(), lastMove: null,
    agentA: null, agentB: null, winner: null,
    scoreA: 0, scoreB: 0,
  });

  while (!game.over) {
    const isWhite = game.turn === 'w';
    const fn = isWhite ? fnW : fnB;
    const result = fn(game);

    if (!result) {
      game.over = true;
      game.winner = game._isInCheck(game.turn) ? (isWhite ? 'B' : 'A') : 'draw';
    } else {
      const notation = result.notation;
      game.makeMove(result.move);
      game.lastMove = [result.move.f[0], result.move.f[1], result.move.t[0], result.move.t[1]];

      // Check end conditions
      const opponentMoves = game.getLegalMoves();
      if (opponentMoves.length === 0) {
        game.over = true;
        game.winner = game._isInCheck(game.turn) ? (isWhite ? 'A' : 'B') : 'draw';
      }
      if (game.halfmoveClock >= 100) { game.over = true; game.winner = 'draw'; }
      if (game.ply >= game.maxPly) { game.over = true; game.winner = 'draw'; }

      // Material count for score display
      let matW = 0, matB = 0;
      for (let r=0;r<8;r++) for (let c=0;c<8;c++) {
        const p = game.board[r][c];
        if (p > 0 && Math.abs(p) !== KING) matW += PIECE_VAL[p];
        if (p < 0 && Math.abs(p) !== KING) matB += PIECE_VAL[-p];
      }

      // Check/checkmate suffix
      let suffix = '';
      if (game.over && game.winner !== 'draw') suffix = '#';
      else if (!game.over && game._isInCheck(game.turn)) suffix = '+';

      history.push({
        turn: game.ply,
        board: game.getBoard(),
        lastMove: game.lastMove,
        agentA: isWhite ? { move: notation + suffix, reasoning: result.reasoning } : null,
        agentB: !isWhite ? { move: notation + suffix, reasoning: result.reasoning } : null,
        winner: game.winner,
        scoreA: Math.round(matW / 100),
        scoreB: Math.round(matB / 100),
      });
    }
  }
  return history;
}


/* ═══════════════════════════════════════════════════════════════════════════
   Snake Rendering (extracted for dispatcher)
   ═══════════════════════════════════════════════════════════════════════════ */

function renderSnakeFrame(ctx, frame, size) {
  const grid = frame.grid;
  const gridH = grid.length, gridW = grid[0].length;
  const cellW = size / gridW, cellH = size / gridH;
  for (let y = 0; y < gridH; y++)
    for (let x = 0; x < gridW; x++) {
      ctx.fillStyle = ARC3[grid[y][x]];
      ctx.fillRect(x * cellW, y * cellH, cellW + 0.5, cellH + 0.5);
    }
  ctx.strokeStyle = 'rgba(255,255,255,0.04)';
  ctx.lineWidth = 0.5;
  for (let x = 0; x <= gridW; x++) {
    ctx.beginPath(); ctx.moveTo(x*cellW, 0); ctx.lineTo(x*cellW, size); ctx.stroke();
  }
  for (let y = 0; y <= gridH; y++) {
    ctx.beginPath(); ctx.moveTo(0, y*cellH); ctx.lineTo(size, y*cellH); ctx.stroke();
  }
}

function renderSnakePreview(canvas, config) {
  const g = new SnakeGame(config);
  const grid = g.getGrid();
  const size = 120;
  canvas.width = size; canvas.height = size;
  const ctx = canvas.getContext('2d');
  const cellW = size / g.W, cellH = size / g.H;
  for (let y = 0; y < g.H; y++)
    for (let x = 0; x < g.W; x++) {
      ctx.fillStyle = ARC3[grid[y][x]];
      ctx.fillRect(x * cellW, y * cellH, cellW + 0.5, cellH + 0.5);
    }
}


/* ═══════════════════════════════════════════════════════════════════════════
   Connect Four Game Engine
   ═══════════════════════════════════════════════════════════════════════════ */

const C4_ROWS = 6, C4_COLS = 7;

class ConnectFourGame {
  constructor(config = {}) {
    this.board = Array.from({length: C4_ROWS}, () => Array(C4_COLS).fill(0));
    this.turn = 1; // 1 = Agent A, -1 = Agent B
    this.ply = 0;
    this.over = false;
    this.winner = null;
    this.lastMove = null;
  }

  getLegalMoves() {
    const moves = [];
    for (let c = 0; c < C4_COLS; c++) if (this.board[0][c] === 0) moves.push(c);
    return moves;
  }

  dropRow(col) {
    for (let r = C4_ROWS - 1; r >= 0; r--) if (this.board[r][col] === 0) return r;
    return -1;
  }

  makeMove(col) {
    const r = this.dropRow(col);
    if (r < 0) return false;
    this.board[r][col] = this.turn;
    this.lastMove = [r, col];
    this.ply++;
    if (this._checkWin(r, col, this.turn)) {
      this.over = true;
      this.winner = this.turn === 1 ? 'A' : 'B';
    } else if (this.getLegalMoves().length === 0) {
      this.over = true;
      this.winner = 'draw';
    }
    this.turn *= -1;
    return true;
  }

  unmakeMove(col) {
    for (let r = 0; r < C4_ROWS; r++) {
      if (this.board[r][col] !== 0) {
        this.board[r][col] = 0;
        this.ply--;
        this.turn *= -1;
        this.over = false;
        this.winner = null;
        return;
      }
    }
  }

  _checkWin(r, c, player) {
    const dirs = [[0,1],[1,0],[1,1],[1,-1]];
    for (const [dr, dc] of dirs) {
      let count = 1;
      for (let i = 1; i < 4; i++) {
        const nr = r+dr*i, nc = c+dc*i;
        if (nr<0||nr>=C4_ROWS||nc<0||nc>=C4_COLS||this.board[nr][nc]!==player) break;
        count++;
      }
      for (let i = 1; i < 4; i++) {
        const nr = r-dr*i, nc = c-dc*i;
        if (nr<0||nr>=C4_ROWS||nc<0||nc>=C4_COLS||this.board[nr][nc]!==player) break;
        count++;
      }
      if (count >= 4) return true;
    }
    return false;
  }

  getBoard() { return this.board.map(r => [...r]); }
}


/* ── Connect Four AI ────────────────────────────────────────────────────── */

function c4Eval(game) {
  let score = 0;
  const b = game.board, dirs = [[0,1],[1,0],[1,1],[1,-1]];
  const weights = [0, 1, 10, 100, 10000];
  for (let r = 0; r < C4_ROWS; r++) for (let c = 0; c < C4_COLS; c++) {
    for (const [dr, dc] of dirs) {
      let a1 = 0, a2 = 0;
      let valid = true;
      for (let i = 0; i < 4; i++) {
        const nr = r+dr*i, nc = c+dc*i;
        if (nr<0||nr>=C4_ROWS||nc<0||nc>=C4_COLS) { valid = false; break; }
        if (b[nr][nc] === 1) a1++; else if (b[nr][nc] === -1) a2++;
      }
      if (!valid) continue;
      if (a1 > 0 && a2 === 0) score += weights[a1];
      if (a2 > 0 && a1 === 0) score -= weights[a2];
    }
  }
  for (let r = 0; r < C4_ROWS; r++) {
    if (b[r][3] === 1) score += 3;
    if (b[r][3] === -1) score -= 3;
  }
  return score;
}

function c4Minimax(game, depth, alpha, beta, maximizing) {
  if (game.over) {
    if (game.winner === 'A') return 100000;
    if (game.winner === 'B') return -100000;
    return 0;
  }
  if (depth === 0) return c4Eval(game);
  const moves = game.getLegalMoves();
  moves.sort((a, b) => Math.abs(3-a) - Math.abs(3-b));
  if (maximizing) {
    let best = -Infinity;
    for (const col of moves) {
      game.makeMove(col);
      best = Math.max(best, c4Minimax(game, depth-1, alpha, beta, false));
      game.unmakeMove(col);
      alpha = Math.max(alpha, best);
      if (beta <= alpha) break;
    }
    return best;
  } else {
    let best = Infinity;
    for (const col of moves) {
      game.makeMove(col);
      best = Math.min(best, c4Minimax(game, depth-1, alpha, beta, true));
      game.unmakeMove(col);
      beta = Math.min(beta, best);
      if (beta <= alpha) break;
    }
    return best;
  }
}

function c4DropperAI(game) {
  const moves = game.getLegalMoves();
  if (!moves.length) return null;
  let bestCol = moves[0], bestScore = -Infinity;
  const lines = [];
  for (const col of moves) {
    game.makeMove(col);
    const score = game.turn === -1 ? c4Eval(game) : -c4Eval(game);
    game.unmakeMove(col);
    lines.push(`  Col ${col}: ${score > 0 ? '+' : ''}${score}`);
    if (score > bestScore) { bestScore = score; bestCol = col; }
  }
  return { col: bestCol, reasoning: `GREEDY\n${lines.join('\n')}\n=> Column ${bestCol}` };
}

function c4BlockerAI(game) {
  const moves = game.getLegalMoves();
  if (!moves.length) return null;
  for (const col of moves) {
    const r = game.dropRow(col);
    game.board[r][col] = game.turn;
    if (game._checkWin(r, col, game.turn)) { game.board[r][col] = 0; return { col, reasoning: `WIN at column ${col}!` }; }
    game.board[r][col] = 0;
  }
  const opp = -game.turn;
  for (const col of moves) {
    const r = game.dropRow(col);
    game.board[r][col] = opp;
    if (game._checkWin(r, col, opp)) { game.board[r][col] = 0; return { col, reasoning: `BLOCK opponent at column ${col}` }; }
    game.board[r][col] = 0;
  }
  const sorted = [...moves].sort((a, b) => Math.abs(3-a) - Math.abs(3-b));
  return { col: sorted[0], reasoning: `No threats, center-ish: column ${sorted[0]}` };
}

function c4BalancedAI(game) {
  const moves = game.getLegalMoves();
  if (!moves.length) return null;
  const maximizing = game.turn === 1;
  const candidates = [];
  for (const col of moves) {
    game.makeMove(col);
    const score = c4Minimax(game, 4, -Infinity, Infinity, !maximizing);
    game.unmakeMove(col);
    candidates.push({ col, score });
  }
  candidates.sort((a, b) => maximizing ? b.score-a.score : a.score-b.score);
  const best = candidates[0];
  const top = candidates.slice(0, 4);
  const lines = top.map((c, i) => `  ${i+1}. Col ${c.col}: ${c.score>0?'+':''}${c.score}`);
  return { col: best.col, reasoning: `Depth 5\n${lines.join('\n')}\n=> Column ${best.col}` };
}

const C4_STRATEGIES = {
  dropper:  { name: 'Dropper',  fn: c4DropperAI,  desc: 'Greedy — maximizes own line potential',
              personality: { aggression: 60, caution: 20, greed: 90 } },
  blocker:  { name: 'Blocker',  fn: c4BlockerAI,  desc: 'Defensive — blocks threats, then builds',
              personality: { aggression: 20, caution: 90, greed: 30 } },
  balanced: { name: 'Balanced', fn: c4BalancedAI,  desc: 'Minimax depth 5, strong all-round play',
              personality: { aggression: 50, caution: 60, greed: 50 } },
};


/* ── Connect Four Rendering ─────────────────────────────────────────────── */

function renderC4Frame(ctx, frame, size) {
  const board = frame.board;
  const cellW = size / C4_COLS, cellH = size / (C4_ROWS + 0.5);
  const radius = Math.min(cellW, cellH) * 0.4;
  ctx.fillStyle = '#1565C0';
  ctx.fillRect(0, 0, size, cellH * C4_ROWS);
  ctx.fillStyle = ARC3[5];
  ctx.fillRect(0, cellH * C4_ROWS, size, size - cellH * C4_ROWS);
  for (let r = 0; r < C4_ROWS; r++) for (let c = 0; c < C4_COLS; c++) {
    const cx = c*cellW + cellW/2, cy = r*cellH + cellH/2;
    const isLast = frame.lastMove && frame.lastMove[0]===r && frame.lastMove[1]===c;
    ctx.beginPath(); ctx.arc(cx, cy, radius, 0, Math.PI*2);
    if (board[r][c]===1) ctx.fillStyle = isLast ? '#FF4444' : ARC3[8];
    else if (board[r][c]===-1) ctx.fillStyle = isLast ? '#FFB84D' : ARC3[12];
    else ctx.fillStyle = ARC3[3];
    ctx.fill();
    if (isLast && board[r][c]!==0) { ctx.strokeStyle='#FFF'; ctx.lineWidth=2; ctx.stroke(); }
  }
  ctx.font = `bold ${cellW*0.28}px monospace`;
  ctx.fillStyle = ARC3[2]; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  for (let c = 0; c < C4_COLS; c++) ctx.fillText(String(c), c*cellW+cellW/2, C4_ROWS*cellH+cellH*0.25);
}

function renderC4Preview(canvas) {
  const size = 120;
  canvas.width = size; canvas.height = size;
  const ctx = canvas.getContext('2d');
  const cellW = size/C4_COLS, cellH = size/C4_ROWS, radius = Math.min(cellW,cellH)*0.38;
  ctx.fillStyle = '#1565C0'; ctx.fillRect(0,0,size,size);
  const preview = [[0,0,0,0,0,0,0],[0,0,0,0,0,0,0],[0,0,0,0,0,0,0],[0,0,0,1,0,0,0],[0,0,-1,1,0,0,0],[0,-1,1,-1,1,0,0]];
  for (let r=0;r<C4_ROWS;r++) for (let c=0;c<C4_COLS;c++) {
    ctx.beginPath(); ctx.arc(c*cellW+cellW/2, r*cellH+cellH/2, radius, 0, Math.PI*2);
    ctx.fillStyle = preview[r][c]===1 ? ARC3[8] : preview[r][c]===-1 ? ARC3[12] : ARC3[3];
    ctx.fill();
  }
}


/* ── Connect Four Match Runner ──────────────────────────────────────────── */

function runC4Match(config, strategyA, strategyB) {
  const game = new ConnectFourGame(config);
  const fnA = C4_STRATEGIES[strategyA].fn, fnB = C4_STRATEGIES[strategyB].fn;
  const history = [];
  history.push({ turn:0, board:game.getBoard(), lastMove:null, agentA:null, agentB:null, winner:null, scoreA:0, scoreB:0 });
  while (!game.over) {
    const isA = game.turn === 1;
    const result = (isA ? fnA : fnB)(game);
    if (!result) break;
    game.makeMove(result.col);
    history.push({
      turn: game.ply, board: game.getBoard(), lastMove: game.lastMove ? [...game.lastMove] : null,
      agentA: isA ? { move: `Column ${result.col}`, reasoning: result.reasoning } : null,
      agentB: !isA ? { move: `Column ${result.col}`, reasoning: result.reasoning } : null,
      winner: game.winner, scoreA: 0, scoreB: 0,
    });
  }
  return history;
}


/* ═══════════════════════════════════════════════════════════════════════════
   Tron (Light Cycles) Game Engine
   ═══════════════════════════════════════════════════════════════════════════ */

const TRON = { EMPTY: 0, A_TRAIL: 1, B_TRAIL: 2, A_HEAD: 3, B_HEAD: 4 };
const TRON_ARC = { 0: 5, 1: 10, 2: 12, 3: 9, 4: 8 };

class TronGame {
  constructor(config = {}) {
    this.W = config.width || 25;
    this.H = config.height || 25;
    this.maxTurns = config.maxTurns || 200;
    this.turn = 0;
    this.over = false;
    this.winner = null;
    this.grid = Array.from({length: this.H}, () => Array(this.W).fill(0));
    const midY = this.H >> 1;
    this.posA = [4, midY]; this.posB = [this.W-5, midY];
    this.dirA = DIR.RIGHT; this.dirB = DIR.LEFT;
    this.aliveA = true; this.aliveB = true;
    this.grid[midY][4] = TRON.A_HEAD;
    this.grid[midY][this.W-5] = TRON.B_HEAD;
  }

  getGrid() { return this.grid.map(r => [...r]); }

  getAIState() {
    return {
      width: this.W, height: this.H, turn: this.turn,
      posA: [...this.posA], posB: [...this.posB],
      dirA: this.dirA, dirB: this.dirB,
      aliveA: this.aliveA, aliveB: this.aliveB,
      grid: this.grid.map(r => [...r]),
    };
  }

  step(moveA, moveB) {
    if (this.over) return;
    this.turn++;
    if (moveA === OPPOSITE[this.dirA]) moveA = this.dirA;
    if (moveB === OPPOSITE[this.dirB]) moveB = this.dirB;
    this.dirA = moveA; this.dirB = moveB;

    if (this.aliveA) this.grid[this.posA[1]][this.posA[0]] = TRON.A_TRAIL;
    if (this.aliveB) this.grid[this.posB[1]][this.posB[0]] = TRON.B_TRAIL;

    const nax = this.posA[0]+DX[moveA], nay = this.posA[1]+DY[moveA];
    const nbx = this.posB[0]+DX[moveB], nby = this.posB[1]+DY[moveB];
    let aDead = !this.aliveA, bDead = !this.aliveB;

    if (this.aliveA && (nax<0||nax>=this.W||nay<0||nay>=this.H)) aDead = true;
    if (this.aliveB && (nbx<0||nbx>=this.W||nby<0||nby>=this.H)) bDead = true;
    if (this.aliveA && !aDead && this.grid[nay][nax]!==0) aDead = true;
    if (this.aliveB && !bDead && this.grid[nby][nbx]!==0) bDead = true;
    if (this.aliveA && this.aliveB && nax===nbx && nay===nby) { aDead = true; bDead = true; }

    if (aDead) this.aliveA = false;
    if (bDead) this.aliveB = false;
    if (this.aliveA) { this.posA = [nax, nay]; this.grid[nay][nax] = TRON.A_HEAD; }
    if (this.aliveB) { this.posB = [nbx, nby]; this.grid[nby][nbx] = TRON.B_HEAD; }

    if (!this.aliveA && !this.aliveB) { this.over = true; this.winner = 'draw'; }
    else if (!this.aliveA) { this.over = true; this.winner = 'B'; }
    else if (!this.aliveB) { this.over = true; this.winner = 'A'; }
    else if (this.turn >= this.maxTurns) { this.over = true; this.winner = 'draw'; }
  }
}


/* ── Tron AI ────────────────────────────────────────────────────────────── */

function tronSafe(x, y, state) {
  return x>=0 && x<state.width && y>=0 && y<state.height && state.grid[y][x]===0;
}

function tronFlood(sx, sy, state, limit) {
  if (!tronSafe(sx, sy, state)) return 0;
  let count = 0;
  const visited = new Set([`${sx},${sy}`]);
  const queue = [[sx, sy]];
  while (queue.length && count < limit) {
    const [cx, cy] = queue.shift(); count++;
    for (let d = 0; d < 4; d++) {
      const nx = cx+DX[d], ny = cy+DY[d], key = `${nx},${ny}`;
      if (!visited.has(key) && tronSafe(nx, ny, state)) { visited.add(key); queue.push([nx, ny]); }
    }
  }
  return count;
}

function tronMoves(state, player) {
  const pos = player==='A' ? state.posA : state.posB;
  const dir = player==='A' ? state.dirA : state.dirB;
  const opp = player==='A' ? state.posB : state.posA;
  const moves = [];
  for (let d = 0; d < 4; d++) {
    if (d === OPPOSITE[dir]) continue;
    const nx = pos[0]+DX[d], ny = pos[1]+DY[d];
    const safe = tronSafe(nx, ny, state);
    moves.push({ dir: d, safe, space: safe ? tronFlood(nx, ny, state, 400) : 0,
                 oppDist: Math.abs(nx-opp[0])+Math.abs(ny-opp[1]), nx, ny });
  }
  return moves;
}

function tronSpaceMaxAI(state, player) {
  const moves = tronMoves(state, player);
  const safe = moves.filter(m => m.safe);
  const lines = moves.map(m => `  ${DIR_NAME[m.dir]}: ${m.safe ? `space ${m.space}` : 'BLOCKED'}`);
  if (!safe.length) return { move: player==='A'?state.dirA:state.dirB, reasoning: lines.join('\n')+'\nTrapped!' };
  // When space is tied (common early game), prefer away from opponent
  safe.sort((a, b) => {
    if (b.space !== a.space) return b.space - a.space;
    return b.oppDist - a.oppDist;
  });
  return { move: safe[0].dir, reasoning: `SPACE-MAX\n${lines.join('\n')}\n=> ${DIR_NAME[safe[0].dir]} (space ${safe[0].space})` };
}

function tronAggressiveAI(state, player) {
  const moves = tronMoves(state, player);
  const safe = moves.filter(m => m.safe);
  const lines = moves.map(m => `  ${DIR_NAME[m.dir]}: ${m.safe ? `space ${m.space}, opp ${m.oppDist}` : 'BLOCKED'}`);
  if (!safe.length) return { move: player==='A'?state.dirA:state.dirB, reasoning: lines.join('\n')+'\nTrapped!' };
  // Only chase if we have enough space (>= 85% of best); otherwise play safe
  const maxSp = Math.max(...safe.map(m => m.space));
  const viable = safe.filter(m => m.space >= maxSp * 0.85);
  // Among safe-enough moves, prefer cutting off opponent
  viable.sort((a, b) => {
    if (Math.abs(b.space - a.space) > 20) return b.space - a.space; // big space difference? prefer space
    return a.oppDist - b.oppDist; // similar space? go toward opponent
  });
  return { move: viable[0].dir, reasoning: `AGGRESSIVE\n${lines.join('\n')}\n=> ${DIR_NAME[viable[0].dir]} (cut off)` };
}

function tronCautiousAI(state, player) {
  const moves = tronMoves(state, player);
  const safe = moves.filter(m => m.safe);
  const lines = moves.map(m => `  ${DIR_NAME[m.dir]}: ${m.safe ? `space ${m.space}` : 'BLOCKED'}`);
  if (!safe.length) return { move: player==='A'?state.dirA:state.dirB, reasoning: lines.join('\n')+'\nTrapped!' };
  // Strongly prefer space; among equal-space moves, stay away from opponent
  safe.sort((a,b) => {
    if (b.space !== a.space) return b.space - a.space;
    return b.oppDist - a.oppDist; // farther from opponent is safer
  });
  return { move: safe[0].dir, reasoning: `CAUTIOUS\n${lines.join('\n')}\n=> ${DIR_NAME[safe[0].dir]} (max space)` };
}

const TRON_STRATEGIES = {
  spacemax:   { name: 'Space Max',  fn: tronSpaceMaxAI,   desc: 'Maximizes accessible space via flood fill',
                personality: { aggression: 30, caution: 70, greed: 80 } },
  aggressive: { name: 'Aggressive', fn: tronAggressiveAI, desc: 'Cuts off opponent while staying safe',
                personality: { aggression: 90, caution: 20, greed: 40 } },
  cautious:   { name: 'Cautious',   fn: tronCautiousAI,   desc: 'Maximum space, stays central',
                personality: { aggression: 10, caution: 95, greed: 30 } },
};


/* ── Tron Rendering ─────────────────────────────────────────────────────── */

function renderTronFrame(ctx, frame, size) {
  const grid = frame.grid, H = grid.length, W = grid[0].length;
  const cellW = size/W, cellH = size/H;
  for (let y=0;y<H;y++) for (let x=0;x<W;x++) {
    ctx.fillStyle = ARC3[TRON_ARC[grid[y][x]] || 5];
    ctx.fillRect(x*cellW, y*cellH, cellW+0.5, cellH+0.5);
  }
  ctx.strokeStyle = 'rgba(255,255,255,0.03)'; ctx.lineWidth = 0.5;
  for (let x=0;x<=W;x++) { ctx.beginPath(); ctx.moveTo(x*cellW,0); ctx.lineTo(x*cellW,size); ctx.stroke(); }
  for (let y=0;y<=H;y++) { ctx.beginPath(); ctx.moveTo(0,y*cellH); ctx.lineTo(size,y*cellH); ctx.stroke(); }
}

function renderTronPreview(canvas) {
  const size = 120; canvas.width = size; canvas.height = size;
  const ctx = canvas.getContext('2d');
  const W = 25, H = 25, cellW = size/W, cellH = size/H;
  ctx.fillStyle = ARC3[5]; ctx.fillRect(0,0,size,size);
  const tA = [[4,12],[5,12],[6,12],[7,12],[8,12],[8,11],[8,10],[8,9],[9,9],[10,9],[11,9]];
  const tB = [[20,12],[19,12],[18,12],[17,12],[16,12],[16,13],[16,14],[15,14],[14,14]];
  for (const [x,y] of tA) { ctx.fillStyle=ARC3[10]; ctx.fillRect(x*cellW,y*cellH,cellW+.5,cellH+.5); }
  ctx.fillStyle=ARC3[9]; ctx.fillRect(12*cellW,9*cellH,cellW+.5,cellH+.5);
  for (const [x,y] of tB) { ctx.fillStyle=ARC3[12]; ctx.fillRect(x*cellW,y*cellH,cellW+.5,cellH+.5); }
  ctx.fillStyle=ARC3[8]; ctx.fillRect(13*cellW,14*cellH,cellW+.5,cellH+.5);
}


/* ── Tron Match Runner ──────────────────────────────────────────────────── */

function runTronMatch(config, strategyA, strategyB) {
  const game = new TronGame(config);
  const fnA = TRON_STRATEGIES[strategyA].fn, fnB = TRON_STRATEGIES[strategyB].fn;
  const history = [];
  history.push({ turn:0, grid:game.getGrid(), agentA:null, agentB:null, winner:null, scoreA:0, scoreB:0 });
  while (!game.over) {
    const st = game.getAIState();
    const rA = fnA(st, 'A'), rB = fnB(st, 'B');
    game.step(rA.move, rB.move);
    let tA=0, tB=0;
    for (let y=0;y<game.H;y++) for (let x=0;x<game.W;x++) {
      const v = game.grid[y][x];
      if (v===1||v===3) tA++; if (v===2||v===4) tB++;
    }
    history.push({
      turn: game.turn, grid: game.getGrid(),
      agentA: { move: DIR_NAME[rA.move], reasoning: rA.reasoning },
      agentB: { move: DIR_NAME[rB.move], reasoning: rB.reasoning },
      winner: game.winner, scoreA: tA, scoreB: tB,
    });
  }
  return history;
}


/* ═══════════════════════════════════════════════════════════════════════════
   Othello (Reversi) Game Engine
   ═══════════════════════════════════════════════════════════════════════════ */

const OTH_DIRS = [[-1,-1],[-1,0],[-1,1],[0,-1],[0,1],[1,-1],[1,0],[1,1]];

class OthelloGame {
  constructor() {
    this.board = Array.from({length: 8}, () => Array(8).fill(0));
    this.board[3][3] = -1; this.board[3][4] = 1;
    this.board[4][3] = 1;  this.board[4][4] = -1;
    this.turn = 1; // 1 = Agent A (dark first)
    this.ply = 0;
    this.over = false;
    this.winner = null;
    this.lastMove = null;
    this.passes = 0;
  }

  _flips(r, c, player) {
    if (this.board[r][c] !== 0) return [];
    const all = [];
    for (const [dr, dc] of OTH_DIRS) {
      const line = [];
      let nr = r+dr, nc = c+dc;
      while (nr>=0&&nr<8&&nc>=0&&nc<8&&this.board[nr][nc]===-player) {
        line.push([nr, nc]); nr += dr; nc += dc;
      }
      if (line.length > 0 && nr>=0&&nr<8&&nc>=0&&nc<8&&this.board[nr][nc]===player) all.push(...line);
    }
    return all;
  }

  getLegalMoves() {
    const moves = [];
    for (let r=0;r<8;r++) for (let c=0;c<8;c++) {
      const fl = this._flips(r, c, this.turn);
      if (fl.length > 0) moves.push({ r, c, flips: fl });
    }
    return moves;
  }

  makeMove(r, c) {
    const flips = this._flips(r, c, this.turn);
    if (!flips.length) return false;
    this.board[r][c] = this.turn;
    for (const [fr, fc] of flips) this.board[fr][fc] = this.turn;
    this.lastMove = [r, c]; this.ply++; this.passes = 0;
    this.turn *= -1;
    this._checkEnd();
    return true;
  }

  _checkEnd() {
    if (this.getLegalMoves().length === 0) {
      this.passes++;
      this.turn *= -1;
      if (this.getLegalMoves().length === 0) this._endGame();
    }
  }

  _endGame() {
    this.over = true;
    let a=0, b=0;
    for (let r=0;r<8;r++) for (let c=0;c<8;c++) {
      if (this.board[r][c]===1) a++; else if (this.board[r][c]===-1) b++;
    }
    this.winner = a>b ? 'A' : b>a ? 'B' : 'draw';
  }

  countPieces() {
    let a=0, b=0;
    for (let r=0;r<8;r++) for (let c=0;c<8;c++) {
      if (this.board[r][c]===1) a++; else if (this.board[r][c]===-1) b++;
    }
    return { a, b };
  }

  getBoard() { return this.board.map(r => [...r]); }
}


/* ── Othello AI ─────────────────────────────────────────────────────────── */

const OTH_WEIGHTS = [
  [120,-20,20, 5, 5,20,-20,120],
  [-20,-40,-5,-5,-5,-5,-40,-20],
  [ 20, -5,15, 3, 3,15, -5, 20],
  [  5, -5, 3, 3, 3, 3, -5,  5],
  [  5, -5, 3, 3, 3, 3, -5,  5],
  [ 20, -5,15, 3, 3,15, -5, 20],
  [-20,-40,-5,-5,-5,-5,-40,-20],
  [120,-20,20, 5, 5,20,-20,120],
];

function othSqName(r, c) { return String.fromCharCode(97+c) + (8-r); }

function othCornerGrabberAI(game) {
  const moves = game.getLegalMoves();
  if (!moves.length) return null;
  const scored = moves.map(m => ({ ...m, score: OTH_WEIGHTS[m.r][m.c], name: othSqName(m.r,m.c) }));
  scored.sort((a,b) => b.score - a.score);
  const top = scored.slice(0,4);
  const lines = top.map((m,i) => `  ${i+1}. ${m.name}: wt ${m.score}, ${m.flips.length} flips`);
  return { r: scored[0].r, c: scored[0].c, reasoning: `CORNER-GRAB\n${lines.join('\n')}\n=> ${scored[0].name}` };
}

function othMaximizerAI(game) {
  const moves = game.getLegalMoves();
  if (!moves.length) return null;
  const scored = moves.map(m => ({ ...m, score: m.flips.length, name: othSqName(m.r,m.c) }));
  scored.sort((a,b) => b.score - a.score);
  const top = scored.slice(0,4);
  const lines = top.map((m,i) => `  ${i+1}. ${m.name}: ${m.score} flips`);
  return { r: scored[0].r, c: scored[0].c, reasoning: `MAXIMIZER\n${lines.join('\n')}\n=> ${scored[0].name}` };
}

function othPositionalAI(game) {
  const moves = game.getLegalMoves();
  if (!moves.length) return null;
  const scored = moves.map(m => ({ ...m, score: OTH_WEIGHTS[m.r][m.c] + m.flips.length*2, name: othSqName(m.r,m.c) }));
  scored.sort((a,b) => b.score - a.score);
  const top = scored.slice(0,4);
  const lines = top.map((m,i) => `  ${i+1}. ${m.name}: ${m.score} (wt ${OTH_WEIGHTS[m.r][m.c]}+${m.flips.length} flips)`);
  return { r: scored[0].r, c: scored[0].c, reasoning: `POSITIONAL\n${lines.join('\n')}\n=> ${scored[0].name}` };
}

const OTHELLO_STRATEGIES = {
  corner_grabber: { name: 'Corner Grabber', fn: othCornerGrabberAI, desc: 'Prioritizes corners and edges',
                    personality: { aggression: 40, caution: 80, greed: 70 } },
  maximizer:      { name: 'Maximizer',      fn: othMaximizerAI,    desc: 'Flips as many pieces as possible',
                    personality: { aggression: 70, caution: 20, greed: 95 } },
  positional:     { name: 'Positional',     fn: othPositionalAI,   desc: 'Balances position value with captures',
                    personality: { aggression: 50, caution: 60, greed: 50 } },
};


/* ── Othello Rendering ──────────────────────────────────────────────────── */

function renderOthelloFrame(ctx, frame, size) {
  const board = frame.board, sq = size/8, radius = sq*0.42;
  for (let r=0;r<8;r++) for (let c=0;c<8;c++) {
    ctx.fillStyle = '#2E7D32'; ctx.fillRect(c*sq, r*sq, sq, sq);
    ctx.strokeStyle = '#1B5E20'; ctx.lineWidth = 1; ctx.strokeRect(c*sq, r*sq, sq, sq);
    if (board[r][c] !== 0) {
      const cx = c*sq+sq/2, cy = r*sq+sq/2;
      const isLast = frame.lastMove && frame.lastMove[0]===r && frame.lastMove[1]===c;
      ctx.beginPath(); ctx.arc(cx+1, cy+1, radius, 0, Math.PI*2);
      ctx.fillStyle = 'rgba(0,0,0,0.3)'; ctx.fill();
      ctx.beginPath(); ctx.arc(cx, cy, radius, 0, Math.PI*2);
      ctx.fillStyle = board[r][c]===1 ? ARC3[9] : ARC3[8]; ctx.fill();
      if (isLast) { ctx.strokeStyle=ARC3[11]; ctx.lineWidth=2; ctx.stroke(); }
    }
  }
}

function renderOthelloPreview(canvas) {
  const size=120; canvas.width=size; canvas.height=size;
  const ctx=canvas.getContext('2d'), sq=size/8, radius=sq*0.38;
  for (let r=0;r<8;r++) for (let c=0;c<8;c++) {
    ctx.fillStyle='#2E7D32'; ctx.fillRect(c*sq,r*sq,sq,sq);
    ctx.strokeStyle='#1B5E20'; ctx.lineWidth=0.5; ctx.strokeRect(c*sq,r*sq,sq,sq);
  }
  for (const [r,c,p] of [[3,3,-1],[3,4,1],[4,3,1],[4,4,-1]]) {
    ctx.beginPath(); ctx.arc(c*sq+sq/2,r*sq+sq/2,radius,0,Math.PI*2);
    ctx.fillStyle = p===1 ? ARC3[9] : ARC3[8]; ctx.fill();
  }
}


/* ── Othello Match Runner ───────────────────────────────────────────────── */

function runOthelloMatch(config, strategyA, strategyB) {
  const game = new OthelloGame();
  const fnA = OTHELLO_STRATEGIES[strategyA].fn, fnB = OTHELLO_STRATEGIES[strategyB].fn;
  const history = [];
  const cnt0 = game.countPieces();
  history.push({ turn:0, board:game.getBoard(), lastMove:null, agentA:null, agentB:null, winner:null, scoreA:cnt0.a, scoreB:cnt0.b });
  while (!game.over) {
    const isA = game.turn === 1;
    const moves = game.getLegalMoves();
    if (!moves.length) { game.passes++; game.turn*=-1; if (game.getLegalMoves().length===0) game._endGame(); continue; }
    const result = (isA ? fnA : fnB)(game);
    if (!result) { game.passes++; game.turn*=-1; continue; }
    const moveName = othSqName(result.r, result.c);
    game.makeMove(result.r, result.c);
    const cnt = game.countPieces();
    history.push({
      turn: game.ply, board: game.getBoard(), lastMove: game.lastMove ? [...game.lastMove] : null,
      agentA: isA ? { move: moveName, reasoning: result.reasoning } : null,
      agentB: !isA ? { move: moveName, reasoning: result.reasoning } : null,
      winner: game.winner, scoreA: cnt.a, scoreB: cnt.b,
    });
  }
  return history;
}


/* ═══════════════════════════════════════════════════════════════════════════
   Go 9x9 Game Engine
   ═══════════════════════════════════════════════════════════════════════════ */

const GO_SIZE = 9, GO_KOMI = 6.5;
const GO_LETTERS = 'ABCDEFGHJ';
const GO_STAR = [[2,2],[2,6],[4,4],[6,2],[6,6]];

class GoGame {
  constructor(config = {}) {
    this.size = GO_SIZE;
    this.board = Array.from({length: this.size}, () => Array(this.size).fill(0));
    this.turn = 1;  // 1 = Black (Agent A), -1 = White (Agent B)
    this.ply = 0;
    this.over = false;
    this.winner = null;
    this.lastMove = null;
    this.prevBoard = null;
    this.passes = 0;
    this.capturedByA = 0;
    this.capturedByB = 0;
    this.maxPly = config.maxMoves || 120;
  }

  _getGroup(r, c) {
    const color = this.board[r][c];
    if (color === 0) return { stones: [], liberties: new Set() };
    const stones = [], liberties = new Set(), visited = new Set([`${r},${c}`]);
    const queue = [[r, c]];
    while (queue.length) {
      const [cr, cc] = queue.shift();
      stones.push([cr, cc]);
      for (const [dr, dc] of [[0,1],[0,-1],[1,0],[-1,0]]) {
        const nr = cr+dr, nc = cc+dc;
        if (nr<0||nr>=this.size||nc<0||nc>=this.size) continue;
        const key = `${nr},${nc}`;
        if (visited.has(key)) continue;
        if (this.board[nr][nc]===0) liberties.add(key);
        else if (this.board[nr][nc]===color) { visited.add(key); queue.push([nr, nc]); }
      }
    }
    return { stones, liberties };
  }

  _boardKey() { return this.board.map(r => r.join('')).join('/'); }

  isLegalMove(r, c) {
    if (r<0||r>=this.size||c<0||c>=this.size||this.board[r][c]!==0) return false;
    this.board[r][c] = this.turn;

    // Check captures
    let captures = 0;
    for (const [dr,dc] of [[0,1],[0,-1],[1,0],[-1,0]]) {
      const nr = r+dr, nc = c+dc;
      if (nr>=0&&nr<this.size&&nc>=0&&nc<this.size&&this.board[nr][nc]===-this.turn) {
        if (this._getGroup(nr,nc).liberties.size===0) captures++;
      }
    }
    const isSuicide = this._getGroup(r,c).liberties.size===0 && captures===0;

    // Ko check
    let isKo = false;
    if (captures > 0 && !isSuicide) {
      const saved = this.board.map(row => [...row]);
      for (const [dr,dc] of [[0,1],[0,-1],[1,0],[-1,0]]) {
        const nr=r+dr, nc=c+dc;
        if (nr>=0&&nr<this.size&&nc>=0&&nc<this.size&&this.board[nr][nc]===-this.turn) {
          const g = this._getGroup(nr,nc);
          if (g.liberties.size===0) for (const [sr,sc] of g.stones) this.board[sr][sc]=0;
        }
      }
      if (this.prevBoard && this._boardKey()===this.prevBoard) isKo = true;
      for (let i=0;i<this.size;i++) for (let j=0;j<this.size;j++) this.board[i][j]=saved[i][j];
    }

    this.board[r][c] = 0;
    return !isSuicide && !isKo;
  }

  getLegalMoves() {
    const moves = [];
    for (let r=0;r<this.size;r++) for (let c=0;c<this.size;c++)
      if (this.isLegalMove(r,c)) moves.push([r,c]);
    return moves;
  }

  makeMove(r, c) {
    if (!this.isLegalMove(r,c)) return false;
    this.prevBoard = this._boardKey();
    this.board[r][c] = this.turn;
    this.lastMove = [r,c];
    for (const [dr,dc] of [[0,1],[0,-1],[1,0],[-1,0]]) {
      const nr=r+dr, nc=c+dc;
      if (nr>=0&&nr<this.size&&nc>=0&&nc<this.size&&this.board[nr][nc]===-this.turn) {
        const g = this._getGroup(nr,nc);
        if (g.liberties.size===0) {
          for (const [sr,sc] of g.stones) this.board[sr][sc]=0;
          if (this.turn===1) this.capturedByA += g.stones.length;
          else this.capturedByB += g.stones.length;
        }
      }
    }
    this.passes = 0; this.turn *= -1; this.ply++;
    if (this.ply >= this.maxPly) this._endGame();
    return true;
  }

  pass() {
    this.prevBoard = this._boardKey();
    this.passes++; this.lastMove = null; this.turn *= -1; this.ply++;
    if (this.passes >= 2) this._endGame();
  }

  scoreTerritory() {
    const visited = new Set();
    let black = 0, white = 0;
    for (let r=0;r<this.size;r++) for (let c=0;c<this.size;c++) {
      if (this.board[r][c]===1) { black++; continue; }
      if (this.board[r][c]===-1) { white++; continue; }
      if (visited.has(`${r},${c}`)) continue;
      const region = [], borders = new Set(), queue = [[r,c]];
      visited.add(`${r},${c}`);
      while (queue.length) {
        const [cr,cc] = queue.shift(); region.push([cr,cc]);
        for (const [dr,dc] of [[0,1],[0,-1],[1,0],[-1,0]]) {
          const nr=cr+dr, nc=cc+dc;
          if (nr<0||nr>=this.size||nc<0||nc>=this.size) continue;
          if (this.board[nr][nc]!==0) { borders.add(this.board[nr][nc]); continue; }
          const key = `${nr},${nc}`;
          if (!visited.has(key)) { visited.add(key); queue.push([nr,nc]); }
        }
      }
      if (borders.size===1) {
        const owner = borders.values().next().value;
        if (owner===1) black += region.length; else white += region.length;
      }
    }
    return { black, white: white + GO_KOMI };
  }

  _endGame() {
    this.over = true;
    const s = this.scoreTerritory();
    this.winner = s.black > s.white ? 'A' : s.white > s.black ? 'B' : 'draw';
  }

  getBoard() { return this.board.map(r => [...r]); }
}


/* ── Go AI ──────────────────────────────────────────────────────────────── */

const GO_POS_W = (() => {
  const w = Array.from({length:9}, () => Array(9).fill(0));
  for (let r=0;r<9;r++) for (let c=0;c<9;c++) {
    const edge = Math.min(Math.min(r,8-r), Math.min(c,8-c));
    w[r][c] = [0,2,5,4,3][Math.min(edge,4)];
  }
  for (const [r,c] of GO_STAR) w[r][c] += 2;
  return w;
})();

function goMoveName(r, c) { return `${GO_LETTERS[c]}${GO_SIZE-r}`; }

function goTerritorialAI(game) {
  const moves = game.getLegalMoves();
  if (!moves.length) return null;
  // Only pass if board is very full (>60 stones placed)
  let stoneCount = 0;
  for (let r=0;r<9;r++) for (let c=0;c<9;c++) if (game.board[r][c]!==0) stoneCount++;
  if (stoneCount > 60 && game.ply > 50) return null;

  const scored = moves.map(([r,c]) => {
    let score = GO_POS_W[r][c];
    // Connection bonus
    for (const [dr,dc] of [[0,1],[0,-1],[1,0],[-1,0]]) {
      const nr=r+dr, nc=c+dc;
      if (nr>=0&&nr<9&&nc>=0&&nc<9) {
        if (game.board[nr][nc]===game.turn) score += 3;
        // Defend own groups in atari (urgent!)
        if (game.board[nr][nc]===game.turn) {
          const g = game._getGroup(nr,nc);
          if (g.liberties.size===1) score += 20; // Save group
          else if (g.liberties.size===2) score += 5;
        }
      }
    }
    game.board[r][c] = game.turn;
    const g = game._getGroup(r,c);
    if (g.liberties.size <= 1) score -= 15;
    else score += Math.min(g.liberties.size, 4);
    // Check if this move captures
    let captures = 0;
    for (const [dr,dc] of [[0,1],[0,-1],[1,0],[-1,0]]) {
      const nr=r+dr, nc=c+dc;
      if (nr>=0&&nr<9&&nc>=0&&nc<9&&game.board[nr][nc]===-game.turn) {
        if (game._getGroup(nr,nc).liberties.size===0) captures++;
      }
    }
    score += captures * 10;
    game.board[r][c] = 0;
    return { r, c, score, name: goMoveName(r,c) };
  });
  scored.sort((a,b) => b.score - a.score);
  if (scored[0].score < -5) return null;
  const top = scored.slice(0,3);
  const lines = top.map((m,i) => `  ${i+1}. ${m.name}: ${m.score}`);
  return { r:scored[0].r, c:scored[0].c, reasoning: `TERRITORIAL\n${lines.join('\n')}\n=> ${scored[0].name}` };
}

function goAggressiveAI(game) {
  const moves = game.getLegalMoves();
  if (!moves.length) return null;
  let stoneCount = 0;
  for (let r=0;r<9;r++) for (let c=0;c<9;c++) if (game.board[r][c]!==0) stoneCount++;
  if (stoneCount > 60 && game.ply > 50) return null;
  const opp = -game.turn;
  const scored = moves.map(([r,c]) => {
    let score = GO_POS_W[r][c];
    game.board[r][c] = game.turn;
    let captures = 0;
    for (const [dr,dc] of [[0,1],[0,-1],[1,0],[-1,0]]) {
      const nr=r+dr, nc=c+dc;
      if (nr>=0&&nr<9&&nc>=0&&nc<9) {
        if (game.board[nr][nc]===opp) {
          const g = game._getGroup(nr,nc);
          if (g.liberties.size===0) captures += g.stones.length;
          else if (g.liberties.size===1) score += 8;
          else if (g.liberties.size===2) score += 3;
        }
        if (game.board[nr][nc]===opp) score += 2;
      }
    }
    score += captures * 15;
    const own = game._getGroup(r,c);
    if (own.liberties.size<=1 && captures===0) score -= 10;
    game.board[r][c] = 0;
    return { r, c, score, captures, name: goMoveName(r,c) };
  });
  scored.sort((a,b) => b.score - a.score);
  if (scored[0].score < 0) return null;
  const top = scored.slice(0,3);
  const lines = top.map((m,i) => `  ${i+1}. ${m.name}: ${m.score}${m.captures?` (cap ${m.captures})`:''}`);
  return { r:scored[0].r, c:scored[0].c, reasoning: `AGGRESSIVE\n${lines.join('\n')}\n=> ${scored[0].name}` };
}

function goBalancedAI(game) {
  const moves = game.getLegalMoves();
  if (!moves.length) return null;
  let stoneCount = 0;
  for (let r=0;r<9;r++) for (let c=0;c<9;c++) if (game.board[r][c]!==0) stoneCount++;
  if (stoneCount > 60 && game.ply > 50) return null;
  const opp = -game.turn;
  const scored = moves.map(([r,c]) => {
    let score = GO_POS_W[r][c] * 2;
    game.board[r][c] = game.turn;
    let captures = 0;
    for (const [dr,dc] of [[0,1],[0,-1],[1,0],[-1,0]]) {
      const nr=r+dr, nc=c+dc;
      if (nr>=0&&nr<9&&nc>=0&&nc<9&&game.board[nr][nc]===opp) {
        const g = game._getGroup(nr,nc);
        if (g.liberties.size===0) captures += g.stones.length;
      }
    }
    score += captures * 12;
    const own = game._getGroup(r,c);
    score += Math.min(own.liberties.size, 4) * 2;
    if (own.liberties.size<=1 && captures===0) score -= 15;
    if (own.stones.length > 1) score += 3;
    game.board[r][c] = 0;
    return { r, c, score, name: goMoveName(r,c) };
  });
  scored.sort((a,b) => b.score - a.score);
  if (scored[0].score < -5) return null;
  const top = scored.slice(0,3);
  const lines = top.map((m,i) => `  ${i+1}. ${m.name}: ${m.score}`);
  return { r:scored[0].r, c:scored[0].c, reasoning: `BALANCED\n${lines.join('\n')}\n=> ${scored[0].name}` };
}

const GO_STRATEGIES = {
  territorial: { name: 'Territorial', fn: goTerritorialAI, desc: 'Claims corners and edges, builds territory',
                 personality: { aggression: 20, caution: 80, greed: 70 } },
  aggressive:  { name: 'Aggressive',  fn: goAggressiveAI,  desc: 'Invades, cuts, and captures opponent stones',
                 personality: { aggression: 90, caution: 20, greed: 50 } },
  balanced:    { name: 'Balanced',    fn: goBalancedAI,    desc: 'Balances territory, captures, and connection',
                 personality: { aggression: 50, caution: 50, greed: 50 } },
};


/* ── Go Rendering ───────────────────────────────────────────────────────── */

function renderGoFrame(ctx, frame, size) {
  const board = frame.board, margin = size*0.06, inner = size-margin*2, step = inner/(GO_SIZE-1);
  ctx.fillStyle = '#DEB887'; ctx.fillRect(0, 0, size, size);
  ctx.strokeStyle = '#8B7355'; ctx.lineWidth = 1;
  for (let i=0;i<GO_SIZE;i++) {
    const p = margin+i*step;
    ctx.beginPath(); ctx.moveTo(margin,p); ctx.lineTo(size-margin,p); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(p,margin); ctx.lineTo(p,size-margin); ctx.stroke();
  }
  for (const [r,c] of GO_STAR) {
    ctx.beginPath(); ctx.arc(margin+c*step, margin+r*step, 3, 0, Math.PI*2);
    ctx.fillStyle='#8B7355'; ctx.fill();
  }
  const stoneR = step*0.45;
  for (let r=0;r<GO_SIZE;r++) for (let c=0;c<GO_SIZE;c++) {
    if (board[r][c]===0) continue;
    const x=margin+c*step, y=margin+r*step;
    const isLast = frame.lastMove && frame.lastMove[0]===r && frame.lastMove[1]===c;
    ctx.beginPath(); ctx.arc(x+1.5,y+1.5,stoneR,0,Math.PI*2);
    ctx.fillStyle='rgba(0,0,0,0.3)'; ctx.fill();
    ctx.beginPath(); ctx.arc(x,y,stoneR,0,Math.PI*2);
    ctx.fillStyle = board[r][c]===1 ? '#111' : '#EEE'; ctx.fill();
    ctx.strokeStyle = board[r][c]===1 ? '#000' : '#CCC'; ctx.lineWidth=1; ctx.stroke();
    if (isLast) {
      ctx.beginPath(); ctx.arc(x,y,stoneR*0.35,0,Math.PI*2);
      ctx.fillStyle = board[r][c]===1 ? '#FFF' : '#F00'; ctx.fill();
    }
  }
  ctx.font = `bold ${margin*0.55}px monospace`; ctx.fillStyle='#8B7355';
  for (let c=0;c<GO_SIZE;c++) { ctx.textAlign='center'; ctx.textBaseline='top'; ctx.fillText(GO_LETTERS[c], margin+c*step, size-margin+4); }
  for (let r=0;r<GO_SIZE;r++) { ctx.textAlign='right'; ctx.textBaseline='middle'; ctx.fillText(String(GO_SIZE-r), margin-5, margin+r*step); }
}

function renderGoPreview(canvas) {
  const size=120; canvas.width=size; canvas.height=size;
  const ctx=canvas.getContext('2d'), margin=size*0.08, inner=size-margin*2, step=inner/8;
  ctx.fillStyle='#DEB887'; ctx.fillRect(0,0,size,size);
  ctx.strokeStyle='#8B7355'; ctx.lineWidth=0.5;
  for (let i=0;i<9;i++) {
    const p=margin+i*step;
    ctx.beginPath(); ctx.moveTo(margin,p); ctx.lineTo(size-margin,p); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(p,margin); ctx.lineTo(p,size-margin); ctx.stroke();
  }
  for (const [r,c] of GO_STAR) {
    ctx.beginPath(); ctx.arc(margin+c*step,margin+r*step,2,0,Math.PI*2);
    ctx.fillStyle='#8B7355'; ctx.fill();
  }
  const sr = step*0.4;
  for (const [r,c,p] of [[2,2,1],[2,6,-1],[3,3,1],[3,5,-1],[4,4,1],[5,3,-1],[6,6,1]]) {
    ctx.beginPath(); ctx.arc(margin+c*step,margin+r*step,sr,0,Math.PI*2);
    ctx.fillStyle = p===1 ? '#111' : '#EEE'; ctx.fill();
    ctx.strokeStyle = p===1 ? '#000' : '#CCC'; ctx.lineWidth=0.5; ctx.stroke();
  }
}


/* ── Go Match Runner ────────────────────────────────────────────────────── */

function runGoMatch(config, strategyA, strategyB) {
  const game = new GoGame(config);
  const fnA = GO_STRATEGIES[strategyA].fn, fnB = GO_STRATEGIES[strategyB].fn;
  const history = [];
  history.push({ turn:0, board:game.getBoard(), lastMove:null, agentA:null, agentB:null, winner:null, scoreA:0, scoreB:GO_KOMI });
  while (!game.over) {
    const isA = game.turn === 1;
    const result = (isA ? fnA : fnB)(game);
    if (!result) {
      game.pass();
      const s = game.scoreTerritory();
      history.push({
        turn: game.ply, board: game.getBoard(), lastMove: null,
        agentA: isA ? { move:'PASS', reasoning:'No good moves' } : null,
        agentB: !isA ? { move:'PASS', reasoning:'No good moves' } : null,
        winner: game.winner, scoreA: s.black, scoreB: s.white,
      });
    } else {
      const moveName = goMoveName(result.r, result.c);
      game.makeMove(result.r, result.c);
      const s = game.scoreTerritory();
      history.push({
        turn: game.ply, board: game.getBoard(), lastMove: game.lastMove ? [...game.lastMove] : null,
        agentA: isA ? { move:moveName, reasoning:result.reasoning } : null,
        agentB: !isA ? { move:moveName, reasoning:result.reasoning } : null,
        winner: game.winner, scoreA: s.black, scoreB: s.white,
      });
    }
  }
  return history;
}


/* ═══════════════════════════════════════════════════════════════════════════
   Gomoku (5-in-a-Row) Game Engine — 15x15 board
   ═══════════════════════════════════════════════════════════════════════════ */

const GMK_SIZE = 15;

class GomokuGame {
  constructor() {
    this.size = GMK_SIZE;
    this.board = Array.from({length: this.size}, () => Array(this.size).fill(0));
    this.turn = 1; // 1 = Black (A), -1 = White (B)
    this.ply = 0;
    this.over = false;
    this.winner = null;
    this.lastMove = null;
  }

  getLegalMoves() {
    const moves = [];
    for (let r=0;r<this.size;r++) for (let c=0;c<this.size;c++)
      if (this.board[r][c]===0) moves.push([r,c]);
    return moves;
  }

  makeMove(r, c) {
    if (this.board[r][c]!==0) return false;
    this.board[r][c] = this.turn;
    this.lastMove = [r, c];
    this.ply++;
    if (this._checkWin(r, c, this.turn)) {
      this.over = true;
      this.winner = this.turn===1 ? 'A' : 'B';
    } else if (this.ply >= this.size*this.size) {
      this.over = true;
      this.winner = 'draw';
    }
    this.turn *= -1;
    return true;
  }

  _checkWin(r, c, p) {
    const dirs = [[0,1],[1,0],[1,1],[1,-1]];
    for (const [dr,dc] of dirs) {
      let count = 1;
      for (let i=1;i<5;i++) { const nr=r+dr*i,nc=c+dc*i; if (nr<0||nr>=this.size||nc<0||nc>=this.size||this.board[nr][nc]!==p) break; count++; }
      for (let i=1;i<5;i++) { const nr=r-dr*i,nc=c-dc*i; if (nr<0||nr>=this.size||nc<0||nc>=this.size||this.board[nr][nc]!==p) break; count++; }
      if (count >= 5) return true;
    }
    return false;
  }

  getBoard() { return this.board.map(r => [...r]); }
}


/* ── Gomoku AI ──────────────────────────────────────────────────────────── */

function gmkLineScore(board, r, c, player, size) {
  // Score a position by counting lines through it in all directions
  const opp = -player;
  const dirs = [[0,1],[1,0],[1,1],[1,-1]];
  let total = 0;
  for (const [dr,dc] of dirs) {
    let mine = 1, open = 0;
    // Forward
    let blocked = false;
    for (let i=1;i<5;i++) {
      const nr=r+dr*i, nc=c+dc*i;
      if (nr<0||nr>=size||nc<0||nc>=size||board[nr][nc]===opp) { blocked=true; break; }
      if (board[nr][nc]===player) mine++; else { open++; break; }
    }
    if (!blocked) open++;
    // Backward
    blocked = false;
    for (let i=1;i<5;i++) {
      const nr=r-dr*i, nc=c-dc*i;
      if (nr<0||nr>=size||nc<0||nc>=size||board[nr][nc]===opp) { blocked=true; break; }
      if (board[nr][nc]===player) mine++; else { open++; break; }
    }
    if (!blocked) open++;
    // Score based on line length and openness
    if (mine >= 5) total += 100000;
    else if (mine === 4 && open >= 1) total += 10000;
    else if (mine === 3 && open >= 2) total += 1000;
    else if (mine === 3 && open === 1) total += 100;
    else if (mine === 2 && open >= 2) total += 50;
    else if (mine === 2 && open === 1) total += 10;
  }
  return total;
}

function gmkNearbyMoves(game, radius) {
  // Only consider moves near existing stones (much faster than all 225 moves)
  const moves = new Set();
  for (let r=0;r<game.size;r++) for (let c=0;c<game.size;c++) {
    if (game.board[r][c] === 0) continue;
    for (let dr=-radius;dr<=radius;dr++) for (let dc=-radius;dc<=radius;dc++) {
      const nr=r+dr, nc=c+dc;
      if (nr>=0&&nr<game.size&&nc>=0&&nc<game.size&&game.board[nr][nc]===0) moves.add(nr*game.size+nc);
    }
  }
  if (moves.size === 0) return [[7, 7]]; // First move: center
  return [...moves].map(v => [Math.floor(v/game.size), v%game.size]);
}

function gmkOffensiveAI(game) {
  const moves = gmkNearbyMoves(game, 2);
  const scored = moves.map(([r,c]) => {
    const attack = gmkLineScore(game.board, r, c, game.turn, game.size);
    const defend = gmkLineScore(game.board, r, c, -game.turn, game.size);
    return { r, c, score: attack * 1.2 + defend, attack, defend,
             name: `${String.fromCharCode(65+c)}${game.size-r}` };
  });
  scored.sort((a,b) => b.score - a.score);
  const top = scored.slice(0,3);
  const lines = top.map((m,i) => `  ${i+1}. ${m.name}: atk ${m.attack} def ${m.defend}`);
  return { r:scored[0].r, c:scored[0].c, reasoning: `OFFENSIVE\n${lines.join('\n')}\n=> ${scored[0].name}` };
}

function gmkDefensiveAI(game) {
  const moves = gmkNearbyMoves(game, 2);
  const scored = moves.map(([r,c]) => {
    const attack = gmkLineScore(game.board, r, c, game.turn, game.size);
    const defend = gmkLineScore(game.board, r, c, -game.turn, game.size);
    return { r, c, score: attack + defend * 1.5, attack, defend,
             name: `${String.fromCharCode(65+c)}${game.size-r}` };
  });
  scored.sort((a,b) => b.score - a.score);
  const top = scored.slice(0,3);
  const lines = top.map((m,i) => `  ${i+1}. ${m.name}: atk ${m.attack} def ${m.defend}`);
  return { r:scored[0].r, c:scored[0].c, reasoning: `DEFENSIVE\n${lines.join('\n')}\n=> ${scored[0].name}` };
}

function gmkBalancedAI(game) {
  const moves = gmkNearbyMoves(game, 2);
  const scored = moves.map(([r,c]) => {
    const attack = gmkLineScore(game.board, r, c, game.turn, game.size);
    const defend = gmkLineScore(game.board, r, c, -game.turn, game.size);
    // Center bonus
    const cx = Math.abs(c - 7), cy = Math.abs(r - 7);
    const center = Math.max(0, 7 - cx - cy) * 2;
    return { r, c, score: attack + defend + center, attack, defend,
             name: `${String.fromCharCode(65+c)}${game.size-r}` };
  });
  scored.sort((a,b) => b.score - a.score);
  const top = scored.slice(0,3);
  const lines = top.map((m,i) => `  ${i+1}. ${m.name}: ${m.score} (atk ${m.attack} def ${m.defend})`);
  return { r:scored[0].r, c:scored[0].c, reasoning: `BALANCED\n${lines.join('\n')}\n=> ${scored[0].name}` };
}

const GMK_STRATEGIES = {
  offensive: { name: 'Offensive', fn: gmkOffensiveAI, desc: 'Builds attacking lines, aims for 5-in-a-row fast',
               personality: { aggression: 85, caution: 20, greed: 70 } },
  defensive: { name: 'Defensive', fn: gmkDefensiveAI, desc: 'Blocks opponent threats, then builds own lines',
               personality: { aggression: 25, caution: 90, greed: 40 } },
  balanced:  { name: 'Balanced',  fn: gmkBalancedAI,  desc: 'Equal weight on attack, defense, and center control',
               personality: { aggression: 50, caution: 55, greed: 55 } },
};


/* ── Gomoku Rendering ───────────────────────────────────────────────────── */

function renderGomokuFrame(ctx, frame, size) {
  const board = frame.board, bsz = board.length;
  const margin = size*0.05, inner = size-margin*2, step = inner/(bsz-1);
  ctx.fillStyle = '#DEB887'; ctx.fillRect(0,0,size,size);
  ctx.strokeStyle = '#8B7355'; ctx.lineWidth = 0.8;
  for (let i=0;i<bsz;i++) {
    const p = margin+i*step;
    ctx.beginPath(); ctx.moveTo(margin,p); ctx.lineTo(size-margin,p); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(p,margin); ctx.lineTo(p,size-margin); ctx.stroke();
  }
  // Star points (3-3, 3-11, 7-7, 11-3, 11-11)
  for (const [r,c] of [[3,3],[3,11],[7,7],[11,3],[11,11]]) {
    ctx.beginPath(); ctx.arc(margin+c*step, margin+r*step, 2.5, 0, Math.PI*2);
    ctx.fillStyle='#8B7355'; ctx.fill();
  }
  const stoneR = step*0.44;
  for (let r=0;r<bsz;r++) for (let c=0;c<bsz;c++) {
    if (board[r][c]===0) continue;
    const x=margin+c*step, y=margin+r*step;
    const isLast = frame.lastMove && frame.lastMove[0]===r && frame.lastMove[1]===c;
    ctx.beginPath(); ctx.arc(x+1,y+1,stoneR,0,Math.PI*2);
    ctx.fillStyle='rgba(0,0,0,0.25)'; ctx.fill();
    ctx.beginPath(); ctx.arc(x,y,stoneR,0,Math.PI*2);
    ctx.fillStyle = board[r][c]===1 ? '#111' : '#EEE'; ctx.fill();
    ctx.strokeStyle = board[r][c]===1 ? '#000' : '#BBB'; ctx.lineWidth=0.8; ctx.stroke();
    if (isLast) {
      ctx.beginPath(); ctx.arc(x,y,stoneR*0.3,0,Math.PI*2);
      ctx.fillStyle = board[r][c]===1 ? '#F00' : '#F00'; ctx.fill();
    }
  }
}

function renderGomokuPreview(canvas) {
  const size=120; canvas.width=size; canvas.height=size;
  const ctx=canvas.getContext('2d'), margin=size*0.06, inner=size-margin*2, step=inner/14;
  ctx.fillStyle='#DEB887'; ctx.fillRect(0,0,size,size);
  ctx.strokeStyle='#8B7355'; ctx.lineWidth=0.4;
  for (let i=0;i<15;i++) {
    const p=margin+i*step;
    ctx.beginPath(); ctx.moveTo(margin,p); ctx.lineTo(size-margin,p); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(p,margin); ctx.lineTo(p,size-margin); ctx.stroke();
  }
  const sr=step*0.4;
  // Sample game position
  for (const [r,c,p] of [[7,7,1],[6,8,-1],[8,6,1],[5,9,-1],[6,6,1],[8,8,-1],[7,5,1]]) {
    ctx.beginPath(); ctx.arc(margin+c*step,margin+r*step,sr,0,Math.PI*2);
    ctx.fillStyle=p===1?'#111':'#EEE'; ctx.fill();
    ctx.strokeStyle=p===1?'#000':'#BBB'; ctx.lineWidth=0.4; ctx.stroke();
  }
}


/* ── Gomoku Match Runner ────────────────────────────────────────────────── */

function runGomokuMatch(config, strategyA, strategyB) {
  const game = new GomokuGame();
  const fnA = GMK_STRATEGIES[strategyA].fn, fnB = GMK_STRATEGIES[strategyB].fn;
  const history = [];
  history.push({ turn:0, board:game.getBoard(), lastMove:null, agentA:null, agentB:null, winner:null, scoreA:0, scoreB:0 });
  while (!game.over) {
    const isA = game.turn === 1;
    const result = (isA ? fnA : fnB)(game);
    if (!result) break;
    const name = `${String.fromCharCode(65+result.c)}${game.size-result.r}`;
    game.makeMove(result.r, result.c);
    // Score = number of stones placed
    let sA=0, sB=0;
    for (let r=0;r<game.size;r++) for (let c=0;c<game.size;c++) {
      if (game.board[r][c]===1) sA++; if (game.board[r][c]===-1) sB++;
    }
    history.push({
      turn: game.ply, board: game.getBoard(), lastMove: game.lastMove ? [...game.lastMove] : null,
      agentA: isA ? { move:name, reasoning:result.reasoning } : null,
      agentB: !isA ? { move:name, reasoning:result.reasoning } : null,
      winner: game.winner, scoreA: sA, scoreB: sB,
    });
  }
  return history;
}


/* ═══════════════════════════════════════════════════════════════════════════
   Artillery Game Engine — 2 tanks on terrain, move or shoot each turn
   ═══════════════════════════════════════════════════════════════════════════ */

const ART_W = 120, ART_H = 80;
const ART_GRAVITY = 0.15;
const ART_MAX_HP = 5;
const ART_MOVE_DIST = 3;
const ART_ANIM_FRAMES = 10;

function artGenerateTerrain(seed) {
  const rng = mulberry32(seed);
  const terrain = new Array(ART_W);
  terrain[0] = 30 + rng() * 15;
  terrain[ART_W-1] = 30 + rng() * 15;
  function subdivide(l, r, roughness) {
    if (r - l < 2) return;
    const mid = (l+r) >> 1;
    terrain[mid] = (terrain[l]+terrain[r])/2 + (rng()-0.5)*roughness;
    terrain[mid] = Math.max(10, Math.min(ART_H-10, terrain[mid]));
    subdivide(l, mid, roughness*0.6);
    subdivide(mid, r, roughness*0.6);
  }
  subdivide(0, ART_W-1, 20);
  for (let i=0;i<ART_W;i++) if (terrain[i]===undefined) terrain[i] = 35;
  return terrain.map(v => Math.round(v));
}

class ArtilleryGame {
  constructor(config = {}) {
    this.seed = config.seed || 42;
    this.terrain = artGenerateTerrain(this.seed);
    this.maxTurns = config.maxTurns || 20;
    this.turn = 1;
    this.ply = 0;
    this.over = false;
    this.winner = null;
    this.lastShot = null;
    this.lastMove = null;
    this.tankA = { x: 10, hp: ART_MAX_HP };
    this.tankB = { x: ART_W - 11, hp: ART_MAX_HP };
    this.tankA.y = ART_H - this.terrain[this.tankA.x];
    this.tankB.y = ART_H - this.terrain[this.tankB.x];
    this.windRng = mulberry32(this.seed * 7 + 13);
    this.wind = (this.windRng() - 0.5) * 0.4;
  }

  move(direction) {
    if (this.over) return;
    const isA = this.turn === 1;
    const tank = isA ? this.tankA : this.tankB;
    const delta = direction === 'left' ? -ART_MOVE_DIST : ART_MOVE_DIST;
    tank.x = Math.max(2, Math.min(ART_W - 3, tank.x + delta));
    tank.y = ART_H - this.terrain[tank.x];
    this.lastMove = { tank: isA ? 'A' : 'B', direction };
    this.lastShot = null;
    this._endTurn();
  }

  shoot(angle, power) {
    if (this.over) return;
    const isA = this.turn === 1;
    const tank = isA ? this.tankA : this.tankB;
    const target = isA ? this.tankB : this.tankA;
    const rad = angle * Math.PI / 180;
    const vx = Math.cos(rad) * power * 0.5;
    let vy = -Math.sin(rad) * power * 0.5;
    let px = tank.x, py = tank.y - 2;
    const trajectory = [[px, py]];
    let hit = false, hitTarget = false;

    for (let t = 0; t < 300; t++) {
      px += vx + this.wind;
      vy += ART_GRAVITY;
      py += vy;
      trajectory.push([px, py]);
      const ix = Math.round(px);
      if (ix < 0 || ix >= ART_W || py > ART_H) break;
      if (py >= ART_H - this.terrain[Math.max(0, Math.min(ART_W-1, ix))]) {
        hit = true;
        if (Math.abs(ix - target.x) <= 4 && py >= target.y - 3) {
          hitTarget = true;
          target.hp--;
          if (target.hp <= 0) { this.over = true; this.winner = isA ? 'A' : 'B'; }
        }
        break;
      }
    }

    this.lastShot = { trajectory, hit, hitTarget, shooter: isA ? 'A' : 'B',
                      angle, power, landX: trajectory[trajectory.length-1][0] };
    this.lastMove = null;
    this._endTurn();
  }

  _endTurn() {
    this.ply++;
    this.turn *= -1;
    this.wind = (this.windRng() - 0.5) * 0.4;
    if (!this.over && this.ply >= this.maxTurns * 2) {
      this.over = true;
      if (this.tankA.hp > this.tankB.hp) this.winner = 'A';
      else if (this.tankB.hp > this.tankA.hp) this.winner = 'B';
      else this.winner = 'draw';
    }
  }

  getState() {
    return {
      terrain: [...this.terrain], turn: this.turn, ply: this.ply, wind: this.wind,
      tankA: { ...this.tankA }, tankB: { ...this.tankB },
      lastShot: this.lastShot, lastMove: this.lastMove,
      over: this.over, winner: this.winner,
    };
  }
}


/* ── Artillery AI ───────────────────────────────────────────────────────── */

function artSimulateShot(me, game, angle, power) {
  const rad = angle * Math.PI / 180;
  const vx = Math.cos(rad) * power * 0.5;
  let px = me.x, py = me.y - 2, vy = -Math.sin(rad) * power * 0.5;
  let landX = px;
  for (let t = 0; t < 300; t++) {
    px += vx + game.wind;
    vy += ART_GRAVITY;
    py += vy;
    const ix = Math.round(px);
    if (ix < 0 || ix >= ART_W || py > ART_H) { landX = px; break; }
    if (py >= ART_H - game.terrain[Math.max(0, Math.min(ART_W-1, ix))]) { landX = px; break; }
  }
  return landX;
}

function artSniperAI(game) {
  const isA = game.turn === 1;
  const me = isA ? game.tankA : game.tankB;
  const target = isA ? game.tankB : game.tankA;
  const dx = target.x - me.x;
  const direction = dx > 0 ? 1 : -1;

  // Dodge if opponent's last shot landed close
  if (game.lastShot && game.lastShot.shooter !== (isA ? 'A' : 'B') && game.lastShot.hit) {
    const landDist = Math.abs(game.lastShot.landX - me.x);
    if (landDist < 6) {
      const dodgeDir = game.lastShot.landX > me.x ? 'left' : 'right';
      return { type: 'move', direction: dodgeDir,
        reasoning: `SNIPER\n  Incoming ${landDist.toFixed(1)} away\n  Dodging ${dodgeDir}` };
    }
  }

  // Precision shot with wind compensation
  let bestAngle = 0, bestPower = 5, bestDist = Infinity;
  for (let ang = 30; ang <= 80; ang += 2) {
    for (let pow = 3; pow <= 10; pow += 0.5) {
      const realAngle = direction > 0 ? ang : 180 - ang;
      const landX = artSimulateShot(me, game, realAngle, pow);
      const d = Math.abs(landX - target.x);
      if (d < bestDist) { bestDist = d; bestAngle = realAngle; bestPower = pow; }
    }
  }
  const lines = [`  Target: x=${target.x}  Wind: ${game.wind.toFixed(2)}`,
    `  Aim: ${bestAngle.toFixed(0)}\u00b0 P${bestPower.toFixed(1)}  Miss: ${bestDist.toFixed(1)}`];
  return { type: 'shoot', angle: bestAngle, power: bestPower,
    reasoning: `SNIPER\n${lines.join('\n')}` };
}

function artLobberAI(game) {
  const isA = game.turn === 1;
  const me = isA ? game.tankA : game.tankB;
  const target = isA ? game.tankB : game.tankA;
  const dx = target.x - me.x;
  const direction = dx > 0 ? 1 : -1;

  // Occasionally reposition forward
  const moveRng = mulberry32(game.ply * 37 + game.seed);
  if (moveRng() < 0.2 && Math.abs(dx) > 20) {
    const moveDir = direction > 0 ? 'right' : 'left';
    return { type: 'move', direction: moveDir,
      reasoning: `LOBBER\n  Closing distance\n  Moving ${moveDir}` };
  }

  // High arc shots with wind compensation
  let bestAngle = 0, bestPower = 5, bestDist = Infinity;
  for (let ang = 55; ang <= 82; ang += 2) {
    for (let pow = 4; pow <= 10; pow += 0.5) {
      const realAngle = direction > 0 ? ang : 180 - ang;
      const landX = artSimulateShot(me, game, realAngle, pow);
      const d = Math.abs(landX - target.x);
      if (d < bestDist) { bestDist = d; bestAngle = realAngle; bestPower = pow; }
    }
  }
  const lines = [`  High arc to x=${target.x}`, `  Aim: ${bestAngle.toFixed(0)}\u00b0 P${bestPower.toFixed(1)}`];
  return { type: 'shoot', angle: bestAngle, power: bestPower,
    reasoning: `LOBBER\n${lines.join('\n')}` };
}

function artRandomizerAI(game) {
  const isA = game.turn === 1;
  const me = isA ? game.tankA : game.tankB;
  const target = isA ? game.tankB : game.tankA;
  const dx = target.x - me.x;
  const direction = dx > 0 ? 1 : -1;

  // Move ~33% of turns
  const moveRng = mulberry32(game.ply * 53 + game.seed);
  if (moveRng() < 0.33) {
    const dirRng = mulberry32(game.ply * 71 + game.seed);
    const moveDir = dirRng() < 0.5 ? 'left' : 'right';
    return { type: 'move', direction: moveDir,
      reasoning: `WILDCARD\n  Chaos move ${moveDir}!` };
  }

  // Jittery shot
  const jitterRng = mulberry32(game.ply * 137 + game.seed);
  const jitter = (jitterRng() - 0.5) * 12;
  let bestAngle = 0, bestPower = 5, bestDist = Infinity;
  for (let ang = 35; ang <= 78; ang += 3) {
    for (let pow = 3; pow <= 10; pow += 0.7) {
      const realAngle = direction > 0 ? ang + jitter : 180 - ang - jitter;
      const landX = artSimulateShot(me, game, realAngle, pow);
      const d = Math.abs(landX - target.x);
      if (d < bestDist) { bestDist = d; bestAngle = realAngle; bestPower = pow; }
    }
  }
  const lines = [`  Jitter: ${jitter.toFixed(1)}\u00b0`, `  Aim: ${bestAngle.toFixed(0)}\u00b0 P${bestPower.toFixed(1)}`];
  return { type: 'shoot', angle: bestAngle, power: bestPower,
    reasoning: `WILDCARD\n${lines.join('\n')}` };
}

const ART_STRATEGIES = {
  sniper:     { name: 'Sniper',   fn: artSniperAI,     desc: 'Precise targeting with wind compensation, dodges incoming fire',
                personality: { aggression: 60, caution: 70, greed: 50 } },
  lobber:     { name: 'Lobber',   fn: artLobberAI,     desc: 'High arc shots, repositions to close distance',
                personality: { aggression: 40, caution: 50, greed: 60 } },
  randomizer: { name: 'Wildcard', fn: artRandomizerAI, desc: 'Unpredictable movement and jittery aim',
                personality: { aggression: 80, caution: 15, greed: 70 } },
};


/* ── Artillery Rendering ────────────────────────────────────────────────── */

function renderArtilleryFrame(ctx, frame, size) {
  const state = frame.state;
  const scaleX = size / ART_W, scaleY = size / ART_H;

  // Sky gradient
  const skyGrad = ctx.createLinearGradient(0, 0, 0, size);
  skyGrad.addColorStop(0, '#1a1a2e'); skyGrad.addColorStop(1, '#16213e');
  ctx.fillStyle = skyGrad; ctx.fillRect(0, 0, size, size);

  // Terrain fill
  ctx.beginPath(); ctx.moveTo(0, size);
  for (let x = 0; x < ART_W; x++) ctx.lineTo(x * scaleX, (ART_H - state.terrain[x]) * scaleY);
  ctx.lineTo(size, size); ctx.closePath();
  ctx.fillStyle = '#2d5a27'; ctx.fill();
  // Terrain outline
  ctx.beginPath();
  for (let x = 0; x < ART_W; x++) ctx[x === 0 ? 'moveTo' : 'lineTo'](x * scaleX, (ART_H - state.terrain[x]) * scaleY);
  ctx.strokeStyle = '#4a8c3f'; ctx.lineWidth = 1.5; ctx.stroke();

  // Trajectory trail (partial during flight, full on impact)
  if (frame.trail && frame.trail.length > 1) {
    ctx.beginPath();
    ctx.moveTo(frame.trail[0][0]*scaleX, frame.trail[0][1]*scaleY);
    for (let i = 1; i < frame.trail.length; i++) ctx.lineTo(frame.trail[i][0]*scaleX, frame.trail[i][1]*scaleY);
    ctx.strokeStyle = frame.shooter === 'A' ? 'rgba(249,60,49,0.5)' : 'rgba(255,133,27,0.5)';
    ctx.lineWidth = 1.5; ctx.setLineDash([4,3]); ctx.stroke(); ctx.setLineDash([]);
  }
  // Fallback: static trajectory from lastShot (non-animated frames)
  else if (state.lastShot && state.lastShot.trajectory.length > 1) {
    const traj = state.lastShot.trajectory;
    ctx.beginPath();
    ctx.moveTo(traj[0][0]*scaleX, traj[0][1]*scaleY);
    for (let i = 1; i < traj.length; i++) ctx.lineTo(traj[i][0]*scaleX, traj[i][1]*scaleY);
    ctx.strokeStyle = state.lastShot.shooter === 'A' ? 'rgba(249,60,49,0.5)' : 'rgba(255,133,27,0.5)';
    ctx.lineWidth = 1.5; ctx.setLineDash([4,3]); ctx.stroke(); ctx.setLineDash([]);
    const end = traj[traj.length-1];
    ctx.beginPath(); ctx.arc(end[0]*scaleX, end[1]*scaleY, state.lastShot.hitTarget ? 8 : 4, 0, Math.PI*2);
    ctx.fillStyle = state.lastShot.hitTarget ? ARC3[11] : 'rgba(255,200,50,0.5)'; ctx.fill();
  }

  // Projectile in flight
  if (frame.projectile) {
    const px = frame.projectile.x * scaleX, py = frame.projectile.y * scaleY;
    ctx.beginPath(); ctx.arc(px, py, 7, 0, Math.PI*2);
    ctx.fillStyle = 'rgba(255,220,0,0.25)'; ctx.fill();
    ctx.beginPath(); ctx.arc(px, py, 3, 0, Math.PI*2);
    ctx.fillStyle = ARC3[11]; ctx.fill();
    ctx.strokeStyle = '#FFF'; ctx.lineWidth = 1; ctx.stroke();
  }

  // Impact explosion
  if (frame.impact) {
    const ix = frame.impact.x * scaleX, iy = frame.impact.y * scaleY;
    const r = frame.impact.hitTarget ? 14 : 8;
    ctx.beginPath(); ctx.arc(ix, iy, r, 0, Math.PI*2);
    ctx.fillStyle = frame.impact.hitTarget ? 'rgba(249,60,49,0.5)' : 'rgba(255,200,50,0.35)';
    ctx.fill();
    ctx.beginPath(); ctx.arc(ix, iy, r * 0.5, 0, Math.PI*2);
    ctx.fillStyle = ARC3[11]; ctx.fill();
    ctx.beginPath(); ctx.arc(ix, iy, r * 0.2, 0, Math.PI*2);
    ctx.fillStyle = '#FFF'; ctx.fill();
  }

  // Tanks
  const drawTank = (tank, color, label) => {
    const tx = tank.x * scaleX, ty = tank.y * scaleY;
    ctx.fillStyle = color;
    ctx.fillRect(tx - 6*scaleX, ty - 3*scaleY, 12*scaleX, 3*scaleY);
    ctx.fillRect(tx - 2*scaleX, ty - 5*scaleY, 4*scaleX, 2*scaleY);
    const hpW = 14 * scaleX, hpH = 2 * scaleY;
    ctx.fillStyle = '#333'; ctx.fillRect(tx - hpW/2, ty - 8*scaleY, hpW, hpH);
    ctx.fillStyle = tank.hp > 1 ? ARC3[14] : ARC3[8];
    ctx.fillRect(tx - hpW/2, ty - 8*scaleY, hpW * (tank.hp / ART_MAX_HP), hpH);
    ctx.font = `bold ${10*scaleX}px monospace`; ctx.fillStyle = '#FFF';
    ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
    ctx.fillText(label, tx, ty - 9*scaleY);
  };
  drawTank(state.tankA, ARC3[8], 'A');
  drawTank(state.tankB, ARC3[12], 'B');

  // HUD
  ctx.font = `bold ${12}px monospace`; ctx.fillStyle = ARC3[2];
  ctx.textAlign = 'left'; ctx.textBaseline = 'top';
  const windStr = state.wind > 0.01 ? 'Wind >>' : state.wind < -0.01 ? '<< Wind' : 'Calm';
  ctx.fillText(`HP: A=${state.tankA.hp}  B=${state.tankB.hp}  ${windStr}`, 8, 8);
}

function renderArtilleryPreview(canvas) {
  const size = 120; canvas.width = size; canvas.height = size;
  const ctx = canvas.getContext('2d');
  const scaleX = size/ART_W, scaleY = size/ART_H;
  ctx.fillStyle = '#1a1a2e'; ctx.fillRect(0, 0, size, size);
  const terrain = artGenerateTerrain(42);
  ctx.beginPath(); ctx.moveTo(0, size);
  for (let x=0;x<ART_W;x++) ctx.lineTo(x*scaleX, (ART_H-terrain[x])*scaleY);
  ctx.lineTo(size, size); ctx.closePath();
  ctx.fillStyle = '#2d5a27'; ctx.fill();
  ctx.fillStyle = ARC3[8]; ctx.fillRect(10*scaleX-3, (ART_H-terrain[10])*scaleY-4, 6, 3);
  ctx.fillStyle = ARC3[12]; ctx.fillRect((ART_W-11)*scaleX-3, (ART_H-terrain[ART_W-11])*scaleY-4, 6, 3);
  ctx.beginPath(); ctx.moveTo(12*scaleX, (ART_H-terrain[10]-5)*scaleY);
  ctx.quadraticCurveTo(size/2, size*0.15, (ART_W-11)*scaleX, (ART_H-terrain[ART_W-11]-3)*scaleY);
  ctx.strokeStyle = 'rgba(249,60,49,0.4)'; ctx.lineWidth = 1; ctx.setLineDash([2,2]); ctx.stroke(); ctx.setLineDash([]);
}


/* ── Artillery Match Runner ─────────────────────────────────────────────── */

function runArtilleryMatch(config, strategyA, strategyB) {
  const game = new ArtilleryGame(config);
  const fnA = ART_STRATEGIES[strategyA].fn, fnB = ART_STRATEGIES[strategyB].fn;
  const history = [];

  // Initial frame
  history.push({ turn: 0, state: game.getState(), agentA: null, agentB: null,
    winner: null, scoreA: ART_MAX_HP, scoreB: ART_MAX_HP,
    projectile: null, impact: null, trail: null, shooter: null });

  while (!game.over) {
    const isA = game.turn === 1;
    const turnNum = game.ply + 1;
    const result = (isA ? fnA : fnB)(game);

    if (result.type === 'move') {
      const tank = isA ? game.tankA : game.tankB;
      const fromX = tank.x;
      game.move(result.direction);
      const postState = game.getState();
      const toX = (isA ? postState.tankA : postState.tankB).x;

      // 4 slide frames for tank movement animation
      for (let f = 0; f <= 3; f++) {
        const t = f / 3;
        const interpX = Math.round(fromX + (toX - fromX) * t);
        const clampX = Math.max(0, Math.min(ART_W - 1, interpX));
        const frameState = JSON.parse(JSON.stringify(postState));
        const movingTank = isA ? frameState.tankA : frameState.tankB;
        movingTank.x = f === 3 ? toX : clampX;
        movingTank.y = ART_H - frameState.terrain[Math.max(0, Math.min(ART_W-1, movingTank.x))];

        const agent = f === 0 ? { move: `Move ${result.direction}`, reasoning: result.reasoning } : null;
        history.push({
          turn: turnNum, state: frameState,
          agentA: isA ? agent : null, agentB: isA ? null : agent,
          winner: f === 3 ? game.winner : null,
          scoreA: frameState.tankA.hp, scoreB: frameState.tankB.hp,
          projectile: null, impact: null, trail: null, shooter: null,
        });
      }

    } else {
      // Shoot — capture pre-shot state for in-flight frames
      const preHpA = game.tankA.hp, preHpB = game.tankB.hp;
      const preTankA = { ...game.tankA }, preTankB = { ...game.tankB };
      const shooter = isA ? 'A' : 'B';

      game.shoot(result.angle, result.power);
      const postState = game.getState();
      const trajectory = game.lastShot.trajectory;
      const hitTarget = game.lastShot.hitTarget;

      // Sample points along trajectory for projectile animation
      const totalPts = trajectory.length;
      const numSamples = Math.min(ART_ANIM_FRAMES, totalPts);
      const indices = [];
      for (let i = 0; i < numSamples; i++) indices.push(Math.floor(i * (totalPts - 1) / Math.max(1, numSamples - 1)));
      if (indices[indices.length - 1] !== totalPts - 1) indices.push(totalPts - 1);

      for (let fi = 0; fi < indices.length; fi++) {
        const idx = indices[fi];
        const isLast = fi === indices.length - 1;
        const pt = trajectory[idx];

        // In-flight frames use pre-shot HP, impact frame uses post-shot HP
        const frameState = JSON.parse(JSON.stringify(postState));
        if (!isLast) {
          frameState.tankA = { ...preTankA };
          frameState.tankB = { ...preTankB };
          frameState.lastShot = null;
        }

        const agent = fi === 0
          ? { move: `${result.angle.toFixed(0)}\u00b0 P${result.power.toFixed(1)}`, reasoning: result.reasoning }
          : null;

        history.push({
          turn: turnNum, state: frameState,
          agentA: isA ? agent : null, agentB: isA ? null : agent,
          winner: isLast ? game.winner : null,
          scoreA: isLast ? postState.tankA.hp : preHpA,
          scoreB: isLast ? postState.tankB.hp : preHpB,
          projectile: isLast ? null : { x: pt[0], y: pt[1] },
          impact: isLast ? { x: pt[0], y: pt[1], hitTarget } : null,
          trail: trajectory.slice(0, idx + 1),
          shooter,
        });
      }
    }
  }

  return history;
}


/* ═══════════════════════════════════════════════════════════════════════════
   Poker Game Engine — Texas Hold'em, 2 players, incomplete information
   ═══════════════════════════════════════════════════════════════════════════ */

const PKR_RANKS = ['2','3','4','5','6','7','8','9','T','J','Q','K','A'];
const PKR_SUITS = ['\u2660','\u2665','\u2666','\u2663'];
const PKR_SUIT_COLORS = ['#FFFFFF', '#F93C31', '#F93C31', '#FFFFFF'];
const PKR_START_CHIPS = 100;
const PKR_SMALL_BLIND = 1;
const PKR_BIG_BLIND = 2;
const PKR_HANDS = 10;

function pkrMakeDeck(rng) {
  const deck = [];
  for (let s = 0; s < 4; s++)
    for (let r = 0; r < 13; r++) deck.push({ rank: r, suit: s });
  // Fisher-Yates shuffle with seeded RNG
  for (let i = deck.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [deck[i], deck[j]] = [deck[j], deck[i]];
  }
  return deck;
}

function pkrCardStr(card) {
  return PKR_RANKS[card.rank] + PKR_SUITS[card.suit];
}

// Hand evaluation — returns [category, ...tiebreakers] (higher = better)
// Categories: 0=high card, 1=pair, 2=two pair, 3=trips, 4=straight, 5=flush,
//             6=full house, 7=quads, 8=straight flush
function pkrEvalHand5(cards) {
  const ranks = cards.map(c => c.rank).sort((a,b) => b-a);
  const suits = cards.map(c => c.suit);
  const isFlush = suits.every(s => s === suits[0]);

  // Check straight
  let isStraight = false;
  let straightHigh = ranks[0];
  if (ranks[0]-ranks[4] === 4 && new Set(ranks).size === 5) isStraight = true;
  // Wheel (A-2-3-4-5)
  if (ranks[0] === 12 && ranks[1] === 3 && ranks[2] === 2 && ranks[3] === 1 && ranks[4] === 0) {
    isStraight = true; straightHigh = 3;
  }

  if (isFlush && isStraight) return [8, straightHigh];

  // Count rank frequencies
  const freq = {};
  for (const r of ranks) freq[r] = (freq[r]||0) + 1;
  const groups = Object.entries(freq).map(([r,c]) => [c, parseInt(r)]).sort((a,b) => b[0]-a[0] || b[1]-a[1]);

  if (groups[0][0] === 4) return [7, groups[0][1], groups[1][1]];
  if (groups[0][0] === 3 && groups[1] && groups[1][0] === 2) return [6, groups[0][1], groups[1][1]];
  if (isFlush) return [5, ...ranks];
  if (isStraight) return [4, straightHigh];
  if (groups[0][0] === 3) return [3, groups[0][1], ...groups.slice(1).map(g=>g[1])];
  if (groups[0][0] === 2 && groups[1] && groups[1][0] === 2) return [2, Math.max(groups[0][1],groups[1][1]), Math.min(groups[0][1],groups[1][1]), groups[2][1]];
  if (groups[0][0] === 2) return [1, groups[0][1], ...groups.slice(1).map(g=>g[1])];
  return [0, ...ranks];
}

// Best 5-card hand from 7 cards
function pkrBestHand(cards) {
  let best = null;
  for (let i = 0; i < 7; i++) {
    for (let j = i+1; j < 7; j++) {
      const hand5 = cards.filter((_,k) => k!==i && k!==j);
      const score = pkrEvalHand5(hand5);
      if (!best || pkrCompareScores(score, best.score) > 0) {
        best = { cards: hand5, score };
      }
    }
  }
  return best;
}

function pkrCompareScores(a, b) {
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    if ((a[i]||0) !== (b[i]||0)) return (a[i]||0) - (b[i]||0);
  }
  return 0;
}

const PKR_HAND_NAMES = ['High Card','Pair','Two Pair','Three of a Kind','Straight','Flush','Full House','Four of a Kind','Straight Flush'];

function pkrHandName(score) {
  return PKR_HAND_NAMES[score[0]] || 'Unknown';
}

// Simple hand strength estimator (0-1) for AI decision-making
function pkrHandStrength(holeCards, communityCards) {
  const r1 = holeCards[0].rank, r2 = holeCards[1].rank;
  const suited = holeCards[0].suit === holeCards[1].suit;
  const highR = Math.max(r1, r2), lowR = Math.min(r1, r2);

  // Pre-flop: simplified Chen formula
  if (communityCards.length === 0) {
    let str = highR / 12;
    if (r1 === r2) str = Math.min(1, str + 0.35);
    if (suited) str = Math.min(1, str + 0.08);
    if (highR - lowR <= 2 && highR - lowR > 0) str = Math.min(1, str + 0.06);
    return str;
  }

  // Post-flop: evaluate actual hand strength
  const all = [...holeCards, ...communityCards];
  if (all.length >= 5) {
    // Pad to 7 if needed (turn/flop has fewer)
    const padded = all.length < 7
      ? [...all, ...Array(7-all.length).fill(null)].filter(Boolean)
      : all;
    if (padded.length >= 7) {
      const best = pkrBestHand(padded);
      return Math.min(1, 0.15 + best.score[0] * 0.1 + highR * 0.02);
    }
    // 5 or 6 cards — evaluate directly
    const best5 = padded.length === 5 ? pkrEvalHand5(padded)
      : (() => { let b=null; for(let i=0;i<padded.length;i++){const h=padded.filter((_,j)=>j!==i);const s=pkrEvalHand5(h);if(!b||pkrCompareScores(s,b)>0)b=s;} return b; })();
    return Math.min(1, 0.15 + best5[0] * 0.1 + highR * 0.02);
  }
  return 0.3;
}


/* ── Poker AI ──────────────────────────────────────────────────────────── */

function pkrTightAI(myCards, community, pot, myChips, oppChips, toCall, canRaise, phase, ply, seed) {
  const str = pkrHandStrength(myCards, community);

  // Pre-flop: only play strong hands
  if (phase === 'preflop') {
    if (str < 0.35) {
      if (toCall === 0) return { action: 'check', amount: 0, reasoning: `TIGHT\n  Str: ${(str*100).toFixed(0)}% \u2014 check` };
      return { action: 'fold', amount: 0, reasoning: `TIGHT\n  Str: ${(str*100).toFixed(0)}% \u2014 too weak, fold` };
    }
    if (str > 0.7 && canRaise) {
      const raise = Math.min(pot, myChips);
      return { action: 'raise', amount: raise, reasoning: `TIGHT\n  Str: ${(str*100).toFixed(0)}% \u2014 premium, raise ${raise}` };
    }
  }

  // Post-flop: play made hands
  if (str > 0.6 && canRaise) {
    const raise = Math.min(Math.ceil(pot * 0.6), myChips);
    return { action: 'raise', amount: raise, reasoning: `TIGHT\n  Str: ${(str*100).toFixed(0)}%\n  Strong, raise ${raise}` };
  }
  if (str > 0.3 || (toCall > 0 && toCall <= myChips * 0.15)) {
    if (toCall === 0) return { action: 'check', amount: 0, reasoning: `TIGHT\n  Str: ${(str*100).toFixed(0)}% \u2014 check` };
    return { action: 'call', amount: toCall, reasoning: `TIGHT\n  Str: ${(str*100).toFixed(0)}% \u2014 call ${toCall}` };
  }
  if (toCall === 0) return { action: 'check', amount: 0, reasoning: `TIGHT\n  Str: ${(str*100).toFixed(0)}% \u2014 check` };
  return { action: 'fold', amount: 0, reasoning: `TIGHT\n  Str: ${(str*100).toFixed(0)}% \u2014 fold` };
}

function pkrAggressiveAI(myCards, community, pot, myChips, oppChips, toCall, canRaise, phase, ply, seed) {
  const str = pkrHandStrength(myCards, community);
  const bluffRng = mulberry32(ply * 97 + seed);
  const willBluff = bluffRng() < 0.25;

  // Raise frequently
  if (canRaise && (str > 0.4 || willBluff)) {
    const raise = Math.min(Math.ceil(pot * 0.75), myChips);
    const label = willBluff && str < 0.4 ? 'BLUFF' : 'Value';
    return { action: 'raise', amount: raise, reasoning: `AGGRO\n  Str: ${(str*100).toFixed(0)}%\n  ${label} raise ${raise}` };
  }

  if (toCall === 0) return { action: 'check', amount: 0, reasoning: `AGGRO\n  Str: ${(str*100).toFixed(0)}% \u2014 check` };
  if (str > 0.25 || toCall <= myChips * 0.2) {
    return { action: 'call', amount: toCall, reasoning: `AGGRO\n  Str: ${(str*100).toFixed(0)}% \u2014 call ${toCall}` };
  }
  return { action: 'fold', amount: 0, reasoning: `AGGRO\n  Str: ${(str*100).toFixed(0)}% \u2014 fold` };
}

function pkrCalculatorAI(myCards, community, pot, myChips, oppChips, toCall, canRaise, phase, ply, seed) {
  const str = pkrHandStrength(myCards, community);
  const potOdds = toCall > 0 ? toCall / (pot + toCall) : 0;
  const equity = str;

  // Bet when equity beats pot odds
  if (canRaise && equity > 0.55) {
    const raise = Math.min(Math.ceil(pot * equity), myChips);
    return { action: 'raise', amount: raise,
      reasoning: `CALC\n  Equity: ${(equity*100).toFixed(0)}% > Odds: ${(potOdds*100).toFixed(0)}%\n  +EV raise ${raise}` };
  }

  if (toCall === 0) return { action: 'check', amount: 0,
    reasoning: `CALC\n  Equity: ${(equity*100).toFixed(0)}% \u2014 check` };

  if (equity > potOdds + 0.05) {
    return { action: 'call', amount: toCall,
      reasoning: `CALC\n  Equity: ${(equity*100).toFixed(0)}% > Odds: ${(potOdds*100).toFixed(0)}%\n  +EV call` };
  }

  return { action: 'fold', amount: 0,
    reasoning: `CALC\n  Equity: ${(equity*100).toFixed(0)}% < Odds: ${(potOdds*100).toFixed(0)}%\n  -EV, fold` };
}

const PKR_STRATEGIES = {
  tight:      { name: 'Tight',      fn: pkrTightAI,      desc: 'Only plays strong hands, patient and selective',
                personality: { aggression: 30, caution: 85, greed: 40 } },
  aggressive: { name: 'Aggressive', fn: pkrAggressiveAI,  desc: 'Raises often, bluffs ~25% of the time',
                personality: { aggression: 85, caution: 20, greed: 70 } },
  calculator: { name: 'Calculator', fn: pkrCalculatorAI, desc: 'Math-based: pot odds and equity calculations',
                personality: { aggression: 50, caution: 60, greed: 55 } },
};


/* ── Poker Rendering ──────────────────────────────────────────────────── */

function renderPokerCard(ctx, x, y, w, h, card, faceDown) {
  const r = 3;
  ctx.beginPath();
  ctx.moveTo(x+r, y); ctx.lineTo(x+w-r, y); ctx.quadraticCurveTo(x+w, y, x+w, y+r);
  ctx.lineTo(x+w, y+h-r); ctx.quadraticCurveTo(x+w, y+h, x+w-r, y+h);
  ctx.lineTo(x+r, y+h); ctx.quadraticCurveTo(x, y+h, x, y+h-r);
  ctx.lineTo(x, y+r); ctx.quadraticCurveTo(x, y, x+r, y);
  ctx.closePath();
  ctx.fillStyle = faceDown ? '#2a4a7f' : '#FFFFF0';
  ctx.fill();
  ctx.strokeStyle = '#555'; ctx.lineWidth = 1; ctx.stroke();

  if (faceDown) {
    ctx.fillStyle = '#1a3a6f';
    ctx.fillRect(x+3, y+3, w-6, h-6);
    ctx.strokeStyle = '#4a7acf'; ctx.lineWidth = 0.5;
    ctx.strokeRect(x+5, y+5, w-10, h-10);
    return;
  }

  const color = PKR_SUIT_COLORS[card.suit];
  ctx.fillStyle = color;
  ctx.font = `bold ${Math.floor(h*0.35)}px monospace`;
  ctx.textAlign = 'center'; ctx.textBaseline = 'top';
  ctx.fillText(PKR_RANKS[card.rank], x + w/2, y + 2);
  ctx.font = `${Math.floor(h*0.3)}px serif`;
  ctx.textBaseline = 'middle';
  ctx.fillText(PKR_SUITS[card.suit], x + w/2, y + h*0.65);
}

function renderPokerFrame(ctx, frame, size) {
  const state = frame.state;
  const cardW = size * 0.07, cardH = cardW * 1.4;

  // Felt background
  const feltGrad = ctx.createRadialGradient(size/2, size/2, 0, size/2, size/2, size*0.7);
  feltGrad.addColorStop(0, '#1a5c2a'); feltGrad.addColorStop(1, '#0d3318');
  ctx.fillStyle = feltGrad; ctx.fillRect(0, 0, size, size);

  // Table oval
  ctx.beginPath(); ctx.ellipse(size/2, size/2, size*0.42, size*0.32, 0, 0, Math.PI*2);
  ctx.fillStyle = '#1e6b34'; ctx.fill();
  ctx.strokeStyle = '#8B4513'; ctx.lineWidth = 4; ctx.stroke();

  // Phase label
  ctx.font = `bold ${size*0.03}px monospace`; ctx.fillStyle = '#AAA';
  ctx.textAlign = 'center'; ctx.textBaseline = 'top';
  const phaseLabel = state.phase === 'showdown' ? 'SHOWDOWN' : state.phase.toUpperCase();
  ctx.fillText(`Hand ${state.handNum}/${PKR_HANDS}  \u2022  ${phaseLabel}`, size/2, size*0.03);

  // Pot
  ctx.font = `bold ${size*0.04}px monospace`; ctx.fillStyle = ARC3[11];
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText(`Pot: ${state.pot}`, size/2, size*0.38);

  // Community cards (center)
  const commX = size/2 - (5 * (cardW + 4)) / 2;
  const commY = size * 0.43;
  for (let i = 0; i < 5; i++) {
    const card = state.community[i];
    if (card) renderPokerCard(ctx, commX + i*(cardW+4), commY, cardW, cardH, card, false);
    else {
      ctx.strokeStyle = '#2a5a3a'; ctx.lineWidth = 1;
      ctx.strokeRect(commX + i*(cardW+4), commY, cardW, cardH);
    }
  }

  // Player A cards (bottom-left)
  const aY = size * 0.78;
  const aX = size * 0.25;
  ctx.font = `bold ${size*0.03}px monospace`; ctx.fillStyle = ARC3[8];
  ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
  ctx.fillText(`A: ${state.chipsA} chips`, aX + cardW, aY - 4);
  if (state.holeA) {
    renderPokerCard(ctx, aX, aY, cardW, cardH, state.holeA[0], false);
    renderPokerCard(ctx, aX + cardW + 4, aY, cardW, cardH, state.holeA[1], false);
  }
  if (state.currentBetA > 0) {
    ctx.font = `${size*0.025}px monospace`; ctx.fillStyle = ARC3[11];
    ctx.textAlign = 'center';
    ctx.fillText(`Bet: ${state.currentBetA}`, aX + cardW, aY + cardH + 14);
  }

  // Player B cards (top-right)
  const bY = size * 0.1;
  const bX = size * 0.58;
  ctx.font = `bold ${size*0.03}px monospace`; ctx.fillStyle = ARC3[12];
  ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
  ctx.fillText(`B: ${state.chipsB} chips`, bX + cardW, bY - 4);
  if (state.holeB) {
    renderPokerCard(ctx, bX, bY, cardW, cardH, state.holeB[0], false);
    renderPokerCard(ctx, bX + cardW + 4, bY, cardW, cardH, state.holeB[1], false);
  }
  if (state.currentBetB > 0) {
    ctx.font = `${size*0.025}px monospace`; ctx.fillStyle = ARC3[11];
    ctx.textAlign = 'center';
    ctx.fillText(`Bet: ${state.currentBetB}`, bX + cardW, bY + cardH + 14);
  }

  // Dealer button
  const dealerX = state.dealer === 'A' ? aX - 14 : bX - 14;
  const dealerY = state.dealer === 'A' ? aY + cardH/2 : bY + cardH/2;
  ctx.beginPath(); ctx.arc(dealerX, dealerY, 8, 0, Math.PI*2);
  ctx.fillStyle = '#FFD700'; ctx.fill();
  ctx.strokeStyle = '#333'; ctx.lineWidth = 1; ctx.stroke();
  ctx.font = `bold 8px monospace`; ctx.fillStyle = '#333';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText('D', dealerX, dealerY);

  // Action text
  if (frame.actionText) {
    ctx.font = `bold ${size*0.035}px monospace`;
    ctx.fillStyle = '#FFF'; ctx.textAlign = 'center';
    ctx.fillText(frame.actionText, size/2, size*0.62);
  }

  // Showdown result
  if (state.phase === 'showdown' && state.handResult) {
    ctx.font = `bold ${size*0.03}px monospace`;
    ctx.fillStyle = ARC3[14]; ctx.textAlign = 'center';
    ctx.fillText(state.handResult, size/2, size*0.68);
  }
}

function renderPokerPreview(canvas) {
  const size = 120; canvas.width = size; canvas.height = size;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#1a5c2a'; ctx.fillRect(0, 0, size, size);
  ctx.beginPath(); ctx.ellipse(60, 60, 45, 35, 0, 0, Math.PI*2);
  ctx.fillStyle = '#1e6b34'; ctx.fill();
  ctx.strokeStyle = '#8B4513'; ctx.lineWidth = 2; ctx.stroke();
  const cw = 12, ch = 17;
  ctx.fillStyle = '#2a4a7f';
  ctx.fillRect(25, 75, cw, ch); ctx.fillRect(39, 75, cw, ch);
  ctx.fillRect(68, 25, cw, ch); ctx.fillRect(82, 25, cw, ch);
  for (let i = 0; i < 5; i++) {
    ctx.fillStyle = '#FFFFF0'; ctx.fillRect(22 + i*16, 48, cw, ch);
    ctx.strokeStyle = '#999'; ctx.lineWidth = 0.5; ctx.strokeRect(22 + i*16, 48, cw, ch);
  }
  ctx.beginPath(); ctx.arc(60, 43, 4, 0, Math.PI*2);
  ctx.fillStyle = ARC3[11]; ctx.fill();
}


/* ── Poker Match Runner ────────────────────────────────────────────────── */

function runPokerMatch(config, strategyA, strategyB) {
  const fnA = PKR_STRATEGIES[strategyA].fn, fnB = PKR_STRATEGIES[strategyB].fn;
  const seed = config.seed || 42;
  const numHands = config.maxHands || PKR_HANDS;
  let chipsA = PKR_START_CHIPS, chipsB = PKR_START_CHIPS;
  let dealer = 'A';
  const history = [];
  const handRng = mulberry32(seed);

  const mkState = (handNum, phase, comm, pot, betA, betB, holeA, holeB, result) => ({
    handNum, phase,
    community: [...comm, ...Array(Math.max(0, 5-comm.length)).fill(null)],
    holeA: holeA ? [...holeA] : null,
    holeB: holeB ? [...holeB] : null,
    pot, chipsA, chipsB, dealer,
    currentBetA: betA, currentBetB: betB,
    handResult: result || null,
  });

  // Initial frame
  history.push({
    turn: 0, state: mkState(0, 'setup', [], 0, 0, 0, null, null, null),
    agentA: null, agentB: null, winner: null, scoreA: chipsA, scoreB: chipsB,
    actionText: 'Texas Hold\'em \u2014 10 hands',
  });

  for (let h = 0; h < numHands; h++) {
    if (chipsA <= 0 || chipsB <= 0) break;

    const deck = pkrMakeDeck(handRng);
    const holeA = [deck[0], deck[1]];
    const holeB = [deck[2], deck[3]];
    const board = [deck[4], deck[5], deck[6], deck[7], deck[8]];
    const handNum = h + 1;

    // Post blinds (heads-up: dealer = SB, other = BB)
    const sbPlayer = dealer;
    const bbPlayer = dealer === 'A' ? 'B' : 'A';
    const sb = Math.min(PKR_SMALL_BLIND, sbPlayer === 'A' ? chipsA : chipsB);
    const bb = Math.min(PKR_BIG_BLIND, bbPlayer === 'A' ? chipsA : chipsB);
    if (sbPlayer === 'A') chipsA -= sb; else chipsB -= sb;
    if (bbPlayer === 'A') chipsA -= bb; else chipsB -= bb;
    let pot = sb + bb;
    let betA = sbPlayer === 'A' ? sb : bb;
    let betB = sbPlayer === 'B' ? sb : bb;

    // Deal frame
    history.push({
      turn: history.length, state: mkState(handNum, 'preflop', [], pot, betA, betB, holeA, holeB, null),
      agentA: null, agentB: null, winner: null, scoreA: chipsA, scoreB: chipsB,
      actionText: `Hand ${handNum} \u2014 Deal`,
    });

    let folded = null;

    const phases = [
      { name: 'preflop', comm: [] },
      { name: 'flop', comm: board.slice(0,3) },
      { name: 'turn', comm: board.slice(0,4) },
      { name: 'river', comm: board.slice(0,5) },
    ];

    for (const phase of phases) {
      if (folded) break;

      // Reveal community cards
      if (phase.name !== 'preflop') {
        betA = 0; betB = 0;
        history.push({
          turn: history.length, state: mkState(handNum, phase.name, phase.comm, pot, betA, betB, holeA, holeB, null),
          agentA: null, agentB: null, winner: null, scoreA: chipsA, scoreB: chipsB,
          actionText: phase.name === 'flop' ? 'Flop' : phase.name === 'turn' ? 'Turn' : 'River',
        });
      }

      // Heads-up: dealer/SB acts first preflop, BB acts first postflop
      const firstActor = phase.name === 'preflop' ? sbPlayer : bbPlayer;
      const order = firstActor === 'A' ? ['A','B'] : ['B','A'];
      let raised = false;

      for (const actor of order) {
        if (folded) break;
        const isA = actor === 'A';
        const myCards = isA ? holeA : holeB;
        const myChips = isA ? chipsA : chipsB;
        const oppChips = isA ? chipsB : chipsA;
        const myBet = isA ? betA : betB;
        const oppBet = isA ? betB : betA;
        const toCall = Math.max(0, oppBet - myBet);
        const canRaise = !raised && myChips > toCall;
        const fn = isA ? fnA : fnB;

        const result = fn(myCards, phase.comm, pot, myChips, oppChips, toCall, canRaise, phase.name, history.length, seed);
        let action = result.action;
        let amount = 0;

        if (action === 'fold') {
          folded = actor;
        } else if (action === 'check' && toCall === 0) {
          // Check
        } else if (action === 'call' || (action === 'check' && toCall > 0)) {
          amount = Math.min(toCall, myChips);
          if (isA) { chipsA -= amount; betA += amount; } else { chipsB -= amount; betB += amount; }
          pot += amount;
          action = 'call';
        } else if (action === 'raise' && canRaise) {
          const callAmt = Math.min(toCall, myChips);
          const raiseAmt = Math.min(result.amount || PKR_BIG_BLIND * 2, myChips - callAmt);
          amount = callAmt + raiseAmt;
          if (isA) { chipsA -= amount; betA += amount; } else { chipsB -= amount; betB += amount; }
          pot += amount;
          raised = true;
        } else {
          if (toCall > 0) {
            amount = Math.min(toCall, myChips);
            if (isA) { chipsA -= amount; betA += amount; } else { chipsB -= amount; betB += amount; }
            pot += amount;
            action = 'call';
          } else { action = 'check'; }
        }

        const moveStr = action === 'fold' ? 'Fold' : action === 'check' ? 'Check' : action === 'call' ? `Call ${amount}` : `Raise ${amount}`;
        const agentData = { move: moveStr, reasoning: result.reasoning };
        history.push({
          turn: history.length, state: mkState(handNum, phase.name, phase.comm, pot, betA, betB, holeA, holeB, null),
          agentA: isA ? agentData : null, agentB: isA ? null : agentData,
          winner: null, scoreA: chipsA, scoreB: chipsB,
          actionText: `${actor}: ${moveStr}`,
        });
      }

      // If raised, give first actor chance to respond
      if (raised && !folded) {
        const responder = order[0];
        const isA = responder === 'A';
        const myCards = isA ? holeA : holeB;
        const myChips = isA ? chipsA : chipsB;
        const oppChips = isA ? chipsB : chipsA;
        const myBet = isA ? betA : betB;
        const oppBet = isA ? betB : betA;
        const toCall = Math.max(0, oppBet - myBet);

        if (toCall > 0) {
          const fn = isA ? fnA : fnB;
          const result = fn(myCards, phase.comm, pot, myChips, oppChips, toCall, false, phase.name, history.length, seed);
          let action = result.action;
          let amount = 0;

          if (action === 'fold') {
            folded = responder;
          } else {
            amount = Math.min(toCall, myChips);
            if (isA) { chipsA -= amount; betA += amount; } else { chipsB -= amount; betB += amount; }
            pot += amount;
            action = 'call';
          }

          const moveStr = action === 'fold' ? 'Fold' : `Call ${amount}`;
          const agentData = { move: moveStr, reasoning: result.reasoning };
          history.push({
            turn: history.length, state: mkState(handNum, phase.name, phase.comm, pot, betA, betB, holeA, holeB, null),
            agentA: isA ? agentData : null, agentB: isA ? null : agentData,
            winner: null, scoreA: chipsA, scoreB: chipsB,
            actionText: `${responder}: ${moveStr}`,
          });
        }
      }
    }

    // Showdown or fold resolution
    let handResult = '';
    if (folded) {
      const winner = folded === 'A' ? 'B' : 'A';
      if (winner === 'A') chipsA += pot; else chipsB += pot;
      handResult = `${folded} folds \u2014 ${winner} wins ${pot}`;
    } else {
      const allA = [...holeA, ...board];
      const allB = [...holeB, ...board];
      const bestA = pkrBestHand(allA);
      const bestB = pkrBestHand(allB);
      const cmp = pkrCompareScores(bestA.score, bestB.score);
      if (cmp > 0) {
        chipsA += pot;
        handResult = `A: ${pkrHandName(bestA.score)} \u2014 wins ${pot}`;
      } else if (cmp < 0) {
        chipsB += pot;
        handResult = `B: ${pkrHandName(bestB.score)} \u2014 wins ${pot}`;
      } else {
        const half = Math.floor(pot / 2);
        chipsA += half; chipsB += pot - half;
        handResult = `Split \u2014 ${pkrHandName(bestA.score)}`;
      }
    }

    history.push({
      turn: history.length, state: mkState(handNum, 'showdown', board, 0, 0, 0, holeA, holeB, handResult),
      agentA: null, agentB: null, winner: null, scoreA: chipsA, scoreB: chipsB,
      actionText: handResult,
    });

    pot = 0; betA = 0; betB = 0;
    dealer = dealer === 'A' ? 'B' : 'A';
  }

  // Final winner
  const finalWinner = chipsA > chipsB ? 'A' : chipsB > chipsA ? 'B' : 'draw';
  history[history.length - 1].winner = finalWinner;

  return history;
}


/* ═══════════════════════════════════════════════════════════════════════════
   Available Games
   ═══════════════════════════════════════════════════════════════════════════ */

// Only Snake is enabled for now — other games kept for future re-enablement
const _ALL_ARENA_GAMES = [
  { id: 'snake', title: 'Snake Battle', category: 'ARC-style',
    desc: 'Two AI snakes compete for food. Eat to grow, avoid walls and each other.',
    tags: ['Territorial', 'Simultaneous'],
    config: { width: 20, height: 20, maxTurns: 200, seed: 42 },
    strategies: AI_STRATEGIES,
    run: runMatch, render: renderSnakeFrame, preview: renderSnakePreview },
  { id: 'tron', title: 'Tron', category: 'ARC-style',
    desc: 'Light cycles leave trails. Last one alive wins. Claim space, cut off your opponent.',
    tags: ['Territorial', 'Simultaneous'],
    config: { width: 25, height: 25, maxTurns: 200, seed: 42 },
    strategies: TRON_STRATEGIES,
    run: runTronMatch, render: renderTronFrame, preview: renderTronPreview },
  { id: 'connect4', title: 'Connect Four', category: 'Board Games',
    desc: 'Drop pieces into columns. First to connect 4 in a row wins.',
    tags: ['Symbolic', 'Turn-based'],
    config: { seed: 42 },
    strategies: C4_STRATEGIES,
    run: runC4Match, render: renderC4Frame, preview: renderC4Preview },
  { id: 'chess960', title: 'Fischer Random Chess', category: 'Board Games',
    desc: 'Chess960 — back rank pieces shuffled. Full chess with unique openings every game.',
    tags: ['Symbolic', 'Turn-based'],
    config: { maxMoves: 80, seed: 42 },
    strategies: CHESS_STRATEGIES,
    run: runChessMatch, render: renderChessFrame, preview: renderChessPreview },
  { id: 'othello', title: 'Othello', category: 'Board Games',
    desc: 'Place pieces to flip your opponent. Control the board — corners are king.',
    tags: ['Symbolic', 'Turn-based'],
    config: { seed: 42 },
    strategies: OTHELLO_STRATEGIES,
    run: runOthelloMatch, render: renderOthelloFrame, preview: renderOthelloPreview },
  { id: 'go9', title: 'Go 9x9', category: 'Board Games',
    desc: 'Ancient strategy game. Surround territory, capture stones. 6.5 komi for White.',
    tags: ['Symbolic', 'Turn-based'],
    config: { maxMoves: 120, seed: 42 },
    strategies: GO_STRATEGIES,
    run: runGoMatch, render: renderGoFrame, preview: renderGoPreview },
  { id: 'gomoku', title: 'Gomoku', category: 'Board Games',
    desc: 'Place stones on a 15x15 board. First to get 5 in a row wins.',
    tags: ['Symbolic', 'Turn-based'],
    config: { seed: 42 },
    strategies: GMK_STRATEGIES,
    run: runGomokuMatch, render: renderGomokuFrame, preview: renderGomokuPreview },
  { id: 'artillery', title: 'Artillery', category: 'Action',
    desc: 'Tanks on opposite hills. Adjust angle and power to land shots on your opponent.',
    tags: ['Physics', 'Turn-based'],
    config: { maxTurns: 20, seed: 42 },
    strategies: ART_STRATEGIES,
    run: runArtilleryMatch, render: renderArtilleryFrame, preview: renderArtilleryPreview },
  { id: 'poker', title: 'Texas Hold\'em', category: 'Incomplete Information',
    desc: 'Hidden hole cards, community board, and betting. Bluff or fold?',
    tags: ['Cards', 'Turn-based'],
    config: { maxHands: 10, seed: 42 },
    strategies: PKR_STRATEGIES,
    run: runPokerMatch, render: renderPokerFrame, preview: renderPokerPreview },
];

const ARENA_ENABLED_IDS = new Set(['snake']);
const ARENA_GAMES = _ALL_ARENA_GAMES.filter(g => ARENA_ENABLED_IDS.has(g.id));


/* ═══════════════════════════════════════════════════════════════════════════
   Match Runner
   ═══════════════════════════════════════════════════════════════════════════ */

function runMatch(config, strategyA, strategyB) {
  const game = new SnakeGame(config);
  const fnA = AI_STRATEGIES[strategyA].fn;
  const fnB = AI_STRATEGIES[strategyB].fn;
  const history = [];

  const snapSnake = s => ({ alive: s.alive, score: s.score, body: s.body.map(p => [...p]) });

  // Turn 0: initial state
  history.push({
    turn: 0, grid: game.getGrid(),
    snakeA: snapSnake(game.snakeA), snakeB: snapSnake(game.snakeB),
    food: game.food ? [...game.food] : null,
    agentA: null, agentB: null, winner: null,
  });

  while (!game.over) {
    const aiState = game.getAIState();
    const resultA = fnA(aiState, 'A');
    const resultB = fnB(aiState, 'B');
    game.step(resultA.move, resultB.move);
    history.push({
      turn: game.turn, grid: game.getGrid(),
      snakeA: snapSnake(game.snakeA), snakeB: snapSnake(game.snakeB),
      food: game.food ? [...game.food] : null,
      agentA: { move: DIR_NAME[resultA.move], reasoning: resultA.reasoning },
      agentB: { move: DIR_NAME[resultB.move], reasoning: resultB.reasoning },
      winner: game.winner,
    });
  }
  return history;
}


/* ═══════════════════════════════════════════════════════════════════════════
   UI State
   ═══════════════════════════════════════════════════════════════════════════ */

const Arena = {
  mode: 'setup',          // 'setup' | 'match' | 'observe'
  obsAgent: null,         // 'A' | 'B' — which agent is being observed
  selectedGame: 'snake',
  history: null,
  currentStep: 0,
  playing: false,
  playTimer: null,
  canvas: null,
  ctx: null,
  obsCanvas: null,
  obsCtx: null,
  modelsData: [],         // model list from /api/llm/models
  modelsLoaded: false,
};


/* ═══════════════════════════════════════════════════════════════════════════
   Init
   ═══════════════════════════════════════════════════════════════════════════ */

function buildGameCards() {
  const container = document.getElementById('gameCardRow');
  container.innerHTML = '';

  // Group games by category, preserving order of first appearance
  const categories = [];
  const catMap = {};
  for (const game of ARENA_GAMES) {
    const cat = game.category || 'Other';
    if (!catMap[cat]) { catMap[cat] = []; categories.push(cat); }
    catMap[cat].push(game);
  }

  let firstGame = true;
  for (const cat of categories) {
    const section = document.createElement('div');
    section.className = 'game-category';

    const label = document.createElement('div');
    label.className = 'game-category-label';
    label.textContent = cat;
    section.appendChild(label);

    const grid = document.createElement('div');
    grid.className = 'game-category-grid';

    for (const game of catMap[cat]) {
      const card = document.createElement('div');
      card.className = 'arena-game-card' + (firstGame ? ' active' : '');
      card.dataset.game = game.id;
      card.onclick = function() { selectGameCard(this, game.id); };

      const canvas = document.createElement('canvas');
      canvas.className = 'arena-game-preview';
      canvas.id = `preview-${game.id}`;
      canvas.width = 120; canvas.height = 120;
      card.appendChild(canvas);

      const meta = document.createElement('div');
      meta.className = 'arena-game-meta';
      meta.innerHTML =
        `<div class="arena-game-title">${game.title}</div>` +
        `<div class="arena-game-desc">${game.desc}</div>` +
        `<div class="arena-game-tags">${game.tags.map(t => `<span class="arena-tag">${t}</span>`).join('')}</div>`;
      card.appendChild(meta);

      grid.appendChild(card);
      firstGame = false;
    }

    section.appendChild(grid);
    container.appendChild(section);
  }
}

function initArena() {
  Arena.canvas = document.getElementById('arenaCanvas');
  Arena.ctx = Arena.canvas.getContext('2d');
  Arena.obsCanvas = document.getElementById('arenaObsCanvas');
  Arena.obsCtx = Arena.obsCanvas.getContext('2d');

  // Build categorized game cards dynamically
  buildGameCards();

  // Render game card previews
  for (const game of ARENA_GAMES) {
    const preview = document.getElementById(`preview-${game.id}`);
    if (preview) renderPreview(preview, game);
  }

  // Wire up scrubbers (main + obs)
  document.getElementById('arenaScrubber').addEventListener('input', e => {
    scrubTo(parseInt(e.target.value));
  });
  document.getElementById('arenaObsScrubber').addEventListener('input', e => {
    scrubTo(parseInt(e.target.value));
  });

  // Wire up speed changes during playback
  document.getElementById('arenaSpeed').addEventListener('change', () => {
    if (Arena.playing) { stopPlayback(); startPlayback(); }
  });

  // Wire up strategy selects to update descriptions and personality bars
  document.getElementById('stratA').addEventListener('change', e => {
    updateStrategyInfo('A', e.target.value);
  });
  document.getElementById('stratB').addEventListener('change', e => {
    updateStrategyInfo('B', e.target.value);
  });

  updateThemeBtn();

  // Load models for harness mode (async, non-blocking)
  arenaLoadModels();

  // Default both agents to harness mode — render immediately
  for (const agent of ['A', 'B']) {
    const container = document.getElementById(`harnessSettings${agent}`);
    if (container && !container.dataset.rendered) {
      const savedType = localStorage.getItem(`arc_arena_${agent.toLowerCase()}_scaffolding_type`) || 'linear';
      renderArenaHarness(agent, savedType);
      container.dataset.rendered = '1';
    }
  }

  // Route from URL hash (arena#matchup, arena#autoresearch)
  if (typeof _arenaRouteFromHash === 'function') _arenaRouteFromHash();
}

function renderPreview(canvas, game) {
  if (game.preview) { game.preview(canvas, game.config); return; }
}


/* ═══════════════════════════════════════════════════════════════════════════
   View Transitions
   ═══════════════════════════════════════════════════════════════════════════ */

function selectGameCard(el, gameId) {
  document.querySelectorAll('.arena-game-card').forEach(c => c.classList.remove('active'));
  el.classList.add('active');
  Arena.selectedGame = gameId;
  // Populate strategy selects for this game's strategies
  const game = ARENA_GAMES.find(g => g.id === gameId);
  if (game && game.strategies) {
    const keys = Object.keys(game.strategies);
    for (const side of ['stratA', 'stratB']) {
      const sel = document.getElementById(side);
      sel.innerHTML = '';
      keys.forEach((k, i) => {
        const opt = document.createElement('option');
        opt.value = k; opt.textContent = game.strategies[k].name;
        if ((side === 'stratA' && i === 0) || (side === 'stratB' && i === (keys.length > 1 ? 1 : 0)))
          opt.selected = true;
        sel.appendChild(opt);
      });
      updateStrategyInfo(side === 'stratA' ? 'A' : 'B', sel.value);
    }
  }
}

function enterMatchMode() {
  Arena.mode = 'match';

  // Hide settings, show logs
  document.getElementById('settingsA').style.display = 'none';
  document.getElementById('settingsB').style.display = 'none';
  document.getElementById('logA').classList.add('visible');
  document.getElementById('logB').classList.add('visible');

  // Hide game selection, show match area
  document.getElementById('gameSelectArea').classList.add('hidden');
  document.getElementById('matchArea').classList.add('visible');

  // Ensure obs screen is hidden
  document.getElementById('arenaObsScreen').style.display = 'none';
}

function enterSetupMode() {
  Arena.mode = 'setup';
  stopPlayback();
  hideWinnerOverlay();

  // Hide obs screen if open
  document.getElementById('arenaObsScreen').style.display = 'none';

  // Show settings, hide logs
  document.getElementById('settingsA').style.display = '';
  document.getElementById('settingsB').style.display = '';
  document.getElementById('logA').classList.remove('visible');
  document.getElementById('logB').classList.remove('visible');

  // Show game selection, hide match area
  document.getElementById('gameSelectArea').classList.remove('hidden');
  document.getElementById('matchArea').classList.remove('visible');

  // Reset scores in sidebar
  document.getElementById('sbScoreA').textContent = '0';
  document.getElementById('sbScoreB').textContent = '0';

  // Clear logs
  document.getElementById('logA').innerHTML = '';
  document.getElementById('logB').innerHTML = '';
  Arena.history = null;
}

function backToSetup() {
  if (Arena.mode === 'observe') {
    // From obs mode, go back to match view (not setup)
    exitArenaObs();
    return;
  }
  enterSetupMode();
}

function restartMatch() {
  enterSetupMode();
}


/* ═══════════════════════════════════════════════════════════════════════════
   Match Start
   ═══════════════════════════════════════════════════════════════════════════ */

function startMatch() {
  const game = ARENA_GAMES.find(g => g.id === Arena.selectedGame);
  if (!game) return;

  const strategyA = document.getElementById('stratA').value;
  const strategyB = document.getElementById('stratB').value;
  const config = {
    ...game.config,
    seed: parseInt(document.getElementById('cfgSeed').value) || 42,
    maxTurns: parseInt(document.getElementById('cfgMaxTurns').value) || 200,
  };

  // Switch to match mode
  enterMatchMode();

  // Update topbar
  document.getElementById('arenaGameTitle').textContent = game.title;

  // Run the full match (dispatch via game entry)
  Arena.history = game.run(config, strategyA, strategyB);
  Arena.currentStep = 0;

  // Build reasoning logs
  buildLogEntries();

  // Set up scrubber
  const maxStep = Arena.history.length - 1;
  document.getElementById('arenaScrubber').max = maxStep;
  document.getElementById('arenaScrubber').value = 0;

  // Render initial frame
  renderStep(0);
  updateMatchStatus('playing', 'Playing');

  // Start auto-play
  startPlayback();
}


/* ═══════════════════════════════════════════════════════════════════════════
   Rendering
   ═══════════════════════════════════════════════════════════════════════════ */

function renderStep(step) {
  if (!Arena.history || step >= Arena.history.length) return;
  Arena.currentStep = step;

  const frame = Arena.history[step];
  const canvasSize = 512;
  const gameDef = ARENA_GAMES.find(g => g.id === Arena.selectedGame);

  // Render on main canvas
  Arena.canvas.width = canvasSize;
  Arena.canvas.height = canvasSize;
  if (gameDef && gameDef.render) gameDef.render(Arena.ctx, frame, canvasSize);

  // Also render on obs canvas if in observe mode
  if (Arena.mode === 'observe') {
    Arena.obsCanvas.width = canvasSize;
    Arena.obsCanvas.height = canvasSize;
    if (gameDef && gameDef.render) gameDef.render(Arena.obsCtx, frame, canvasSize);
    // Update obs scrubber
    document.getElementById('arenaObsScrubber').value = step;
    document.getElementById('obsScrubLabel').textContent = `Turn ${frame.turn}`;
    // Update obs status
    document.getElementById('obsStatTurn').textContent = frame.turn;
    document.getElementById('obsStatStep').textContent = step;
    // Update obs play button
    document.getElementById('arenaObsPlayBtn').textContent = Arena.playing ? 'Pause' : 'Play';
    // Highlight obs log
    highlightObsLogEntry(step);
  }

  // Update main scrubber position
  document.getElementById('arenaScrubber').value = step;
  document.getElementById('scrubLabel').textContent = `Turn ${frame.turn}`;

  // Update scores (generic: use scoreA/scoreB if present, else snake-specific)
  const sA = frame.scoreA !== undefined ? frame.scoreA : (frame.snakeA ? frame.snakeA.score : 0);
  const sB = frame.scoreB !== undefined ? frame.scoreB : (frame.snakeB ? frame.snakeB.score : 0);
  document.getElementById('sbScoreA').textContent = sA;
  document.getElementById('sbScoreB').textContent = sB;
  document.getElementById('sbScoreAMatch').textContent = sA;
  document.getElementById('sbScoreBMatch').textContent = sB;
  updateTurnInfo(frame.turn, Arena.history[Arena.history.length - 1].turn);

  // Highlight + scroll reasoning logs
  highlightLogEntry(step);

  // Winner overlay on final step
  if (step === Arena.history.length - 1 && frame.winner) {
    showWinnerOverlay(frame.winner, sA, sB);
    const statusClass = frame.winner === 'A' ? 'win-a' : frame.winner === 'B' ? 'win-b' : 'draw';
    const statusText = frame.winner === 'draw' ? 'Draw!' : `Agent ${frame.winner} Wins!`;
    updateMatchStatus(statusClass, statusText);
  } else {
    hideWinnerOverlay();
  }
}


/* ═══════════════════════════════════════════════════════════════════════════
   Reasoning Logs
   ═══════════════════════════════════════════════════════════════════════════ */

function buildLogEntries() {
  const logA = document.getElementById('logA');
  const logB = document.getElementById('logB');
  logA.innerHTML = '';
  logB.innerHTML = '';

  for (let i = 0; i < Arena.history.length; i++) {
    const frame = Arena.history[i];
    // Handle both simultaneous (snake) and turn-based (chess) games
    if (frame.agentA) logA.appendChild(createLogEntry(i, frame.turn, frame.agentA, C.A_HEAD));
    if (frame.agentB) logB.appendChild(createLogEntry(i, frame.turn, frame.agentB, C.B_HEAD));
  }
}

function createLogEntry(stepIndex, turn, agentData, colorIndex) {
  const entry = document.createElement('div');
  entry.className = 'log-entry';
  entry.dataset.step = stepIndex;
  entry.innerHTML =
    `<div class="log-entry-turn">Turn ${turn}</div>` +
    `<div class="log-entry-move" style="color:${ARC3[colorIndex]}">${escHtml(agentData.move)}</div>` +
    `<div class="log-entry-reasoning">${escHtml(agentData.reasoning)}</div>`;
  entry.addEventListener('click', () => { stopPlayback(); scrubTo(stepIndex); });
  return entry;
}

function highlightLogEntry(step) {
  document.querySelectorAll('.log-entry.active').forEach(el => el.classList.remove('active'));

  const activeA = document.querySelector(`#logA .log-entry[data-step="${step}"]`);
  const activeB = document.querySelector(`#logB .log-entry[data-step="${step}"]`);
  if (activeA) {
    activeA.classList.add('active');
    activeA.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  if (activeB) {
    activeB.classList.add('active');
    activeB.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
}

function escHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}


/* ═══════════════════════════════════════════════════════════════════════════
   Scrubber & Playback
   ═══════════════════════════════════════════════════════════════════════════ */

function scrubTo(step) {
  step = Math.max(0, Math.min(step, (Arena.history?.length || 1) - 1));
  renderStep(step);
}

function startPlayback() {
  if (Arena.playing || !Arena.history) return;
  Arena.playing = true;
  document.getElementById('arenaPlayBtn').textContent = 'Pause';
  const speed = parseInt(document.getElementById('arenaSpeed').value) || 200;

  Arena.playTimer = setInterval(() => {
    if (Arena.currentStep >= Arena.history.length - 1) {
      stopPlayback();
      return;
    }
    scrubTo(Arena.currentStep + 1);
  }, speed);
}

function stopPlayback() {
  Arena.playing = false;
  if (Arena.playTimer) { clearInterval(Arena.playTimer); Arena.playTimer = null; }
  document.getElementById('arenaPlayBtn').textContent = 'Play';
}

function arenaPlayPause() {
  if (Arena.playing) stopPlayback();
  else startPlayback();
}

function arenaStepBack() {
  stopPlayback();
  scrubTo(Arena.currentStep - 1);
}

function arenaStepForward() {
  stopPlayback();
  scrubTo(Arena.currentStep + 1);
}


/* ═══════════════════════════════════════════════════════════════════════════
   UI Helpers
   ═══════════════════════════════════════════════════════════════════════════ */

function updateStrategyInfo(agent, strategyKey) {
  const game = ARENA_GAMES.find(g => g.id === Arena.selectedGame);
  const strategies = game ? game.strategies : AI_STRATEGIES;
  const strat = strategies[strategyKey];
  if (!strat) return;

  document.getElementById(`stratDesc${agent}`).textContent = strat.desc;

  // Update personality bars
  const panel = document.getElementById(`personality${agent}`);
  const fills = panel.querySelectorAll('.stat-fill');
  fills[0].style.width = strat.personality.aggression + '%';
  fills[1].style.width = strat.personality.caution + '%';
  fills[2].style.width = strat.personality.greed + '%';
}

function updateTurnInfo(current, total) {
  document.getElementById('turnInfo').textContent = `Turn ${current} / ${total}`;
}

function updateMatchStatus(cls, text) {
  const el = document.getElementById('matchStatus');
  el.className = 'match-status ' + cls;
  el.textContent = text;
}

function showWinnerOverlay(winner, scoreA, scoreB) {
  const overlay = document.getElementById('winnerOverlay');
  const textEl = document.getElementById('winnerText');
  const subEl = document.getElementById('winnerSub');

  if (winner === 'draw') {
    textEl.textContent = 'Draw!';
    textEl.style.color = ARC3[15]; // purple
  } else if (winner === 'A') {
    textEl.textContent = 'Agent A Wins!';
    textEl.style.color = ARC3[C.A_HEAD];
  } else {
    textEl.textContent = 'Agent B Wins!';
    textEl.style.color = ARC3[C.B_HEAD];
  }
  subEl.textContent = `Score: ${scoreA} - ${scoreB}`;
  overlay.classList.add('show');
}

function hideWinnerOverlay() {
  document.getElementById('winnerOverlay').classList.remove('show');
}


/* ═══════════════════════════════════════════════════════════════════════════
   Theme
   ═══════════════════════════════════════════════════════════════════════════ */

function toggleTheme() {
  const html = document.documentElement;
  const current = html.getAttribute('data-theme');
  const next = current === 'light' ? null : 'light';
  if (next) {
    html.setAttribute('data-theme', next);
    localStorage.setItem('arc-theme', next);
  } else {
    html.removeAttribute('data-theme');
    localStorage.removeItem('arc-theme');
  }
  updateThemeBtn();
}

function updateThemeBtn() {
  const btn = document.getElementById('themeToggle');
  if (btn) {
    const isLight = document.documentElement.getAttribute('data-theme') === 'light';
    btn.textContent = isLight ? '\u263E' : '\u2600';
  }
}


/* ═══════════════════════════════════════════════════════════════════════════
   Keyboard Shortcuts
   ═══════════════════════════════════════════════════════════════════════════ */

document.addEventListener('keydown', e => {
  if ((Arena.mode !== 'match' && Arena.mode !== 'observe') || !Arena.history) return;

  if (e.key === ' ' || e.key === 'k') { e.preventDefault(); arenaPlayPause(); }
  if (e.key === 'ArrowLeft' || e.key === 'j') { e.preventDefault(); arenaStepBack(); }
  if (e.key === 'ArrowRight' || e.key === 'l') { e.preventDefault(); arenaStepForward(); }
  if (e.key === 'Home') { e.preventDefault(); stopPlayback(); scrubTo(0); }
  if (e.key === 'End') { e.preventDefault(); stopPlayback(); scrubTo(Arena.history.length - 1); }
  if (e.key === 'Escape') {
    if (Arena.mode === 'observe') exitArenaObs();
    else backToSetup();
  }
});


/* ═══════════════════════════════════════════════════════════════════════════
   Agent Mode (Harness default)
   ═══════════════════════════════════════════════════════════════════════════ */

function getAgentMode(agent) {
  return localStorage.getItem(`arc_arena_${agent.toLowerCase()}_mode`) || 'harness';
}

function toggleAgentMode(agent) {
  const current = getAgentMode(agent);
  const next = current === 'harness' ? 'code' : 'harness';
  const codeDiv = document.getElementById(`codeMode${agent}`);
  const harnessDiv = document.getElementById(`harnessMode${agent}`);
  if (next === 'code') {
    if (harnessDiv) harnessDiv.style.display = 'none';
    if (codeDiv) codeDiv.style.display = '';
  } else {
    if (codeDiv) codeDiv.style.display = 'none';
    if (harnessDiv) harnessDiv.style.display = '';
    const container = document.getElementById(`harnessSettings${agent}`);
    if (container && !container.dataset.rendered) {
      const savedType = localStorage.getItem(`arc_arena_${agent.toLowerCase()}_scaffolding_type`) || 'linear';
      renderArenaHarness(agent, savedType);
      container.dataset.rendered = '1';
    }
  }
  localStorage.setItem(`arc_arena_${agent.toLowerCase()}_mode`, next);
}


/* ═══════════════════════════════════════════════════════════════════════════
   Arena Harness Settings Renderer
   Renders scaffolding settings into agent panels using SCAFFOLDING_SCHEMAS
   ═══════════════════════════════════════════════════════════════════════════ */

function renderArenaHarness(agent, schemaId) {
  const schema = SCAFFOLDING_SCHEMAS[schemaId];
  if (!schema) return;

  const prefix = `arena${agent}_`;
  const container = document.getElementById(`harnessSettings${agent}`);
  if (!container) return;

  let html = '';

  // Harness type selector
  html += '<div class="setting-section">';
  html += '<div class="setting-label">Harness</div>';
  html += `<select class="setting-select" id="${prefix}scaffoldingSelect" onchange="switchArenaHarness('${agent}', this.value)">`;
  for (const key of Object.keys(SCAFFOLDING_SCHEMAS)) {
    const s = SCAFFOLDING_SCHEMAS[key];
    html += `<option value="${key}"${key === schemaId ? ' selected' : ''}>${s.name}</option>`;
  }
  html += '</select>';
  html += `<div style="font-size:10px;color:var(--text-dim);margin-top:4px;">${schema.description}</div>`;
  html += '</div>';

  // Pipeline visualizer
  html += `<div id="${prefix}pipelineViz" style="margin-bottom:8px;"></div>`;

  // Render sections
  for (const section of schema.sections) {
    const openCls = section.open ? ' open' : '';
    html += `<div class="opt-section${openCls}" id="${prefix}${section.id}">`;
    html += `<div class="opt-header" onclick="arenaToggleSection('${prefix}${section.id}')">`;
    html += `<span>${section.label}</span><span class="chevron">&#9654;</span></div>`;

    if (section.customHtml) {
      // Replace static IDs with prefixed ones for BYOK containers
      let customHtml = section.customHtml();
      customHtml = customHtml.replace(/id="byokKeysContainer"/g, `id="${prefix}byokKeysContainer"`);
      customHtml = customHtml.replace(/id="copilotNotAuth"/g, `id="${prefix}copilotNotAuth"`);
      customHtml = customHtml.replace(/id="copilotAuthed"/g, `id="${prefix}copilotAuthed"`);
      customHtml = customHtml.replace(/id="copilotDeviceCode"/g, `id="${prefix}copilotDeviceCode"`);
      customHtml = customHtml.replace(/id="copilotUserCode"/g, `id="${prefix}copilotUserCode"`);
      customHtml = customHtml.replace(/id="copilotVerifyLink"/g, `id="${prefix}copilotVerifyLink"`);
      html += `<div class="opt-body">${customHtml}</div>`;
    } else if (section.fields) {
      html += `<div class="opt-body${section.bodyClass ? ' ' + section.bodyClass : ''}">`;
      for (const f of section.fields) {
        html += arenaRenderField(f, prefix);
      }
      html += '</div>';
    } else if (section.groups) {
      html += '<div class="opt-body">';
      for (const g of section.groups) {
        html += arenaRenderGroup(g, prefix);
      }
      html += '</div>';
    }
    html += '</div>';
  }

  container.innerHTML = html;

  // Render pipeline visualizer
  arenaRenderPipeline(schema, `${prefix}pipelineViz`);

  // Populate model selects
  arenaPopulateModels(prefix);

  // Restore saved settings
  arenaRestoreSettings(agent, schemaId);
}

function switchArenaHarness(agent, schemaId) {
  localStorage.setItem(`arc_arena_${agent.toLowerCase()}_scaffolding_type`, schemaId);
  renderArenaHarness(agent, schemaId);
}

function arenaToggleSection(sectionId) {
  const section = document.getElementById(sectionId);
  if (section) section.classList.toggle('open');
}

function arenaRenderField(f, prefix) {
  const id = prefix + f.id;
  switch (f.type) {
    case 'toggle': {
      const label = f.labelHtml || f.label;
      return `<div class="opt-row"><span class="opt-label">${label}</span><label class="toggle"><input type="checkbox" id="${id}"${f.default ? ' checked' : ''}><span class="slider"></span></label></div>`;
    }
    case 'model-select': {
      let h = '<div style="margin-bottom:8px;">';
      h += `<select id="${id}"><option value="">Loading...</option></select>`;
      if (f.capsId) h += `<div class="model-caps" id="${prefix}${f.capsId}"></div>`;
      h += '</div>';
      return h;
    }
    case 'quadswitch':
    case 'triswitch':
    case 'multiswitch': {
      const cls = f.type === 'quadswitch' ? 'quadswitch' : 'triswitch';
      let h = '<div>';
      h += `<div class="opt-label" style="margin-bottom:4px;">${f.label}</div>`;
      h += `<div class="${cls}" id="${id}">`;
      for (const o of f.options) {
        h += `<label><input type="radio" name="${prefix}${f.name}" value="${o.v}"${o.checked ? ' checked' : ''}><span>${o.l}</span></label>`;
      }
      h += '</div>';
      if (f.hint) h += `<div style="font-size:10px;color:var(--text-dim);margin-top:4px;">${f.hint}</div>`;
      h += '</div>';
      return h;
    }
    case 'number-spin': {
      let h = '<div class="opt-row" style="margin-top:8px;">';
      h += `<span class="opt-label">${f.label}</span>`;
      h += '<span class="spin-wrap">';
      h += `<input type="number" id="${id}" value="${f.default}" min="${f.min}" max="${f.max}" step="${f.step}" style="width:68px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px 0 0 4px;padding:3px 6px;font-family:inherit;font-size:12px;">`;
      h += '<span class="spin-btns">';
      h += `<button class="spin-btn" onclick="arenaSpinField('${id}',${f.step},${f.max})">&#9650;</button>`;
      h += `<button class="spin-btn" onclick="arenaSpinField('${id}',-${f.step},${f.max},${f.min})">&#9660;</button>`;
      h += '</span></span></div>';
      return h;
    }
    case 'number-input': {
      let h = `<div class="opt-row"><span class="opt-label">${f.label}</span>`;
      h += `<input type="number" id="${id}"`;
      if (f.default !== undefined) h += ` value="${f.default}"`;
      if (f.placeholder) h += ` placeholder="${f.placeholder}"`;
      h += ` min="${f.min}" max="${f.max}"`;
      h += ` style="width:${f.width || '55px'};background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:3px 6px;font-family:inherit;font-size:12px;">`;
      h += '</div>';
      return h;
    }
    case 'number-spin-unit': {
      let h = `<div class="opt-row"><span class="opt-label">${f.label}</span>`;
      h += '<span class="spin-wrap">';
      h += `<input type="number" id="${id}" value="${f.default}" min="${f.min}" step="${f.step}" style="width:${f.width || '68px'};background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px 0 0 4px;padding:3px 6px;font-family:inherit;font-size:12px;">`;
      h += '<span class="spin-btns">';
      h += `<button class="spin-btn" onclick="arenaSpinField('${id}',${f.step},999999)">&#9650;</button>`;
      h += `<button class="spin-btn" onclick="arenaSpinField('${id}',-${f.step},999999,${f.min})">&#9660;</button>`;
      h += '</span></span>';
      h += `<select id="${prefix}${f.unitId}" style="width:62px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:3px 4px;font-family:inherit;font-size:11px;margin-left:4px;">`;
      for (const u of f.units) {
        h += `<option value="${u.v}"${u.selected ? ' selected' : ''}>${u.l}</option>`;
      }
      h += '</select></div>';
      return h;
    }
    case 'compact-model-select': {
      let h = '<div style="margin-bottom:8px;">';
      h += `<select id="${id}" style="width:100%;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:6px 8px;font-family:inherit;font-size:12px;">`;
      h += '<option value="auto">Auto (cheapest of same provider)</option>';
      h += '<option value="auto-fastest">Auto (fastest of same provider)</option>';
      h += '<option value="same">Same as reasoning</option>';
      h += '</select>';
      if (f.hint) h += `<div style="font-size:9px;color:var(--dim);margin-top:3px;">${f.hint}</div>`;
      h += '</div>';
      return h;
    }
    case 'grid-2col':
    case 'grid-2col-body': {
      let h = `<div class="settings-grid"${f.marginBottom ? ` style="margin-bottom:${f.marginBottom};"` : ''}>`;
      for (const child of f.children) {
        h += arenaRenderField(child, prefix);
      }
      h += '</div>';
      return h;
    }
    default: return '';
  }
}

function arenaRenderGroup(g, prefix) {
  let h = '';
  if (g.toggleId) {
    h += '<div class="sub-header" style="display:flex;align-items:center;justify-content:space-between;">';
    h += `<span>${g.subHeader}</span>`;
    h += `<label class="toggle" style="margin:0;"><input type="checkbox" id="${prefix}${g.toggleId}"${g.toggleDefault ? ' checked' : ''}><span class="slider"></span></label>`;
    h += '</div>';
    h += `<div id="${prefix}${g.bodyId}">`;
  } else {
    h += `<div class="sub-header">${g.subHeader}</div>`;
  }
  for (const f of g.fields) {
    h += arenaRenderField(f, prefix);
  }
  if (g.toggleId) h += '</div>';
  return h;
}

function arenaSpinField(id, delta, max, min) {
  const el = document.getElementById(id);
  if (!el) return;
  const cur = parseInt(el.value) || 0;
  const step = Math.abs(delta);
  let next = cur + delta;
  if (min !== undefined) next = Math.max(min, next);
  if (max !== undefined) next = Math.min(max, next);
  el.value = next;
}


/* ═══════════════════════════════════════════════════════════════════════════
   Arena Pipeline Visualizer (simplified version)
   ═══════════════════════════════════════════════════════════════════════════ */

function arenaRenderPipeline(schema, containerId) {
  const container = document.getElementById(containerId);
  if (!container || !schema.pipeline?.length) { if (container) container.innerHTML = ''; return; }

  const nodes = schema.pipeline;
  const edges = schema.edges || [];

  // Agent Spawn: compact 3-row layout (Orchestrator → agents → memory)
  if (schema.id === 'agent_spawn') {
    const agentIds = ['explorer', 'theorist', 'tester', 'solver'];
    const agentNodes = nodes.filter(n => agentIds.includes(n.id));
    const orchNode = nodes.find(n => n.id === 'orchestrator');
    const memNode = nodes.find(n => n.id === 'memory');
    const aW = 80, aH = 22, aGap = 6, orchW = 120, orchH = 26, memW = 120, memH = 22;
    const totalAgentW = agentNodes.length * aW + (agentNodes.length - 1) * aGap;
    const svgW = Math.max(totalAgentW, orchW, memW) + 30;
    const cx = svgW / 2;
    const r1Y = 8, r2Y = 58, r3Y = 108;
    const nodePos = {};
    if (orchNode) nodePos[orchNode.id] = { x: cx - orchW / 2, y: r1Y, w: orchW, h: orchH };
    const agentStartX = cx - totalAgentW / 2;
    agentNodes.forEach((n, i) => { nodePos[n.id] = { x: agentStartX + i * (aW + aGap), y: r2Y, w: aW, h: aH }; });
    if (memNode) nodePos[memNode.id] = { x: cx - memW / 2, y: r3Y, w: memW, h: memH };
    const svgH = r3Y + memH + 8;
    let svg = `<svg width="${svgW}" height="${svgH}" viewBox="0 0 ${svgW} ${svgH}" xmlns="http://www.w3.org/2000/svg" style="display:block;margin:0 auto;">`;
    svg += '<defs><marker id="arrowA" viewBox="0 0 10 7" refX="10" refY="3.5" markerWidth="8" markerHeight="6" orient="auto-start-reverse"><path d="M0 0 L10 3.5 L0 7 z" fill="var(--text-dim)"/></marker></defs>';
    for (const an of agentNodes) {
      const op = nodePos['orchestrator'], ap = nodePos[an.id];
      if (op && ap) { svg += `<line x1="${op.x+op.w/2}" y1="${op.y+op.h}" x2="${ap.x+ap.w/2}" y2="${ap.y}" stroke="var(--text-dim)" stroke-width="1" marker-end="url(#arrowA)" opacity="0.4"/>`; }
      const mp = nodePos['memory'];
      if (ap && mp) { svg += `<line x1="${ap.x+ap.w/2}" y1="${ap.y+ap.h}" x2="${mp.x+mp.w/2}" y2="${mp.y}" stroke="var(--text-dim)" stroke-width="1" marker-end="url(#arrowA)" opacity="0.4"/>`; }
    }
    for (const node of nodes) {
      const p = nodePos[node.id]; if (!p) continue;
      svg += `<rect x="${p.x}" y="${p.y}" width="${p.w}" height="${p.h}" rx="5" fill="none" stroke="${node.color}" stroke-width="1.5"/>`;
      svg += `<text x="${p.x+p.w/2}" y="${p.y+p.h/2+1}" font-size="${agentIds.includes(node.id)?8:9}" fill="${node.color}" text-anchor="middle" dominant-baseline="middle" font-weight="600">${node.label}</text>`;
    }
    svg += '</svg>';
    container.innerHTML = svg;
    return;
  }

  // Simple vertical pipeline for side panel
  const nodeW = 120, nodeH = 24, gapY = 20, padX = 20, padTop = 8, padBot = 8;
  const svgW = nodeW + padX * 2;
  const svgH = padTop + nodes.length * nodeH + (nodes.length - 1) * gapY + padBot;

  let svg = `<svg width="${svgW}" height="${svgH}" viewBox="0 0 ${svgW} ${svgH}" xmlns="http://www.w3.org/2000/svg" style="display:block;margin:0 auto;">`;
  svg += '<defs><marker id="arrowA" viewBox="0 0 10 7" refX="10" refY="3.5" markerWidth="8" markerHeight="6" orient="auto-start-reverse"><path d="M0 0 L10 3.5 L0 7 z" fill="var(--text-dim)"/></marker></defs>';

  const nodePos = {};
  nodes.forEach((n, i) => {
    nodePos[n.id] = { x: padX, y: padTop + i * (nodeH + gapY), w: nodeW, h: nodeH };
  });

  // Draw edges (forward only for simplicity)
  for (const e of edges) {
    const fromP = nodePos[e.from];
    const toP = nodePos[e.to];
    if (!fromP || !toP) continue;
    const x = fromP.x + fromP.w / 2;
    const y1 = fromP.y + fromP.h;
    const y2 = toP.y;
    if (y2 > y1) {
      svg += `<line x1="${x}" y1="${y1}" x2="${x}" y2="${y2}" stroke="var(--text-dim)" stroke-width="1" marker-end="url(#arrowA)" opacity="0.4"/>`;
    }
  }

  // Draw nodes
  for (const node of nodes) {
    const p = nodePos[node.id];
    svg += `<rect x="${p.x}" y="${p.y}" width="${p.w}" height="${p.h}" rx="5" fill="none" stroke="${node.color}" stroke-width="1.5"/>`;
    svg += `<text x="${p.x + p.w/2}" y="${p.y + p.h/2 + 1}" font-size="9" fill="${node.color}" text-anchor="middle" dominant-baseline="middle" font-weight="600">${node.label}</text>`;
  }

  svg += '</svg>';
  container.innerHTML = svg;
}


/* ═══════════════════════════════════════════════════════════════════════════
   Arena Model Loading & Population
   ═══════════════════════════════════════════════════════════════════════════ */

async function arenaLoadModels() {
  try {
    const resp = await fetch('/api/llm/models');
    const data = await resp.json();
    Arena.modelsData = data.models || [];
    Arena.modelsLoaded = true;

    // Sync to global modelsData so getModelInfo() and callLLM() work from arena context
    modelsData = Arena.modelsData;

    // Populate any already-rendered harness panels
    arenaPopulateModels('arenaA_');
    arenaPopulateModels('arenaB_');
  } catch (e) {
    console.warn('[Arena] Failed to load models:', e.message);
  }
}

function arenaPopulateModels(prefix) {
  if (!Arena.modelsLoaded) return;

  const models = Arena.modelsData;
  const groups = {};
  for (const m of models) {
    if (!m.available) continue;
    const key = m.provider.charAt(0).toUpperCase() + m.provider.slice(1);
    (groups[key] ??= []).push(m);
  }
  const providerOrder = ['Local', 'Lmstudio', 'Ollama', 'Copilot', 'Gemini', 'Anthropic', 'Cloudflare', 'Groq', 'Mistral', 'Huggingface'];
  const providerLabels = { Local: 'Local Models (free)', Lmstudio: 'LM Studio (free, local)', Puter: 'Puter.js (free)' };

  const unavail = models.filter(m => !m.available);
  const byokGroups = {};
  for (const m of unavail) {
    const key = m.provider.charAt(0).toUpperCase() + m.provider.slice(1);
    (byokGroups[key] ??= []).push(m);
  }
  const byokProviderOrder = ['Gemini', 'Anthropic', 'Cloudflare', 'Groq', 'Mistral', 'Huggingface'];

  // Find all <select> elements in this prefix's container
  const container = document.getElementById(prefix === 'arenaA_' ? 'harnessSettingsA' : 'harnessSettingsB');
  if (!container) return;

  const selects = container.querySelectorAll('select');
  for (const sel of selects) {
    // Only populate model selects (not harness selector, compact selects, etc.)
    if (!sel.id || !sel.id.endsWith('modelSelect') && !sel.id.endsWith('ModelSelect')) continue;
    if (sel.querySelector('option[value="auto"]')) continue; // compact model select

    const savedVal = sel.value;
    sel.innerHTML = '<option value="">Select a model...</option>';

    for (const prov of providerOrder) {
      const provModels = groups[prov];
      if (!provModels?.length) continue;
      const grp = document.createElement('optgroup');
      grp.label = providerLabels[prov] || prov;
      for (const m of provModels) {
        const opt = document.createElement('option');
        opt.value = m.name;
        const caps = [];
        if (m.capabilities?.image) caps.push('IMG');
        if (m.capabilities?.reasoning) caps.push('RSN');
        if (m.capabilities?.tools) caps.push('TLS');
        const capStr = caps.length ? ` [${caps.join(',')}]` : '';
        opt.textContent = `${m.name} — ${m.price}${capStr}`;
        grp.appendChild(opt);
      }
      sel.appendChild(grp);
    }

    for (const prov of byokProviderOrder) {
      const provModels = byokGroups[prov];
      if (!provModels?.length) continue;
      const grp = document.createElement('optgroup');
      grp.label = `${prov} (BYOK)`;
      for (const m of provModels) {
        const opt = document.createElement('option');
        opt.value = m.name;
        const caps = [];
        if (m.capabilities?.image) caps.push('IMG');
        if (m.capabilities?.reasoning) caps.push('RSN');
        if (m.capabilities?.tools) caps.push('TLS');
        const capStr = caps.length ? ` [${caps.join(',')}]` : '';
        opt.textContent = `${m.name} — ${m.price}${capStr}`;
        grp.appendChild(opt);
      }
      sel.appendChild(grp);
    }

    if (savedVal && [...sel.options].some(o => o.value === savedVal)) sel.value = savedVal;
  }
}

function arenaRestoreSettings(agent, schemaId) {
  try {
    const raw = localStorage.getItem(`arc_arena_${agent.toLowerCase()}_settings_${schemaId}`);
    if (!raw) return;
    const s = JSON.parse(raw);
    const prefix = `arena${agent}_`;

    // Restore model select
    const modelSel = document.getElementById(`${prefix}modelSelect`);
    if (modelSel && s.model && [...modelSel.options].some(o => o.value === s.model)) {
      modelSel.value = s.model;
    }
  } catch {}
}

function arenaSaveSettings(agent) {
  try {
    const prefix = `arena${agent}_`;
    const scaffoldingSel = document.getElementById(`${prefix}scaffoldingSelect`);
    const schemaId = scaffoldingSel?.value || 'linear';
    const modelSel = document.getElementById(`${prefix}modelSelect`);
    const settings = {
      scaffolding: schemaId,
      model: modelSel?.value || '',
    };
    localStorage.setItem(`arc_arena_${agent.toLowerCase()}_settings_${schemaId}`, JSON.stringify(settings));
  } catch {}
}


/* ═══════════════════════════════════════════════════════════════════════════
   Arena Observatory — Per-Agent Observability
   ═══════════════════════════════════════════════════════════════════════════ */

function enterArenaObs(agent) {
  if (!Arena.history) return;
  Arena.mode = 'observe';
  Arena.obsAgent = agent;

  const obsScreen = document.getElementById('arenaObsScreen');
  const obsBody = document.getElementById('arenaObsBody');
  const obsTitle = document.getElementById('obsAgentTitle');

  // Show obs screen
  obsScreen.style.display = 'flex';

  // Set layout direction (agent A = obs LEFT, agent B = obs RIGHT)
  obsBody.className = 'arena-obs-body ' + (agent === 'A' ? 'obs-agent-a' : 'obs-agent-b');

  // Update title
  obsTitle.textContent = `Agent ${agent} Observatory`;

  // Update agent switch buttons
  document.getElementById('obsSwitchA').classList.toggle('active', agent === 'A');
  document.getElementById('obsSwitchB').classList.toggle('active', agent === 'B');

  // Update obs status
  document.getElementById('obsStatAgent').textContent = agent;

  // Set up obs scrubber
  const maxStep = Arena.history.length - 1;
  document.getElementById('arenaObsScrubber').max = maxStep;
  document.getElementById('arenaObsScrubber').value = Arena.currentStep;

  // Build obs log for this agent
  buildObsLog(agent);

  // Render current step on obs canvas
  renderStep(Arena.currentStep);
}

function exitArenaObs() {
  Arena.mode = 'match';
  Arena.obsAgent = null;
  document.getElementById('arenaObsScreen').style.display = 'none';
}

function switchArenaObs(agent) {
  if (Arena.obsAgent === agent) return;
  enterArenaObs(agent);
}

function buildObsLog(agent) {
  const logContainer = document.getElementById('arenaObsLog');
  logContainer.innerHTML = '';

  if (!Arena.history) return;

  for (let i = 0; i < Arena.history.length; i++) {
    const frame = Arena.history[i];
    const agentData = agent === 'A' ? frame.agentA : frame.agentB;
    if (!agentData) continue;

    const colorIndex = agent === 'A' ? C.A_HEAD : C.B_HEAD;
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.dataset.step = i;
    entry.innerHTML =
      `<div class="log-entry-turn">Turn ${frame.turn}</div>` +
      `<div class="log-entry-move" style="color:${ARC3[colorIndex]}">${escHtml(agentData.move)}</div>` +
      `<div class="log-entry-reasoning">${escHtml(agentData.reasoning)}</div>`;
    entry.addEventListener('click', () => { stopPlayback(); scrubTo(i); });
    logContainer.appendChild(entry);
  }
}

function highlightObsLogEntry(step) {
  const logContainer = document.getElementById('arenaObsLog');
  if (!logContainer) return;

  logContainer.querySelectorAll('.log-entry.active').forEach(el => el.classList.remove('active'));
  const active = logContainer.querySelector(`.log-entry[data-step="${step}"]`);
  if (active) {
    active.classList.add('active');
    active.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
}


/* ═══════════════════════════════════════════════════════════════════════════
   Auto Research Module
   ═══════════════════════════════════════════════════════════════════════════ */

const AR = {
  mode: 'community',       // 'community' | 'local'
  selectedGame: null,       // current game being researched
  pollTimer: null,
  localRunning: false,
};

function switchArenaMode(mode, skipHash) {
  const matchBtn = document.getElementById('modeBtnMatch');
  const researchBtn = document.getElementById('modeBtnResearch');
  const layout = document.getElementById('arenaLayout');
  const researchView = document.getElementById('arResearchView');
  const statusBar = document.getElementById('arStatusBar');

  // Update URL hash
  if (!skipHash && typeof _ARENA_VIEW_TO_HASH !== 'undefined') {
    const hash = _ARENA_VIEW_TO_HASH[mode] || 'matchup';
    if (location.hash !== '#' + hash) history.replaceState(null, '', '#' + hash);
  }

  if (mode === 'research') {
    matchBtn.classList.remove('active');
    researchBtn.classList.add('active');
    layout.style.display = 'none';
    researchView.style.display = 'flex';
    statusBar.style.display = 'flex';
    arBuildGameList();
    if (!AR.selectedGame) {
      // Auto-select first game (snake) on initial load
      const firstGame = ARENA_GAMES[0];
      if (firstGame) arSelectGame(firstGame.id, 'community');
    }
  } else {
    researchBtn.classList.remove('active');
    matchBtn.classList.add('active');
    layout.style.display = 'flex';
    researchView.style.display = 'none';
    statusBar.style.display = 'none';
    arStopPolling();
  }
}

function arBuildGameList() {
  const container = document.getElementById('arGameList');
  container.innerHTML = '';

  const categories = [];
  const catMap = {};
  for (const game of ARENA_GAMES) {
    const cat = game.category || 'Other';
    if (!catMap[cat]) { catMap[cat] = []; categories.push(cat); }
    catMap[cat].push(game);
  }

  for (const cat of categories) {
    const catDiv = document.createElement('div');
    catDiv.className = 'ar-game-cat';
    catDiv.innerHTML = `<div class="ar-game-cat-label">${escHtml(cat)}</div>`;

    for (const game of catMap[cat]) {
      const item = document.createElement('div');
      item.className = 'ar-game-item' + (AR.selectedGame === game.id ? ' active' : '');
      item.dataset.game = game.id;
      const tagsHtml = (game.tags || []).map(t => `<span class="ar-game-item-tag">${escHtml(t)}</span>`).join('');

      // Canvas thumbnail — rendered with the game's preview function
      const canvas = document.createElement('canvas');
      canvas.className = 'ar-game-item-preview';
      canvas.width = 64; canvas.height = 64;
      item.appendChild(canvas);

      const meta = document.createElement('div');
      meta.className = 'ar-game-item-meta';
      meta.innerHTML =
        `<div class="ar-game-item-name">${escHtml(game.title)}</div>` +
        `<div class="ar-game-item-desc">${escHtml(game.desc || '')}</div>` +
        (tagsHtml ? `<div class="ar-game-item-tags">${tagsHtml}</div>` : '');
      item.appendChild(meta);

      item.addEventListener('click', () => arSelectGame(game.id, 'community'));
      catDiv.appendChild(item);

      // Render preview using the game's preview function (ARC-style grid)
      if (game.preview) {
        try { game.preview(canvas, game.config); } catch (e) { /* skip */ }
      }
    }
    container.appendChild(catDiv);
  }
}

async function arSelectGame(gameId, mode) {
  AR.selectedGame = gameId;
  AR.mode = mode || 'community';

  // Highlight in game list
  document.querySelectorAll('.ar-game-item').forEach(el => {
    el.classList.toggle('active', el.dataset.game === gameId);
  });

  const game = ARENA_GAMES.find(g => g.id === gameId);

  // Local mode: skip community data fetch — local research UI is handled by arStartLocal
  if (mode === 'local') {
    document.getElementById('arStatusText').textContent = `${game ? game.title : gameId} — Local Research`;
    return;
  }

  // Community mode: fetch research data from server
  document.getElementById('arStatusText').textContent = `Loading ${game ? game.title : gameId}...`;
  try {
    const data = await fetch(`/api/arena/research/${gameId}`).then(r => r.json());
    if (data.error) {
      document.getElementById('arStatusText').textContent = `Error: ${data.error}`;
      return;
    }
    arRenderResearch(gameId, data);
    arStartPolling(gameId);
  } catch (e) {
    document.getElementById('arStatusText').textContent = `Failed to load: ${e.message}`;
  }
}

function arRenderResearch(gameId, data) {
  const game = ARENA_GAMES.find(g => g.id === gameId);
  const title = game ? game.title : gameId;

  // Status bar
  document.getElementById('arStatusText').textContent =
    `${title} | Gen ${data.generation} | ${data.agent_count} agents | ${data.game_count} games` +
    (data.best_agent ? ` | Best: ${data.best_agent} (${data.best_elo})` : '');

  // Program.md
  arRenderProgram(data.program);

  // Leaderboard
  arRenderLeaderboard(gameId, data.leaderboard || []);
  document.getElementById('arAgentCount').textContent = `${data.agent_count} agents`;

  // Comments (load separately for freshness)
  arLoadComments(gameId);

  // Recent games
  arLoadRecentGames(gameId);
}

// Default program.md for snake (shown when server has no program yet)
const _AR_DEFAULT_PROGRAM = `# Snake Agent Evolution Program

## Objective
Create snake agents that win competitive 2-player snake games on a 20x20 grid.

## Agent Interface
Each agent is a standalone Python file with ONE function:
\`\`\`python
def get_move(state):
    # state keys:
    #   'grid_size': (20, 20)
    #   'my_snake': [[x,y], ...] - head first, LISTS not tuples
    #   'my_direction': 'UP'/'DOWN'/'LEFT'/'RIGHT'
    #   'enemy_snake': [[x,y], ...] - empty list if dead
    #   'enemy_direction': str or None
    #   'food': [[x,y], ...]
    #   'turn': int
    # Returns: 'UP', 'DOWN', 'LEFT', or 'RIGHT'
\`\`\`

## Critical Rules
- Coordinates are LISTS [x,y] - convert with tuple() before using in sets
- Always: \\\`occupied = set(tuple(s) for s in state['my_snake'])\\\`
- enemy_snake can be empty (dead) - always check first
- Only standard library (random, math, collections). No os/subprocess/socket.
- Must return in <100ms. Must not crash.
- Directions: UP=(0,-1) DOWN=(0,1) LEFT=(-1,0) RIGHT=(1,0)
- (0,0) = top-left, x right, y down

## Agent Memory (prev_moves)
Each agent has access to \\\`state['prev_moves']\\\` — a mutable list that persists across turns within a game.
Use it to track your own history, detect patterns, or implement stateful strategies.

## Scoring & ELO System
Agents are ranked by ELO rating (starting at 1000, K-factor=32).

**How games are decided:**
- Last snake alive wins (opponent hit wall, self, or your body)
- Head-on collision (both heads on same cell) = both die = draw
- If both survive to turn 350 (max turns): longer snake wins; equal length = draw

**How ELO updates:**
- Expected score: E = 1 / (1 + 10^((opponent_elo - your_elo) / 400))
- Win = 1.0, Draw = 0.5, Loss = 0.0
- New ELO = old ELO + 32 * (actual - expected)

**Key implications for strategy:**
- Killing the opponent (making them crash) is the fastest way to win
- If you can't kill them, out-eat them — longer snake wins at timeout
- Draws gain ELO only if opponent is higher-rated
- Survival matters: crashing = instant loss, even if you were longer

## Strategies to Explore
- BFS/A* pathfinding to nearest food
- Flood fill to maximize reachable space
- Enemy movement prediction and path cutting
- Center board control
- Survival-first: maximize distance from walls and enemy
- Hybrid: BFS when safe, defensive when threatened
- Trap setting: herd enemy toward walls
- Space denial: cut off enemy's reachable area

## Current Focus
Your #1 goal is to BEAT the current top-performing agents on the leaderboard.

Study the best agent's code carefully. Identify its weaknesses:
- What situations does it handle poorly?
- Where does it make suboptimal decisions?
- What strategies would exploit its blind spots?

Then build an agent specifically designed to counter and outperform it.
Every new agent should aim to climb to #1 on the ELO leaderboard.
`;

// Store original program content for diffing
let _arProgramOriginal = '';

function arRenderProgram(program) {
  const view = document.getElementById('arProgramView');
  const content = (program && program.content) || _AR_DEFAULT_PROGRAM;
  _arProgramOriginal = content;

  view.innerHTML = `<div class="ar-markdown">${arSimpleMarkdown(content)}</div>`;

  // Hide edit view, show rendered
  const editEl = document.getElementById('arProgramEdit');
  if (editEl) editEl.style.display = 'none';
  view.style.display = '';

  // Version selector
  const sel = document.getElementById('arProgramVersion');
  if (sel) {
    sel.innerHTML = '';
    if (program && program.versions) {
      for (const v of program.versions) {
        const opt = document.createElement('option');
        opt.value = v.version;
        opt.textContent = `v${v.version}` + (v.author ? ` (${v.author})` : '');
        sel.appendChild(opt);
      }
    }
  }

  // Active proposal indicator
  if (program && program.active_proposal) {
    const remaining = Math.max(0, Math.ceil((program.active_proposal.vote_deadline - Date.now()/1000)));
    view.innerHTML += `<div class="ar-vote-banner">Active proposal: ${remaining}s left — For: ${program.active_proposal.votes_for} Against: ${program.active_proposal.votes_against}</div>`;
  }
}

function arToggleEdit() {
  const view = document.getElementById('arProgramView');
  const edit = document.getElementById('arProgramEdit');
  const textarea = document.getElementById('arProgramTextarea');
  const diff = document.getElementById('arProgramDiff');
  if (!edit || !view) return;

  if (edit.style.display === 'none') {
    // Switch to edit mode
    textarea.value = _arProgramOriginal;
    edit.style.display = 'flex';
    view.style.display = 'none';
    if (diff) diff.style.display = 'none';
    // Live diff on input
    textarea.oninput = () => arUpdateDiff();
  } else {
    arCancelEdit();
  }
}

function arCancelEdit() {
  const view = document.getElementById('arProgramView');
  const edit = document.getElementById('arProgramEdit');
  if (edit) edit.style.display = 'none';
  if (view) view.style.display = '';
}

function arUpdateDiff() {
  const diff = document.getElementById('arProgramDiff');
  const textarea = document.getElementById('arProgramTextarea');
  if (!diff || !textarea) return;

  const oldLines = _arProgramOriginal.split('\n');
  const newLines = textarea.value.split('\n');
  const maxLen = Math.max(oldLines.length, newLines.length);
  let html = '';
  let hasChanges = false;

  for (let i = 0; i < maxLen; i++) {
    const oldLine = i < oldLines.length ? oldLines[i] : undefined;
    const newLine = i < newLines.length ? newLines[i] : undefined;
    if (oldLine === newLine) {
      // Context line — skip for brevity unless near a change
    } else {
      hasChanges = true;
      if (oldLine !== undefined && newLine !== undefined) {
        html += `<div class="ar-diff-del">- ${escHtml(oldLine)}</div>`;
        html += `<div class="ar-diff-add">+ ${escHtml(newLine)}</div>`;
      } else if (oldLine !== undefined) {
        html += `<div class="ar-diff-del">- ${escHtml(oldLine)}</div>`;
      } else {
        html += `<div class="ar-diff-add">+ ${escHtml(newLine)}</div>`;
      }
    }
  }

  if (hasChanges) {
    diff.innerHTML = html;
    diff.style.display = 'block';
  } else {
    diff.style.display = 'none';
  }
}

function arSimpleMarkdown(text) {
  // Handle code blocks first (```...```)
  let html = '';
  const parts = text.split(/```(\w*)\n?([\s\S]*?)```/g);
  for (let i = 0; i < parts.length; i++) {
    if (i % 3 === 0) {
      // Normal text
      html += _arInlineMarkdown(parts[i]);
    } else if (i % 3 === 1) {
      // Language tag (skip)
    } else {
      // Code block content
      html += `<pre><code>${escHtml(parts[i])}</code></pre>`;
    }
  }
  return html;
}

function _arInlineMarkdown(text) {
  return escHtml(text)
    .replace(/^#### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>[\s\S]*?<\/li>)/g, '<ul>$1</ul>')
    .replace(/<\/ul>\s*<ul>/g, '')
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br>');
}

function arRenderLeaderboard(gameId, agents) {
  const tbody = document.getElementById('arLeaderboardBody');
  if (!agents.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="ar-no-data">No agents yet</td></tr>';
    return;
  }
  tbody.innerHTML = agents.map((a, i) => {
    const eloClass = a.elo >= 1200 ? 'ar-elo-high' : a.elo < 1000 ? 'ar-elo-low' : '';
    const humanBadge = a.is_human ? ' <span class="ar-badge-human">H</span>' : '';
    const anchorBadge = a.is_anchor ? ' <span class="ar-badge-anchor">⚓</span>' : '';
    return `<tr class="ar-lb-row" data-agent-id="${a.id}">
      <td>${i + 1}</td>
      <td>
        <span class="ar-agent-name" onclick="arShowAgentCode('${gameId}',${a.id},'${escHtml(a.name)}')">${escHtml(a.name)}</span>
        ${humanBadge}${anchorBadge}
      </td>
      <td class="ar-elo ${eloClass}">${Math.round(a.elo)}</td>
      <td>${a.wins}/${a.losses}/${a.draws}</td>
      <td>${a.games_played}</td>
      <td class="ar-contributor">${escHtml(a.contributor || '—')}</td>
      <td>
        ${a.is_human ? '' : `<button class="ar-btn ar-btn-xs" onclick="arShowHumanDialog('${gameId}',${a.id},'${escHtml(a.name)}',${Math.round(a.elo)})">Play ▶</button>`}
      </td>
    </tr>`;
  }).join('');
}

async function arLoadComments(gameId) {
  try {
    const comments = await fetch(`/api/arena/comments/${gameId}`).then(r => r.json());
    const container = document.getElementById('arCommentsList');
    if (!comments.length) {
      container.innerHTML = '<div class="ar-no-data">No discussion yet. Be the first!</div>';
      return;
    }
    container.innerHTML = comments.map(c => `
      <div class="ar-comment">
        <div class="ar-comment-header">
          <span class="ar-comment-author">${escHtml(c.username)}</span>
          <span class="ar-comment-time">${arTimeAgo(c.created_at)}</span>
          <span class="ar-comment-votes">
            <button class="ar-vote-btn" onclick="arVoteComment(${c.id},1)">▲ ${c.upvotes}</button>
            <button class="ar-vote-btn" onclick="arVoteComment(${c.id},-1)">▼ ${c.downvotes}</button>
          </span>
        </div>
        <div class="ar-comment-body">${escHtml(c.content)}</div>
      </div>
    `).join('');
  } catch (e) {
    // Silently fail
  }
}

async function arLoadRecentGames(gameId) {
  try {
    const games = await fetch(`/api/arena/games/${gameId}?limit=20`).then(r => r.json());
    const container = document.getElementById('arRecentGames');
    if (!games.length) {
      container.innerHTML = '<div class="ar-no-data">No games yet</div>';
      return;
    }
    container.innerHTML = games.map(g => {
      const winnerClass = g.winner_name === 'Draw' ? 'ar-draw' : '';
      return `<div class="ar-recent-game">
        <span class="ar-rg-agents">${escHtml(g.agent1_name)} vs ${escHtml(g.agent2_name)}</span>
        <span class="ar-rg-result ${winnerClass}">${escHtml(g.winner_name)}</span>
        <span class="ar-rg-turns">${g.turns}t</span>
      </div>`;
    }).join('');
  } catch (e) {
    // Silently fail
  }
}

function arTimeAgo(ts) {
  const s = Math.floor(Date.now()/1000 - ts);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s/60)}m ago`;
  if (s < 86400) return `${Math.floor(s/3600)}h ago`;
  return `${Math.floor(s/86400)}d ago`;
}


/* ── Agent Code Modal ── */

async function arShowAgentCode(gameId, agentId, name) {
  try {
    const agent = await fetch(`/api/arena/agents/${gameId}/${agentId}`).then(r => r.json());
    document.getElementById('arCodeModalTitle').textContent = `${name} — Code`;
    document.getElementById('arCodeModalCode').textContent = agent.code || '(no code)';
    document.getElementById('arCodeModal').style.display = 'flex';
  } catch (e) {
    // Silently fail
  }
}


/* ── Comments ── */

async function arPostComment() {
  if (!AR.selectedGame) return;
  const text = document.getElementById('arCommentText').value.trim();
  if (!text) return;
  try {
    await fetch(`/api/arena/comments/${AR.selectedGame}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ content: text }),
    });
    document.getElementById('arCommentText').value = '';
    arLoadComments(AR.selectedGame);
  } catch (e) {
    // Silently fail
  }
}

async function arVoteComment(commentId, vote) {
  if (!AR.selectedGame) return;
  try {
    await fetch(`/api/arena/comments/${AR.selectedGame}/${commentId}/vote`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ vote }),
    });
    arLoadComments(AR.selectedGame);
  } catch (e) {
    // Silently fail
  }
}


/* ── Program.md ── */

async function arProposeProgram() {
  if (!AR.selectedGame) return;
  const content = document.getElementById('arProgramTextarea').value.trim();
  const summary = document.getElementById('arProgramSummary').value.trim();
  if (!content) return;
  try {
    await fetch(`/api/arena/program/${AR.selectedGame}/propose`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ content, change_summary: summary }),
    });
    document.getElementById('arProgramEdit').style.display = 'none';
    arSelectGame(AR.selectedGame, AR.mode);
  } catch (e) {
    // Silently fail
  }
}

// (Program edit/diff wired via onclick in HTML — arToggleEdit, arCancelEdit, arUpdateDiff)


/* ── Human vs AI Dialog ── */

function arShowHumanDialog(gameId, agentId, name, elo) {
  AR._humanGameId = gameId;
  AR._humanAgentId = agentId;
  document.getElementById('arHumanDialogTitle').textContent = `Play Against: ${name}`;
  document.getElementById('arHumanOpponent').innerHTML =
    `<span class="ar-elo">${elo}</span> ELO — ${name}`;
  document.getElementById('arHumanDialog').style.display = 'flex';

  // Wire up delay radio change to update label
  document.querySelectorAll('input[name="arDelay"]').forEach(r => {
    r.addEventListener('change', () => {
      const ms = parseInt(r.value);
      document.getElementById('arHumanLabel').textContent =
        ms === 0 ? 'human-inf' : `human-${ms}ms`;
    });
  });
}

function arCloseHumanDialog() {
  document.getElementById('arHumanDialog').style.display = 'none';
}

async function arStartHumanPlay() {
  const delay = parseInt(document.querySelector('input[name="arDelay"]:checked')?.value ?? 1000);
  const gameId = AR._humanGameId;
  const agentId = AR._humanAgentId;
  arCloseHumanDialog();

  // Fetch agent code from server (or local pool)
  let agentCode = null;
  let agentName = 'AI';
  const localAgent = LocalResearch?.agents?.find(a => a.id === agentId || a.name === String(agentId));
  if (localAgent) {
    agentCode = localAgent.code;
    agentName = localAgent.name;
  } else {
    try {
      const resp = await fetch(`/api/arena/agents/${gameId}/${agentId}`);
      const data = await resp.json();
      agentCode = data.code;
      agentName = data.name || 'AI';
    } catch (e) {
      alert('Failed to load agent: ' + e.message);
      return;
    }
  }
  if (!agentCode) { alert('Agent has no code'); return; }

  // Launch human play mode (defined in arena-autoresearch.js)
  arLaunchHumanPlay(gameId, agentCode, agentName, delay);
}


/* ── Local Auto Research Dialog ── */

async function arShowLocalDialog(gameId) {
  AR._localGameId = gameId;
  const game = ARENA_GAMES.find(g => g.id === gameId);
  document.getElementById('arLocalDialogTitle').textContent =
    `Local Auto Research: ${game ? game.title : gameId}`;

  // Ensure models are loaded
  if (!Arena.modelsLoaded) {
    await arenaLoadModels();
  }

  // Populate model select from Arena's loaded models
  const sel = document.getElementById('arLocalModel');
  if (sel) {
    sel.innerHTML = '';
    const models = Arena.modelsData || [];
    if (!models.length) {
      sel.innerHTML = '<option value="">No models available</option>';
    } else {
      for (const m of models) {
        const opt = document.createElement('option');
        opt.value = m.name;
        opt.textContent = `${m.name} (${m.provider})`;
        sel.appendChild(opt);
      }
    }
  }

  // Also populate contribute model select
  const contSel = document.getElementById('arContributeModel');
  if (contSel && sel) {
    contSel.innerHTML = sel.innerHTML;
  }

  document.getElementById('arLocalDialog').style.display = 'flex';
}

function arCloseLocalDialog() {
  document.getElementById('arLocalDialog').style.display = 'none';
}

function arStartLocalResearch() {
  const gameId = AR._localGameId;
  const model = document.getElementById('arLocalModel').value;
  const apiKey = document.getElementById('arLocalKey').value;
  const maxTokens = document.getElementById('arLocalTokens').value;

  if (!model) { alert('Select a model'); return; }

  const config = {
    model,
    apiKey,
    maxTokens: parseInt(maxTokens) || 16384,
    workers: parseInt(document.getElementById('arLocalWorkers').value) || 3,
    matchmaking: {
      swiss: parseInt(document.getElementById('arMmSwiss').value) || 90,
      random: parseInt(document.getElementById('arMmRandom').value) || 10,
    },
  };

  arCloseLocalDialog();

  // Switch to research view if not already there
  switchArenaMode('research');

  arSelectGame(gameId, 'local');

  // Start local research (async, runs in background)
  arStartLocal(gameId, config);
}


/* ── Polling ── */

function arStartPolling(gameId) {
  arStopPolling();
  // Refresh dashboard every 60 seconds — leaderboard, comments, recent games
  AR.pollTimer = setInterval(async () => {
    if (AR.selectedGame !== gameId) { arStopPolling(); return; }
    try {
      const data = await fetch(`/api/arena/research/${gameId}`).then(r => r.json());
      if (!data.error) arRenderResearch(gameId, data);
    } catch (e) {
      // Silently fail
    }
  }, 60 * 1000);
}

function arStopPolling() {
  if (AR.pollTimer) { clearInterval(AR.pollTimer); AR.pollTimer = null; }
}


/* ═══════════════════════════════════════════════════════════════════════════
   Bootstrap
   ═══════════════════════════════════════════════════════════════════════════ */

document.addEventListener('DOMContentLoaded', initArena);
