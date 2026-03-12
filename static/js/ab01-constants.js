'use strict';

// ═══════════════════════════════════════════════════════════════
//  CONSTANTS
// ═══════════════════════════════════════════════════════════════
const W = 900, H = 500, GROUND = 440;
const GRAV = 0.38;
const SLING_X = 162, SLING_Y = 338;  // bird launch point
const MAX_PULL = 75;
const BIRD_SPEED_SCALE = 0.14;       // pull distance → launch speed

// ───── Bird type IDs ─────
const RED='red', BLU='blue', YEL='yellow', BLK='black', GRN='green';

// ───── Block type IDs ─────
const WOOD='wood', STONE='stone', ICE='ice';

// ───── ARC colour palette (for HUD) ─────
const BIRD_LABEL = {
  [RED]:'Red – Standard',
  [BLU]:'Blue – Splits into 3',
  [YEL]:'Yellow – Speed boost',
  [BLK]:'Black – Explodes',
  [GRN]:'Green – Boomerang',
};
const ABILITY_HINT = {
  [RED]:'',
  [BLU]:'Click to split into 3!',
  [YEL]:'Click to boost speed!',
  [BLK]:'Click to explode early!',
  [GRN]:'Click to boomerang!',
};

// ═══════════════════════════════════════════════════════════════
//  LEVELS  (fully hardcoded – deterministic)
// ═══════════════════════════════════════════════════════════════
// Block: [type, x, y, w, h]     Pig: [x, y, hp]
const LEVELS = [
  // ── Level 1 ─────────────────────────────────────────────────
  { birds:[RED,RED,RED],
    bg:0,
    blocks:[
      [WOOD,560,400,36,40],[WOOD,560,360,36,40],[WOOD,560,320,36,40],
      [WOOD,640,400,36,40],[WOOD,640,360,36,40],
      [WOOD,530,280,108,20],
    ],
    pigs:[[596,258,1],[640,340,1]]
  },
  // ── Level 2 ─────────────────────────────────────────────────
  { birds:[RED,RED,BLU,BLU],
    bg:1,
    blocks:[
      [WOOD,540,400,30,40],[STONE,540,360,30,40],[WOOD,540,320,30,40],
      [WOOD,620,400,30,40],[STONE,620,360,30,40],
      [ICE,580,280,30,30],[ICE,580,250,30,30],
      [WOOD,510,280,120,20],
      [WOOD,660,400,30,100],[STONE,660,300,30,100],
    ],
    pigs:[[595,228,1],[595,260,1],[675,278,2]]
  },
  // ── Level 3 ─────────────────────────────────────────────────
  { birds:[RED,YEL,YEL,BLU,RED],
    bg:2,
    blocks:[
      // Left tower
      [STONE,490,400,30,80],[STONE,490,320,30,80],
      [WOOD,522,400,30,80],[WOOD,522,320,30,80],
      [STONE,490,240,62,24],
      // Middle tower
      [WOOD,600,400,28,40],[ICE,600,360,28,40],[WOOD,600,320,28,40],
      [ICE,600,280,28,40],[WOOD,572,240,84,20],
      // Right tower
      [STONE,690,400,28,60],[WOOD,690,340,28,60],[ICE,690,280,28,60],
      [STONE,720,400,28,60],[WOOD,720,340,28,60],
      [WOOD,686,220,66,20],
    ],
    pigs:[[521,216,2],[614,216,1],[704,196,1],[705,316,1]]
  },
  // ── Level 4 ─────────────────────────────────────────────────
  { birds:[RED,YEL,BLK,BLU,BLU,RED],
    bg:1,
    blocks:[
      // Bunker left
      [STONE,480,400,100,40],[STONE,480,360,40,40],[STONE,540,360,40,40],
      [STONE,480,320,100,40],[STONE,480,280,100,28],
      // Tower mid
      [WOOD,610,400,28,120],[ICE,638,400,28,120],
      [WOOD,610,280,56,28],
      // Bunker right
      [STONE,680,400,90,40],[STONE,680,360,90,40],[STONE,680,320,90,28],
      // Plank bridge
      [WOOD,598,252,172,16],
      // Top decorations
      [ICE,620,236,30,30],[ICE,680,236,30,30],
    ],
    pigs:[[510,252,2],[625,212,1],[710,294,2],[625,254,1],[710,212,1]]
  },
  // ── Level 5 ─────────────────────────────────────────────────
  { birds:[RED,YEL,BLK,BLK,GRN,BLU,RED],
    bg:2,
    blocks:[
      // Far left pillar
      [STONE,460,400,28,120],[STONE,460,280,28,120],[STONE,460,160,28,120],
      // Left fortress
      [STONE,490,400,80,40],[WOOD,490,360,80,40],[STONE,490,320,80,40],
      [ICE,490,280,80,40],[STONE,490,240,80,28],
      // Center tower
      [STONE,600,400,30,100],[WOOD,600,300,30,100],[STONE,600,200,30,100],
      [STONE,630,400,30,100],[WOOD,630,300,30,100],[ICE,630,200,30,100],
      [STONE,598,170,64,28],
      // Right fortress
      [STONE,690,400,80,40],[WOOD,690,360,80,40],[STONE,690,320,80,40],
      [ICE,690,280,80,40],[STONE,690,240,80,28],
      // Far right pillar
      [STONE,772,400,28,120],[STONE,772,280,28,120],[STONE,772,160,28,120],
      // Roof planks
      [WOOD,488,212,174,16],[WOOD,596,142,66,16],
      // Extra blocks
      [ICE,560,360,28,40],[ICE,670,360,28,40],
    ],
    pigs:[[530,212,2],[615,142,2],[725,212,2],[615,168,1],[530,168,1],[725,168,1]]
  },
];
