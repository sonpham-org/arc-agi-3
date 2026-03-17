// Author: Claude Opus 4.6
// Date: 2026-03-17 15:00
// PURPOSE: Arena Auto Research — in-browser evolution + tournament engine.
//   Phase 2: headless match runner, per-game state adapters, live tournament canvases.
//   Phase 4: human vs AI play mode — keyboard/click input, timed moves, result submission.
//   Evolution: LLM tool-calling loop generates JS agents using BYOK API keys.
//   Tournament: runs game matches headlessly via game engine classes from arena.js.
//   Swiss matchmaking, ELO tracking, agent validation, safety sandbox.
//   Text-based tool calling (XML tags) for cross-provider compatibility.
//   Mini-frame renderer: snake (custom), chess960 (wooden board + Unicode pieces), ARC3 fallback.
// SRP/DRY check: Pass — reuses callLLM() from scaffolding.js, game engines from arena.js

/* ═══════════════════════════════════════════════════════════════════════════
   Local Research State
   ═══════════════════════════════════════════════════════════════════════════ */

const LocalResearch = {
  running: false,
  gameId: null,
  config: null,       // { model, apiKey, workers, maxTokens, matchmaking }
  agents: [],         // { name, code, elo, gamesPlayed, wins, losses, draws }
  games: [],          // { agent1, agent2, winner, scores, turns }
  generation: 0,
  conversation: [],   // LLM conversation log for observatory
  stopRequested: false,
  evoTimer: null,
  tournamentTimer: null,
  liveMatches: [],    // up to 4 recent match histories for mini canvas rendering
  liveTimers: [],     // animation timers for live canvases
};


/* ═══════════════════════════════════════════════════════════════════════════
   Agent Interface Per Game
   ═══════════════════════════════════════════════════════════════════════════ */

const AGENT_INTERFACE = {
  snake: `
function getMove(state) {
  // state.grid: 2D array (20x20), state.mySnake: {body:[[x,y],...], dir, alive, score}
  // state.enemySnake: same, state.food: [x,y] or null, state.turn: int
  // state.memory: {} (mutable, persists across turns within a game)
  // Return: 'UP', 'DOWN', 'LEFT', or 'RIGHT'
  return 'UP';
}`,
  snake_random: `
function getMove(state) {
  // state.grid: 2D array (20x20), state.mySnake: {body:[[x,y],...], dir, alive, score}
  // state.enemySnake: same, state.food: [x,y] or null, state.turn: int
  // state.walls: [[x,y], ...] — extra wall positions (changes each match)
  // state.memory: {} (mutable, persists across turns within a game)
  // Return: 'UP', 'DOWN', 'LEFT', or 'RIGHT'
  return 'UP';
}`,
  snake_royale: `
function getMove(state) {
  // state.grid: 2D array (30x30), state.mySnake: {body:[[x,y],...], dir, alive, score}
  // state.snakes: [{body, dir, alive, score}, ...] — all 4 snakes
  // state.myIndex: 0-3 (which snake you are)
  // state.food: [[x,y], ...], state.turn: int
  // state.memory: {} (mutable, persists across turns within a game)
  // Return: 'UP', 'DOWN', 'LEFT', or 'RIGHT'
  return 'UP';
}`,
  snake_2v2: `
function getMove(state) {
  // state.grid: 2D array (24x24), state.mySnake: {body:[[x,y],...], dir, alive, score}
  // state.allySnake: same (your teammate — you can pass through each other)
  // state.enemies: [{body, dir, alive, score}, ...] — 2 enemy snakes
  // state.myIndex: 0-3, state.food: [[x,y], ...], state.turn: int
  // state.memory: {} (mutable, persists across turns within a game)
  // Return: 'UP', 'DOWN', 'LEFT', or 'RIGHT'
  return 'UP';
}`,
  tron: `
function getMove(state) {
  // state.grid: 2D array (0=empty, 1=myTrail, 2=enemyTrail, 3=myHead, 4=enemyHead)
  // state.myPos: [x,y], state.myDir: 0-3 (UP/RIGHT/DOWN/LEFT)
  // state.enemyPos: [x,y], state.turn: int, state.memory: {}
  // Return: 'UP', 'DOWN', 'LEFT', or 'RIGHT'
  return 'UP';
}`,
  connect4: `
function getMove(state) {
  // state.board: 6x7 2D array (0=empty, 1=me, 2=opponent)
  // state.validMoves: [col,...], state.turn: int, state.memory: {}
  // Return: column number (0-6)
  return state.validMoves[0];
}`,
  chess960: `
function getMove(state) {
  // state.board: 8x8 int array (positive=white, negative=black)
  //   1=pawn, 2=knight, 3=bishop, 4=rook, 5=queen, 6=king
  //   Row 0=rank 8 (black back rank), Row 7=rank 1 (white back rank)
  // state.my_color: 'white'|'black'
  // state.legal_moves: ['e2e4','g1f3',...] — long algebraic notation
  // state.opponent_last_move: 'e7e5' or null
  // state.turn: int (half-moves), state.king_in_check: bool
  // state.prev_moves: [] — mutable persistent memory
  // Return: one of state.legal_moves (e.g. 'e2e4')
  return state.legal_moves[0];
}`,
  othello: `
function get_move(state) {
  // state.board: 8x8 int array (1=black, -1=white, 0=empty)
  // state.my_color: 1 (black) or -1 (white)
  // state.legal_moves: [[row,col], ...] — pre-computed legal moves
  // state.opponent_last_move: [row,col] or null
  // state.turn: int (half-moves), state.scores: {black, white, empty}
  // state.prev_moves: [] — mutable persistent memory
  // Return: [row, col] from state.legal_moves
  return state.legal_moves[0];
}`,
  go9: `
function getMove(state) {
  // state.board: 9x9 (0=empty, 1=me, 2=opponent)
  // state.validMoves: [{row,col},...], state.turn: int, state.memory: {}
  // Return: {row, col} or 'pass'
  return state.validMoves[0] || 'pass';
}`,
  gomoku: `
function getMove(state) {
  // state.board: 15x15 (0=empty, 1=me, 2=opponent)
  // state.validMoves: [{row,col},...], state.turn: int, state.memory: {}
  // Return: {row, col}
  return state.validMoves[0];
}`,
  artillery: `
function getMove(state) {
  // state.myPos: {x,y}, state.enemyPos: {x,y}, state.terrain: [heights,...]
  // state.wind: float, state.myHP: int, state.enemyHP: int, state.memory: {}
  // Return: {angle: 0-90, power: 0-100}
  return {angle: 45, power: 50};
}`,
  poker: `
function getMove(state) {
  // state.myHand: [{rank,suit},...], state.communityCards: [{rank,suit},...]
  // state.pot: int, state.myChips: int, state.enemyChips: int
  // state.validActions: ['fold','call','raise'], state.memory: {}
  // Return: 'fold', 'call', or 'raise'
  return 'call';
}`,
};


/* ═══════════════════════════════════════════════════════════════════════════
   Agent Validation & Safety
   ═══════════════════════════════════════════════════════════════════════════ */

function arValidateAgent(code, gameId) {
  const errors = [];

  // Syntax check
  try {
    new Function(code + '\n; typeof getMove === "function" ? getMove : null;');
  } catch (e) {
    errors.push(`Syntax error: ${e.message}`);
    return { passed: false, errors };
  }

  // Safety check — block dangerous patterns
  const forbidden = ['fetch(', 'XMLHttpRequest', 'import(', 'require(',
    'eval(', 'document.', 'window.location', 'localStorage', 'sessionStorage',
    'WebSocket', 'Worker(', 'navigator.', 'process.'];
  for (const pat of forbidden) {
    if (code.includes(pat)) {
      errors.push(`Forbidden pattern: ${pat}`);
    }
  }
  if (errors.length) return { passed: false, errors };

  // Function existence check
  try {
    const fn = new Function(code + '\nreturn typeof getMove === "function";');
    if (!fn()) {
      errors.push('No getMove function found');
      return { passed: false, errors };
    }
  } catch (e) {
    errors.push(`Runtime error: ${e.message}`);
    return { passed: false, errors };
  }

  // Timeout test — run getMove with dummy state
  try {
    const testFn = new Function(code + `
      const _start = Date.now();
      const _state = {
        grid: [], mySnake: {body:[[5,5]], dir:0, alive:true, score:0},
        enemySnake: {body:[[15,15]], dir:2, alive:true, score:0},
        food: [10,10], turn: 0, memory: {},
        board: Array(20).fill(null).map(() => Array(20).fill(0)),
        validMoves: [{row:0,col:0}], myColor: 'w', myPos: [5,5], enemyPos: [15,15],
        myHand: [], communityCards: [], pot: 100, myChips: 500, enemyChips: 500,
        validActions: ['fold','call','raise'], terrain: [], wind: 0, myHP: 100, enemyHP: 100,
      };
      const _result = getMove(_state);
      const _elapsed = Date.now() - _start;
      return { result: _result, elapsed: _elapsed };
    `);
    const { result, elapsed } = testFn();
    if (elapsed > 100) {
      errors.push(`Too slow: ${elapsed}ms (max 100ms)`);
    }
    if (result === undefined || result === null) {
      errors.push('getMove returned undefined/null');
    }
  } catch (e) {
    errors.push(`Test run error: ${e.message}`);
  }

  return { passed: errors.length === 0, errors };
}

function arCreateAgentFn(code) {
  try {
    const fn = new Function(code + '\nreturn getMove;');
    return fn();
  } catch (e) {
    return null;
  }
}


/* ═══════════════════════════════════════════════════════════════════════════
   Direction Helpers
   ═══════════════════════════════════════════════════════════════════════════ */

const _AR_DIR_MAP = { 'UP': 0, 'RIGHT': 1, 'DOWN': 2, 'LEFT': 3 };
const _AR_DIR_NAMES = ['UP', 'RIGHT', 'DOWN', 'LEFT'];

function _arParseDir(raw) {
  if (typeof raw === 'number' && raw >= 0 && raw <= 3) return raw;
  if (typeof raw === 'string') {
    const up = raw.toUpperCase().trim();
    if (_AR_DIR_MAP[up] !== undefined) return _AR_DIR_MAP[up];
  }
  return 0; // fallback UP
}


/* ═══════════════════════════════════════════════════════════════════════════
   State Adapters — Convert game engine state to AGENT_INTERFACE format
   ═══════════════════════════════════════════════════════════════════════════ */

function _arSnakeState(engine, player, memory) {
  const st = engine.getAIState ? engine.getAIState() : {};
  const isA = player === 'A';

  // 4-player engine (snake_royale / snake_2v2)
  if (st.snakes && st.snakes.length > 2) {
    const idx = isA ? 0 : 1;
    const mySnake = st.snakes[idx];
    const allyIdx = engine.mode === '2v2' ? (idx === 0 ? 2 : 3) : -1;
    const allySnake = allyIdx >= 0 ? st.snakes[allyIdx] : null;
    const enemies = st.snakes.filter((_, i) => i !== idx && i !== allyIdx);
    return {
      grid: engine.getGrid(),
      mySnake: mySnake,
      allySnake: allySnake,
      enemySnake: enemies[0] || null,
      enemies: enemies,
      snakes: st.snakes,
      myIndex: idx,
      food: st.food,
      turn: st.turn,
      memory: memory,
    };
  }

  // 2-player engine (snake / snake_random)
  return {
    grid: engine.getGrid(),
    mySnake: isA ? st.snakeA : st.snakeB,
    enemySnake: isA ? st.snakeB : st.snakeA,
    food: st.food,
    turn: st.turn,
    walls: st.walls || null,
    memory: memory,
  };
}

function _arTronState(engine, player, memory) {
  const st = engine.getAIState();
  const isA = player === 'A';
  // Remap grid: from perspective of player, 1=myTrail, 2=enemyTrail
  const grid = st.grid.map(row => row.map(v => {
    if (isA) {
      if (v === 1 || v === 3) return 1; // A trail/head → my
      if (v === 2 || v === 4) return 2; // B trail/head → enemy
      return v;
    } else {
      if (v === 2 || v === 4) return 1; // B trail/head → my
      if (v === 1 || v === 3) return 2; // A trail/head → enemy
      return v;
    }
  }));
  return {
    grid: grid,
    myPos: isA ? [...st.posA] : [...st.posB],
    myDir: isA ? st.dirA : st.dirB,
    enemyPos: isA ? [...st.posB] : [...st.posA],
    turn: st.turn,
    memory: memory,
  };
}

function _arC4State(engine, player, memory) {
  const isA = player === 'A'; // A plays as turn=1, B plays as turn=-1
  const board = engine.getBoard().map(row => row.map(v => {
    if (v === 0) return 0;
    if (isA) return v === 1 ? 1 : 2;  // 1=me, -1=opponent
    return v === -1 ? 1 : 2;
  }));
  return {
    board: board,
    validMoves: engine.getLegalMoves(),
    turn: engine.ply,
    memory: memory,
  };
}

function _arChessState(engine, player, memory) {
  const isA = player === 'A'; // A=white, B=black
  const myColor = isA ? 'w' : 'b';
  const legalMoves = engine.getLegalMoves();
  // Convert internal moves to {from, to} algebraic notation
  const validMoves = legalMoves.map(m => ({
    from: String.fromCharCode(97 + m.f[1]) + (8 - m.f[0]),
    to: String.fromCharCode(97 + m.t[1]) + (8 - m.t[0]),
    _internal: m, // keep reference for parsing back
  }));
  return {
    board: engine.getBoard(),
    myColor: myColor,
    validMoves: validMoves,
    turn: engine.ply,
    memory: memory,
  };
}

function _arOthelloState(engine, player, memory) {
  const isA = player === 'A'; // A plays as turn=1, B as turn=-1
  const board = engine.getBoard().map(row => row.map(v => {
    if (v === 0) return 0;
    if (isA) return v === 1 ? 1 : 2;
    return v === -1 ? 1 : 2;
  }));
  const legalMoves = engine.getLegalMoves(); // [{r, c, flips}, ...]
  return {
    board: board,
    validMoves: legalMoves.map(m => ({ row: m.r, col: m.c })),
    turn: engine.ply,
    memory: memory,
  };
}

