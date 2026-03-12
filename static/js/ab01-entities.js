'use strict';

// ═══════════════════════════════════════════════════════════════
//  UTILITY
// ═══════════════════════════════════════════════════════════════
function clamp(v,lo,hi){return v<lo?lo:v>hi?hi:v}
function dist(ax,ay,bx,by){const dx=ax-bx,dy=ay-by;return Math.sqrt(dx*dx+dy*dy)}
function lerp(a,b,t){return a+(b-a)*t}

// ═══════════════════════════════════════════════════════════════
//  BIRD
// ═══════════════════════════════════════════════════════════════
class Bird {
  constructor(type){
    this.type=type;
    this.x=0; this.y=0;
    this.vx=0; this.vy=0;
    this.r=this.baseRadius();
    this.active=false;  // in-flight
    this.landed=false;
    this.abilityUsed=false;
    this.life=300;       // frames before removed
    this.trail=[];
    this.angryEye=false;
    this.scale=1;
    this.alpha=1;
    // For black: countdown before forced explode
    this.fuseTimer=0;
  }

  baseRadius(){
    return {[RED]:16,[BLU]:11,[YEL]:14,[BLK]:19,[GRN]:15}[this.type];
  }

  launch(vx,vy){
    this.vx=vx; this.vy=vy;
    this.active=true; this.angryEye=true;
    if(this.type===BLK) this.fuseTimer=90; // ~1.5s
  }

  // Returns list of new birds if ability splits; otherwise null
  useAbility(){
    if(this.abilityUsed||!this.active) return null;
    this.abilityUsed=true;
    switch(this.type){
      case BLU:{
        const speed=Math.sqrt(this.vx*this.vx+this.vy*this.vy);
        const a=Math.atan2(this.vy,this.vx);
        const spread=0.35;
        const b1=new Bird(BLU); b1.x=this.x; b1.y=this.y;
        b1.vx=Math.cos(a-spread)*speed; b1.vy=Math.sin(a-spread)*speed;
        b1.active=true; b1.angryEye=true; b1.abilityUsed=true;
        const b2=new Bird(BLU); b2.x=this.x; b2.y=this.y;
        b2.vx=Math.cos(a+spread)*speed; b2.vy=Math.sin(a+spread)*speed;
        b2.active=true; b2.angryEye=true; b2.abilityUsed=true;
        // Main bird continues straight
        return [b1,b2];
      }
      case YEL:{
        const speed=Math.sqrt(this.vx*this.vx+this.vy*this.vy);
        const a=Math.atan2(this.vy,this.vx);
        this.vx=Math.cos(a)*speed*2.2;
        this.vy=Math.sin(a)*speed*2.2;
        return null;
      }
      case BLK:
        this.fuseTimer=1; // explode next frame
        return null;
      case GRN:
        this.vx=-this.vx*0.9;
        this.vy=-Math.abs(this.vy)*0.6;
        return null;
      default: return null;
    }
  }

  update(){
    if(!this.active) return;
    this.vy+=GRAV;
    this.x+=this.vx; this.y+=this.vy;

    // Trail
    this.trail.push({x:this.x,y:this.y});
    if(this.trail.length>28) this.trail.shift();

    // Black bird fuse
    if(this.type===BLK&&this.fuseTimer>0){
      this.fuseTimer--;
    }

    // Ground
    if(this.y+this.r>=GROUND){
      this.y=GROUND-this.r;
      this.vy*=-0.28;
      this.vx*=0.72;
      if(Math.abs(this.vy)<1.5){this.vy=0;this.landed=true;}
    }

    // Off-screen left
    if(this.x<-100) this.life=0;
    if(!this.landed) this.life--;
    else this.life-=3;
  }

  get dead(){return this.life<=0;}

