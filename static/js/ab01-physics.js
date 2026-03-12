'use strict';

// ═══════════════════════════════════════════════════════════════
//  PHYSICS & COLLISION MODULE — ab01-physics.js
// ═══════════════════════════════════════════════════════════════

Game.prototype._circleRect = function(cx, cy, cr, rx, ry, rw, rh){
  const nx = clamp(cx, rx, rx + rw);
  const ny = clamp(cy, ry, ry + rh);
  const dx = cx - nx, dy = cy - ny;
  return dx*dx + dy*dy < cr*cr;
};

Game.prototype._birdVsBlocks = function(bird){
  if (!bird.active) return;
  for (const blk of this.blocks) {
    if (blk.destroyed) continue;
    if (!this._circleRect(bird.x, bird.y, bird.r, blk.x, blk.y, blk.w, blk.h)) continue;

    const spd = Math.sqrt(bird.vx*bird.vx + bird.vy*bird.vy);
    const dmg = ({[WOOD]: 2, [STONE]: 1, [ICE]: 3})[blk.type];
    blk.hit(Math.ceil(spd * dmg * .18));
    if (blk.destroyed) this._spawnDestroyParticles(blk);

    // Give block impulse
    blk.vx += bird.vx * .3;
    blk.vy += bird.vy * .3;
    blk.angVel += (bird.x - blk.cx) * .01;

    // Slow bird
    bird.vx *= 0.55; bird.vy *= 0.55;

    // Damage score
    this._addScore(10);
  }
};

Game.prototype._birdVsPigs = function(bird){
  if (!bird.active) return;
  for (const pig of this.pigs) {
    if (pig.destroyed) continue;
    if (dist(bird.x, bird.y, pig.x, pig.y) > bird.r + pig.r) continue;
    const spd = Math.sqrt(bird.vx*bird.vx + bird.vy*bird.vy);
    pig.hit(Math.ceil(spd * .22));
    if (pig.destroyed) {
      this._spawnPigDeathParticles(pig);
      this._addScore(500);
    }
    bird.vx *= 0.45; bird.vy *= 0.45;
  }
};

Game.prototype._explodeBird = function(bird){
  const R = 90;
  for (const blk of this.blocks) {
    if (blk.destroyed) continue;
    if (dist(bird.x, bird.y, blk.cx, blk.cy) < R) {
      blk.hit(6);
      blk.vx += (blk.cx - bird.x) * .12;
      blk.vy += (blk.cy - bird.y) * .12 - (bird.x > blk.cx ? .2 : .2);
      blk.angVel += (blk.cx - bird.x) * .006;
      if (blk.destroyed) { this._spawnDestroyParticles(blk); this._addScore(10); }
    }
  }
  for (const pig of this.pigs) {
    if (pig.destroyed) continue;
    if (dist(bird.x, bird.y, pig.x, pig.y) < R + pig.r) {
      pig.hit(4);
      if (pig.destroyed) { this._spawnPigDeathParticles(pig); this._addScore(500); }
    }
  }
  // Explosion particles
  this._spawnExplosion(bird.x, bird.y);
  bird.life = 0;
};

Game.prototype._spawnDestroyParticles = function(blk){
  const cols = {[WOOD]: ['#a06020', '#c08030', '#603000'],
                [STONE]: ['#888', '#aaa', '#555'],
                [ICE]: ['#c0e8ff', '#90c8f0', '#ffffff']}[blk.type];
  const N = 8;
  for (let i = 0; i < N; i++) {
    const a = (i / N) * Math.PI * 2;
    const sp = 2 + i * .5;
    this.particles.push(new Particle(
      blk.cx, blk.cy,
      Math.cos(a) * sp, Math.sin(a) * sp,
      cols[i % cols.length], 40 + i*3, 4 + i*.5
    ));
  }
};

Game.prototype._spawnPigDeathParticles = function(pig){
  const N = 10;
  for (let i = 0; i < N; i++) {
    const a = (i / N) * Math.PI * 2;
    const sp = 1.5 + i * .6;
    this.particles.push(new Particle(
      pig.x, pig.y,
      Math.cos(a) * sp, Math.sin(a) * sp,
      i % 2 === 0 ? '#80e040' : '#50b020', 35 + i*2, 5
    ));
  }
};

Game.prototype._spawnExplosion = function(x, y){
  const N = 16;
  for (let i = 0; i < N; i++) {
    const a = (i / N) * Math.PI * 2;
    const sp = 3 + i * .7;
    const cols = ['#ff8800', '#ffcc00', '#ff4400', '#fff'];
    this.particles.push(new Particle(
      x, y, Math.cos(a) * sp, Math.sin(a) * sp,
      cols[i % cols.length], 50 + i, 6 + (i % 4)
    ));
  }
  // Shockwave flash particles outward
  for (let i = 0; i < 8; i++) {
    const a = (i / 8) * Math.PI * 2;
    this.particles.push(new Particle(
      x, y, Math.cos(a) * 8, Math.sin(a) * 8,
      '#ffffff', 20, 3
    ));
  }
};

Game.prototype._updatePhysics = function(){
  if (this.state !== 'playing') return;

  // Update active bird
  if (this.activeBirdIdx >= 0) {
    const bird = this.birds[this.activeBirdIdx];
    bird.update();
    this._birdVsBlocks(bird);
    this._birdVsPigs(bird);

    // Black bomb fuse
    if (bird.type === BLK && bird.active && bird.fuseTimer === 0 && !bird.abilityUsed) {
      bird.abilityUsed = true;
      this._explodeBird(bird);
    }
    // On explicit explode
    if (bird.type === BLK && bird.active && bird.abilityUsed && bird.fuseTimer === 1 && !bird.dead) {
      this._explodeBird(bird);
    }

    if (bird.dead || bird.landed) {
      this.postShotTimer--;
      if (this.postShotTimer <= 0) {
        this._showAbilityHint('');
        this._loadNextBird();
        this._checkEnd();
      }
    }
  }

  // Update extra birds (blue splits etc.)
  for (let i = 0; i < this.birds.length; i++) {
    if (i === this.activeBirdIdx) continue;
    const b = this.birds[i];
    if (!b.active || b.dead) continue;
    b.update();
    this._birdVsBlocks(b);
    this._birdVsPigs(b);
    if (b.type === BLK && b.fuseTimer === 0 && !b.abilityUsed) {
      b.abilityUsed = true; this._explodeBird(b);
    }
  }

  // Blocks: apply velocity (knocked blocks slide a bit)
  for (const blk of this.blocks) {
    if (blk.destroyed) continue;
    blk.vy += GRAV * .6;
    blk.angle += blk.angVel;
    blk.angVel *= 0.92;
    blk.x += blk.vx; blk.y += blk.vy;
    blk.vx *= 0.85;
    // Ground
    if (blk.y + blk.h >= GROUND) { blk.y = GROUND - blk.h; blk.vy *= -.15; blk.vx *= .8; blk.angVel *= .6; }
  }

  // Particles
  this.particles = this.particles.filter(p => { p.update(); return !p.dead; });

  // Pigs: simple gravity if not on ground
  for (const pig of this.pigs) {
    if (pig.destroyed) continue;
    if (pig.y + pig.r < GROUND) { pig.y = Math.min(pig.y + GRAV*2, GROUND - pig.r); }
  }
};