function _arGoState(engine, player, memory) {
  const isA = player === 'A'; // A=turn 1 (black), B=turn -1 (white)
  const board = engine.getBoard().map(row => row.map(v => {
    if (v === 0) return 0;
    if (isA) return v === 1 ? 1 : 2;
    return v === -1 ? 1 : 2;
  }));
  const legalMoves = engine.getLegalMoves();
  return {
    board: board,
    validMoves: legalMoves.map(m => ({ row: m[0], col: m[1] })),
    turn: engine.ply,
    memory: memory,
  };
}

function _arGomokuState(engine, player, memory) {
  const isA = player === 'A';
  const board = engine.getBoard().map(row => row.map(v => {
    if (v === 0) return 0;
    if (isA) return v === 1 ? 1 : 2;
    return v === -1 ? 1 : 2;
  }));
  const legalMoves = engine.getLegalMoves();
  return {
    board: board,
    validMoves: legalMoves.map(m => ({ row: m[0], col: m[1] })),
    turn: engine.ply,
    memory: memory,
  };
}

function _arArtilleryState(engine, player, memory) {
  const st = engine.getState();
  const isA = player === 'A'; // A = turn 1, B = turn -1
  return {
    myPos: isA ? { x: st.tankA.x, y: st.tankA.hp } : { x: st.tankB.x, y: st.tankB.hp },
    enemyPos: isA ? { x: st.tankB.x, y: st.tankB.hp } : { x: st.tankA.x, y: st.tankA.hp },
    terrain: st.terrain,
    wind: st.wind,
    myHP: isA ? st.tankA.hp : st.tankB.hp,
    enemyHP: isA ? st.tankB.hp : st.tankA.hp,
    turn: st.ply,
    memory: memory,
  };
}

/** Dispatch state builder by game ID */
function _arBuildState(gameId, engine, player, memory) {
  switch (gameId) {
    case 'snake':
    case 'snake_random':
    case 'snake_royale':
    case 'snake_2v2': return _arSnakeState(engine, player, memory);
    case 'tron': return _arTronState(engine, player, memory);
    case 'connect4': return _arC4State(engine, player, memory);
    case 'chess960': return _arChessState(engine, player, memory);
    case 'othello': return _arOthelloState(engine, player, memory);
    case 'go9': return _arGoState(engine, player, memory);
    case 'gomoku': return _arGomokuState(engine, player, memory);
    case 'artillery': return _arArtilleryState(engine, player, memory);
    default: return { memory };
  }
}


/* ═══════════════════════════════════════════════════════════════════════════
   Engine Factories — create + step game engines headlessly
   ═══════════════════════════════════════════════════════════════════════════ */

function _arNewEngine(gameId, config) {
  // Resolve seed to a real value if it's a function (e.g. () => Date.now())
  const resolvedConfig = { ...config };
  if (typeof resolvedConfig.seed === 'function') resolvedConfig.seed = resolvedConfig.seed();
  switch (gameId) {
    case 'snake': return new SnakeGame(resolvedConfig);
    case 'snake_random': return typeof SnakeRandomGame !== 'undefined' ? new SnakeRandomGame(resolvedConfig) : new SnakeGame(resolvedConfig);
    case 'snake_royale': return typeof SnakeGame4P !== 'undefined' ? new SnakeGame4P({ ...resolvedConfig, mode: 'royale' }) : new SnakeGame(resolvedConfig);
    case 'snake_2v2': return typeof SnakeGame4P !== 'undefined' ? new SnakeGame4P({ ...resolvedConfig, mode: '2v2' }) : new SnakeGame(resolvedConfig);
    case 'tron': return new TronGame(config);
    case 'connect4': return new ConnectFourGame(config);
    case 'chess960': return new ChessGame(config);
    case 'othello': return new OthelloGame(config);
    case 'go9': return new GoGame(config);
    case 'gomoku': return new GomokuGame(config);
    case 'artillery': return new ArtilleryGame(config);
    default: return null;
  }
}

/** Is this a simultaneous-move game (both players act at once)? */
function _arIsSimultaneous(gameId) {
  return gameId === 'snake' || gameId === 'snake_random' || gameId === 'snake_royale' || gameId === 'snake_2v2' || gameId === 'tron';
}

/** Whose turn is it? Returns 'A' or 'B'. For simultaneous games, always 'A' (both move). */
function _arWhoseTurn(gameId, engine) {
  if (_arIsSimultaneous(gameId)) return 'A';
  switch (gameId) {
    case 'connect4': return engine.turn === 1 ? 'A' : 'B';
    case 'chess960': return engine.turn === 'w' ? 'A' : 'B';
    case 'othello': return engine.turn === 1 ? 'A' : 'B';
    case 'go9': return engine.turn === 1 ? 'A' : 'B';
    case 'gomoku': return engine.turn === 1 ? 'A' : 'B';
    case 'artillery': return engine.turn === 1 ? 'A' : 'B';
    default: return 'A';
  }
}

/** Step the engine with the agent's raw move. Returns description of what happened. */
function _arStepEngine(gameId, engine, rawMoveA, rawMoveB, stateA, stateB) {
  switch (gameId) {
    case 'snake':
    case 'snake_random': {
      const dirA = _arParseDir(rawMoveA);
      const dirB = _arParseDir(rawMoveB);
      engine.step(dirA, dirB);
      return { moveA: _AR_DIR_NAMES[dirA], moveB: _AR_DIR_NAMES[dirB] };
    }
    case 'snake_royale':
    case 'snake_2v2': {
      // 4P games: fnA/fnB are used for first 2 players, AI strategies for 3rd/4th
      const dirA = _arParseDir(rawMoveA);
      const dirB = _arParseDir(rawMoveB);
      // For headless 2-agent mode, fill remaining with greedy AI
      const dirC = engine.snakes && engine.snakes[2]?.alive ? _arParseDir('UP') : 0;
      const dirD = engine.snakes && engine.snakes[3]?.alive ? _arParseDir('UP') : 0;
      if (typeof engine.step4P === 'function') {
        engine.step4P(dirA, dirB, dirC, dirD);
      } else {
        engine.step(dirA, dirB);
      }
      return { moveA: _AR_DIR_NAMES[dirA], moveB: _AR_DIR_NAMES[dirB] };
    }
    case 'tron': {
      const dirA = _arParseDir(rawMoveA);
      const dirB = _arParseDir(rawMoveB);
      engine.step(dirA, dirB);
      return { moveA: _AR_DIR_NAMES[dirA], moveB: _AR_DIR_NAMES[dirB] };
    }
    case 'connect4': {
      const col = typeof rawMoveA === 'number' ? rawMoveA : parseInt(rawMoveA);
      const legal = engine.getLegalMoves();
      const safeCol = legal.includes(col) ? col : (legal[0] ?? 0);
      engine.makeMove(safeCol);
      return { move: safeCol };
    }
    case 'chess960': {
      // rawMoveA is {from, to} in algebraic — find matching legal move
      const legalMoves = stateA?.validMoves || [];
      let matched = legalMoves.find(m =>
        m.from === rawMoveA?.from && m.to === rawMoveA?.to
      );
      if (matched && matched._internal) {
        engine.makeMove(matched._internal);
        // Check end conditions after the move
        const opponentMoves = engine.getLegalMoves();
        if (opponentMoves.length === 0) {
          engine.over = true;
          engine.winner = engine._isInCheck(engine.turn)
            ? (engine.turn === 'w' ? 'B' : 'A')
            : 'draw';
        }
        if (engine.halfmoveClock >= 100) { engine.over = true; engine.winner = 'draw'; }
        if (engine.ply >= engine.maxPly) { engine.over = true; engine.winner = 'draw'; }
        return { move: `${rawMoveA.from}-${rawMoveA.to}` };
      }
      // Fallback: pick first legal move
      const fallback = engine.getLegalMoves()[0];
      if (fallback) {
        engine.makeMove(fallback);
        const opponentMoves = engine.getLegalMoves();
        if (opponentMoves.length === 0) {
          engine.over = true;
          engine.winner = engine._isInCheck(engine.turn)
            ? (engine.turn === 'w' ? 'B' : 'A')
            : 'draw';
        }
        if (engine.halfmoveClock >= 100) { engine.over = true; engine.winner = 'draw'; }
        if (engine.ply >= engine.maxPly) { engine.over = true; engine.winner = 'draw'; }
      } else {
        engine.over = true;
        engine.winner = 'draw';
      }
      return { move: 'fallback' };
    }
    case 'othello': {
      const legalMoves = engine.getLegalMoves(); // [{r, c, flips}, ...]
      if (legalMoves.length === 0) {
        // No legal moves — _checkEnd inside makeMove handles pass logic
        // But since we can't call makeMove with no moves, manually pass
        engine.passes++;
        engine.turn *= -1;
        if (engine.passes >= 2) {
          engine.over = true;
          const counts = engine.countPieces();
          engine.winner = counts.a > counts.b ? 'A' : counts.b > counts.a ? 'B' : 'draw';
        }
        return { move: 'pass' };
      }
      let move = rawMoveA;
      if (move && typeof move === 'object' && move.row !== undefined) {
        const found = legalMoves.find(m => m.r === move.row && m.c === move.col);
        if (found) {
          engine.makeMove(found.r, found.c);
          return { move: `${found.r},${found.c}` };
        }
      }
      // Fallback: play first legal move
      engine.makeMove(legalMoves[0].r, legalMoves[0].c);
      return { move: `${legalMoves[0].r},${legalMoves[0].c}` };
    }
    case 'go9': {
      const legalMoves = engine.getLegalMoves();
      let move = rawMoveA;
      if (move === 'pass' || (legalMoves.length === 0)) {
        engine.pass();
        return { move: 'pass' };
      }
      if (move && typeof move === 'object' && move.row !== undefined) {
        if (engine.isLegalMove(move.row, move.col)) {
          engine.makeMove(move.row, move.col);
          return { move: `${move.row},${move.col}` };
        }
      }
      // Fallback
      if (legalMoves.length > 0) {
        engine.makeMove(legalMoves[0][0], legalMoves[0][1]);
        return { move: `${legalMoves[0][0]},${legalMoves[0][1]}` };
      }
      engine.pass();
      return { move: 'pass' };
    }
    case 'gomoku': {
      const legalMoves = engine.getLegalMoves();
      let move = rawMoveA;
      if (move && typeof move === 'object' && move.row !== undefined) {
        const found = legalMoves.find(m => m[0] === move.row && m[1] === move.col);
        if (found) {
          engine.makeMove(found[0], found[1]);
          return { move: `${found[0]},${found[1]}` };
        }
      }
      if (legalMoves.length > 0) {
        engine.makeMove(legalMoves[0][0], legalMoves[0][1]);
        return { move: `${legalMoves[0][0]},${legalMoves[0][1]}` };
      }
      engine.over = true;
      engine.winner = 'draw';
      return { move: 'none' };
    }
    case 'artillery': {
      let move = rawMoveA;
      if (move && typeof move === 'object' && typeof move.angle === 'number') {
        const angle = Math.max(0, Math.min(90, move.angle));
        const power = Math.max(0, Math.min(100, move.power || 50));
        engine.shoot(angle, power);
        return { move: `shoot ${angle}deg ${power}pwr` };
      }
      // Fallback: shoot at 45 degrees, 50 power
      engine.shoot(45, 50);
      return { move: 'shoot 45deg 50pwr (fallback)' };
    }
    default:
      return { move: 'unknown' };
  }
}


/* ═══════════════════════════════════════════════════════════════════════════
   Headless Match Runner — run any game with two getMove() functions
   ═══════════════════════════════════════════════════════════════════════════ */

function arRunHeadless(gameId, fnA, fnB, config) {
  if (gameId === 'poker') {
    // Poker uses functional approach — not yet supported for headless
    return { winner: 'draw', turns: 0, history: [], error: 'Poker headless not supported' };
  }

  const engine = _arNewEngine(gameId, config);
  if (!engine) return { winner: 'draw', turns: 0, history: [], error: 'Unknown game' };

  const memA = {}, memB = {};
  const history = [];
  const maxTurns = 500; // safety cap

  // Record initial state
  if (typeof engine.getGrid === 'function') {
    const initFrame = { turn: 0, grid: engine.getGrid(), winner: null };
    if (engine._corpseCells) initFrame.corpseCells = engine._corpseCells;
    history.push(initFrame);
  }

  let turnCount = 0;

  if (_arIsSimultaneous(gameId)) {
    // Both players move simultaneously each turn
    while (!engine.over && turnCount < maxTurns) {
      const stateA = _arBuildState(gameId, engine, 'A', memA);
      const stateB = _arBuildState(gameId, engine, 'B', memB);
      const rawA = arSafeCall(fnA, stateA, 50);
      const rawB = arSafeCall(fnB, stateB, 50);
      const result = _arStepEngine(gameId, engine, rawA, rawB, stateA, stateB);
      turnCount++;

      if (typeof engine.getGrid === 'function') {
        const frame = {
          turn: turnCount, grid: engine.getGrid(),
          moveA: result.moveA, moveB: result.moveB,
          winner: engine.winner,
        };
        // Add snake-specific state for mini-frame renderer
        if (gameId.startsWith('snake') && engine.snakeA) {
          frame.snakes = [engine.snakeA.body.map(p => [...p]), engine.snakeB.body.map(p => [...p])];
          frame.alive = [engine.snakeA.alive, engine.snakeB.alive];
          frame.scores = [engine.snakeA.body.length, engine.snakeB.body.length];
          frame.food = Array.isArray(engine.food) ? engine.food : [];
          if (engine.walls) frame.walls = [...engine.walls];
        } else if (gameId.startsWith('snake') && engine.snakes) {
          frame.snakes = engine.snakes.map(s => s.body.map(p => [...p]));
          frame.alive = engine.snakes.map(s => s.alive);
          frame.scores = engine.snakes.map(s => s.score);
          frame.food = engine.food || [];
        }
        if (engine._corpseCells) frame.corpseCells = engine._corpseCells;
        history.push(frame);
      }
    }
  } else {
    // Turn-based: one player moves per turn
    while (!engine.over && turnCount < maxTurns) {
      const who = _arWhoseTurn(gameId, engine);
      const isA = who === 'A';
      const state = _arBuildState(gameId, engine, who, isA ? memA : memB);
      const fn = isA ? fnA : fnB;
      const raw = arSafeCall(fn, state, 50);
      const result = _arStepEngine(gameId, engine, raw, null, state, null);
      turnCount++;

      if (typeof engine.getGrid === 'function') {
        history.push({
          turn: turnCount, grid: engine.getGrid(),
          move: result.move, player: who,
          winner: engine.winner,
        });
      } else if (typeof engine.getBoard === 'function') {
        history.push({
          turn: turnCount, board: engine.getBoard(),
          move: result.move, player: who,
          winner: engine.winner,
        });
      } else if (typeof engine.getState === 'function') {
        history.push({
          turn: turnCount, state: engine.getState(),
          move: result.move, player: who,
          winner: engine.winner,
        });
      }
    }
  }

  const winner = engine.winner || 'draw';
  return { winner, turns: turnCount, history };
}