  drawBody(ctx){
    const r=this.r;
    ctx.save();
    ctx.translate(this.x,this.y);
    if(this.active){
      const a=Math.atan2(this.vy,this.vx);
      ctx.rotate(a*0.25);
    }

    // Shadow
    ctx.beginPath();
    ctx.ellipse(r*0.15,r*0.5,r*0.9,r*0.3,0,0,Math.PI*2);
    ctx.fillStyle='rgba(0,0,0,0.18)';
    ctx.fill();

    // Body gradient
    ctx.beginPath();
    ctx.arc(0,0,r,0,Math.PI*2);
    const g=ctx.createRadialGradient(-r*.35,-r*.35,r*.08,r*.1,r*.1,r*1.1);
    const cols={
      [RED]:['#ff7070','#cc0000'],
      [BLU]:['#6ab0ff','#1a55cc'],
      [YEL]:['#ffe566','#cc8800'],
      [BLK]:['#888','#111'],
      [GRN]:['#80ef60','#1a7a00'],
    }[this.type];
    g.addColorStop(0,cols[0]);
    g.addColorStop(1,cols[1]);
    ctx.fillStyle=g;
    ctx.fill();
    ctx.strokeStyle='rgba(0,0,0,.25)';
    ctx.lineWidth=1.5;
    ctx.stroke();

    // Feather/crest detail
    if(this.type===RED||this.type===YEL){
      ctx.beginPath();
      ctx.moveTo(-r*.1,-r);
      ctx.lineTo(-r*.3,-r*1.35);
      ctx.lineTo(0,-r*1.1);
      ctx.lineTo(r*.1,-r*1.4);
      ctx.lineTo(r*.2,-r*1.0);
      ctx.fillStyle=cols[0];
      ctx.fill();
    }
    if(this.type===GRN){
      ctx.beginPath();
      ctx.moveTo(0,-r);
      ctx.lineTo(-r*.2,-r*1.3);
      ctx.lineTo(r*.2,-r*1.3);
      ctx.closePath();
      ctx.fillStyle='#a0ff70';
      ctx.fill();
    }

    // Eye whites
    ctx.beginPath();
    ctx.arc(r*.28,-r*.18,r*.28,0,Math.PI*2);
    ctx.fillStyle='#fff';
    ctx.fill();

    // Pupil (angry if active)
    const pup={x:r*.32+(this.angryEye?.04:0),y:-r*.12};
    ctx.beginPath();
    ctx.arc(pup.x,pup.y,r*.13,0,Math.PI*2);
    ctx.fillStyle='#111';
    ctx.fill();
    // Angry eyebrow
    if(this.angryEye){
      ctx.beginPath();
      ctx.moveTo(r*.02,-r*.42);
      ctx.lineTo(r*.58,-r*.32);
      ctx.strokeStyle='#222';
      ctx.lineWidth=2.5;
      ctx.stroke();
    }

    // Beak
    ctx.beginPath();
    ctx.moveTo(r*.5,r*.05);
    ctx.lineTo(r*.9,r*.0);
    ctx.lineTo(r*.5,r*.2);
    ctx.closePath();
    ctx.fillStyle='#ffb300';
    ctx.fill();

    // Black bird fuse spark
    if(this.type===BLK&&this.fuseTimer>0){
      const sz=this.fuseTimer>30?4:2;
      ctx.beginPath();
      ctx.arc(0,-r,sz,0,Math.PI*2);
      ctx.fillStyle=this.fuseTimer%6<3?'#fff':'#ff8800';
      ctx.fill();
    }

    ctx.restore();
  }

  draw(ctx){
    // Trail
    for(let i=0;i<this.trail.length;i++){
      const t=this.trail[i];
      const a=(i/this.trail.length)*0.45;
      ctx.beginPath();
      ctx.arc(t.x,t.y,this.r*.28*(i/this.trail.length),0,Math.PI*2);
      ctx.fillStyle=`rgba(255,255,255,${a})`;
      ctx.fill();
    }
    ctx.globalAlpha=this.alpha;
    this.drawBody(ctx);
    ctx.globalAlpha=1;
  }
}

// ═══════════════════════════════════════════════════════════════
//  BLOCK
// ═══════════════════════════════════════════════════════════════
class Block {
  constructor(type,x,y,w,h){
    this.type=type;
    this.x=x; this.y=y; this.w=w; this.h=h;
    this.maxHp=this.hp=({[WOOD]:4,[STONE]:9,[ICE]:2})[type];
    this.vx=0; this.vy=0;
    this.angle=0; this.angVel=0;
    this.destroyed=false;
    this.crumble=0; // countdown for death animation
  }

  get cx(){return this.x+this.w/2}
  get cy(){return this.y+this.h/2}
  get right(){return this.x+this.w}
  get bottom(){return this.y+this.h}

  hit(dmg){
    if(this.destroyed) return;
    this.hp-=dmg;
    if(this.hp<=0){this.hp=0;this.destroyed=true;this.crumble=25;}
  }

