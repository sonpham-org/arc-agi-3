'use strict';

// ═══════════════════════════════════════════════════════════════
//  SESSION MANAGEMENT MODULE — ab01-session.js
// ═══════════════════════════════════════════════════════════════

Game.prototype.startLevel = function(idx){
  this.levelIdx = idx;
  const ld = LEVELS[idx];
  this.state = 'playing';
  this.score = 0;
  this.particles = [];
  this.bgCache = null;
  this.postShotTimer = 0;
  this.nextBirdTimer = 0;

  // Build birds
  this.birds = ld.birds.map(t => new Bird(t));
  this.birdQueue = this.birds.map((_, i) => i);
  this.activeBirdIdx = -1;

  // Build blocks
  this.blocks = ld.blocks.map(b => new Block(b[0], b[1], b[2], b[3], b[4]));

  // Build pigs
  this.pigs = ld.pigs.map(p => new Pig(p[0], p[1], p[2]));

  this._setOverlay(null);
  this._hudLevel.textContent = `Level ${idx + 1}`;
  this._hudScore.textContent = 'Score: 0';
  this._loadNextBird();
};

Game.prototype._loadNextBird = function(){
  if (this.birdQueue.length === 0) { this.activeBirdIdx = -1; return; }
  this.activeBirdIdx = this.birdQueue.shift();
  const bird = this.birds[this.activeBirdIdx];
  bird.x = SLING_X; bird.y = SLING_Y;
  bird.active = false;
  // Queue display: position waiting birds
  this.birdQueue.forEach((bi, qi) => {
    const b = this.birds[bi];
    b.x = 80 - qi*32; b.y = GROUND - 22 - b.r;
  });
};

Game.prototype.retry = function(){ this.startLevel(this.levelIdx); };

Game.prototype.nextLevel = function(){ this.startLevel(Math.min(this.levelIdx + 1, 4)); };

Game.prototype.showMenu = function(){ 
  this.state = 'menu';
  this._setOverlay('menu');
  this._refreshLevelBtns();
};

Game.prototype._addScore = function(n){
  this.score += n;
  this._hudScore.textContent = `Score: ${this.score}`;
};

Game.prototype._showAbilityHint = function(txt){
  const el = this._abilityHint;
  el.style.opacity = txt ? '1' : '0';
  el.textContent = txt;
};

Game.prototype._checkEnd = function(){
  const alivePigs = this.pigs.filter(p => !p.destroyed);
  if (alivePigs.length === 0) {
    // Win!
    const birdsLeft = this.birdQueue.length + (this.activeBirdIdx >= 0 && !this.birds[this.activeBirdIdx].active ? 1 : 0);
    this._addScore(birdsLeft * 200);
    const stars = this.score > 4000 ? 3 : this.score > 2000 ? 2 : 1;
    this.state = 'win';
    // Unlock next
    if (this.levelIdx + 1 < 5) this.unlockedLevels = Math.max(this.unlockedLevels, this.levelIdx + 2);
    this._refreshLevelBtns();
    // Animate stars
    setTimeout(() => {
      this._setOverlay('win');
      document.getElementById('win-score').textContent = `Score: ${this.score}`;
      this._stars.forEach((s, i) => {
        s.className = 'star unlit';
        if (i < stars) {
          setTimeout(() => { s.className = 'star lit'; }, i*400 + 200);
        }
      });
      this._btnNext.style.display = this.levelIdx < 4 ? 'inline-block' : 'none';
      if (this.levelIdx === 4) {
        setTimeout(() => {
          this._setOverlay('clear');
          this.unlockedLevels = 1;
        }, 2000);
      }
    }, 1000);
    return;
  }

  // Check fail: no birds left and active bird has landed/gone
  const active = this.activeBirdIdx >= 0 ? this.birds[this.activeBirdIdx] : null;
  const flyingExtra = this.birds.some((b, i) => b.active && i !== this.activeBirdIdx);
  if (this.birdQueue.length === 0 && (!active || active.landed || active.dead) && !flyingExtra) {
    this.state = 'fail';
    setTimeout(() => this._setOverlay('fail'), 1200);
  }
};