function arSafeCall(fn, state, timeoutMs) {
  try {
    const start = Date.now();
    const result = fn(state);
    if (Date.now() - start > timeoutMs) {
      // Too slow — return a safe fallback
      if (state.validMoves && state.validMoves.length > 0) return state.validMoves[0];
      return 'UP';
    }
    return result;
  } catch (e) {
    if (state.validMoves && state.validMoves.length > 0) return state.validMoves[0];
    return 'UP';
  }
}


/* ═══════════════════════════════════════════════════════════════════════════
   Tournament — In-Browser Match Runner using Headless Engine
   ═══════════════════════════════════════════════════════════════════════════ */

function arRunTournamentRound(gameId, agents, matchCount = 10) {
  if (agents.length < 2) return [];

  const game = ARENA_GAMES.find(g => g.id === gameId);
  if (!game) return [];

  const results = [];

  for (let i = 0; i < matchCount && agents.length >= 2; i++) {
    // Swiss matchmaking: pair similar ELO with some randomness
    const sorted = [...agents].sort((a, b) => b.elo - a.elo);
    const idx = Math.floor(Math.random() * sorted.length);
    const a1 = sorted[idx];

    // Pick opponent close in ranking
    const candidates = sorted.filter(a => a !== a1);
    if (!candidates.length) break;
    const weights = candidates.map((_, j) => 1 / Math.pow(Math.abs(j - idx) + 1, 1.5));
    const totalW = weights.reduce((s, w) => s + w, 0);
    let r = Math.random() * totalW, cumul = 0;
    let a2 = candidates[0];
    for (let j = 0; j < candidates.length; j++) {
      cumul += weights[j];
      if (r <= cumul) { a2 = candidates[j]; break; }
    }

    // Skip if ELO gap too large
    if (Math.abs(a1.elo - a2.elo) > 400) continue;

    // Load agent functions
    const fn1 = arCreateAgentFn(a1.code);
    const fn2 = arCreateAgentFn(a2.code);
    if (!fn1 || !fn2) continue;

    // Run headless match
    try {
      const config = { ...game.config, seed: 42 + i + LocalResearch.generation * 100 };
      const result = arRunHeadless(gameId, fn1, fn2, config);
      const winner = result.winner;

      // Determine ELO result
      let eloResult;
      if (winner === 'A') eloResult = 1.0;
      else if (winner === 'B') eloResult = 0.0;
      else eloResult = 0.5;

      // Update stats
      a1.gamesPlayed++;
      a2.gamesPlayed++;
      if (winner === 'A') { a1.wins++; a2.losses++; }
      else if (winner === 'B') { a2.wins++; a1.losses++; }
      else { a1.draws++; a2.draws++; }

      // ELO update
      const K1 = a1.gamesPlayed < 20 ? 64 : 32;
      const K2 = a2.gamesPlayed < 20 ? 64 : 32;
      const e1 = 1 / (1 + Math.pow(10, (a2.elo - a1.elo) / 400));
      const e2 = 1 - e1;
      a1.elo += K1 * (eloResult - e1);
      a2.elo += K2 * ((1 - eloResult) - e2);

      const matchResult = {
        agent1: a1.name, agent2: a2.name,
        winner: winner === 'A' ? a1.name : winner === 'B' ? a2.name : 'Draw',
        turns: result.turns,
        history: result.history.length <= 60 ? result.history : null,
        gameId: gameId,
      };
      results.push(matchResult);
    } catch (e) {
      console.warn('Tournament match error:', e);
    }
  }

  return results;
}


/* ═══════════════════════════════════════════════════════════════════════════
   Evolution — LLM Tool-Calling Loop
   ═══════════════════════════════════════════════════════════════════════════ */

const EVOLUTION_TOOLS_DESC = `
You have these tools available. To use one, write a tool_call block:

<tool_call>
{"name": "tool_name", "args": {"key": "value"}}
</tool_call>

Available tools:

1. **query_leaderboard** — Get current agent rankings
   Args: none

2. **read_agent** — Read an agent's source code
   Args: {"agent_name": "name"}

3. **create_agent** — Create a new agent. Code will be validated and tested.
   Args: {"name": "unique_name", "code": "function getMove(state) { ... }"}

4. **test_match** — Run a test match between two agents (returns winner + turns)
   Args: {"agent1_name": "name1", "agent2_name": "name2"}

After each tool call, I'll respond with the result. You can make multiple tool calls across rounds.
Create ONE strong agent per generation. Study top agents first, then create a counter-strategy.
`;

async function arRunEvolutionCycle(gameId, model) {
  const game = ARENA_GAMES.find(g => g.id === gameId);
  if (!game) return;

  const gen = LocalResearch.generation;
  LocalResearch.generation++;

  arLog('info', `--- Generation ${gen} ---`);

  // Build system prompt
  const programMd = LocalResearch.programMd || `Create strong ${game.title} agents that win matches.`;
  const agentInterface = AGENT_INTERFACE[gameId] || AGENT_INTERFACE.snake;
  const systemPrompt = `You are an AI agent designer. Your job is to create strong game-playing agents.

${programMd}

## Agent Interface for ${game.title}
\`\`\`javascript
${agentInterface}
\`\`\`

## Rules
- Your agent must define a \`getMove(state)\` function
- No fetch, eval, document, localStorage, or other browser APIs
- Must return within 50ms
- Use state.memory to persist data across turns (it's a mutable object)

${EVOLUTION_TOOLS_DESC}`;

  // Build user prompt with leaderboard
  const top = [...LocalResearch.agents].sort((a, b) => b.elo - a.elo).slice(0, 5);
  let userPrompt = `Generation ${gen}.\n`;
  if (top.length) {
    userPrompt += 'Current leaderboard:\n';
    top.forEach((a, i) => {
      userPrompt += ` #${i + 1} ${a.name} ELO=${Math.round(a.elo)} W/L/D=${a.wins}/${a.losses}/${a.draws}\n`;
    });
    if (top[0] && !top[0].isAnchor) {
      userPrompt += `\nBest agent code (${top[0].name}):\n\`\`\`javascript\n${top[0].code}\n\`\`\`\n`;
    }
  } else {
    userPrompt += 'No agents yet — create the first one!\n';
  }
  userPrompt += `\nCreate ONE agent with a unique name like 'gen${gen}_strategy'. Think about what strategy would work well for ${game.title}.`;

  const messages = [
    { role: 'system', content: systemPrompt },
    { role: 'user', content: userPrompt },
  ];

  const createdThisRound = new Set();
  const maxRounds = 6;

  for (let round = 0; round < maxRounds; round++) {
    if (LocalResearch.stopRequested) break;

    arLog('info', `  LLM round ${round + 1}/${maxRounds}...`);

    let response;
    try {
      response = await callLLM(messages, model, {
        maxTokens: parseInt(LocalResearch.config?.maxTokens || 4096),
      });
    } catch (e) {
      arLog('error', `LLM call failed: ${e.message}`);
      break;
    }

    if (typeof response !== 'string') {
      arLog('error', 'LLM returned non-string response');
      break;
    }

    arLog('llm', response.substring(0, 300) + (response.length > 300 ? '...' : ''));

    // Check for tool calls
    const toolCallMatch = response.match(/<tool_call>\s*([\s\S]*?)\s*<\/tool_call>/);
    if (!toolCallMatch) {
      // No tool call — LLM is done
      messages.push({ role: 'assistant', content: response });
      break;
    }

    // Parse and execute tool call
    let toolCall;
    try {
      toolCall = JSON.parse(toolCallMatch[1]);
    } catch (e) {
      arLog('error', `Invalid tool call JSON: ${e.message}`);
      messages.push({ role: 'assistant', content: response });
      messages.push({ role: 'user', content: '<tool_result>\n{"error": "Invalid JSON in tool_call block"}\n</tool_result>' });
      continue;
    }

    const toolResult = arHandleToolCall(toolCall.name, toolCall.args || {}, gameId, createdThisRound);
    arLog('tool', `${toolCall.name} → ${toolResult.substring(0, 200)}${toolResult.length > 200 ? '...' : ''}`);

    messages.push({ role: 'assistant', content: response });
    messages.push({ role: 'user', content: `<tool_result>\n${toolResult}\n</tool_result>` });
  }

  arLog('info', `Generation ${gen} complete. ${createdThisRound.size} agent(s) created.`);
}

function arHandleToolCall(name, args, gameId, createdThisRound) {
  if (name === 'query_leaderboard') {
    const sorted = [...LocalResearch.agents].sort((a, b) => b.elo - a.elo);
    if (!sorted.length) return JSON.stringify({ agents: [], message: 'No agents yet.' });
    return JSON.stringify(sorted.map((a, i) => ({
      rank: i + 1, name: a.name, elo: Math.round(a.elo),
      wins: a.wins, losses: a.losses, draws: a.draws, games: a.gamesPlayed,
    })));
  }

  if (name === 'read_agent') {
    const agent = LocalResearch.agents.find(a => a.name === args.agent_name);
    if (!agent) return JSON.stringify({ error: `Agent '${args.agent_name}' not found` });
    return agent.code;
  }

  if (name === 'create_agent') {
    const agentName = args.name || '';
    const code = args.code || '';

    if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(agentName)) {
      return JSON.stringify({ error: 'Invalid name. Use letters, digits, underscores only.' });
    }

    const validation = arValidateAgent(code, gameId);
    if (!validation.passed) {
      return JSON.stringify({ error: 'Validation failed', details: validation.errors });
    }

    // Register agent
    const existing = LocalResearch.agents.find(a => a.name === agentName);
    if (existing) {
      existing.code = code;
      existing.generation = LocalResearch.generation;
    } else {
      LocalResearch.agents.push({
        name: agentName, code, generation: LocalResearch.generation,
        elo: 1000, gamesPlayed: 0, wins: 0, losses: 0, draws: 0,
      });
    }
    createdThisRound.add(agentName);

    // Run a quick test match against a random existing agent
    let testNote = '';
    if (LocalResearch.agents.length >= 2) {
      const opponents = LocalResearch.agents.filter(a => a.name !== agentName);
      if (opponents.length > 0) {
        const opp = opponents[Math.floor(Math.random() * opponents.length)];
        const fn1 = arCreateAgentFn(code);
        const fn2 = arCreateAgentFn(opp.code);
        if (fn1 && fn2) {
          try {
            const game = ARENA_GAMES.find(g => g.id === gameId);
            const result = arRunHeadless(gameId, fn1, fn2, game.config);
            testNote = ` Quick test vs ${opp.name}: ${result.winner === 'A' ? 'WIN' : result.winner === 'B' ? 'LOSS' : 'DRAW'} in ${result.turns} turns.`;
          } catch (e) {
            testNote = ` Quick test failed: ${e.message}`;
          }
        }
      }
    }

    return JSON.stringify({ success: true, message: `Agent '${agentName}' created (ELO: 1000).${testNote}` });
  }

  if (name === 'test_match') {
    const a1 = LocalResearch.agents.find(a => a.name === args.agent1_name);
    const a2 = LocalResearch.agents.find(a => a.name === args.agent2_name);
    if (!a1) return JSON.stringify({ error: `Agent '${args.agent1_name}' not found` });
    if (!a2) return JSON.stringify({ error: `Agent '${args.agent2_name}' not found` });

    const fn1 = arCreateAgentFn(a1.code);
    const fn2 = arCreateAgentFn(a2.code);
    if (!fn1 || !fn2) return JSON.stringify({ error: 'Failed to load agent code' });

    const game = ARENA_GAMES.find(g => g.id === gameId);
    if (!game) return JSON.stringify({ error: 'Game not found' });

    try {
      const result = arRunHeadless(gameId, fn1, fn2, game.config);
      const winnerName = result.winner === 'A' ? a1.name : result.winner === 'B' ? a2.name : 'Draw';
      return JSON.stringify({
        winner: winnerName, turns: result.turns,
        p1: a1.name, p2: a2.name,
      });
    } catch (e) {
      return JSON.stringify({ error: `Match error: ${e.message}` });
    }
  }

  return JSON.stringify({ error: `Unknown tool: ${name}` });
}


/* ═══════════════════════════════════════════════════════════════════════════
   Observatory Log
   ═══════════════════════════════════════════════════════════════════════════ */

function arLog(type, content) {
  const entry = {
    type, content,
    time: new Date().toLocaleTimeString(),
  };
  LocalResearch.conversation.push(entry);
  arRenderObservatory();
}

function arRenderObservatory() {
  const container = document.getElementById('arObservatoryLog');
  if (!container) return;
  const html = LocalResearch.conversation.slice(-50).map(e => {
    const cls = `ar-obs-${e.type}`;
    return `<div class="ar-obs-entry ${cls}">
      <span class="ar-obs-time">${e.time}</span>
      <span class="ar-obs-type">${e.type}</span>
      <span class="ar-obs-content">${escHtml(e.content)}</span>
    </div>`;
  }).join('');
  container.innerHTML = html;
  container.scrollTop = container.scrollHeight;
}


/* ═══════════════════════════════════════════════════════════════════════════
   Main Loop — Start / Stop Local Research
   ═══════════════════════════════════════════════════════════════════════════ */

