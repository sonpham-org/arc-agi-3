// Author: Claude Opus 4.6
// Date: 2026-03-16 01:00
// PURPOSE: Arena Auto Research — in-browser evolution + tournament engine.
//   Phase 2: headless match runner, per-game state adapters, live tournament canvases.
//   Phase 4: human vs AI play mode — keyboard/click input, timed moves, result submission.
//   Evolution: LLM tool-calling loop generates JS agents using BYOK API keys.
//   Tournament: runs game matches headlessly via game engine classes from arena.js.
//   Swiss matchmaking, ELO tracking, agent validation, safety sandbox.
//   Text-based tool calling (XML tags) for cross-provider compatibility.
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
  // state.board: 8x8 (positive=white, negative=black, 1=pawn,2=knight,3=bishop,4=rook,5=queen,6=king)
  // state.myColor: 'w'|'b', state.validMoves: [{from:'e2',to:'e4'},...],
  // state.turn: int, state.memory: {}
  // Return: {from: 'e2', to: 'e4'}
  return state.validMoves[0];
}`,
  othello: `
function getMove(state) {
  // state.board: 8x8 (0=empty, 1=me, 2=opponent)
  // state.validMoves: [{row,col},...], state.turn: int, state.memory: {}
  // Return: {row, col}
  return state.validMoves[0];
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
  const st = engine.getAIState();
  const isA = player === 'A';
  return {
    grid: engine.getGrid(),
    mySnake: isA ? st.snakeA : st.snakeB,
    enemySnake: isA ? st.snakeB : st.snakeA,
    food: st.food,
    turn: st.turn,
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
    case 'snake': return _arSnakeState(engine, player, memory);
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
  switch (gameId) {
    case 'snake': return new SnakeGame(config);
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
  return gameId === 'snake' || gameId === 'tron';
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
    case 'snake': {
      const dirA = _arParseDir(rawMoveA);
      const dirB = _arParseDir(rawMoveB);
      engine.step(dirA, dirB);
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
    history.push({ turn: 0, grid: engine.getGrid(), winner: null });
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
        history.push({
          turn: turnCount, grid: engine.getGrid(),
          moveA: result.moveA, moveB: result.moveB,
          winner: engine.winner,
        });
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
  LocalResearch.liveMatches = seedResults.filter(r => r.history).slice(-4);
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
    LocalResearch.liveMatches = results.filter(r => r.history).slice(-4);
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
  const seeds = _AR_SEED_AGENTS[gameId];
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
  document.getElementById('arCodeModalCode').textContent = agent.code;
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
          contributor: 'local_research',
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

function arRenderLiveCanvases() {
  // Stop existing animations
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
      ctx.fillStyle = '#1a1a2e';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = '#555';
      ctx.font = '11px monospace';
      ctx.textAlign = 'center';
      ctx.fillText('Waiting...', canvas.width / 2, canvas.height / 2);
      info.textContent = '';
      continue;
    }

    info.textContent = `${match.agent1} vs ${match.agent2} — ${match.winner}`;

    // Animate through history frames
    let frameIdx = 0;
    const history = match.history;
    const gameId = match.gameId || LocalResearch.gameId;

    // Render one frame
    const renderFrame = () => {
      const frame = history[frameIdx];
      if (!frame) return;
      _arRenderMiniFrame(canvas, gameId, frame);
      frameIdx = (frameIdx + 1) % history.length;
    };

    renderFrame();
    const timer = setInterval(renderFrame, 200);
    LocalResearch.liveTimers.push(timer);
  }
}

function _arRenderMiniFrame(canvas, gameId, frame) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;

  // Get grid data from the frame
  const grid = frame.grid || frame.board;
  if (!grid || !grid.length) {
    // For games with state objects (artillery), render a simple indicator
    ctx.fillStyle = '#1a1a2e';
    ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = frame.winner ? '#4FCC30' : '#e09540';
    ctx.font = '10px monospace';
    ctx.textAlign = 'center';
    ctx.fillText(`Turn ${frame.turn || 0}`, w / 2, h / 2 - 6);
    if (frame.move) ctx.fillText(String(frame.move).substring(0, 20), w / 2, h / 2 + 8);
    return;
  }

  const rows = grid.length, cols = grid[0].length;
  const cellW = w / cols, cellH = h / rows;

  // Tron raw grid: 0=empty, 1=A_trail, 2=B_trail, 3=A_head, 4=B_head
  const TRON_COLORS = { 0: '#000000', 1: '#88D8F1', 2: '#FF851B', 3: '#1E93FF', 4: '#F93C31' };

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const val = grid[r][c];
      if (gameId === 'snake') {
        // Snake grid uses ARC3 color indices directly
        ctx.fillStyle = ARC3[val] || ARC3[5];
      } else if (gameId === 'tron') {
        ctx.fillStyle = TRON_COLORS[val] || '#000000';
      } else {
        // Board games: 0=empty, 1=playerA, -1/2=playerB
        if (val === 0) ctx.fillStyle = '#1a1a2e';
        else if (val === 1) ctx.fillStyle = '#F93C31';
        else if (val === -1 || val === 2) ctx.fillStyle = '#e09540';
        else ctx.fillStyle = '#333';
      }
      ctx.fillRect(c * cellW, r * cellH, cellW + 0.5, cellH + 0.5);
    }
  }
}


