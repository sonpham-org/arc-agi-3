'use strict';

// ═══════════════════════════════════════════════════════════════
//  RENDERING MODULE — ab01-render.js
// ═══════════════════════════════════════════════════════════════

// Add render methods to Game prototype
Game.prototype._drawBG = function(){
  const ctx = this.ctx;
  const lvl = this.levelIdx;
  
  // Sky gradient
  const sky = ctx.createLinearGradient(0, 0, 0, H);
  if (lvl === 2) {
    sky.addColorStop(0, '#ff9a3c');  // sunset
    sky.addColorStop(.45, '#ff6b6b');
    sky.addColorStop(1, '#2a1a3a');
  } else {
    sky.addColorStop(0, '#1e90ff');
    sky.addColorStop(.6, '#87ceeb');
    sky.addColorStop(1, '#c9e8ff');
  }
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, W, H);

  // Clouds (fixed positions)
  ctx.fillStyle = 'rgba(255,255,255,0.82)';
  [[120,80,55,30],[280,55,70,35],[500,90,60,28],[720,65,80,38],[830,100,50,25]].forEach(([cx,cy,rw,rh]) => {
    ctx.beginPath();
    ctx.ellipse(cx, cy, rw, rh, 0, 0, Math.PI*2);
    ctx.fill();
    ctx.beginPath();
    ctx.ellipse(cx - rw*.4, cy + rh*.3, rw*.6, rh*.7, 0, 0, Math.PI*2);
    ctx.fill();
    ctx.beginPath();
    ctx.ellipse(cx + rw*.4, cy + rh*.3, rw*.6, rh*.7, 0, 0, Math.PI*2);
    ctx.fill();
  });

  // Mountains
  ctx.fillStyle = lvl === 2 ? '#6a3a2a' : '#5a8a3a';
  [[200, GROUND-60, 150], [450, GROUND-90, 200], [700, GROUND-50, 180]].forEach(([mx, my, mw]) => {
    ctx.beginPath();
    ctx.moveTo(mx - mw/2, GROUND);
    ctx.lineTo(mx, my);
    ctx.lineTo(mx + mw/2, GROUND);
    ctx.closePath();
    ctx.fill();
  });
  
  // Mountain highlights
  ctx.fillStyle = lvl === 2 ? '#a06a4a' : '#7ab05a';
  [[200, GROUND-60, 50], [450, GROUND-90, 70], [700, GROUND-50, 55]].forEach(([mx, my, mw]) => {
    ctx.beginPath();
    ctx.moveTo(mx, my);
    ctx.lineTo(mx + mw/2, GROUND);
    ctx.lineTo(mx, GROUND);
    ctx.closePath();
    ctx.fill();
  });

  // Ground
  const grd = ctx.createLinearGradient(0, GROUND, 0, H);
  grd.addColorStop(0, '#5a9a30');
  grd.addColorStop(.08, '#4a8a20');
  grd.addColorStop(1, '#3a6a18');
  ctx.fillStyle = grd;
  ctx.fillRect(0, GROUND, W, H - GROUND);

  // Ground edge highlight
  ctx.fillStyle = '#70c040';
  ctx.fillRect(0, GROUND, W, 5);
};

Game.prototype._drawWorld = function(){
  const ctx = this.ctx;

  // Slingshot
  this._drawSlingshot();

  // Blocks
  for (const blk of this.blocks) blk.draw(ctx);

  // Pigs
  for (const pig of this.pigs) pig.draw(ctx);

  // Particles
  for (const p of this.particles) p.draw(ctx);

  // Queued birds (not yet launched)
  this.birdQueue.forEach((bi, qi) => {
    const b = this.birds[bi];
    const qx = 80 - qi*30, qy = GROUND - b.r - 4;
    b.x = qx; b.y = qy;
    b.draw(ctx);
  });

  // Active bird
  if (this.activeBirdIdx >= 0) {
    const bird = this.birds[this.activeBirdIdx];
    // Draw trajectory preview
    if (!bird.active && this.dragging && this.aimPreview.length > 0) {
      ctx.save();
      ctx.setLineDash([6, 8]);
      ctx.strokeStyle = 'rgba(255,255,255,0.55)';
      ctx.lineWidth = 2;
      ctx.beginPath();
      this.aimPreview.forEach((p, i) => {
        i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y);
      });
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.restore();
    }
    bird.draw(ctx);

    // Draw slingshot elastic when aiming
    if (!bird.active) {
      this._drawElastic(bird.x, bird.y);
    }
  }

  // Extra birds (split)
  for (let i = 0; i < this.birds.length; i++) {
    if (i === this.activeBirdIdx) continue;
    const b = this.birds[i];
    if (b.active && !b.dead) b.draw(ctx);
  }
};

Game.prototype._drawSlingshot = function(){
  const ctx = this.ctx;
  const sx = SLING_X, groundY = GROUND;

  // Posts
  ctx.save();
  ctx.strokeStyle = '#6b3a10';
  ctx.lineWidth = 10;
  ctx.lineCap = 'round';

  // Left fork
  ctx.beginPath();
  ctx.moveTo(sx - 22, groundY);
  ctx.lineTo(sx - 8, SLING_Y - 18);
  ctx.stroke();
  // Right fork
  ctx.beginPath();
  ctx.moveTo(sx + 22, groundY);
  ctx.lineTo(sx + 8, SLING_Y - 18);
  ctx.stroke();

  // Fork tips
  ctx.fillStyle = '#4a2808';
  ctx.beginPath(); ctx.arc(sx - 8, SLING_Y - 18, 6, 0, Math.PI*2); ctx.fill();
  ctx.beginPath(); ctx.arc(sx + 8, SLING_Y - 18, 6, 0, Math.PI*2); ctx.fill();

  // Main trunk
  ctx.beginPath();
  ctx.moveTo(sx, groundY);
  ctx.lineTo(sx, SLING_Y + 10);
  ctx.strokeStyle = '#8b4a15';
  ctx.lineWidth = 12;
  ctx.stroke();

  // Highlight
  ctx.beginPath();
  ctx.moveTo(sx + 2, groundY);
  ctx.lineTo(sx + 2, SLING_Y + 10);
  ctx.strokeStyle = 'rgba(255,200,100,.3)';
  ctx.lineWidth = 4;
  ctx.stroke();

  ctx.restore();
};

Game.prototype._drawElastic = function(bx, by){
  const ctx = this.ctx;
  const lx = SLING_X - 8, ly = SLING_Y - 18;
  const rx = SLING_X + 8, ry = SLING_Y - 18;

  ctx.save();
  ctx.strokeStyle = '#8b6914';
  ctx.lineWidth = 3;
  ctx.lineCap = 'round';

  // Left band: fork tip -> bird -> mid
  ctx.beginPath();
  ctx.moveTo(lx, ly);
  ctx.lineTo(bx, by);
  ctx.stroke();

  // Right band: fork tip -> bird
  ctx.beginPath();
  ctx.moveTo(rx, ry);
  ctx.lineTo(bx, by);
  ctx.stroke();

  ctx.restore();
};