async function arStartLocal(gameId, config) {
  if (LocalResearch.running) return;

  LocalResearch.running = true;
  LocalResearch.stopRequested = false;
  LocalResearch.gameId = gameId;
  LocalResearch.config = config;
  LocalResearch.conversation = [];
  LocalResearch.generation = 0;

  // Load seed agents if pool is empty
  if (!LocalResearch.agents.length) {
    arSeedAgents(gameId);
  }

  // Load program.md from server
  try {
    const prog = await fetch(`/api/arena/program/${gameId}`).then(r => r.json());
    LocalResearch.programMd = prog.content || '';
  } catch (e) {
    LocalResearch.programMd = '';
  }

  arLog('info', `Starting local research for ${gameId} with model ${config.model}`);

  // Store the BYOK key for callLLM
  if (config.apiKey) {
    // Try to determine provider from model name
    const modelInfo = (typeof getModelInfo === 'function') ? getModelInfo(config.model) : null;
    const provider = modelInfo?.provider;
    if (provider) {
      localStorage.setItem(`byok_key_${provider}`, config.apiKey);
      arLog('info', `BYOK key stored for provider: ${provider}`);
    } else {
      // Guess provider from model name prefix
      const prefixes = {
        'claude': 'anthropic', 'gemini': 'gemini', 'gpt': 'openai',
        'groq/': 'groq', 'mistral': 'mistral', 'hf/': 'huggingface',
      };
      for (const [prefix, prov] of Object.entries(prefixes)) {
        if (config.model.toLowerCase().startsWith(prefix)) {
          localStorage.setItem(`byok_key_${prov}`, config.apiKey);
          arLog('info', `BYOK key stored for provider: ${prov} (guessed)`);
          break;
        }
      }
    }
  }

  arShowLocalDashboard(gameId);

  // Run initial tournament to calibrate seed agents
  arLog('info', 'Running seed tournament (50 games)...');
  const seedResults = arRunTournamentRound(gameId, LocalResearch.agents, 50);
  for (const r of seedResults) LocalResearch.games.push(r);
  arLog('info', `Seed tournament: ${seedResults.length} games played`);
  arUpdateLocalDashboard();

  // Store up to 4 recent matches for live canvases
  LocalResearch.liveMatches = seedResults.filter(r => r.history).slice(-8);
  arRenderLiveCanvases();

  // Main loop
  while (LocalResearch.running && !LocalResearch.stopRequested) {
    // Evolution cycle
    try {
      await arRunEvolutionCycle(gameId, config.model);
    } catch (e) {
      arLog('error', `Evolution error: ${e.message}`);
    }

    if (LocalResearch.stopRequested) break;

    // Tournament round
    arLog('info', 'Running tournament round (20 games)...');
    const results = arRunTournamentRound(gameId, LocalResearch.agents, 20);
    for (const r of results) {
      LocalResearch.games.push(r);
    }
    arLog('info', `Tournament: ${results.length} games played`);

    // Update live canvases with recent matches
    LocalResearch.liveMatches = results.filter(r => r.history).slice(-8);
    arRenderLiveCanvases();

    // Update UI
    arUpdateLocalDashboard();

    // Pause between generations
    await new Promise(r => setTimeout(r, 2000));
  }

  LocalResearch.running = false;
  arLog('info', 'Local research stopped.');
  arUpdateLocalDashboard();
}

function arStopLocal() {
  LocalResearch.stopRequested = true;
  LocalResearch.running = false;
  // Stop live canvas animations
  for (const t of LocalResearch.liveTimers) clearInterval(t);
  LocalResearch.liveTimers = [];
}


/* ═══════════════════════════════════════════════════════════════════════════
   Seed Agents — Simple but functional baseline agents
   ═══════════════════════════════════════════════════════════════════════════ */

function arSeedAgents(gameId) {
  let seeds = _AR_SEED_AGENTS[gameId];
  // Resolve alias (snake variants point to 'snake')
  if (typeof seeds === 'string') seeds = _AR_SEED_AGENTS[seeds];
  if (!seeds || !seeds.length) {
    arLog('info', 'No seed agents for this game, creating generic ones');
    LocalResearch.agents.push({
      name: 'seed_random', code: `function getMove(state) {
  if (state.validMoves && state.validMoves.length > 0) {
    return state.validMoves[Math.floor(Math.random() * state.validMoves.length)];
  }
  return ['UP','DOWN','LEFT','RIGHT'][Math.floor(Math.random()*4)];
}`,
      generation: 0, elo: 1000, gamesPlayed: 0, wins: 0, losses: 0, draws: 0, isAnchor: true,
    });
    return;
  }
  for (const seed of seeds) {
    LocalResearch.agents.push({
      name: seed.name, code: seed.code, generation: 0,
      elo: 1000, gamesPlayed: 0, wins: 0, losses: 0, draws: 0,
      isAnchor: true,
    });
  }
  arLog('info', `Seeded ${seeds.length} baseline agents`);
}

const _AR_SEED_AGENTS = {
  snake: [
    { name: 'seed_greedy', code: `function getMove(state) {
  var head = state.mySnake.body[0];
  var food = state.food;
  if (!food) return 'UP';
  var dx = food[0] - head[0], dy = food[1] - head[1];
  if (Math.abs(dx) > Math.abs(dy)) return dx > 0 ? 'RIGHT' : 'LEFT';
  return dy > 0 ? 'DOWN' : 'UP';
}` },
    { name: 'seed_waller', code: `function getMove(state) {
  var head = state.mySnake.body[0];
  var grid = state.grid;
  var h = grid.length, w = grid[0].length;
  var dirs = ['UP','RIGHT','DOWN','LEFT'];
  var dx = [0,1,0,-1], dy = [-1,0,1,0];
  for (var i = 0; i < 4; i++) {
    var nx = head[0]+dx[i], ny = head[1]+dy[i];
    if (nx>=0 && nx<w && ny>=0 && ny<h && (grid[ny][nx]===5 || grid[ny][nx]===11)) return dirs[i];
  }
  for (var i = 0; i < 4; i++) {
    var nx = head[0]+dx[i], ny = head[1]+dy[i];
    if (nx>=1 && nx<w-1 && ny>=1 && ny<h-1 && grid[ny][nx]===5) return dirs[i];
  }
  return 'UP';
}` },
    { name: 'seed_cautious', code: `function getMove(state) {
  var head = state.mySnake.body[0];
  var grid = state.grid;
  var h = grid.length, w = grid[0].length;
  var dirs = ['UP','RIGHT','DOWN','LEFT'];
  var dx = [0,1,0,-1], dy = [-1,0,1,0];
  var safe = [];
  for (var i = 0; i < 4; i++) {
    var nx = head[0]+dx[i], ny = head[1]+dy[i];
    if (nx>=1 && nx<w-1 && ny>=1 && ny<h-1) {
      var cell = grid[ny][nx];
      if (cell === 5 || cell === 11) safe.push(dirs[i]);
    }
  }
  if (!safe.length) return 'RIGHT';
  var food = state.food;
  if (food) {
    var best = safe[0], bestDist = 999;
    for (var s of safe) {
      var di = dirs.indexOf(s);
      var nx = head[0]+dx[di], ny = head[1]+dy[di];
      var dist = Math.abs(nx-food[0])+Math.abs(ny-food[1]);
      if (dist < bestDist) { bestDist = dist; best = s; }
    }
    return best;
  }
  return safe[0];
}` },
  ],

  // Snake variants reuse the same seed agents — they share the same base interface
  snake_random: 'snake',  // alias — resolved by arSeedAgents()
  snake_royale: 'snake',
  snake_2v2: 'snake',

  tron: [
    { name: 'seed_straight', code: `function getMove(state) {
  var dirs = ['UP','RIGHT','DOWN','LEFT'];
  return dirs[state.myDir];
}` },
    { name: 'seed_spacer', code: `function getMove(state) {
  var grid = state.grid, pos = state.myPos;
  var h = grid.length, w = grid[0].length;
  var dirs = ['UP','RIGHT','DOWN','LEFT'];
  var dx = [0,1,0,-1], dy = [-1,0,1,0];
  var best = dirs[state.myDir], bestSpace = -1;
  for (var i = 0; i < 4; i++) {
    var nx = pos[0]+dx[i], ny = pos[1]+dy[i];
    if (nx<0||nx>=w||ny<0||ny>=h||grid[ny][nx]!==0) continue;
    var space = 0;
    for (var j = 0; j < 4; j++) {
      var nnx = nx+dx[j], nny = ny+dy[j];
      if (nnx>=0&&nnx<w&&nny>=0&&nny<h&&grid[nny][nnx]===0) space++;
    }
    if (space > bestSpace) { bestSpace = space; best = dirs[i]; }
  }
  return best;
}` },
  ],

  connect4: [
    { name: 'seed_center', code: `function getMove(state) {
  var prefs = [3,2,4,1,5,0,6];
  for (var c of prefs) { if (state.validMoves.includes(c)) return c; }
  return state.validMoves[0];
}` },
    { name: 'seed_random_c4', code: `function getMove(state) {
  return state.validMoves[Math.floor(Math.random()*state.validMoves.length)];
}` },
  ],

  chess960: [
    { name: 'seed_first_legal', code: `function getMove(state) {
  return state.validMoves[0];
}` },
    { name: 'seed_random_chess', code: `function getMove(state) {
  return state.validMoves[Math.floor(Math.random()*state.validMoves.length)];
}` },
  ],

  othello: [
    { name: 'seed_corner', code: `function getMove(state) {
  var corners = [{row:0,col:0},{row:0,col:7},{row:7,col:0},{row:7,col:7}];
  for (var c of corners) {
    if (state.validMoves.find(m => m.row===c.row && m.col===c.col)) return c;
  }
  return state.validMoves[0];
}` },
    { name: 'seed_max_flip', code: `function getMove(state) {
  return state.validMoves[state.validMoves.length-1] || state.validMoves[0];
}` },
  ],

  go9: [
    { name: 'seed_center_go', code: `function getMove(state) {
  var center = {row:4,col:4};
  if (state.validMoves.find(m => m.row===4 && m.col===4)) return center;
  return state.validMoves[0] || 'pass';
}` },
    { name: 'seed_random_go', code: `function getMove(state) {
  if (!state.validMoves.length) return 'pass';
  return state.validMoves[Math.floor(Math.random()*state.validMoves.length)];
}` },
  ],

  gomoku: [
    { name: 'seed_center_gmk', code: `function getMove(state) {
  var center = {row:7,col:7};
  if (state.validMoves.find(m => m.row===7 && m.col===7)) return center;
  return state.validMoves[0];
}` },
    { name: 'seed_random_gmk', code: `function getMove(state) {
  return state.validMoves[Math.floor(Math.random()*state.validMoves.length)];
}` },
  ],

  artillery: [
    { name: 'seed_lob', code: `function getMove(state) {
  return {angle: 45, power: 60};
}` },
    { name: 'seed_flat', code: `function getMove(state) {
  return {angle: 25, power: 80};
}` },
  ],

  poker: [
    { name: 'seed_caller', code: `function getMove(state) {
  return 'call';
}` },
    { name: 'seed_folder', code: `function getMove(state) {
  if (state.validActions.includes('call')) return 'call';
  return 'fold';
}` },
  ],
};


/* ═══════════════════════════════════════════════════════════════════════════
   Local Dashboard UI
   ═══════════════════════════════════════════════════════════════════════════ */

function arShowLocalDashboard(gameId) {
  const center = document.getElementById('arCenter');
  const game = ARENA_GAMES.find(g => g.id === gameId);
  const title = game ? game.title : gameId;

  center.innerHTML = `
    <div class="ar-section-header">
      <span>Local Research: ${escHtml(title)}</span>
      <div>
        <button class="ar-btn ar-btn-sm" onclick="arStopLocal()" id="arStopBtn">Stop</button>
        <button class="ar-btn ar-btn-sm ar-btn-primary" onclick="arSubmitToCommunity()" id="arSubmitBtn">Submit Best to Community</button>
      </div>
    </div>
    <div class="ar-local-dashboard">
      <div class="ar-local-top">
        <div class="ar-local-obs">
          <div class="ar-section-header"><span>Observatory</span></div>
          <div class="ar-obs-log" id="arObservatoryLog"></div>
        </div>
        <div class="ar-local-lb">
          <div class="ar-section-header"><span>Local Leaderboard</span></div>
          <div class="ar-local-lb-wrap" id="arLocalLeaderboard"></div>
        </div>
      </div>
      <div class="ar-local-status" id="arLocalStatus">
        Gen ${LocalResearch.generation} | ${LocalResearch.agents.length} agents | ${LocalResearch.games.length} games
      </div>
    </div>
  `;

  arUpdateLocalDashboard();
}

function arUpdateLocalDashboard() {
  // Update leaderboard
  const lb = document.getElementById('arLocalLeaderboard');
  if (lb) {
    const sorted = [...LocalResearch.agents].sort((a, b) => b.elo - a.elo);
    lb.innerHTML = `<table class="ar-table"><thead><tr><th>#</th><th>Agent</th><th>ELO</th><th>W/L/D</th><th>Games</th></tr></thead><tbody>` +
      sorted.map((a, i) => `<tr>
        <td>${i + 1}</td>
        <td><span class="ar-agent-name" onclick="arShowLocalAgentCode('${escHtml(a.name)}')">${escHtml(a.name)}</span>${a.isAnchor ? ' <span class="ar-badge-anchor">&#9875;</span>' : ''}</td>
        <td class="ar-elo ${a.elo >= 1200 ? 'ar-elo-high' : a.elo < 1000 ? 'ar-elo-low' : ''}">${Math.round(a.elo)}</td>
        <td>${a.wins}/${a.losses}/${a.draws}</td>
        <td>${a.gamesPlayed}</td>
      </tr>`).join('') +
      '</tbody></table>';
  }

  // Update status
  const status = document.getElementById('arLocalStatus');
  if (status) {
    const best = [...LocalResearch.agents].sort((a, b) => b.elo - a.elo)[0];
    status.textContent = `Gen ${LocalResearch.generation} | ${LocalResearch.agents.length} agents | ${LocalResearch.games.length} games` +
      (best ? ` | Best: ${best.name} (${Math.round(best.elo)})` : '') +
      (LocalResearch.running ? ' | Running...' : ' | Stopped');
  }

  // Render observatory
  arRenderObservatory();
}