  draw(ctx){
    if(this.destroyed&&this.crumble<=0) return;
    ctx.save();
    if(this.destroyed) ctx.globalAlpha=this.crumble/25;

    ctx.translate(this.cx,this.cy);
    ctx.rotate(this.angle);
    const hw=this.w/2, hh=this.h/2;

    // Colours per type
    const C={
      [WOOD]:{m:'#a0622a',hi:'#c8812e',sh:'#5a3200',grain:true},
      [STONE]:{m:'#8a8a8a',hi:'#b0b0b0',sh:'#444',grain:false},
      [ICE]:{m:'#a8d8f0',hi:'#d8f0ff',sh:'#70b0d8',grain:false},
    }[this.type];

    // Shadow
    ctx.fillStyle='rgba(0,0,0,.2)';
    ctx.fillRect(-hw+3,-hh+3,this.w,this.h);

    // Body
    ctx.fillStyle=C.m;
    ctx.fillRect(-hw,-hh,this.w,this.h);

    // Highlight edge
    ctx.fillStyle=C.hi;
    ctx.fillRect(-hw,-hh,this.w*0.16,this.h);
    ctx.fillRect(-hw,-hh,this.w,this.h*0.16);

    // Shadow edge
    ctx.fillStyle=C.sh;
    ctx.fillRect(hw-this.w*.16,-hh,this.w*.16,this.h);
    ctx.fillRect(-hw,hh-this.h*.16,this.w,this.h*.16);

    // Wood grain
    if(C.grain){
      ctx.strokeStyle='rgba(60,30,0,.3)';
      ctx.lineWidth=1;
      for(let gx=-hw+8;gx<hw;gx+=10){
        ctx.beginPath();ctx.moveTo(gx,-hh);ctx.lineTo(gx,hh);ctx.stroke();
      }
    }
    // Ice shine
    if(this.type===ICE){
      ctx.fillStyle='rgba(255,255,255,.35)';
      ctx.beginPath();
      ctx.moveTo(-hw+2,-hh+2);
      ctx.lineTo(-hw+hw*.4,-hh+2);
      ctx.lineTo(-hw+2,-hh+hh*.4);
      ctx.closePath();
      ctx.fill();
    }

    // Cracks
    const hp01=this.hp/this.maxHp;
    if(hp01<0.85){
      ctx.strokeStyle='rgba(0,0,0,.55)';
      ctx.lineWidth=1;
      ctx.beginPath();ctx.moveTo(-hw*.3,-hh*.5);ctx.lineTo(hw*.1,hh*.35);ctx.stroke();
    }
    if(hp01<0.55){
      ctx.beginPath();ctx.moveTo(hw*.2,-hh*.7);ctx.lineTo(-hw*.4,hh*.55);ctx.stroke();
      ctx.beginPath();ctx.moveTo(-hw*.6,-hh*.1);ctx.lineTo(hw*.5,hh*.2);ctx.stroke();
    }
    if(hp01<0.25){
      ctx.beginPath();ctx.moveTo(hw*.4,-hh*.3);ctx.lineTo(-hw*.2,hh*.6);ctx.stroke();
      ctx.beginPath();ctx.moveTo(-hw*.8,hh*.4);ctx.lineTo(hw*.1,-hh*.8);ctx.stroke();
    }

    ctx.restore();
    if(this.destroyed) ctx.globalAlpha=1;
    if(this.crumble>0) this.crumble--;
  }
}