/* ═══════════════════════════════════════════════════════════════════════════
   Human vs AI Play — Phase 4
   ═══════════════════════════════════════════════════════════════════════════ */

const HumanPlay = {
  active: false,
  gameId: null,
  engine: null,
  aiFn: null,
  aiName: '',
  aiMemory: {},
  humanMemory: {},
  delayMs: 1000,       // time limit per human move (0 = infinite)
  timer: null,          // game loop interval (simultaneous games)
  timerCountdown: null, // countdown display interval
  moveDeadline: 0,      // timestamp when current move times out
  humanDir: null,        // buffered direction for simultaneous games
  turns: 0,
  canvas: null,
  ctx: null,
  canvasSize: 480,
  _keyHandler: null,
  _clickHandler: null,
};

/** Launch human vs AI play session. Called from arStartHumanPlay() in arena.js */
function arLaunchHumanPlay(gameId, agentCode, agentName, delayMs) {
  if (gameId === 'poker') {
    alert('Poker human play is not yet supported.');
    return;
  }

  const aiFn = arCreateAgentFn(agentCode);
  if (!aiFn) { alert('Failed to load AI agent code.'); return; }

  const game = ARENA_GAMES.find(g => g.id === gameId);
  if (!game) return;

  // Init state
  HumanPlay.active = true;
  HumanPlay.gameId = gameId;
  HumanPlay.engine = _arNewEngine(gameId, game.config);
  HumanPlay.aiFn = aiFn;
  HumanPlay.aiName = agentName;
  HumanPlay.aiMemory = {};
  HumanPlay.humanMemory = {};
  HumanPlay.delayMs = delayMs;
  HumanPlay.turns = 0;
  HumanPlay.humanDir = null;

  // Build UI in arCenter
  const center = document.getElementById('arCenter');
  const sz = HumanPlay.canvasSize;

  center.innerHTML = `
    <div class="ar-section-header">
      <span>You vs ${escHtml(agentName)}</span>
      <div>
        <span class="ar-human-timer-badge" id="hpTimer">${delayMs ? delayMs + 'ms' : 'No limit'}</span>
        <button class="ar-btn ar-btn-sm" onclick="arHumanQuit()">Quit</button>
      </div>
    </div>
    <div style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;overflow:hidden;padding:12px;">
      <canvas id="hpCanvas" width="${sz}" height="${sz}" style="image-rendering:pixelated;border:2px solid var(--border);border-radius:4px;max-width:100%;max-height:calc(100vh - 200px);cursor:${_arIsSimultaneous(gameId) ? 'default' : 'pointer'};"></canvas>
      <div id="hpStatus" style="margin-top:8px;font-size:13px;font-weight:600;color:var(--text);"></div>
      <div id="hpHint" style="font-size:11px;color:var(--text-dim);margin-top:4px;"></div>
    </div>
  `;

  HumanPlay.canvas = document.getElementById('hpCanvas');
  HumanPlay.ctx = HumanPlay.canvas.getContext('2d');

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
  if (HumanPlay.timer) { clearInterval(HumanPlay.timer); HumanPlay.timer = null; }
  if (HumanPlay.timerCountdown) { clearInterval(HumanPlay.timerCountdown); HumanPlay.timerCountdown = null; }
  if (HumanPlay._keyHandler) { document.removeEventListener('keydown', HumanPlay._keyHandler); HumanPlay._keyHandler = null; }
  if (HumanPlay._clickHandler && HumanPlay.canvas) { HumanPlay.canvas.removeEventListener('click', HumanPlay._clickHandler); HumanPlay._clickHandler = null; }

  // Restore research view
  const gameId = AR.selectedGame || HumanPlay.gameId;
  if (gameId) arSelectGame(gameId, 'community');
  else {
    const center = document.getElementById('arCenter');
    if (center) center.innerHTML = '<div class="ar-no-data">Select a game to begin</div>';
  }
}