function arShowLocalAgentCode(name) {
  const agent = LocalResearch.agents.find(a => a.name === name);
  if (!agent) return;
  document.getElementById('arCodeModalTitle').textContent = `${name} — Code`;
  const codeEl = document.getElementById('arCodeModalCode');
  codeEl.textContent = agent.code;
  codeEl.classList.remove('hljs');
  if (typeof hljs !== 'undefined') hljs.highlightElement(codeEl);
  document.getElementById('arCodeModal').style.display = 'flex';
}

async function arSubmitToCommunity() {
  if (!LocalResearch.gameId) return;

  const top = [...LocalResearch.agents]
    .filter(a => !a.isAnchor)
    .sort((a, b) => b.elo - a.elo)
    .slice(0, 3);

  if (!top.length) {
    arLog('info', 'No non-anchor agents to submit');
    return;
  }

  let submitted = 0;
  for (const agent of top) {
    try {
      const resp = await fetch(`/api/arena/agents/${LocalResearch.gameId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: agent.name,
          code: agent.code,
          contributor: (typeof currentUser !== 'undefined' && currentUser) ? currentUser.display_name || currentUser.email.split('@')[0] : 'local_research',
        }),
      });
      if (resp.ok) submitted++;
    } catch (e) {
      arLog('error', `Submit failed for ${agent.name}: ${e.message}`);
    }
  }
  arLog('info', `Submitted ${submitted}/${top.length} agents to community leaderboard`);
}

// Keep old name as alias for any existing onclick references
const arSubmitToComminity = arSubmitToCommunity;


/* ═══════════════════════════════════════════════════════════════════════════
   Live Tournament Canvases — animate recent matches on mini canvases
   ═══════════════════════════════════════════════════════════════════════════ */

async function arFetchLiveTournament(gameId) {
  try {
    const matches = await fetch(`/api/arena/live-tournament/${gameId}`).then(r => r.json());
    if (Array.isArray(matches) && matches.length > 0) {
      LocalResearch.liveMatches = matches;
      arRenderLiveCanvases();
    }
  } catch (e) {
    // Silently fail
  }
}

function arRenderLiveCanvases() {
  for (const t of LocalResearch.liveTimers) clearInterval(t);
  LocalResearch.liveTimers = [];

  const matches = LocalResearch.liveMatches;
  for (let i = 0; i < 4; i++) {
    const canvas = document.getElementById(`arLive${i}`);
    const info = document.getElementById(`arLiveInfo${i}`);
    if (!canvas || !info) continue;

    const match = matches[i];
    if (!match || !match.history || !match.history.length) {
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#0c0c18';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = '#555';
      ctx.font = '11px monospace';
      ctx.textAlign = 'center';
      ctx.fillText('Waiting...', canvas.width / 2, canvas.height / 2);
      info.textContent = '';
      continue;
    }

    // Agent names colored, ELO greyed out, no W/L, no spoilers
    const a1 = match.agent1, a2 = match.agent2;
    const a1Elo = match.agent1_elo ? `<span style="color:#555"> ${Math.round(match.agent1_elo)}</span>` : '';
    const a2Elo = match.agent2_elo ? `<span style="color:#555"> ${Math.round(match.agent2_elo)}</span>` : '';
    info.innerHTML = `<span style="color:#00ff87">${a1}</span>${a1Elo} vs <span style="color:#00b4d8">${a2}</span>${a2Elo}`;

    // Animate at 120ms/frame, freeze 3s on death
    let frameIdx = 0;
    let freezeCount = 0;
    const FREEZE_FRAMES = 25; // 25 * 120ms = 3s
    const history = match.history;
    const gameId = match.gameId || LocalResearch.gameId;

    const renderFrame = () => {
      if (freezeCount > 0) {
        freezeCount--;
        if (freezeCount === 0) frameIdx = 0;
        return;
      }
      const frame = history[frameIdx];
      if (!frame) return;
      _arRenderMiniFrame(canvas, gameId, frame);
      frameIdx++;
      if (frameIdx >= history.length) {
        freezeCount = FREEZE_FRAMES;
      }
    };

    renderFrame();
    const timer = setInterval(renderFrame, 120);
    LocalResearch.liveTimers.push(timer);
  }
}

// Snake colors (from snake_autoresearch)
const _SNAKE_COLORS = [['#00ff87', '#00a85a'], ['#00b4d8', '#007a94']];
const _SNAKE_FOOD = '#ff006e';
const _SNAKE_DEAD = '#2a2a2a';
const _SNAKE_BG = '#0c0c18';
const _SNAKE_GRID_DOT = '#16182a';

function _arRenderMiniFrame(canvas, gameId, frame) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;

  // Snake (all variants): raw state format {snakes, food, alive, scores, turn}
  const isSnakeVariant = gameId === 'snake' || gameId === 'snake_random' || gameId === 'snake_royale' || gameId === 'snake_2v2';
  if (isSnakeVariant && frame.snakes) {
    const GRID = gameId === 'snake_royale' ? 30 : gameId === 'snake_2v2' ? 24 : 20;
    const SC = w / GRID;

    ctx.fillStyle = _SNAKE_BG;
    ctx.fillRect(0, 0, w, h);

    ctx.fillStyle = _SNAKE_GRID_DOT;
    for (let x = 0; x <= GRID; x++)
      for (let y = 0; y <= GRID; y++)
        ctx.fillRect(x * SC, y * SC, 1, 1);

    // Walls (snake_random) — dark gray blocks
    if (frame.walls && frame.walls.length) {
      ctx.fillStyle = '#444455';
      for (const key of frame.walls) {
        const [wx, wy] = typeof key === 'string' ? key.split(',').map(Number) : key;
        ctx.fillRect(wx * SC + 0.5, wy * SC + 0.5, SC - 1, SC - 1);
      }
    }

    for (const f of (frame.food || [])) {
      ctx.fillStyle = _SNAKE_FOOD;
      ctx.beginPath();
      ctx.arc(f[0] * SC + SC / 2, f[1] * SC + SC / 2, SC * 0.35, 0, Math.PI * 2);
      ctx.fill();
    }

    // Corpse cells: gray with cross-hatch
    if (frame.corpseCells && frame.corpseCells.length > 0) {
      ctx.fillStyle = '#3a3a3a';
      for (const [cx, cy] of frame.corpseCells) {
        ctx.fillRect(cx * SC + 1, cy * SC + 1, SC - 2, SC - 2);
      }
      ctx.strokeStyle = 'rgba(80, 80, 80, 0.7)';
      ctx.lineWidth = Math.max(0.5, SC * 0.1);
      for (const [cx, cy] of frame.corpseCells) {
        const px = cx * SC, py = cy * SC;
        ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(px + SC, py + SC); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(px + SC, py); ctx.lineTo(px, py + SC); ctx.stroke();
      }
    }

    const alive = frame.alive || [true, true, true, true];
    const snakeCount = frame.snakes.length;
    // Royale: 4 distinct colors. 2v2: two greens (team AC) vs two blues (team BD)
    const _SNAKE_COLORS_ROYALE = [
      ['#00ff87', '#00a85a'], ['#00b4d8', '#007a94'],
      ['#4FCC30', '#2d8a1c'], ['#A356D6', '#7a3aad'],
    ];
    const _SNAKE_COLORS_2V2 = [
      ['#00ff87', '#00a85a'], ['#00b4d8', '#007a94'],  // 0=green(AC), 1=blue(BD)
      ['#4FCC30', '#2d8a1c'], ['#48a0cc', '#2e7a9e'],  // 2=green(AC), 3=blue(BD)
    ];
    const colorsForGame = snakeCount > 2
      ? (gameId === 'snake_2v2' ? _SNAKE_COLORS_2V2 : _SNAKE_COLORS_ROYALE)
      : _SNAKE_COLORS;
    for (let s = 0; s < snakeCount; s++) {
      const sn = frame.snakes[s];
      if (!sn || !sn.length) continue;
      const [hc, bc] = alive[s] ? (colorsForGame[s] || _SNAKE_COLORS[0]) : [_SNAKE_DEAD, _SNAKE_DEAD];
      const P = 1;
      for (let i = sn.length - 1; i >= 0; i--) {
        const [sx, sy] = sn[i];
        ctx.fillStyle = i === 0 ? hc : bc;
        const x = sx * SC + P, y = sy * SC + P, bw = SC - P * 2, bh = SC - P * 2, r = Math.min(3, SC * 0.15);
        ctx.beginPath();
        ctx.moveTo(x + r, y); ctx.lineTo(x + bw - r, y); ctx.quadraticCurveTo(x + bw, y, x + bw, y + r);
        ctx.lineTo(x + bw, y + bh - r); ctx.quadraticCurveTo(x + bw, y + bh, x + bw - r, y + bh);
        ctx.lineTo(x + r, y + bh); ctx.quadraticCurveTo(x, y + bh, x, y + bh - r);
        ctx.lineTo(x, y + r); ctx.quadraticCurveTo(x, y, x + r, y);
        ctx.fill();
        if (i === 0 && alive[s]) {
          ctx.fillStyle = '#000';
          ctx.beginPath();
          ctx.arc(sx * SC + SC * 0.35, sy * SC + SC * 0.38, Math.max(1.5, SC * 0.12), 0, Math.PI * 2);
          ctx.arc(sx * SC + SC * 0.65, sy * SC + SC * 0.38, Math.max(1.5, SC * 0.12), 0, Math.PI * 2);
          ctx.fill();
          ctx.fillStyle = '#fff';
          ctx.beginPath();
          ctx.arc(sx * SC + SC * 0.35, sy * SC + SC * 0.36, Math.max(0.7, SC * 0.05), 0, Math.PI * 2);
          ctx.arc(sx * SC + SC * 0.65, sy * SC + SC * 0.36, Math.max(0.7, SC * 0.05), 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }

    if (frame.scores) {
      ctx.font = `bold ${Math.max(9, SC * 0.7 | 0)}px monospace`;
      ctx.textAlign = 'left';
      if (snakeCount <= 2) {
        ctx.fillStyle = colorsForGame[0][0];
        ctx.fillText(frame.scores[0], 4, h - 4);
        ctx.fillStyle = colorsForGame[1][0];
        ctx.textAlign = 'right';
        ctx.fillText(frame.scores[1], w - 4, h - 4);
        ctx.textAlign = 'left';
      } else {
        // 4P: show all scores in corners
        const positions = [[4, h - 4], [w - 4, h - 4], [4, 12], [w - 4, 12]];
        const aligns = ['left', 'right', 'left', 'right'];
        for (let s = 0; s < Math.min(snakeCount, 4); s++) {
          ctx.fillStyle = colorsForGame[s][0];
          ctx.textAlign = aligns[s];
          ctx.fillText(frame.scores[s], positions[s][0], positions[s][1]);
        }
        ctx.textAlign = 'left';
      }
    }
    return;
  }

  // Chess960: proper wooden board with Unicode pieces
  if (gameId === 'chess960' && frame.board) {
    const board = frame.board;
    const rows = 8, cols = 8;
    const sq = w / cols;
    const lm = frame.lastMove; // [fr,fc,tr,tc] or null

    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const isLight = (r + c) % 2 === 0;
        const highlight = lm && ((r===lm[0]&&c===lm[1])||(r===lm[2]&&c===lm[3]));
        ctx.fillStyle = highlight
          ? (isLight ? '#F6F669' : '#BACA2B')
          : (isLight ? '#F0D9B5' : '#B58863');
        ctx.fillRect(c*sq, r*sq, sq, sq);

        const piece = board[r][c];
        if (piece !== 0) {
          // Python engine encoding: 1=Pawn,2=Knight,3=Bishop,4=Rook,5=Queen,6=King
          // Use FILLED Unicode glyphs (♟♞♝♜♛♚) for both colors — solid look
          const _PY_PIECE_FILLED = {1:'\u265F',2:'\u265E',3:'\u265D',4:'\u265C',5:'\u265B',6:'\u265A'};
          const ch = _PY_PIECE_FILLED[Math.abs(piece)] || '';
          ctx.font = `${sq * 0.82}px serif`;
          ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          // Shadow for depth
          ctx.fillStyle = 'rgba(0,0,0,0.4)';
          ctx.fillText(ch, c*sq+sq/2+1, r*sq+sq/2+1);
          // White pieces: white fill with dark stroke; black pieces: dark fill
          if (piece > 0) {
            ctx.fillStyle = '#FFFFFF';
            ctx.fillText(ch, c*sq+sq/2, r*sq+sq/2);
            ctx.strokeStyle = 'rgba(0,0,0,0.3)';
            ctx.lineWidth = 0.5;
            ctx.strokeText(ch, c*sq+sq/2, r*sq+sq/2);
          } else {
            ctx.fillStyle = '#1a1a1a';
            ctx.fillText(ch, c*sq+sq/2, r*sq+sq/2);
          }
        }
      }
    }

    // Material score at bottom
    if (frame.scoreA !== undefined && frame.scoreB !== undefined) {
      ctx.font = `bold ${Math.max(9, sq * 0.55 | 0)}px monospace`;
      ctx.textAlign = 'left';
      ctx.fillStyle = '#FFFFFF';
      ctx.fillText(String(frame.scoreA || 0), 3, h - 3);
      ctx.textAlign = 'right';
      ctx.fillStyle = '#1a1a1a';
      ctx.strokeStyle = '#999';
      ctx.lineWidth = 0.5;
      ctx.strokeText(String(frame.scoreB || 0), w - 3, h - 3);
      ctx.fillText(String(frame.scoreB || 0), w - 3, h - 3);
    }
    return;
  }

  // Othello: green board with black/white discs
  if (gameId === 'othello' && frame.board) {
    const board = frame.board;
    const sq = w / 8;
    const radius = sq * 0.40;

    for (let r = 0; r < 8; r++) {
      for (let c = 0; c < 8; c++) {
        // Green board
        ctx.fillStyle = '#2E7D32';
        ctx.fillRect(c * sq, r * sq, sq, sq);
        ctx.strokeStyle = '#1B5E20';
        ctx.lineWidth = 0.5;
        ctx.strokeRect(c * sq, r * sq, sq, sq);

        const piece = board[r][c];
        if (piece !== 0) {
          const cx = c * sq + sq / 2, cy = r * sq + sq / 2;
          const isLast = frame.last_move && frame.last_move[0] === r && frame.last_move[1] === c;
          // Shadow
          ctx.beginPath();
          ctx.arc(cx + 0.8, cy + 0.8, radius, 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(0,0,0,0.3)';
          ctx.fill();
          // Disc
          ctx.beginPath();
          ctx.arc(cx, cy, radius, 0, Math.PI * 2);
          ctx.fillStyle = piece === 1 ? '#111111' : '#F5F5F5';
          ctx.fill();
          // Last move ring
          if (isLast) {
            ctx.strokeStyle = '#FFDC00';
            ctx.lineWidth = 1.5;
            ctx.stroke();
          }
        }
      }
    }

    // Scores at bottom
    if (frame.scores) {
      const scores = frame.scores;
      const bk = typeof scores === 'object' && !Array.isArray(scores) ? scores.black || scores[0] : scores[0];
      const wt = typeof scores === 'object' && !Array.isArray(scores) ? scores.white || scores[1] : scores[1];
      ctx.font = `bold ${Math.max(9, sq * 0.55 | 0)}px monospace`;
      ctx.textAlign = 'left';
      ctx.fillStyle = '#111';
      ctx.fillText(String(bk || 0), 3, h - 3);
      ctx.textAlign = 'right';
      ctx.fillStyle = '#F5F5F5';
      ctx.strokeStyle = '#333';
      ctx.lineWidth = 0.5;
      ctx.strokeText(String(wt || 0), w - 3, h - 3);
      ctx.fillText(String(wt || 0), w - 3, h - 3);
    }
    return;
  }

  // Fallback: ARC3 grid format
  const grid = frame.grid || frame.board;
  if (!grid || !grid.length) {
    ctx.fillStyle = _SNAKE_BG;
    ctx.fillRect(0, 0, w, h);
    return;
  }
  const rows = grid.length, cols = grid[0].length;
  const cellW = w / cols, cellH = h / rows;
  for (let r = 0; r < rows; r++)
    for (let c = 0; c < cols; c++) {
      ctx.fillStyle = ARC3[grid[r][c]] || ARC3[5];
      ctx.fillRect(c * cellW, r * cellH, cellW + 0.5, cellH + 0.5);
    }
}


/* ═══════════════════════════════════════════════════════════════════════════
   ELO Chart — Chart.js line graph, orange, with hover tooltips
   ═══════════════════════════════════════════════════════════════════════════ */

let _arEloChart = null;

function arRenderEloChart(gameId, agents) {
  const canvas = document.getElementById('arEloChart');
  if (!canvas) return;
  if (typeof Chart === 'undefined') return;
  // Destroy old chart when switching games or no data — prevents stale data
  if (!agents || !agents.length) {
    if (_arEloChart) { _arEloChart.destroy(); _arEloChart = null; }
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    return;
  }

  // Sort by creation time (id is auto-increment, so lower id = created earlier)
  const sorted = [...agents].sort((a, b) => a.id - b.id);
  const labels = sorted.map((_, i) => i + 1);
  const data = sorted.map(a => Math.round(a.elo));
  const meta = sorted.map(a => ({
    name: a.name, elo: Math.round(a.elo),
    wld: `${a.wins}/${a.losses}/${a.draws}`,
    games: a.games_played, by: a.contributor || '—',
  }));

  if (_arEloChart) {
    _arEloChart.data.labels = labels;
    _arEloChart.data.datasets[0].data = data;
    _arEloChart.data.datasets[0]._meta = meta;
    _arEloChart.update('none');
    return;
  }

  _arEloChart = new Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data,
        _meta: meta,
        borderColor: '#FF851B',
        backgroundColor: '#FF851B44',
        borderWidth: 2,
        pointRadius: 4,
        pointHoverRadius: 7,
        pointBackgroundColor: '#FF851B',
        pointBorderColor: '#FF851B',
        tension: 0.1,
        fill: true,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => {
              const m = ctx.dataset._meta?.[ctx.dataIndex];
              if (!m) return `ELO: ${ctx.parsed.y}`;
              return `${m.name}: ELO ${m.elo} | W/L/D ${m.wld} | ${m.games} games | by ${m.by}`;
            },
          },
          backgroundColor: '#1a1a2e',
          titleColor: '#FF851B',
          bodyColor: '#ccc',
          borderColor: '#FF851B44',
          borderWidth: 1,
        },
      },
      scales: {
        x: {
          display: false,
        },
        y: {
          title: { display: true, text: 'ELO', color: '#888', font: { size: 10 } },
          grid: { color: '#ffffff08' },
          ticks: { color: '#666', font: { size: 9 } },
        },
      },
    },
  });
}


/* ═══════════════════════════════════════════════════════════════════════════
   Populate Model Select for Agent Creation
   ═══════════════════════════════════════════════════════════════════════════ */

function _arPopulateCreateModels() {
  const sel = document.getElementById('arCreateModel');
  if (!sel) return;

  // Use modelsData from state.js if available
  const models = window.modelsData || {};
  const providers = ['anthropic', 'gemini', 'groq', 'mistral', 'openai'];
  const options = [];

  for (const [key, info] of Object.entries(models)) {
    if (providers.includes(info.provider)) {
      options.push({ key, label: key, provider: info.provider });
    }
  }

  if (!options.length) {
    // Fallback — hardcode common models
    options.push(
      { key: 'claude-sonnet-4-6', label: 'claude-sonnet-4.6', provider: 'anthropic' },
      { key: 'claude-haiku-4-5', label: 'claude-haiku-4.5', provider: 'anthropic' },
      { key: 'gemini-2.5-flash', label: 'gemini-2.5-flash', provider: 'gemini' },
    );
  }

  sel.innerHTML = options.map(o =>
    `<option value="${o.key}">${o.label}</option>`
  ).join('');

  // Restore saved key
  const savedKey = localStorage.getItem('arc_arena_create_api_key');
  const keyInput = document.getElementById('arCreateApiKey');
  if (savedKey && keyInput) keyInput.value = savedKey;

  // Auto-fill key from BYOK if available
  sel.addEventListener('change', () => {
    const info = models[sel.value];
    if (info && keyInput) {
      const byokKey = localStorage.getItem(`byok_key_${info.provider}`);
      if (byokKey) keyInput.value = byokKey;
    }
  });
  // Trigger initial fill
  sel.dispatchEvent(new Event('change'));
}


/* ═══════════════════════════════════════════════════════════════════════════
   Client-Side Agent Creation — runs LLM tool-calling loop in browser
   ═══════════════════════════════════════════════════════════════════════════ */

async function arCreateAgentLocal() {
  const btn = document.getElementById('arCreateAgentBtn');
  const log = document.getElementById('arCreateAgentLog');
  const modelSel = document.getElementById('arCreateModel');
  const keyInput = document.getElementById('arCreateApiKey');
  if (!modelSel || !keyInput) return;

  const model = modelSel.value;
  const apiKey = keyInput.value.trim();
  if (!apiKey) { alert('Please enter an API key'); return; }

  // Save key for next time
  localStorage.setItem('arc_arena_create_api_key', apiKey);
  const info = window.modelsData?.[model];
  if (info) localStorage.setItem(`byok_key_${info.provider}`, apiKey);

  const gameId = AR.selectedGame || 'snake';
  btn.disabled = true;
  btn.textContent = 'Creating...';
  log.style.display = 'block';
  log.innerHTML = '<div style="color:#00ff87">Starting agent creation...</div>';

  const _log = (msg, color = '#ccc') => {
    log.innerHTML += `<div style="color:${color}">${msg}</div>`;
    log.scrollTop = log.scrollHeight;
  };

  try {
    // Check if program.md was edited — propose changes first
    const progTa = document.getElementById('arProgramTextarea');
    const editedProgram = progTa ? progTa.value.trim() : '';
    if (editedProgram && AR._lastProgramContent && editedProgram !== AR._lastProgramContent) {
      _log('Submitting program.md changes...', '#ffdc00');
      const summary = document.getElementById('arProgramSummary')?.value.trim() || 'Updated via Create Agent';
      try {
        await fetch(`/api/arena/program/${gameId}`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ content: editedProgram, summary }),
        });
        AR._lastProgramContent = editedProgram;
        _log('Program.md updated', '#4FCC30');
      } catch (e) {
        _log('Program.md update failed (continuing)', '#ff851b');
      }
    }

    // Load program.md + leaderboard
    const research = await fetch(`/api/arena/research/${gameId}`).then(r => r.json());
    const programMd = editedProgram || research.program?.content || _AR_DEFAULT_PROGRAM;
    const leaderboard = research.leaderboard || [];

    // Build leaderboard text
    let lbText = '';
    if (leaderboard.length) {
      lbText = 'Current leaderboard:\n';
      for (let i = 0; i < Math.min(5, leaderboard.length); i++) {
        const a = leaderboard[i];
        lbText += `  #${i + 1} ${a.name} ELO=${Math.round(a.elo)} W/L/D=${a.wins}/${a.losses}/${a.draws}\n`;
      }
      // Include top agent code
      if (leaderboard[0]) {
        try {
          const topAgent = await fetch(`/api/arena/agents/${gameId}/${leaderboard[0].id}`).then(r => r.json());
          if (topAgent.code) lbText += `\nBest agent code (${leaderboard[0].name}):\n\`\`\`python\n${topAgent.code}\n\`\`\`\n`;
        } catch (e) {}
      }
    }

    const gen = (research.generation || 0) + 1;
    const systemPrompt = programMd + '\n\nCall create_agent with name and complete Python code.\nThe agent must have a get_move(state) function.\nOnly standard library imports (random, math, collections).\nMust return in <100ms.';
    const userMessage = `Generation ${gen}. ${lbText}\nCreate ONE agent. Name it gen${gen}_<strategy>.\nStudy the top agents and create a counter-strategy.\nCall create_agent with name and full Python code.`;

    _log(`Using ${model}`, '#00b4d8');
    _log(`Sending prompt to LLM...`);

    // Anthropic tool-calling loop (direct browser fetch)
    const tools = [
      { name: 'create_agent', description: 'Create a new agent. Code must define get_move(state).', input_schema: {
        type: 'object', properties: { name: { type: 'string' }, code: { type: 'string' } }, required: ['name', 'code']
      }},
      { name: 'read_agent', description: "Read an agent's source code by name.", input_schema: {
        type: 'object', properties: { agent_name: { type: 'string' } }, required: ['agent_name']
      }},
      { name: 'test_match', description: 'Run a test match between two agents.', input_schema: {
        type: 'object', properties: { agent1_name: { type: 'string' }, agent2_name: { type: 'string' } }, required: ['agent1_name', 'agent2_name']
      }},
    ];

    let messages = [{ role: 'user', content: userMessage }];
    let createdAgent = null;

    for (let round = 0; round < 6; round++) {
      const isAnthropic = model.startsWith('claude');
      const provider = info?.provider || (isAnthropic ? 'anthropic' : 'gemini');

      let data;
      if (provider === 'anthropic') {
        const headers = { 'Content-Type': 'application/json', 'x-api-key': apiKey, 'anthropic-version': '2023-06-01', 'anthropic-dangerous-direct-browser-access': 'true' };
        const resp = await fetch('https://api.anthropic.com/v1/messages', {
          method: 'POST', headers,
          body: JSON.stringify({ model: info?.api_model || model, max_tokens: 8192, system: systemPrompt, tools, messages }),
        });
        data = await resp.json();
        if (!resp.ok) { _log(`API error: ${data.error?.message || resp.status}`, '#F93C31'); break; }
      } else {
        // For non-Anthropic, use callLLM (no tool calling, parse text)
        const fullPrompt = [{ role: 'system', content: systemPrompt }, ...messages];
        const text = await callLLM(fullPrompt, model, { maxTokens: 8192 });
        _log(`LLM responded (text mode). Parsing for create_agent call...`);
        // Try to parse XML-style tool call
        const nameMatch = text.match(/create_agent.*?name['":\s]+(\w+)/s);
        const codeMatch = text.match(/```python\n([\s\S]*?)```/);
        if (nameMatch && codeMatch) {
          data = { stop_reason: 'tool_use', content: [{ type: 'tool_use', id: 'tc_1', name: 'create_agent', input: { name: nameMatch[1], code: codeMatch[1] } }] };
        } else {
          _log('Could not parse agent from LLM response', '#F93C31');
          break;
        }
      }

      // Extract text
      const textParts = (data.content || []).filter(b => b.type === 'text' && b.text);
      for (const t of textParts) _log(t.text.substring(0, 200));

      messages.push({ role: 'assistant', content: data.content });

      if (data.stop_reason !== 'tool_use') {
        _log('LLM finished without creating an agent', '#FFDC00');
        break;
      }

      // Process tool calls
      const toolResults = [];
      for (const block of data.content) {
        if (block.type !== 'tool_use') continue;
        _log(`Tool: ${block.name}(${JSON.stringify(block.input).substring(0, 80)}...)`, '#00b4d8');

        let result;
        if (block.name === 'create_agent') {
          // Submit to server
          try {
            const resp = await fetch(`/api/arena/agents/${gameId}`, {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ name: block.input.name, code: block.input.code, contributor: (typeof currentUser !== 'undefined' && currentUser) ? currentUser.display_name || currentUser.email.split('@')[0] : model }),
            });
            const r = await resp.json();
            if (resp.ok && !r.error) {
              createdAgent = { name: block.input.name, ...r };
              result = JSON.stringify({ success: true, message: `Agent '${block.input.name}' created!` });
              _log(`Agent '${block.input.name}' created and registered!`, '#00ff87');
            } else {
              result = JSON.stringify({ error: r.error || 'Submit failed' });
              _log(`Submit failed: ${r.error || 'Unknown error'}`, '#F93C31');
            }
          } catch (e) {
            result = JSON.stringify({ error: e.message });
            _log(`Submit error: ${e.message}`, '#F93C31');
          }
        } else if (block.name === 'read_agent') {
          try {
            const a = leaderboard.find(x => x.name === block.input.agent_name);
            if (a) {
              const full = await fetch(`/api/arena/agents/${gameId}/${a.id}`).then(r => r.json());
              result = full.code || '(no code)';
            } else {
              result = JSON.stringify({ error: 'Agent not found' });
            }
          } catch (e) { result = JSON.stringify({ error: e.message }); }
          _log(`  → ${(result || '').substring(0, 100)}...`);
        } else if (block.name === 'test_match') {
          result = JSON.stringify({ message: 'Test matches not available in browser mode. Agent was auto-tested on submit.' });
          _log('  → Test match skipped (browser mode)');
        } else {
          result = JSON.stringify({ error: `Unknown tool: ${block.name}` });
        }

        toolResults.push({ type: 'tool_result', tool_use_id: block.id, content: result || '' });
      }
      messages.push({ role: 'user', content: toolResults });

      if (createdAgent) break;
    }

    if (createdAgent) {
      _log(`\nDone! Agent "${createdAgent.name}" is now on the leaderboard.`, '#00ff87');
      // Refresh leaderboard
      const data = await fetch(`/api/arena/research/${gameId}`).then(r => r.json());
      if (!data.error) arRenderResearch(gameId, data);
    } else {
      _log('\nNo agent was created this round.', '#FFDC00');
    }
  } catch (e) {
    _log(`Error: ${e.message}`, '#F93C31');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Create Agent';
  }
}


