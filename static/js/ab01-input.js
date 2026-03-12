'use strict';

// ═══════════════════════════════════════════════════════════════
//  INPUT HANDLING MODULE — ab01-input.js
// ═══════════════════════════════════════════════════════════════

Game.prototype._bindInput = function(){
  const cv = this.canvas;
  cv.addEventListener('mousedown', e => this._onDown(e.offsetX, e.offsetY));
  cv.addEventListener('mousemove', e => this._onMove(e.offsetX, e.offsetY));
  cv.addEventListener('mouseup', e => this._onUp(e.offsetX, e.offsetY));
  cv.addEventListener('touchstart', e => { e.preventDefault(); const t = this._touch(e); this._onDown(t.x, t.y); }, {passive: false});
  cv.addEventListener('touchmove', e => { e.preventDefault(); const t = this._touch(e); this._onMove(t.x, t.y); }, {passive: false});
  cv.addEventListener('touchend', e => { e.preventDefault(); const t = this._touch(e); this._onUp(t.x, t.y); }, {passive: false});
};

Game.prototype._touch = function(e){
  const r = this.canvas.getBoundingClientRect();
  const t = e.changedTouches[0] || e.touches[0];
  const scaleX = W / r.width, scaleY = H / r.height;
  return {x: (t.clientX - r.left) * scaleX, y: (t.clientY - r.top) * scaleY};
};

Game.prototype._onDown = function(x, y){
  if (this.state !== 'playing') return;
  if (this.activeBirdIdx < 0) return;
  const bird = this.birds[this.activeBirdIdx];
  if (bird.active) {
    // In-flight: trigger ability
    const extras = bird.useAbility();
    if (extras) this.birds.push(...extras);
    this._showAbilityHint('');
  } else {
    // On slingshot: start drag
    const d = dist(x, y, SLING_X, SLING_Y);
    if (d < 50) { this.dragging = true; this.dragX = x; this.dragY = y; }
  }
};

Game.prototype._onMove = function(x, y){
  if (!this.dragging) return;
  const dx = x - SLING_X, dy = y - SLING_Y;
  const d = Math.min(Math.sqrt(dx*dx + dy*dy), MAX_PULL);
  const a = Math.atan2(dy, dx);
  this.pullX = Math.cos(a) * d;
  this.pullY = Math.sin(a) * d;
  this._calcPreview();
};

Game.prototype._onUp = function(x, y){
  if (!this.dragging) return;
  this.dragging = false;
  const d = Math.sqrt(this.pullX*this.pullX + this.pullY*this.pullY);
  if (d < 8) { this.pullX = 0; this.pullY = 0; this.aimPreview = []; return; }
  const vx = -this.pullX * BIRD_SPEED_SCALE;
  const vy = -this.pullY * BIRD_SPEED_SCALE;
  const bird = this.birds[this.activeBirdIdx];
  bird.x = SLING_X; bird.y = SLING_Y;
  bird.launch(vx, vy);
  this.pullX = 0; this.pullY = 0; this.aimPreview = [];
  this._showAbilityHint(ABILITY_HINT[bird.type]);
  this.postShotTimer = 180;
};

Game.prototype._calcPreview = function(){
  const vx = -this.pullX * BIRD_SPEED_SCALE;
  const vy = -this.pullY * BIRD_SPEED_SCALE;
  const pts = [];
  let px = SLING_X, py = SLING_Y, pvx = vx, pvy = vy;
  for (let i = 0; i < 120; i += 2) {
    pvy += GRAV; px += pvx; py += pvy;
    if (i % 6 === 0) pts.push({x: px, y: py});
    if (py > GROUND || px > W + 50 || px < -50) break;
  }
  this.aimPreview = pts;
};