/* ── Render ─────────────────────────────────────────────────────────────── */

function _hpRender() {
  const { gameId, engine, ctx, canvasSize: sz } = HumanPlay;
  if (!engine || !ctx) return;

  // Build a frame object matching what the arena render functions expect
  const frame = _hpBuildFrame(gameId, engine);
  const game = ARENA_GAMES.find(g => g.id === gameId);
  if (game && game.render) {
    game.render(ctx, frame, sz);
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
    case 'snake': return { grid: engine.getGrid() };
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

  // Default human direction = current snake/tron direction
  if (gameId === 'snake') HumanPlay.humanDir = engine.snakeA.dir;
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
  _hpUpdateHint(gameId === 'snake' ? 'You are the BLUE snake (left side)' : 'You are BLUE (left side)');

  // Start game loop after 1s
  setTimeout(() => {
    if (!HumanPlay.active) return;
    const tickRate = delayMs > 0 ? Math.max(delayMs, 150) : 200;
    HumanPlay.timer = setInterval(() => {
      if (!HumanPlay.active || engine.over) {
        clearInterval(HumanPlay.timer);
        HumanPlay.timer = null;
        if (engine.over) _hpGameOver();
        return;
      }

      // Build AI state and get AI move
      const aiState = _arBuildState(gameId, engine, 'B', HumanPlay.aiMemory);
      const aiRaw = arSafeCall(HumanPlay.aiFn, aiState, 50);
      const aiDir = _arParseDir(aiRaw);

      // Step engine with human's buffered direction + AI direction
      engine.step(HumanPlay.humanDir, aiDir);
      HumanPlay.turns++;

      _hpRender();
      _hpUpdateStatus(`Turn ${HumanPlay.turns} | You: ${_AR_DIR_NAMES[HumanPlay.humanDir]} | AI: ${_AR_DIR_NAMES[aiDir]}`);
    }, tickRate);
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
    _hpRender();
    _hpUpdateStatus(`Turn ${HumanPlay.turns} | Timeout — random move played`);
    if (engine.over) { _hpGameOver(); return; }
    _hpDoAiTurn();
  }
}

function _hpDoAiTurn() {
  const { gameId, engine } = HumanPlay;
  if (engine.over) { _hpGameOver(); return; }

  // Check if it's actually AI's turn (for games like Othello where passing happens)
  if (_arWhoseTurn(gameId, engine) !== 'B') {
    _hpStartHumanTurn();
    return;
  }

  _hpUpdateStatus(`Turn ${HumanPlay.turns + 1} | AI thinking...`);

  // Small delay so human can see the "thinking" state
  setTimeout(() => {
    if (!HumanPlay.active || engine.over) return;
    const aiState = _arBuildState(gameId, engine, 'B', HumanPlay.aiMemory);
    const raw = arSafeCall(HumanPlay.aiFn, aiState, 50);
    _arStepEngine(gameId, engine, raw, null, aiState, null);
    HumanPlay.turns++;
    _hpRender();

    if (engine.over) { _hpGameOver(); return; }

    // Back to human
    _hpStartHumanTurn();
  }, 300);
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
  if (HumanPlay.timer) { clearInterval(HumanPlay.timer); HumanPlay.timer = null; }
  if (HumanPlay.timerCountdown) { clearInterval(HumanPlay.timerCountdown); HumanPlay.timerCountdown = null; }

  const winner = HumanPlay.engine.winner;
  const isWin = winner === 'A';
  const isDraw = winner === 'draw' || !winner;
  const resultText = isWin ? 'You Win!' : isDraw ? 'Draw!' : `${HumanPlay.aiName} Wins!`;
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