/* ═══════════════════════════════════════════════════════════════════════════
   Human vs AI Play — Phase 4
   ═══════════════════════════════════════════════════════════════════════════ */

const HumanPlay = {
  active: false,
  gameId: null,
  engine: null,
  agents: [],            // [{id, code, name}, ...] — 1 for 2P, 3 for 4P
  agentId: null,
  agentCode: null,
  aiName: '',
  delayMs: 1000,       // time limit per human move (0 = infinite)
  timer: null,          // game loop interval (simultaneous games)
  timerCountdown: null, // countdown display interval
  moveDeadline: 0,      // timestamp when current move times out
  humanDir: null,        // buffered direction for simultaneous games
  aiPrevMoves: [],       // track AI moves for prev_moves state field
  turns: 0,
  canvas: null,
  ctx: null,
  canvasSize: 480,
  _keyHandler: null,
  _clickHandler: null,
};

/** Build state in Python SnakeGame.get_state() format for server-side agents.
 *  @param {object} engine — JS snake engine
 *  @param {number} playerIdx — 0-based index (0=human for 2P, 0-3 for 4P)
 *  @param {number} agentSlot — index into HumanPlay.agents for prev_moves tracking */
function _hpBuildPythonState(engine, playerIdx, agentSlot) {
  const gameId = HumanPlay.gameId;
  const prevMoves = (HumanPlay.aiPrevMoves && HumanPlay.aiPrevMoves[agentSlot]) || [];

  // 4-player modes (royale / 2v2)
  if (engine.snakes && engine.snakes.length > 2) {
    const me = engine.snakes[playerIdx];
    const state = {
      grid_size: [engine.W, engine.H],
      my_snake: me.body.map(p => [...p]),
      my_direction: DIR_NAME[me.dir],
      my_index: playerIdx,
      snakes: engine.snakes.map((s, i) => ({
        body: s.alive ? s.body.map(p => [...p]) : [],
        direction: s.alive ? DIR_NAME[s.dir] : null,
        alive: s.alive,
        is_ally: engine.mode === '2v2' ? (i % 2) === (playerIdx % 2) : false,
      })),
      food: (engine.foodList || engine.food || []).map(f => [...f]),
      turn: engine.turn,
      prev_moves: prevMoves,
    };
    // 2v2: add convenience ally/enemies fields
    if (engine.mode === '2v2') {
      const allyIdx = playerIdx === 0 ? 2 : playerIdx === 1 ? 3 : playerIdx === 2 ? 0 : 1;
      const ally = engine.snakes[allyIdx];
      state.ally_snake = ally.alive ? ally.body.map(p => [...p]) : [];
      state.ally_direction = ally.alive ? DIR_NAME[ally.dir] : null;
      state.enemies = engine.snakes
        .filter((_, i) => (i % 2) !== (playerIdx % 2))
        .map(e => ({
          body: e.alive ? e.body.map(p => [...p]) : [],
          direction: e.alive ? DIR_NAME[e.dir] : null,
          alive: e.alive,
        }));
    }
    return state;
  }

  // 2-player modes (snake / snake_random)
  const isA = playerIdx === 0;
  const me = isA ? engine.snakeA : engine.snakeB;
  const enemy = isA ? engine.snakeB : engine.snakeA;
  const state = {
    grid_size: [engine.W, engine.H],
    my_snake: me.body.map(p => [...p]),
    my_direction: DIR_NAME[me.dir],
    enemy_snake: enemy.alive ? enemy.body.map(p => [...p]) : [],
    enemy_direction: enemy.alive ? DIR_NAME[enemy.dir] : null,
    food: (Array.isArray(engine.food) ? engine.food : (engine.food ? [engine.food] : [])).map(f => [...f]),
    turn: engine.turn,
    prev_moves: prevMoves,
  };
  // snake_random: include walls
  if (gameId === 'snake_random' && engine.walls) {
    state.walls = [...engine.walls].map(k => k.split(',').map(Number));
  }
  return state;
}