// ═══════════════════════════════════════════════════════════════
//  PIG
// ═══════════════════════════════════════════════════════════════
class Pig {
  constructor(x,y,hp){
    this.x=x; this.y=y; this.r=18; this.hp=hp; this.maxHp=hp;
    this.destroyed=false;
    this.hitFlash=0;
    this.dieAnim=0;
  }
  hit(dmg){
    this.hp-=dmg;
    this.hitFlash=14;
    if(this.hp<=0){this.hp=0;this.destroyed=true;this.dieAnim=30;}
  }
  draw(ctx){
    if(this.destroyed&&this.dieAnim<=0) return;
    ctx.save();
    ctx.translate(this.x,this.y);
    if(this.destroyed){
      const s=this.dieAnim/30;
      ctx.scale(s,s);
      ctx.globalAlpha=s;
      this.dieAnim--;
    }
    const r=this.r;
    const flash=this.hitFlash>0;
    // Body
    ctx.beginPath();
    ctx.arc(0,0,r,0,Math.PI*2);
    const g=ctx.createRadialGradient(-r*.3,-r*.3,r*.1,r*.1,r*.1,r);
    g.addColorStop(0,flash?'#eeff80':'#90e060');
    g.addColorStop(1,flash?'#aadd00':'#2a7a15');
    ctx.fillStyle=g;
    ctx.fill();
    ctx.strokeStyle='#1a5a0a';ctx.lineWidth=2;ctx.stroke();
    // Ears
    ctx.beginPath();
    ctx.ellipse(-r*.55,-r*.7,r*.22,r*.18,-.3,0,Math.PI*2);
    ctx.fillStyle='#3a9020';ctx.fill();
    ctx.ellipse(r*.55,-r*.7,r*.22,r*.18,.3,0,Math.PI*2);
    ctx.fill();
    // Snout
    ctx.beginPath();
    ctx.ellipse(0,r*.2,r*.38,r*.26,0,0,Math.PI*2);
    ctx.fillStyle='#58a830';ctx.fill();
    ctx.strokeStyle='#1a5a0a';ctx.lineWidth=1;ctx.stroke();
    // Nostrils
    [-r*.14,r*.14].forEach(nx=>{
      ctx.beginPath();ctx.arc(nx,r*.22,r*.08,0,Math.PI*2);
      ctx.fillStyle='#0d4008';ctx.fill();
    });
    // Eyes
    [-r*.28,r*.28].forEach(ex=>{
      ctx.beginPath();ctx.arc(ex,-r*.22,r*.2,0,Math.PI*2);
      ctx.fillStyle='#fff';ctx.fill();
      ctx.beginPath();ctx.arc(ex+(this.destroyed?0:r*.05),-r*.18,r*.1,0,Math.PI*2);
      ctx.fillStyle='#111';ctx.fill();
    });
    // X eyes if dead
    if(this.destroyed){
      ctx.strokeStyle='#333';ctx.lineWidth=2;
      [-r*.28,r*.28].forEach(ex=>{
        ctx.beginPath();
        ctx.moveTo(ex-r*.12,-r*.34);ctx.lineTo(ex+r*.12,-r*.1);
        ctx.moveTo(ex+r*.12,-r*.34);ctx.lineTo(ex-r*.12,-r*.1);
        ctx.stroke();
      });
    }
    // Damage bruise
    if(!this.destroyed&&this.hp<this.maxHp){
      ctx.strokeStyle='rgba(0,60,0,.6)';ctx.lineWidth=1;
      ctx.beginPath();ctx.moveTo(-r*.5,r*.4);ctx.lineTo(-r*.1,r*.1);ctx.lineTo(r*.3,r*.5);ctx.stroke();
    }
    // Helmet for hp>=2
    if(this.maxHp>=2&&!this.destroyed){
      ctx.fillStyle='#888';
      ctx.beginPath();
      ctx.ellipse(0,-r*.55,r*.7,r*.5,-0.05,Math.PI,Math.PI*2);
      ctx.fill();
      ctx.strokeStyle='#555';ctx.lineWidth=1.5;ctx.stroke();
      // Helmet rivets
      [[-r*.4,-r*.7],[r*.4,-r*.7],[0,-r*.95]].forEach(([px,py])=>{
        ctx.beginPath();ctx.arc(px,py,r*.07,0,Math.PI*2);
        ctx.fillStyle='#666';ctx.fill();
      });
    }
    if(this.hitFlash>0) this.hitFlash--;
    ctx.restore();
    ctx.globalAlpha=1;
  }
}

// ═══════════════════════════════════════════════════════════════
//  PARTICLE
// ═══════════════════════════════════════════════════════════════
class Particle {
  constructor(x,y,vx,vy,col,life,r){
    this.x=x;this.y=y;this.vx=vx;this.vy=vy;
    this.col=col;this.life=life;this.maxLife=life;this.r=r;
  }
  update(){
    this.vy+=0.32;this.x+=this.vx;this.y+=this.vy;
    this.vx*=0.94;this.life--;
    if(this.y>GROUND){this.y=GROUND;this.vy*=-.3;this.vx*=.7;}
  }
  draw(ctx){
    const a=this.life/this.maxLife;
    ctx.globalAlpha=a;
    ctx.beginPath();
    ctx.arc(this.x,this.y,this.r*a,0,Math.PI*2);
    ctx.fillStyle=this.col;ctx.fill();
    ctx.globalAlpha=1;
  }
  get dead(){return this.life<=0;}
}