/** Fetch AI move from server (agents are Python, executed server-side).
 *  @param {object} state — Python-format game state
 *  @param {object} [agent] — {id, code} for specific agent (default: HumanPlay primary agent) */
async function _hpFetchAiMove(state, agent) {
  try {
    const a = agent || HumanPlay.agents[0];
    const body = { game_id: HumanPlay.gameId, state };
    if (a.id) body.agent_id = a.id;
    else body.code = a.code;
    const resp = await fetch('/api/arena/agent-move', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (data.error) {
      console.warn('Agent move error:', data.error);
      if (state.validMoves && state.validMoves.length > 0) return state.validMoves[0];
      return 'UP';
    }
    return data.move;
  } catch (e) {
    console.warn('Agent move fetch error:', e);
    if (state.validMoves && state.validMoves.length > 0) return state.validMoves[0];
    return 'UP';
  }
}

/** Launch human vs AI play session. Called from arStartHumanPlay() in arena.js
 *  @param {string} gameId
 *  @param {Array<{id, code, name}>} agents — 1 agent for 2P, 3 agents for 4P
 *  @param {number} delayMs */
function arLaunchHumanPlay(gameId, agents, delayMs) {
  if (gameId === 'poker') {
    alert('Poker human play is not yet supported.');
    return;
  }

  if (!agents || !agents.length) { alert('No agent code available.'); return; }

  const game = ARENA_GAMES.find(g => g.id === gameId);
  if (!game) return;

  const is4P = gameId === 'snake_royale' || gameId === 'snake_2v2';

  // Init state — agent moves are proxied through the server (Python code)
  HumanPlay.active = true;
  HumanPlay.gameId = gameId;
  HumanPlay.engine = _arNewEngine(gameId, game.config);
  // agents[0] = selected opponent, agents[1..2] = random fill for 4P
  HumanPlay.agents = agents;
  HumanPlay.agentId = agents[0].id;
  HumanPlay.agentCode = agents[0].code;
  HumanPlay.aiName = agents[0].name;
  HumanPlay.aiPrevMoves = agents.map(() => []);
  HumanPlay.delayMs = delayMs;
  HumanPlay.turns = 0;
  HumanPlay.humanDir = null;
  HumanPlay.history = [];

  // Show game area inside the dialog popup (don't replace arCenter)
  const configArea = document.getElementById('arHumanConfig');
  const gameArea = document.getElementById('arHumanGameArea');
  if (configArea) configArea.style.display = 'none';
  if (gameArea) gameArea.style.display = 'block';

  // Title: show opponent name, or all names for 4P
  const titleEl = document.getElementById('hpTitle');
  if (titleEl) {
    if (is4P) {
      const names = agents.map(a => a.name).join(', ');
      titleEl.textContent = `You vs ${names}`;
    } else {
      titleEl.textContent = `You vs ${agents[0].name}`;
    }
  }
  const timerEl = document.getElementById('hpTimer');
  if (timerEl) timerEl.textContent = delayMs ? delayMs + 'ms' : 'No limit';

  // Show the dialog overlay
  document.getElementById('arHumanDialog').style.display = 'flex';

  HumanPlay.canvas = document.getElementById('hpCanvas');
  HumanPlay.ctx = HumanPlay.canvas.getContext('2d');
  HumanPlay.canvasSize = HumanPlay.canvas.width;

  // Render initial state
  _hpRender();

  // Set up input handlers
  if (_arIsSimultaneous(gameId)) {
    _hpSetupSimultaneous();
  } else {
    _hpSetupTurnBased();
  }
}

/** Clean up and exit human play */
function arHumanQuit() {
  HumanPlay.active = false;
  if (HumanPlay.timer) { clearTimeout(HumanPlay.timer); HumanPlay.timer = null; }
  if (HumanPlay.timerCountdown) { clearInterval(HumanPlay.timerCountdown); HumanPlay.timerCountdown = null; }
  if (HumanPlay._keyHandler) { document.removeEventListener('keydown', HumanPlay._keyHandler); HumanPlay._keyHandler = null; }
  if (HumanPlay._clickHandler && HumanPlay.canvas) { HumanPlay.canvas.removeEventListener('click', HumanPlay._clickHandler); HumanPlay._clickHandler = null; }

  // Hide the dialog — research view is intact behind it
  document.getElementById('arHumanDialog').style.display = 'none';
  // Reset dialog to config state for next time
  const configArea = document.getElementById('arHumanConfig');
  const gameArea = document.getElementById('arHumanGameArea');
  if (configArea) configArea.style.display = 'block';
  if (gameArea) gameArea.style.display = 'none';
}


/* ── Render ─────────────────────────────────────────────────────────────── */

function _hpRender() {
  const { gameId, engine, ctx, canvasSize: sz } = HumanPlay;
  if (!engine || !ctx) return;

  // Build a frame object and use the tournament mini-frame renderer for snake
  const frame = _hpBuildFrame(gameId, engine);
  if (gameId === 'snake' || gameId.startsWith('snake_')) {
    _arRenderMiniFrame(HumanPlay.canvas, gameId, frame);
  } else {
    const game = ARENA_GAMES.find(g => g.id === gameId);
    if (game && game.render) game.render(ctx, frame, sz);
  }

  // Overlay valid moves for turn-based click games
  if (!_arIsSimultaneous(gameId) && !engine.over) {
    const who = _arWhoseTurn(gameId, engine);
    if (who === 'A') { // Human's turn
      _hpDrawValidMoves(gameId, engine, ctx, sz);
    }
  }
}

function _hpBuildFrame(gameId, engine) {
  switch (gameId) {
    case 'snake':
    case 'snake_random': {
      // 2P snake variants
      const frame = {
        snakes: [engine.snakeA.body.map(p => [...p]), engine.snakeB.body.map(p => [...p])],
        alive: [engine.snakeA.alive, engine.snakeB.alive],
        scores: [engine.snakeA.body.length, engine.snakeB.body.length],
        food: Array.isArray(engine.food) ? engine.food : (engine.food ? [engine.food] : []),
        turn: engine.turn,
      };
      if (engine.walls) frame.walls = [...engine.walls];
      return frame;
    }
    case 'snake_royale':
    case 'snake_2v2': {
      // 4P snake variants
      return {
        snakes: engine.snakes.map(s => s.body.map(p => [...p])),
        alive: engine.snakes.map(s => s.alive),
        scores: engine.snakes.map(s => s.body.length),
        food: (engine.foodList || engine.food || []).map(f => [...f]),
        turn: engine.turn,
      };
    }
    case 'tron': return { grid: engine.getGrid() };
    case 'connect4': return { board: engine.getBoard(), lastMove: engine.lastMove };
    case 'chess960': return { board: engine.getBoard(), lastMove: engine.lastMove };
    case 'othello': return { board: engine.getBoard(), lastMove: engine.lastMove };
    case 'go9': return { board: engine.getBoard(), lastMove: engine.lastMove };
    case 'gomoku': return { board: engine.getBoard(), lastMove: engine.lastMove };
    case 'artillery': return { state: engine.getState() };
    default: return {};
  }
}

function _hpDrawValidMoves(gameId, engine, ctx, sz) {
  ctx.fillStyle = 'rgba(79, 204, 48, 0.25)';

  if (gameId === 'connect4') {
    const moves = engine.getLegalMoves();
    const cellW = sz / 7;
    for (const col of moves) {
      ctx.fillRect(col * cellW + 2, 2, cellW - 4, 10);
    }
  } else if (gameId === 'othello') {
    const moves = engine.getLegalMoves();
    const sq = sz / 8;
    for (const m of moves) {
      ctx.beginPath();
      ctx.arc((m.c + 0.5) * sq, (m.r + 0.5) * sq, sq * 0.15, 0, Math.PI * 2);
      ctx.fill();
    }
  } else if (gameId === 'go9') {
    const moves = engine.getLegalMoves();
    const margin = sz * 0.06, inner = sz - margin * 2, step = inner / 8;
    for (const m of moves) {
      ctx.beginPath();
      ctx.arc(margin + m[1] * step, margin + m[0] * step, step * 0.2, 0, Math.PI * 2);
      ctx.fill();
    }
  } else if (gameId === 'gomoku') {
    // Too many moves to highlight — skip for gomoku
  } else if (gameId === 'chess960') {
    const moves = engine.getLegalMoves();
    const sq = sz / 8;
    const sources = new Set(moves.map(m => m.f[0] * 8 + m.f[1]));
    ctx.fillStyle = 'rgba(79, 204, 48, 0.15)';
    for (const idx of sources) {
      const r = Math.floor(idx / 8), c = idx % 8;
      ctx.fillRect(c * sq, r * sq, sq, sq);
    }
  }
}


/* ── Simultaneous Game Loop (Snake, Tron) ──────────────────────────────── */

function _hpSetupSimultaneous() {
  const { gameId, engine, delayMs } = HumanPlay;

  const is4P = gameId === 'snake_royale' || gameId === 'snake_2v2';

  // Default human direction = current snake direction
  if (is4P) HumanPlay.humanDir = engine.snakes[0].dir;
  else if (gameId === 'snake' || gameId === 'snake_random') HumanPlay.humanDir = engine.snakeA.dir;
  else if (gameId === 'tron') HumanPlay.humanDir = engine.dirA;
  else HumanPlay.humanDir = 0;

  // Keyboard handler
  const keyHandler = (e) => {
    if (!HumanPlay.active) return;
    switch (e.key) {
      case 'ArrowUp': case 'w': case 'W': HumanPlay.humanDir = 0; e.preventDefault(); break;
      case 'ArrowRight': case 'd': case 'D': HumanPlay.humanDir = 1; e.preventDefault(); break;
      case 'ArrowDown': case 's': case 'S': HumanPlay.humanDir = 2; e.preventDefault(); break;
      case 'ArrowLeft': case 'a': case 'A': HumanPlay.humanDir = 3; e.preventDefault(); break;
      case 'Escape': arHumanQuit(); break;
    }
  };
  document.addEventListener('keydown', keyHandler);
  HumanPlay._keyHandler = keyHandler;

  _hpUpdateStatus('Arrow keys or WASD to move. Game starts in 1s...');
  if (is4P) {
    const label = gameId === 'snake_2v2' ? 'You are GREEN (top-left). Your ally is bottom-left.' : 'You are GREEN (top-left). Free for all!';
    _hpUpdateHint(label);
  } else {
    _hpUpdateHint('You are the GREEN snake (top-left)');
  }

  // Start game loop after 1s — async because AI moves are fetched from server
  const tickRate = delayMs > 0 ? Math.max(delayMs, 150) : 200;
  const agents = HumanPlay.agents;

  async function _hpSimulTick() {
    if (!HumanPlay.active || engine.over) {
      if (engine.over) _hpGameOver();
      return;
    }

    if (is4P) {
      // 4P: fetch moves for agents at player indices 1, 2, 3 in parallel
      const [raw1, raw2, raw3] = await Promise.all([
        _hpFetchAiMove(_hpBuildPythonState(engine, 1, 0), agents[0]),
        _hpFetchAiMove(_hpBuildPythonState(engine, 2, 1), agents[1]),
        _hpFetchAiMove(_hpBuildPythonState(engine, 3, 2), agents[2]),
      ]);
      const dirs = [_arParseDir(raw1), _arParseDir(raw2), _arParseDir(raw3)];
      dirs.forEach((d, i) => HumanPlay.aiPrevMoves[i].push(DIR_NAME[d]));

      if (!HumanPlay.active) return;
      engine.step([HumanPlay.humanDir, dirs[0], dirs[1], dirs[2]]);
    } else {
      // 2P: fetch single AI move
      const aiState = _hpBuildPythonState(engine, 1, 0);
      const aiRaw = await _hpFetchAiMove(aiState, agents[0]);
      const aiDir = _arParseDir(aiRaw);
      HumanPlay.aiPrevMoves[0].push(DIR_NAME[aiDir]);

      if (!HumanPlay.active) return;
      engine.step(HumanPlay.humanDir, aiDir);
    }
    HumanPlay.turns++;
    HumanPlay.history.push(_hpBuildFrame(gameId, engine));

    _hpRender();
    _hpUpdateStatus(`Turn ${HumanPlay.turns}`);

    // Schedule next tick (recursive setTimeout avoids pileup from slow server calls)
    HumanPlay.timer = setTimeout(_hpSimulTick, tickRate);
  }

  setTimeout(() => {
    if (!HumanPlay.active) return;
    _hpSimulTick();
  }, 1000);
}


/* ── Turn-Based Game Loop (C4, Chess, Othello, Go, Gomoku, Artillery) ── */

function _hpSetupTurnBased() {
  const { gameId, engine, delayMs } = HumanPlay;

  // Human = A (moves first in most games)
  _hpUpdateHint(_hpGetControlHint(gameId));

  // Start countdown if human moves first
  if (_arWhoseTurn(gameId, engine) === 'A') {
    _hpStartHumanTurn();
  } else {
    _hpDoAiTurn();
  }

  // Click handler for board
  const clickHandler = (e) => {
    if (!HumanPlay.active || engine.over) return;
    if (_arWhoseTurn(gameId, engine) !== 'A') return; // Not human's turn

    const rect = HumanPlay.canvas.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;

    const move = _hpClickToMove(gameId, engine, x, y);
    if (!move) return;

    // Cancel timer
    if (HumanPlay.timerCountdown) { clearInterval(HumanPlay.timerCountdown); HumanPlay.timerCountdown = null; }

    // Apply human move
    _hpApplyHumanMove(gameId, engine, move);
    HumanPlay.turns++;
    HumanPlay.history.push(_hpBuildFrame(gameId, engine));
    _hpRender();

    if (engine.over) { _hpGameOver(); return; }

    // AI's turn
    _hpDoAiTurn();
  };
  HumanPlay.canvas.addEventListener('click', clickHandler);
  HumanPlay._clickHandler = clickHandler;

  // Escape to quit
  const keyHandler = (e) => {
    if (e.key === 'Escape') arHumanQuit();
  };
  document.addEventListener('keydown', keyHandler);
  HumanPlay._keyHandler = keyHandler;
}

function _hpStartHumanTurn() {
  _hpUpdateStatus(`Turn ${HumanPlay.turns + 1} | Your move`);
  _hpRender();

  if (HumanPlay.delayMs > 0) {
    HumanPlay.moveDeadline = Date.now() + HumanPlay.delayMs;
    const timerEl = document.getElementById('hpTimer');

    HumanPlay.timerCountdown = setInterval(() => {
      const remaining = Math.max(0, HumanPlay.moveDeadline - Date.now());
      if (timerEl) timerEl.textContent = Math.ceil(remaining / 1000) + 's';

      if (remaining <= 0) {
        clearInterval(HumanPlay.timerCountdown);
        HumanPlay.timerCountdown = null;
        // Timeout: play random valid move
        _hpTimeoutMove();
      }
    }, 100);
  }
}

function _hpTimeoutMove() {
  const { gameId, engine } = HumanPlay;
  if (!HumanPlay.active || engine.over) return;
  if (_arWhoseTurn(gameId, engine) !== 'A') return;

  // Pick a random valid move
  const state = _arBuildState(gameId, engine, 'A', HumanPlay.humanMemory);
  let move;
  if (state.validMoves && state.validMoves.length > 0) {
    move = state.validMoves[Math.floor(Math.random() * state.validMoves.length)];
  }
  if (move) {
    _hpApplyHumanMove(gameId, engine, move);
    HumanPlay.turns++;
    HumanPlay.history.push(_hpBuildFrame(gameId, engine));
    _hpRender();
    _hpUpdateStatus(`Turn ${HumanPlay.turns} | Timeout — random move played`);
    if (engine.over) { _hpGameOver(); return; }
    _hpDoAiTurn();
  }
}

async function _hpDoAiTurn() {
  const { gameId, engine } = HumanPlay;
  if (engine.over) { _hpGameOver(); return; }

  // Check if it's actually AI's turn (for games like Othello where passing happens)
  if (_arWhoseTurn(gameId, engine) !== 'B') {
    _hpStartHumanTurn();
    return;
  }

  _hpUpdateStatus(`Turn ${HumanPlay.turns + 1} | AI thinking...`);

  // Build Python-format state and fetch AI move from server
  const aiState = _hpBuildPythonState(engine, 'B');
  const raw = await _hpFetchAiMove(aiState);

  if (!HumanPlay.active || engine.over) return;
  _arStepEngine(gameId, engine, raw, null, aiState, null);
  HumanPlay.turns++;
  HumanPlay.history.push(_hpBuildFrame(gameId, engine));
  _hpRender();

  if (engine.over) { _hpGameOver(); return; }

  // Back to human
  _hpStartHumanTurn();
}


/* ── Click → Move Conversion ──────────────────────────────────────────── */

function _hpClickToMove(gameId, engine, normX, normY) {
  switch (gameId) {
    case 'connect4': {
      const col = Math.floor(normX * 7);
      const legal = engine.getLegalMoves();
      return legal.includes(col) ? col : null;
    }
    case 'chess960': {
      // Two-click: first click selects piece, second click selects destination
      const r = Math.floor(normY * 8), c = Math.floor(normX * 8);
      if (!HumanPlay._selectedSquare) {
        // First click: select a piece
        const piece = engine.board[r][c];
        const isWhite = piece > 0 && engine.turn === 'w';
        if (isWhite) {
          HumanPlay._selectedSquare = [r, c];
          _hpRender(); // Will highlight selected
          // Highlight valid destinations
          const moves = engine.getLegalMoves().filter(m => m.f[0] === r && m.f[1] === c);
          const sz = HumanPlay.canvasSize, sq = sz / 8;
          const ctx = HumanPlay.ctx;
          ctx.fillStyle = 'rgba(30, 147, 255, 0.3)';
          ctx.fillRect(c * sq, r * sq, sq, sq);
          ctx.fillStyle = 'rgba(79, 204, 48, 0.35)';
          for (const m of moves) {
            ctx.fillRect(m.t[1] * sq, m.t[0] * sq, sq, sq);
          }
          return null; // Wait for second click
        }
        return null;
      } else {
        // Second click: select destination
        const [sr, sc] = HumanPlay._selectedSquare;
        HumanPlay._selectedSquare = null;
        const move = engine.getLegalMoves().find(m => m.f[0] === sr && m.f[1] === sc && m.t[0] === r && m.t[1] === c);
        if (move) return move;
        // If clicked own piece, re-select
        const piece = engine.board[r][c];
        if (piece > 0 && engine.turn === 'w') {
          HumanPlay._selectedSquare = [r, c];
          _hpRender();
          const moves = engine.getLegalMoves().filter(m => m.f[0] === r && m.f[1] === c);
          const sz = HumanPlay.canvasSize, sq = sz / 8;
          const ctx = HumanPlay.ctx;
          ctx.fillStyle = 'rgba(30, 147, 255, 0.3)';
          ctx.fillRect(c * sq, r * sq, sq, sq);
          ctx.fillStyle = 'rgba(79, 204, 48, 0.35)';
          for (const m of moves) ctx.fillRect(m.t[1] * sq, m.t[0] * sq, sq, sq);
          return null;
        }
        return null;
      }
    }
    case 'othello': {
      const r = Math.floor(normY * 8), c = Math.floor(normX * 8);
      const legal = engine.getLegalMoves();
      const found = legal.find(m => m.r === r && m.c === c);
      return found ? { row: r, col: c } : null;
    }
    case 'go9': {
      const margin = 0.06, inner = 1 - margin * 2;
      const col = Math.round((normX - margin) / inner * 8);
      const row = Math.round((normY - margin) / inner * 8);
      if (row < 0 || row > 8 || col < 0 || col > 8) return null;
      if (!engine.isLegalMove(row, col)) return null;
      return { row, col };
    }
    case 'gomoku': {
      const bsz = engine.size;
      const margin = 0.05, inner = 1 - margin * 2;
      const col = Math.round((normX - margin) / inner * (bsz - 1));
      const row = Math.round((normY - margin) / inner * (bsz - 1));
      if (row < 0 || row >= bsz || col < 0 || col >= bsz) return null;
      if (engine.board[row][col] !== 0) return null;
      return { row, col };
    }
    case 'artillery': {
      // Click anywhere = shoot at 45 degrees, power based on click height
      const power = Math.round((1 - normY) * 100);
      const angle = Math.round(normX * 90);
      return { angle: Math.max(5, Math.min(85, angle)), power: Math.max(10, Math.min(100, power)) };
    }
    default:
      return null;
  }
}

/** Apply a human move to the engine */
function _hpApplyHumanMove(gameId, engine, move) {
  // Reuse the step engine for the "A" player side
  _arStepEngine(gameId, engine, move, null, null, null);
}


/* ── Game Over ─────────────────────────────────────────────────────────── */

function _hpGameOver() {
  HumanPlay.active = false;
  if (HumanPlay.timer) { clearTimeout(HumanPlay.timer); HumanPlay.timer = null; }
  if (HumanPlay.timerCountdown) { clearInterval(HumanPlay.timerCountdown); HumanPlay.timerCountdown = null; }

  const winner = HumanPlay.engine.winner;
  const gameId = HumanPlay.gameId;
  // Human is player A (index 0). In 2v2, human is on teamAC.
  const isWin = winner === 'A' || winner === 'teamAC';
  const isDraw = winner === 'draw' || !winner;
  let resultText;
  if (isWin) resultText = 'You Win!';
  else if (isDraw) resultText = 'Draw!';
  else if (gameId === 'snake_royale') resultText = `${winner} Wins!`;
  else if (gameId === 'snake_2v2') resultText = 'Enemy Team Wins!';
  else resultText = `${HumanPlay.aiName} Wins!`;
  const resultColor = isWin ? '#4FCC30' : isDraw ? '#e09540' : '#F93C31';

  _hpUpdateStatus(`<span style="color:${resultColor};font-size:18px;">${resultText}</span>`);
  _hpUpdateHint(`${HumanPlay.turns} turns played. <button class="ar-btn ar-btn-sm" onclick="arHumanQuit()">Back to Research</button>`);

  // Submit result to server
  const humanResult = isWin ? 'human' : isDraw ? 'draw' : 'ai';
  fetch(`/api/arena/human-play/${HumanPlay.gameId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      opponent_agent_id: AR._humanAgentId,
      delay_ms: HumanPlay.delayMs,
      winner: humanResult,
      turns: HumanPlay.turns,
      history: HumanPlay.history,
    }),
  }).then(r => r.json()).then(data => {
    if (data.error) console.warn('Human play submit error:', data.error);
  }).catch(e => console.warn('Human play submit failed:', e.message));
}


/* ── UI Helpers ─────────────────────────────────────────────────────────── */

function _hpUpdateStatus(html) {
  const el = document.getElementById('hpStatus');
  if (el) el.innerHTML = html;
}

function _hpUpdateHint(html) {
  const el = document.getElementById('hpHint');
  if (el) el.innerHTML = html;
}

function _hpGetControlHint(gameId) {
  switch (gameId) {
    case 'connect4': return 'Click a column to drop your piece (you are RED)';
    case 'chess960': return 'Click a piece, then click where to move it (you are WHITE)';
    case 'othello': return 'Click a green dot to place your piece (you are DARK)';
    case 'go9': return 'Click an intersection to place a stone (you are BLACK)';
    case 'gomoku': return 'Click to place a stone — get 5 in a row (you are BLACK)';
    case 'artillery': return 'Click to aim: X = angle (0-90), Y = power (bottom=high)';
    default: return 'Click to make your move';
  }
}
