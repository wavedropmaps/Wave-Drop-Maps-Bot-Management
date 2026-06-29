const { useState, useEffect, useRef, useCallback } = React;

// ── Sound Engine ──────────────────────────────────────────────────────────────
window._sfxOn = false;
const SFX = {
  _ctx: null,
  ctx(){ if(!this._ctx) this._ctx=new(window.AudioContext||window.webkitAudioContext)(); return this._ctx; },
  play(type){
    if(!window._sfxOn) return;
    try{
      const ctx=this.ctx(), now=ctx.currentTime;
      const o=ctx.createOscillator(), g=ctx.createGain();
      o.connect(g); g.connect(ctx.destination);
      if(type==='tab'){
        o.type='sine';
        o.frequency.setValueAtTime(520,now);
        o.frequency.exponentialRampToValueAtTime(780,now+0.07);
        g.gain.setValueAtTime(0.07,now);
        g.gain.exponentialRampToValueAtTime(0.001,now+0.14);
        o.start(now); o.stop(now+0.14);
      } else if(type==='open'){
        o.type='sine';
        o.frequency.setValueAtTime(380,now);
        o.frequency.exponentialRampToValueAtTime(560,now+0.1);
        g.gain.setValueAtTime(0.06,now);
        g.gain.exponentialRampToValueAtTime(0.001,now+0.18);
        o.start(now); o.stop(now+0.18);
      } else if(type==='god'){
        [[523,0],[659,0.12],[784,0.24],[1047,0.36]].forEach(([freq,t])=>{
          const o2=ctx.createOscillator(), g2=ctx.createGain();
          o2.connect(g2); g2.connect(ctx.destination);
          o2.type='sine'; o2.frequency.setValueAtTime(freq,now+t);
          g2.gain.setValueAtTime(0.1,now+t);
          g2.gain.exponentialRampToValueAtTime(0.001,now+t+0.18);
          o2.start(now+t); o2.stop(now+t+0.2);
        });
        return;
      }
    }catch(e){}
  }
};

function SoundToggle(){
  const [on,setOn]=useState(false);
  const toggle=()=>{
    const next=!on;
    window._sfxOn=next;
    setOn(next);
    if(next) SFX.play('tab');
  };
  return(
    <button onClick={toggle} title={on?"Sound ON — click to mute":"Sound OFF — click to enable"}
      style={{
        background:on?"rgba(0,212,255,0.1)":"rgba(255,255,255,0.03)",
        border:`1px solid ${on?"rgba(0,212,255,0.4)":"rgba(255,255,255,0.07)"}`,
        borderRadius:8,padding:"6px 12px",cursor:"pointer",
        display:"flex",alignItems:"center",gap:6,flexShrink:0,
        color:on?"#00d4ff":"#7d99bd",
        fontFamily:"'Orbitron',monospace",fontSize:8,fontWeight:700,
        letterSpacing:"0.1em",transition:"all 0.2s",
      }}>
      {on?(
        <>
          <span style={{display:"flex",alignItems:"flex-end",gap:1,height:12}}>
            {[0.35,0.65,1,0.65,0.35].map((h,i)=>(
              <div key={i} style={{width:2,background:"#00d4ff",borderRadius:1,
                height:`${h*12}px`,
                animation:`soundWave 0.5s ${i*0.08}s ease-in-out infinite`}}/>
            ))}
          </span>
          SFX ON
        </>
      ):<>🔇 SFX</>}
    </button>
  );
}

const GITHUB_USER = "wavedropmaps";
const GITHUB_REPO = "wave-leaderboard";
const DATA_URL = `https://raw.githubusercontent.com/${GITHUB_USER}/${GITHUB_REPO}/main/milestone_totals.json`;

const DUTIES = {
  message:{ label:"Messages",           short:"MESSAGES",  emoji:"⚔️",  color:"#00d4ff", desc:"Messages sent in the server",                    thresholds:{Bronze:1000,Silver:3000,Gold:8000,Legend:10000,God:50000}},
  role:   { label:"Role Giver",         short:"ROLES",    emoji:"✨", color:"#a78bfa", desc:"Help process proof from the community",            thresholds:{Bronze:500, Silver:1500,Gold:4000,Legend:5000, God:25000}},
  req:    { label:"Map Request Helper", short:"REQUESTS", emoji:"🗺️", color:"#00ff88", desc:"Help process map requests from the community",     thresholds:{Bronze:250, Silver:750, Gold:2000,Legend:2500, God:12500}},
  modlog: { label:"Mod Commands",       short:"MOD CMD",  emoji:"📋",  color:"#ffaa00", desc:"Mod commands executed to help keep community safe",thresholds:{Bronze:50,  Silver:200, Gold:500, Legend:1000, God:10000}},
};
const TIERS = ["Bronze","Silver","Gold","Legend","God"];
const TC = {
  Bronze:{bg:"linear-gradient(135deg,#2a1200,#1a0a00)", border:"#cd7f32", text:"#fde68a", icon:"🥉", glow:"rgba(205,127,50,0.45)"},
  Silver:{bg:"linear-gradient(135deg,#141c28,#0c1018)", border:"#b8c4d0", text:"#f0f4f8", icon:"🥈", glow:"rgba(184,196,208,0.35)"},
  Gold:  {bg:"linear-gradient(135deg,#281800,#180f00)", border:"#ffd700", text:"#fef08a", icon:"🥇", glow:"rgba(255,215,0,0.55)"},
  Legend:{bg:"linear-gradient(135deg,#180830,#0d0420)", border:"#a78bfa", text:"#e9d5ff", icon:"⭐", glow:"rgba(167,139,250,0.55)"},
  God:   {bg:"linear-gradient(135deg,#280018,#180010)", border:"#ff0080", text:"#fce7f3", icon:"👑", glow:"rgba(255,0,128,0.65)"},
};

function getEarnedBadges(scores={}){
  const b={};
  for(const [dk,d] of Object.entries(DUTIES)){
    const s=scores[dk]||0; let hi=null;
    for(const t of TIERS) if(s>=d.thresholds[t]) hi=t;
    if(hi) b[dk]=hi;
  }
  return b;
}
function getTopTier(badges){
  return TIERS.slice().reverse().find(t=>Object.values(badges).includes(t))||null;
}
function getNextTarget(score,dk){
  const d=DUTIES[dk];
  for(const t of TIERS) if(score<d.thresholds[t]) return{tier:t,needed:d.thresholds[t]};
  return null;
}
function getDutyTier(score,dk){
  const d=DUTIES[dk]; let hi=null;
  for(const t of TIERS) if(score>=d.thresholds[t]) hi=t;
  return hi;
}
function badgeScore(scores){
  const b=getEarnedBadges(scores),w={Bronze:1,Silver:2,Gold:4,Legend:8,God:16};
  return Object.values(b).reduce((s,t)=>s+(w[t]||0),0);
}

// ── Power Points Tier System ──────────────────────────────────────────────────
const POWER_TIERS = [
  {tier:"God",    minPts:64, waveReward:500},
  {tier:"Legend", minPts:32, waveReward:300},
  {tier:"Gold",   minPts:16, waveReward:100},
  {tier:"Silver", minPts:8,  waveReward:50},
  {tier:"Bronze", minPts:4,  waveReward:20},
];
function getPowerTier(scores){
  const pts=badgeScore(scores);
  for(const t of POWER_TIERS) if(pts>=t.minPts) return t;
  return null;
}
function getNextPowerTier(scores){
  const pts=badgeScore(scores);
  // Find the lowest tier the user hasn't reached yet
  for(let i=POWER_TIERS.length-1;i>=0;i--){
    if(pts<POWER_TIERS[i].minPts) return POWER_TIERS[i];
  }
  return null;
}

function getDominantDuty(scores){
  let best=null, bestPct=0;
  for(const [dk,d] of Object.entries(DUTIES)){
    const sc=scores[dk]||0;
    const max=d.thresholds.God;
    const pct=sc/max;
    if(pct>bestPct){bestPct=pct;best=dk;}
  }
  return best;
}
function fmt(n){
  if(n>=1000) return (n/1000).toFixed(1).replace(/\.0$/,"")+"k";
  return String(n);
}

function useCountUp(target, duration=1200, active=true){
  const [val,setVal]=useState(0);
  useEffect(()=>{
    if(!active){setVal(target);return;}
    let start=null;
    const step=(ts)=>{
      if(!start) start=ts;
      const progress=Math.min((ts-start)/duration,1);
      const eased=1-Math.pow(1-progress,3);
      setVal(Math.floor(eased*target));
      if(progress<1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  },[target,active]);
  return val;
}

function AnimatedNumber({value,duration=1000}){
  const v=useCountUp(value,duration,true);
  return <span>{fmt(v)}</span>;
}

function TierPill({tier,size="sm"}){
  const tc=TC[tier], big=size==="lg";
  return(
    <span style={{display:"inline-flex",alignItems:"center",gap:big?5:3,
      background:tc.bg,border:`1px solid ${tc.border}`,borderRadius:6,
      padding:big?"5px 13px":"2px 8px",fontSize:big?12:9,color:tc.text,
      fontFamily:"'Orbitron',monospace",fontWeight:700,letterSpacing:"0.1em",
      boxShadow:`0 0 12px ${tc.glow}`,whiteSpace:"nowrap"}}>
      {tc.icon} {tier.toUpperCase()}
    </span>
  );
}

function PipRow({score,dk}){
  const d=DUTIES[dk];
  const filled=TIERS.filter(t=>score>=d.thresholds[t]).length;
  return(
    <div style={{display:"flex",gap:3,alignItems:"center"}}>
      {TIERS.map((t,i)=>{
        const f=i<filled, col=TC[t].border;
        return <div key={t} title={`${t}: ${d.thresholds[t].toLocaleString()}`} style={{
          width:7,height:7,borderRadius:"50%",
          background:f?col:"#0d1a26",
          boxShadow:f?`0 0 7px ${col}`:"none",
          border:f?"none":"1px solid #111e2e",
          transition:"all 0.3s",
        }}/>;
      })}
    </div>
  );
}

function TierBreakdown({dk}){
  const d=DUTIES[dk];
  return(
    <div style={{
      display:"flex",flexWrap:"wrap",gap:5,
      padding:"14px 18px 14px",
      background:"rgba(2,5,12,0.7)",
      borderRadius:"0 0 14px 14px",
      borderLeft:`1px solid ${d.color}22`,
      borderRight:`1px solid ${d.color}22`,
      borderBottom:`1px solid ${d.color}22`,
      marginBottom:8,
    }}>
      <div style={{width:"100%",fontSize:8,color:d.color,fontFamily:"'Orbitron',monospace",
        fontWeight:700,letterSpacing:"0.22em",marginBottom:8,opacity:0.55}}>
        ◈ HOW TO EARN EACH BADGE
      </div>
      {TIERS.map(t=>{
        const tc=TC[t];
        return(
          <div key={t} style={{
            display:"flex",alignItems:"center",gap:7,
            background:`${tc.border}0a`,
            border:`1px solid ${tc.border}25`,
            borderRadius:8,padding:"6px 11px",
            flex:"1 1 100px",minWidth:95,
          }}>
            <span style={{fontSize:16,lineHeight:1}}>{tc.icon}</span>
            <div>
              <div style={{fontSize:8,color:tc.border,fontFamily:"'Orbitron',monospace",
                fontWeight:700,letterSpacing:"0.12em",marginBottom:2}}>{t.toUpperCase()}</div>
              <div style={{fontSize:13,color:"rgba(255,255,255,0.88)",
                fontFamily:"'JetBrains Mono',monospace",fontWeight:700,lineHeight:1}}>
                {d.thresholds[t].toLocaleString()}
                <span style={{fontSize:8,color:"rgba(255,255,255,0.22)",marginLeft:3,fontWeight:400}}>actions</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function DutyHeader({dk}){
  const d=DUTIES[dk];
  return(
    <div style={{
      position:"relative",overflow:"hidden",
      background:`linear-gradient(135deg,rgba(3,8,16,0.98) 0%,${d.color}0a 100%)`,
      border:`1px solid ${d.color}35`,
      borderRadius:"14px 14px 0 0",
      padding:"20px 22px 18px",
    }}>
      <div style={{position:"absolute",top:0,left:0,right:0,height:1,
        background:`linear-gradient(90deg,transparent,${d.color}dd 35%,${d.color} 50%,${d.color}dd 65%,transparent)`}}/>
      <div style={{position:"absolute",top:0,left:0,bottom:0,width:3,
        background:`linear-gradient(180deg,${d.color} 0%,${d.color}33 70%,transparent 100%)`,
        borderRadius:"14px 0 0 0"}}/>
      <div style={{position:"absolute",right:16,top:"50%",transform:"translateY(-50%)",
        fontSize:72,opacity:0.04,pointerEvents:"none",userSelect:"none",lineHeight:1}}>{d.emoji}</div>
      <div style={{display:"flex",alignItems:"center",gap:12}}>
        <div style={{
          width:42,height:42,borderRadius:11,flexShrink:0,
          background:`${d.color}14`,border:`1px solid ${d.color}38`,
          display:"flex",alignItems:"center",justifyContent:"center",
          fontSize:20,boxShadow:`0 0 14px ${d.color}28`,
        }}>{d.emoji}</div>
        <div style={{flex:1,minWidth:0}}>
          <h2 style={{
            fontFamily:"'Orbitron',monospace",fontWeight:900,
            fontSize:"clamp(13px,2vw,18px)",letterSpacing:"0.03em",
            color:d.color,textShadow:`0 0 16px ${d.color}88`,marginBottom:3,
          }}>{d.label}</h2>
          <p style={{fontSize:11,color:"rgba(255,255,255,0.5)",fontFamily:"'Exo 2',sans-serif",
            whiteSpace:"nowrap",overflow:"hidden",textOverflow:"ellipsis"}}>{d.desc}</p>
        </div>
      </div>
    </div>
  );
}

function PodiumSection({staffList, dk, onSelectStaff}){
  const sorted=[...staffList].sort((a,b)=>(b.scores[dk]||0)-(a.scores[dk]||0));
  const top3=sorted.slice(0,3);
  if(top3.length<1) return null;
  const d=DUTIES[dk];
  const order=[1,0,2];
  const heights=[80,110,60];
  const anims=["silverPulse","goldPulse","bronzePulse"];
  const podiumColors=["#b8c4d0","#ffd700","#cd7f32"];
  const ranks=[2,1,3];

  return (
    <div style={{display:"flex",justifyContent:"center",alignItems:"flex-end",gap:10,margin:"24px 0 16px",padding:"0 10px"}}>
      {order.map((idx,displayPos)=>{
        const s=top3[idx];
        if(!s) return <div key={displayPos} style={{flex:1,maxWidth:200}}/>;
        const score=s.scores[dk]||0;
        const tier=getDutyTier(score,dk);
        const col=podiumColors[displayPos];
        const rank=ranks[displayPos];
        const anim=anims[displayPos];
        return (
          <div key={s.name} className="podium-card" onClick={()=>onSelectStaff(s)}
            style={{flex:1,maxWidth:200,cursor:"pointer",
              animation:`podiumRise 0.5s ${0.1*displayPos}s ease both`}}>
            {rank===1&&(
              <div style={{textAlign:"center",fontSize:26,marginBottom:4,
                animation:"crownBob 2.4s ease-in-out infinite"}}>👑</div>
            )}
            <div style={{
              background:`linear-gradient(180deg,${col}18,${col}08)`,
              border:`1px solid ${col}50`,borderRadius:"12px 12px 0 0",
              padding:"14px 10px 10px",textAlign:"center",
              animation:`${anim} 2.5s ease-in-out infinite`,
            }}>
              <div style={{width:44,height:44,borderRadius:12,margin:"0 auto 8px",
                background:`${col}20`,border:`2px solid ${col}80`,
                display:"flex",alignItems:"center",justifyContent:"center",
                fontSize:18,fontFamily:"'Orbitron',monospace",fontWeight:900,color:col,overflow:"hidden"}}>
                {s.avatar_url ? <img src={s.avatar_url} style={{width:"100%",height:"100%",objectFit:"cover"}} onError={(e)=>{e.target.style.display='none'}} alt=""/> : s.name[0].toUpperCase()}
              </div>
              <div style={{fontSize:10,color:"#fff",fontFamily:"'Exo 2',sans-serif",
                fontWeight:700,marginBottom:4,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>
                {s.name}
              </div>
              {tier&&<TierPill tier={tier}/>}
              <div style={{marginTop:6,fontFamily:"'Orbitron',monospace",fontWeight:900,
                fontSize:15,color:col,textShadow:`0 0 14px ${col}88`}}>
                {fmt(score)}
              </div>
            </div>
            <div style={{
              height:heights[displayPos],
              background:`linear-gradient(180deg,${col}25,${col}08)`,
              border:`1px solid ${col}30`,borderTop:"none",
              borderRadius:"0 0 10px 10px",
              display:"flex",alignItems:"center",justifyContent:"center",
            }}>
              <div style={{fontFamily:"'Orbitron',monospace",fontWeight:900,fontSize:22,
                color:`${col}60`}}>#{rank}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function StaffRow({staff,rank,dk,onClick,delay,compact}){
  const score=staff.scores[dk]||0;
  const tier=getDutyTier(score,dk);
  const tc=tier?TC[tier]:null;
  const d=DUTIES[dk];
  const next=getNextTarget(score,dk);
  let pct=0;
  if(next){const ti=TIERS.indexOf(next.tier);const prev=ti>0?d.thresholds[TIERS[ti-1]]:0;pct=Math.min(100,Math.max(0,((score-prev)/(next.needed-prev))*100));}
  else pct=100;
  const rCol=rank===1?"#ffd700":rank===2?"#b8c4d0":rank===3?"#cd7f32":null;
  const tooltip=next
    ? `${(next.needed-score).toLocaleString()} more to ${next.tier} (${Math.round(pct)}%)`
    : "MAX TIER REACHED 👑";

  return(
    <div className="row-card" onClick={onClick} style={{
      display:"grid",
      gridTemplateColumns:compact?"40px 1fr auto":"46px 1fr auto",
      alignItems:"center",gap:compact?12:16,
      background:tier?`linear-gradient(90deg,${tc.border}09,rgba(3,8,16,0.72))`:"rgba(5,11,20,0.72)",
      border:`1px solid ${tier?tc.border+"2a":"#0d1825"}`,
      borderRadius:12,padding:compact?"11px 14px":"13px 18px",cursor:"pointer",
      animation:delay?`fadeUp 0.36s ${delay}s ease both`:"none",
    }}>
      <div style={{textAlign:"center",flexShrink:0}}>
        {rCol
          ? <div style={{width:compact?30:34,height:compact?30:34,borderRadius:9,
              background:`${rCol}18`,border:`1px solid ${rCol}55`,
              display:"flex",alignItems:"center",justifyContent:"center",
              fontSize:rank===1?16:14,boxShadow:`0 0 10px ${rCol}40`,margin:"0 auto"}}>
              {rank===1?"🥇":rank===2?"🥈":"🥉"}
            </div>
          : <div style={{width:compact?30:34,height:compact?30:34,borderRadius:9,
              background:"rgba(10,20,34,0.8)",border:"1px solid #0d1825",
              display:"flex",alignItems:"center",justifyContent:"center",
              fontSize:9,fontFamily:"'Orbitron',monospace",fontWeight:700,
              color:"#7d99bd",margin:"0 auto"}}>{rank}</div>
        }
      </div>
      <div style={{minWidth:0}}>
        <div style={{display:"flex",alignItems:"center",gap:7,marginBottom:compact?3:5,flexWrap:"wrap"}}>
          {staff.avatar_url && (
            <img src={staff.avatar_url} style={{width:compact?20:24,height:compact?20:24,borderRadius:"50%",border:`1.5px solid ${tier?tc.border:"#7d99bd"}`,objectFit:"cover",flexShrink:0}} onError={(e)=>{e.target.style.display='none'}} alt=""/>
          )}
          <span style={{
            color:tier?"#fff":"#aec1d6",
            fontFamily:"'Exo 2',sans-serif",fontWeight:800,
            fontSize:compact?13:14,
            textShadow:tier?`0 0 12px ${tc.border}50`:"none",
            letterSpacing:"0.01em",
            whiteSpace:"nowrap",overflow:"hidden",textOverflow:"ellipsis",maxWidth:160,
          }}>{staff.name}</span>
          {tier&&<TierPill tier={tier}/>}
        </div>
        {staff.role&&<div style={{fontSize:7,color:"rgba(0,212,255,0.62)",fontFamily:"'Orbitron',monospace",
          letterSpacing:"0.12em",marginBottom:compact?3:5}}>{staff.role.toUpperCase()}</div>}
        <div title={tooltip} style={{height:2,borderRadius:2,background:"rgba(10,20,34,0.9)",overflow:"hidden",marginBottom:compact?3:5,cursor:"help"}}>
          <div style={{height:"100%",borderRadius:2,width:`${pct}%`,
            background:tier?`linear-gradient(90deg,${tc.border}70,${tc.border})`:`linear-gradient(90deg,${d.color}30,${d.color}60)`,
            boxShadow:tier?`0 0 6px ${tc.border}80`:"none",
            transition:"width 1.4s cubic-bezier(0.4,0,0.2,1)"}}/>
        </div>
        {!compact&&(
          <div style={{display:"flex",justifyContent:"space-between",alignItems:"center"}}>
            <span style={{fontSize:9,color:"rgba(255,255,255,0.42)",fontFamily:"'JetBrains Mono',monospace"}}>
              {score.toLocaleString()} actions
            </span>
            {next
              ? <span style={{fontSize:8,color:"rgba(255,255,255,0.4)",fontFamily:"'JetBrains Mono',monospace"}}>
                  {(next.needed-score).toLocaleString()} → {TC[next.tier].icon} {next.tier}
                </span>
              : <span style={{fontSize:8,color:"#ff0080",fontFamily:"'Orbitron',monospace",
                  fontWeight:700,textShadow:"0 0 8px #ff008088"}}>MAX 👑</span>
            }
          </div>
        )}
      </div>
      <div style={{textAlign:"right",flexShrink:0}}>
        <div style={{fontFamily:"'Orbitron',monospace",fontWeight:900,
          fontSize:compact?15:17,lineHeight:1,marginBottom:2,
          color:tier?tc.border:`${d.color}77`,
          textShadow:tier?`0 0 16px ${tc.glow}`:"none"}}>
          {fmt(score)}
        </div>
        {(()=>{const w=(staff.weekly||{})[dk]||0;return w>0&&(
          <div style={{fontSize:8,color:"#00ff88",fontFamily:"'JetBrains Mono',monospace",
            fontWeight:700,textShadow:"0 0 8px #00ff8855",marginBottom:2}}>
            ▲ +{w.toLocaleString()} wk
          </div>
        );})()}
        <div style={{display:"flex",justifyContent:"flex-end"}}>
          <PipRow score={score} dk={dk}/>
        </div>
      </div>
    </div>
  );
}

function AllDutyCard({dk,staffList,onViewAll,onSelectStaff,animDelay}){
  const d=DUTIES[dk];
  const sorted=[...staffList].sort((a,b)=>(b.scores[dk]||0)-(a.scores[dk]||0));
  const top3=sorted.slice(0,3);
  return(
    <div style={{marginBottom:32,animation:`fadeUp 0.45s ${animDelay}s ease both`}}>
      <DutyHeader dk={dk}/>
      <TierBreakdown dk={dk}/>
      <div style={{display:"flex",flexDirection:"column",gap:6,marginBottom:8}}>
        {top3.map((s,i)=>(
          <StaffRow key={s.name} staff={s} rank={i+1} dk={dk}
            compact={true} delay={0} onClick={()=>onSelectStaff(s)}/>
        ))}
        {top3.length===0&&(
          <div style={{textAlign:"center",color:"#0d1825",fontFamily:"'Orbitron',monospace",
            padding:24,fontSize:9,letterSpacing:"0.2em"}}>NO DATA YET</div>
        )}
      </div>
      {sorted.length>3&&(
        <button className="view-all-btn" onClick={()=>onViewAll(dk)} style={{
          width:"100%",background:"rgba(5,11,20,0.6)",
          border:`1px solid ${d.color}20`,borderRadius:10,
          padding:"9px 16px",
          display:"flex",alignItems:"center",justifyContent:"center",gap:8,
          color:`${d.color}88`,fontFamily:"'Orbitron',monospace",fontWeight:700,
          fontSize:9,letterSpacing:"0.15em",cursor:"pointer",
        }}>
          VIEW ALL {sorted.length} STAFF
          <span style={{fontSize:12,opacity:0.7}}>→</span>
        </button>
      )}
    </div>
  );
}

function HallOfFame({staffList,onSelect}){
  const gods=[];
  for(const s of staffList){
    const godDuties=Object.entries(DUTIES).filter(([dk,d])=>(s.scores[dk]||0)>=d.thresholds.God).map(([dk])=>dk);
    if(godDuties.length>0) gods.push({...s,godDuties});
  }
  if(gods.length===0) return(
    <div style={{textAlign:"center",padding:"60px 20px",
      background:"linear-gradient(135deg,rgba(255,0,128,0.03),rgba(3,6,13,0.8))",
      border:"1px solid rgba(255,0,128,0.12)",borderRadius:16,
      fontFamily:"'Orbitron',monospace",color:"rgba(255,0,128,0.3)",
      fontSize:10,letterSpacing:"0.3em"}}>
      👑 NO GOD TIER ACHIEVERS YET — BE THE FIRST
    </div>
  );
  return(
    <div>
      <div style={{textAlign:"center",marginBottom:24}}>
        <div style={{fontSize:9,color:"#ff0080",fontFamily:"'Orbitron',monospace",fontWeight:700,
          letterSpacing:"0.35em",marginBottom:8,textShadow:"0 0 20px #ff008066"}}>
          ◈ THE ELITE ◈
        </div>
        <div style={{fontSize:"clamp(16px,3vw,28px)",fontFamily:"'Orbitron',monospace",fontWeight:900,
          background:"linear-gradient(90deg,#ff0080,#ff69b4,#ff0080)",
          backgroundSize:"200% auto",WebkitBackgroundClip:"text",WebkitTextFillColor:"transparent",backgroundClip:"text",
          animation:"shimmer 3s linear infinite",letterSpacing:"0.05em"}}>
          HALL OF FAME
        </div>
      </div>
      <div style={{display:"flex",flexDirection:"column",gap:10}}>
        {gods.map((s,i)=>{
          const bs=badgeScore(s.scores);
          return(
            <div key={s.name} onClick={()=>onSelect(s)} style={{
              cursor:"pointer",
              background:"linear-gradient(135deg,rgba(255,0,128,0.07),rgba(3,6,13,0.9))",
              border:"1px solid rgba(255,0,128,0.2)",borderRadius:14,
              padding:"16px 20px",
              animation:`fadeUp 0.4s ${i*0.07}s ease both`,
              transition:"transform 0.15s,box-shadow 0.15s",
              boxShadow:"0 2px 20px rgba(255,0,128,0.08)",
            }}
            onMouseEnter={e=>{e.currentTarget.style.transform="translateX(4px)";e.currentTarget.style.boxShadow="0 4px 30px rgba(255,0,128,0.18)";}}
            onMouseLeave={e=>{e.currentTarget.style.transform="translateX(0)";e.currentTarget.style.boxShadow="0 2px 20px rgba(255,0,128,0.08)";}}>
              <div style={{display:"flex",alignItems:"center",gap:14,flexWrap:"wrap"}}>
                <div style={{width:46,height:46,borderRadius:12,
                  background:"linear-gradient(135deg,rgba(255,0,128,0.2),rgba(255,0,128,0.05))",
                  border:"1px solid rgba(255,0,128,0.4)",
                  display:"flex",alignItems:"center",justifyContent:"center",
                  fontSize:18,fontFamily:"'Orbitron',monospace",fontWeight:900,color:"#ff0080",
                  boxShadow:"0 0 20px rgba(255,0,128,0.3)",overflow:"hidden"}}>
                  {s.avatar_url ? <img src={s.avatar_url} style={{width:"100%",height:"100%",objectFit:"cover"}} onError={(e)=>{e.target.style.display='none'}} alt=""/> : s.name[0].toUpperCase()}
                </div>
                <div style={{flex:1,minWidth:0}}>
                  <div style={{fontFamily:"'Exo 2',sans-serif",fontWeight:800,color:"#fff",
                    fontSize:15,marginBottom:6,textShadow:"0 0 16px rgba(255,0,128,0.4)"}}>
                    {s.name}
                  </div>
                  <div style={{display:"flex",gap:6,flexWrap:"wrap"}}>
                    {s.godDuties.map(dk=>(
                      <span key={dk} style={{
                        fontSize:8,fontFamily:"'Orbitron',monospace",fontWeight:700,
                        color:"#ff0080",background:"rgba(255,0,128,0.08)",
                        border:"1px solid rgba(255,0,128,0.25)",borderRadius:4,padding:"2px 7px",
                        letterSpacing:"0.1em",
                      }}>👑 {DUTIES[dk].short}</span>
                    ))}
                  </div>
                </div>
                <div style={{textAlign:"right"}}>
                  <div style={{fontFamily:"'Orbitron',monospace",fontWeight:900,fontSize:18,
                    color:"#ff0080",textShadow:"0 0 20px rgba(255,0,128,0.6)",marginBottom:2}}>
                    {bs}
                  </div>
                  <div style={{fontSize:7,color:"rgba(255,0,128,0.4)",fontFamily:"'Orbitron',monospace",
                    letterSpacing:"0.15em"}}>PWR SCORE</div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function HowItWorks(){
  const [open,setOpen]=useState(false);
  const weights={Bronze:1,Silver:2,Gold:4,Legend:8,God:16};
  return(
    <div style={{maxWidth:860,margin:"0 auto 20px",
      background:"rgba(0,212,255,0.03)",border:"1px solid rgba(0,212,255,0.1)",borderRadius:12}}>
      <button className="explainer-toggle" onClick={()=>setOpen(o=>!o)} style={{
        width:"100%",background:"none",border:"none",cursor:"pointer",
        padding:"12px 20px",display:"flex",alignItems:"center",justifyContent:"space-between",
      }}>
        <span style={{fontSize:9,color:"rgba(0,212,255,0.55)",fontFamily:"'Orbitron',monospace",
          fontWeight:700,letterSpacing:"0.2em"}}>ℹ HOW SCORE & POWER POINTS WORK</span>
        <span style={{color:"rgba(0,212,255,0.4)",fontSize:14,transition:"transform 0.2s",
          display:"inline-block",transform:open?"rotate(180deg)":"none"}}>▾</span>
      </button>
      {open&&(
        <div style={{padding:"0 20px 20px",animation:"fadeUp 0.2s ease"}}>
          <div style={{fontSize:8,color:"rgba(0,212,255,0.4)",fontFamily:"'Orbitron',monospace",
            fontWeight:700,letterSpacing:"0.2em",marginBottom:8}}>◈ WHAT EACH DUTY TRACKS</div>
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(200px,1fr))",gap:8,marginBottom:18}}>
            {Object.entries(DUTIES).map(([dk,d])=>(
              <div key={dk} style={{background:"rgba(3,8,16,0.7)",border:`1px solid ${d.color}20`,
                borderRadius:10,padding:"10px 12px",borderLeft:`3px solid ${d.color}60`}}>
                <div style={{fontSize:12,marginBottom:4}}>{d.emoji} <span style={{color:d.color,
                  fontFamily:"'Orbitron',monospace",fontWeight:700,fontSize:9}}>{d.label}</span></div>
                <div style={{fontSize:10,color:"rgba(255,255,255,0.4)",fontFamily:"'Exo 2',sans-serif"}}>{d.desc}</div>
              </div>
            ))}
          </div>
          <div style={{fontSize:8,color:"rgba(0,212,255,0.4)",fontFamily:"'Orbitron',monospace",
            fontWeight:700,letterSpacing:"0.2em",marginBottom:8}}>◈ WHAT IS SCORE POINTS?</div>
          <div style={{background:"rgba(3,8,16,0.8)",border:"1px solid rgba(0,212,255,0.1)",
            borderRadius:12,padding:"14px 16px",marginBottom:18}}>
            <div style={{background:"rgba(0,212,255,0.05)",border:"1px solid rgba(0,212,255,0.15)",
              borderRadius:9,padding:"10px 14px",marginBottom:12,display:"flex",alignItems:"flex-start",gap:10}}>
              <span style={{fontSize:18,flexShrink:0}}>📊</span>
              <div>
                <div style={{fontFamily:"'Orbitron',monospace",fontWeight:700,fontSize:9,
                  color:"#00d4ff",letterSpacing:"0.12em",marginBottom:4}}>SCORE = RAW ACTIONS IN ONE DUTY</div>
                <div style={{fontSize:11,color:"rgba(255,255,255,0.55)",fontFamily:"'Exo 2',sans-serif",lineHeight:1.6}}>
                  Your Score is simply how many times you performed that specific duty. Sent 12,400 messages? Your message score is 12,400.
                </div>
              </div>
            </div>
          </div>
          <div style={{fontSize:8,color:"rgba(0,212,255,0.4)",fontFamily:"'Orbitron',monospace",
            fontWeight:700,letterSpacing:"0.2em",marginBottom:8}}>◈ WHAT IS POWER POINTS?</div>
          <div style={{background:"rgba(3,8,16,0.8)",border:"1px solid rgba(0,212,255,0.1)",
            borderRadius:12,padding:"14px 16px",marginBottom:10}}>
            <div style={{background:"rgba(0,212,255,0.06)",border:"1px solid rgba(0,212,255,0.18)",
              borderRadius:9,padding:"10px 14px",marginBottom:14,display:"flex",alignItems:"flex-start",gap:10}}>
              <span style={{fontSize:18,flexShrink:0}}>⭐</span>
              <div>
                <div style={{fontFamily:"'Orbitron',monospace",fontWeight:700,fontSize:9,
                  color:"#00d4ff",letterSpacing:"0.12em",marginBottom:4}}>POWER POINTS = YOUR BADGE POINTS ADDED UP</div>
                <div style={{fontSize:11,color:"rgba(255,255,255,0.55)",fontFamily:"'Exo 2',sans-serif",lineHeight:1.6}}>
                  Every badge you earn across any duty gives you points. Higher tier badges are worth more.
                </div>
              </div>
            </div>
            <div style={{display:"flex",gap:6,flexWrap:"wrap",marginBottom:14}}>
              {TIERS.map(t=>(
                <div key={t} style={{flex:"1 1 80px",background:`${TC[t].border}0d`,
                  border:`1px solid ${TC[t].border}30`,borderRadius:10,padding:"10px 8px",textAlign:"center"}}>
                  <div style={{fontSize:18,marginBottom:4}}>{TC[t].icon}</div>
                  <div style={{fontSize:8,color:TC[t].border,fontFamily:"'Orbitron',monospace",
                    fontWeight:700,letterSpacing:"0.1em",marginBottom:4}}>{t.toUpperCase()}</div>
                  <div style={{fontFamily:"'JetBrains Mono',monospace",fontWeight:900,fontSize:18,
                    color:"#fff",lineHeight:1}}>{weights[t]}</div>
                  <div style={{fontSize:7,color:"rgba(255,255,255,0.2)",fontFamily:"'Orbitron',monospace",
                    letterSpacing:"0.12em",marginTop:2}}>PT{weights[t]>1?"S":""}</div>
                </div>
              ))}
            </div>
          </div>

          <div style={{fontSize:8,color:"rgba(0,212,255,0.4)",fontFamily:"'Orbitron',monospace",
            fontWeight:700,letterSpacing:"0.2em",marginBottom:8}}>◈ POWER TIER REWARDS</div>
          <div style={{background:"rgba(3,8,16,0.8)",border:"1px solid rgba(0,212,255,0.1)",
            borderRadius:12,padding:"14px 16px",marginBottom:10}}>
            <div style={{background:"rgba(0,212,255,0.05)",border:"1px solid rgba(0,212,255,0.15)",
              borderRadius:9,padding:"10px 14px",marginBottom:14,display:"flex",alignItems:"flex-start",gap:10}}>
              <span style={{fontSize:18,flexShrink:0}}>🏆</span>
              <div>
                <div style={{fontFamily:"'Orbitron',monospace",fontWeight:700,fontSize:9,
                  color:"#00d4ff",letterSpacing:"0.12em",marginBottom:4}}>REACH POWER POINT THRESHOLDS → EARN REWARDS</div>
                <div style={{fontSize:11,color:"rgba(255,255,255,0.55)",fontFamily:"'Exo 2',sans-serif",lineHeight:1.6}}>
                  As your Power Points grow, you unlock tier badges, Discord roles in the Staff Hub, and one-time Wave Point bonuses.
                </div>
              </div>
            </div>
            <div style={{display:"flex",gap:6,flexWrap:"wrap"}}>
              {POWER_TIERS.slice().reverse().map(pt=>{
                const ptc=TC[pt.tier];
                return(
                  <div key={pt.tier} style={{flex:"1 1 90px",background:`${ptc.border}0d`,
                    border:`1px solid ${ptc.border}30`,borderRadius:10,padding:"10px 8px",textAlign:"center"}}>
                    <div style={{fontSize:16,marginBottom:3}}>{ptc.icon}</div>
                    <div style={{fontSize:8,color:ptc.border,fontFamily:"'Orbitron',monospace",
                      fontWeight:700,letterSpacing:"0.1em",marginBottom:3}}>{pt.tier.toUpperCase()}</div>
                    <div style={{fontFamily:"'JetBrains Mono',monospace",fontWeight:900,fontSize:14,
                      color:"#fff",lineHeight:1}}>{pt.minPts}+</div>
                    <div style={{fontSize:7,color:"rgba(255,255,255,0.2)",fontFamily:"'Orbitron',monospace",
                      letterSpacing:"0.08em",marginTop:2}}>PWR PTS</div>
                    <div style={{marginTop:4,fontSize:9,color:"#00ff88",fontFamily:"'JetBrains Mono',monospace",
                      fontWeight:700}}>+{pt.waveReward} 🌊</div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ShareButton({staff}){
  const [status,setStatus]=useState("idle");
  const copy=()=>{
    const badges=getEarnedBadges(staff.scores);
    const lines=[
      `🌊 Wave Staff — ${staff.name}`,
      `Power Points: ${badgeScore(staff.scores)}`,
      `Badges: ${Object.entries(badges).map(([dk,t])=>`${TC[t].icon}${DUTIES[dk].short}`).join(" ")}`,
      `Top Tier: ${getTopTier(badges)||"None"}`,
    ];
    const text=lines.join("\n");
    const finish=(ok)=>{setStatus(ok?"copied":"failed");setTimeout(()=>setStatus("idle"),2500);};
    if(navigator.clipboard&&window.isSecureContext){
      navigator.clipboard.writeText(text).then(()=>finish(true)).catch(()=>fallback());
    } else { fallback(); }
    function fallback(){
      try{
        const ta=document.createElement("textarea");
        ta.value=text;ta.style.cssText="position:fixed;top:-9999px;left:-9999px;opacity:0;";
        document.body.appendChild(ta);ta.focus();ta.select();
        const ok=document.execCommand("copy");document.body.removeChild(ta);finish(ok);
      }catch(e){finish(false);}
    }
  };
  const label=status==="copied"?"✓ CLIPPED TO CLIPBOARD":status==="failed"?"✕ COPY FAILED":"⎘ CLIP TO CLIPBOARD";
  const col=status==="copied"?"#00ff88":status==="failed"?"#ff4466":"rgba(0,212,255,0.7)";
  const bg=status==="copied"?"rgba(0,255,136,0.1)":status==="failed"?"rgba(255,68,102,0.1)":"rgba(0,212,255,0.07)";
  const border=status==="copied"?"rgba(0,255,136,0.3)":status==="failed"?"rgba(255,68,102,0.3)":"rgba(0,212,255,0.2)";
  return(
    <button className="copy-btn" onClick={copy} style={{
      background:bg,border:`1px solid ${border}`,borderRadius:8,padding:"7px 14px",
      cursor:"pointer",color:col,fontFamily:"'Orbitron',monospace",fontSize:8,fontWeight:700,
      letterSpacing:"0.12em",transition:"all 0.2s",display:"flex",alignItems:"center",gap:6,whiteSpace:"nowrap",
    }}>{label}</button>
  );
}

function spawnConfetti(el){
  if(!el) return;
  const colors=['#00d4ff','#ff0080','#ffd700','#00ff88','#a78bfa','#ff69b4','#ffffff'];
  for(let i=0;i<64;i++){
    const d=document.createElement('div');
    const c=colors[Math.floor(Math.random()*colors.length)];
    const sz=4+Math.random()*9;
    const startX=20+Math.random()*60;
    const dur=0.8+Math.random()*1.4;
    const delay=Math.random()*0.6;
    d.style.cssText=`position:fixed;pointer-events:none;z-index:9999;
      width:${sz}px;height:${sz}px;border-radius:${Math.random()>.5?'50%':'2px'};
      background:${c};left:${startX}%;top:15%;
      animation:confettiFall ${dur}s ${delay}s ease-out forwards;`;
    document.body.appendChild(d);
    setTimeout(()=>d.remove(),(dur+delay)*1000+100);
  }
}

function AnimatedBar({pct,col,glow,delay=0}){
  const [w,setW]=useState(0);
  useEffect(()=>{const t=setTimeout(()=>setW(pct),delay);return()=>clearTimeout(t);},[pct,delay]);
  return(
    <div style={{position:"relative",height:7,borderRadius:4,background:"rgba(4,10,20,0.95)",margin:"8px 0 4px",overflow:"visible"}}>
      <div style={{position:"absolute",inset:0,borderRadius:4,overflow:"hidden"}}>
        <div style={{height:"100%",borderRadius:4,
          width:`${w}%`,transition:`width ${w>0?"1.3s":"0s"} cubic-bezier(0.2,0,0.1,1)`,
          background:`linear-gradient(90deg,${col}55,${col}cc,${col})`,
          boxShadow:w>0?`0 0 10px ${glow},0 0 20px ${glow}`:"none"}}/>
      </div>
      {w>0&&w<100&&(
        <div style={{position:"absolute",top:"50%",left:`${w}%`,transform:"translate(-50%,-50%)",
          width:11,height:11,borderRadius:"50%",background:col,
          boxShadow:`0 0 8px ${col},0 0 18px ${col}`,
          '--ec':col,animation:"endPulse 1.6s ease-in-out infinite",zIndex:2}}/>
      )}
      {w===100&&(
        <div style={{position:"absolute",top:"50%",right:0,transform:"translateY(-50%)",
          fontSize:11,filter:`drop-shadow(0 0 6px ${col})`,animation:"endPulse 2s ease-in-out infinite",'--ec':col}}>⭐</div>
      )}
    </div>
  );
}

// ── Compare Modal — UPGRADED: Blue vs Red, winner highlights, shimmer bars ────
function CompareModal({staffA,staffB,onClose}){
  const COL_A="#00d4ff";
  const COL_B="#ff0080";
  const [barsVisible,setBarsVisible]=useState(false);
  useEffect(()=>{const t=setTimeout(()=>setBarsVisible(true),120);return()=>clearTimeout(t);},[]);

  const overallWin=(()=>{
    const winA=Object.keys(DUTIES).filter(dk=>(staffA.scores[dk]||0)>(staffB.scores[dk]||0)).length;
    const winB=Object.keys(DUTIES).filter(dk=>(staffB.scores[dk]||0)>(staffA.scores[dk]||0)).length;
    return winA>winB?'A':winB>winA?'B':'tie';
  })();
  const overallCol=overallWin==='A'?COL_A:overallWin==='B'?COL_B:"rgba(255,255,255,0.5)";
  const overallName=overallWin==='A'?staffA.name:overallWin==='B'?staffB.name:null;

  return(
    <div style={{position:"fixed",inset:0,background:"rgba(0,0,0,0.94)",backdropFilter:"blur(22px)",
      display:"flex",alignItems:"center",justifyContent:"center",zIndex:1100,padding:16}}
      onClick={onClose}>
      <div style={{background:"linear-gradient(160deg,#060e1a,#030910)",
        border:"1px solid rgba(255,255,255,0.08)",borderRadius:22,padding:24,
        maxWidth:680,width:"100%",maxHeight:"90vh",overflowY:"auto",
        animation:"compareIn 0.3s ease",position:"relative",
        boxShadow:"0 0 60px rgba(0,0,0,0.8)"}}
        onClick={e=>e.stopPropagation()}>

        {/* Dual-color top bar: blue left → red right */}
        <div style={{position:"absolute",top:0,left:0,right:0,height:2,borderRadius:"22px 22px 0 0",
          background:"linear-gradient(90deg,#00d4ff,#00d4ff66 35%,transparent 50%,#ff008066 65%,#ff0080)"}}/>
        <div style={{position:"absolute",top:0,left:0,bottom:0,width:2,borderRadius:"22px 0 0 22px",
          background:"linear-gradient(180deg,#00d4ff,#00d4ff22,transparent)"}}/>
        <div style={{position:"absolute",top:0,right:0,bottom:0,width:2,borderRadius:"0 22px 22px 0",
          background:"linear-gradient(180deg,#ff0080,#ff008022,transparent)"}}/>

        {/* Header */}
        <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:18}}>
          <span style={{fontFamily:"'Orbitron',monospace",fontWeight:900,fontSize:12,
            letterSpacing:"0.12em",
            background:"linear-gradient(90deg,#00d4ff,#fff,#ff0080)",
            WebkitBackgroundClip:"text",WebkitTextFillColor:"transparent",backgroundClip:"text"}}>
            ⚔ STAFF COMPARISON
          </span>
          <button onClick={onClose} style={{background:"#070d16",border:"1px solid #0d1825",
            borderRadius:8,color:"#7d99bd",cursor:"pointer",padding:"5px 10px",fontSize:14,lineHeight:1}}>✕</button>
        </div>

        {/* Player header cards */}
        <div style={{display:"grid",gridTemplateColumns:"1fr auto 1fr",gap:10,marginBottom:18,alignItems:"center"}}>
          {[staffA,staffB].map((s,si)=>{
            const col=si===0?COL_A:COL_B;
            const top=getTopTier(getEarnedBadges(s.scores));
            const isWinner=(si===0&&overallWin==='A')||(si===1&&overallWin==='B');
            return(
              <React.Fragment key={si}>
                {si===1&&(
                  <div style={{textAlign:"center",padding:"0 4px"}}>
                    <div style={{fontFamily:"'Orbitron',monospace",fontWeight:900,fontSize:15,
                      background:"linear-gradient(135deg,#00d4ff,#ff0080)",
                      WebkitBackgroundClip:"text",WebkitTextFillColor:"transparent",backgroundClip:"text",
                      marginBottom:4}}>VS</div>
                    <div style={{fontSize:7,color:"rgba(255,255,255,0.42)",fontFamily:"'Orbitron',monospace",
                      letterSpacing:"0.1em"}}>COMPARE</div>
                  </div>
                )}
                <div style={{
                  background:`${col}0a`,
                  border:`1px solid ${col}${isWinner?"66":"28"}`,
                  borderRadius:12,padding:"14px 16px",
                  boxShadow:isWinner?`0 0 28px ${col}28,inset 0 0 20px ${col}08`:`0 0 8px ${col}08`,
                  position:"relative",overflow:"hidden",
                }}>
                  {isWinner&&<div style={{position:"absolute",top:0,left:0,right:0,height:1,
                    background:`linear-gradient(90deg,transparent,${col}cc,transparent)`,
                    animation:"pulse 2s ease-in-out infinite"}}/>}
                  <div style={{fontSize:7,color:`${col}99`,fontFamily:"'Orbitron',monospace",
                    fontWeight:700,letterSpacing:"0.18em",marginBottom:6,
                    textAlign:si===0?"left":"right"}}>
                    {si===0?"◀ BLUE":"RED ▶"}{isWinner?" 🏆":""}
                  </div>
                  <div style={{fontFamily:"'Exo 2',sans-serif",fontWeight:800,fontSize:14,
                    color:isWinner?"#fff":"rgba(255,255,255,0.55)",marginBottom:6,
                    whiteSpace:"nowrap",overflow:"hidden",textOverflow:"ellipsis",
                    textAlign:si===0?"left":"right",
                    textShadow:isWinner?`0 0 18px ${col}77`:"none"}}>
                    {s.name}
                  </div>
                  <div style={{display:"flex",justifyContent:si===0?"flex-start":"flex-end",marginBottom:6}}>
                    {top&&<TierPill tier={top}/>}
                  </div>
                  <div style={{fontFamily:"'Orbitron',monospace",fontWeight:900,fontSize:17,
                    color:col,textShadow:isWinner?`0 0 20px ${col}`:`0 0 8px ${col}44`,
                    textAlign:si===0?"left":"right"}}>
                    {badgeScore(s.scores)}
                    <span style={{fontSize:8,color:"rgba(255,255,255,0.2)",marginLeft:4}}>PWR</span>
                  </div>
                </div>
              </React.Fragment>
            );
          })}
        </div>

        <div style={{fontSize:8,color:"rgba(255,255,255,0.2)",fontFamily:"'Orbitron',monospace",
          letterSpacing:"0.2em",marginBottom:10,textAlign:"center"}}>◈ DUTY BREAKDOWN</div>

        {/* Duty comparison rows */}
        {Object.entries(DUTIES).map(([dk,d])=>{
          const sA=staffA.scores[dk]||0, sB=staffB.scores[dk]||0;
          const total=Math.max(sA+sB,1);
          const rawPctA=Math.round(sA/total*100);
          const pA=barsVisible?rawPctA:0;
          const pB=barsVisible?(100-rawPctA):0;
          const win=sA>sB?'A':sB>sA?'B':'tie';
          const diff=Math.abs(sA-sB);
          const dominated=(Math.max(sA,sB)/total)>0.75;

          return(
            <div key={dk} style={{marginBottom:8,
              background:win==='A'?`linear-gradient(90deg,${COL_A}07,rgba(3,8,16,0.85))`
                        :win==='B'?`linear-gradient(90deg,rgba(3,8,16,0.85),${COL_B}07)`
                        :"rgba(3,8,16,0.85)",
              border:`1px solid ${win==='A'?COL_A+"30":win==='B'?COL_B+"30":"rgba(255,255,255,0.06)"}`,
              borderRadius:12,padding:"11px 14px",
              boxShadow:win==='A'?`-3px 0 0 0 ${COL_A}88,0 0 16px ${COL_A}0a`
                        :win==='B'?`3px 0 0 0 ${COL_B}88,0 0 16px ${COL_B}0a`
                        :"none",
              position:"relative",overflow:"hidden",
            }}>
              {/* Pulsing edge stripe on winner side */}
              {win!=='tie'&&<div style={{
                position:"absolute",top:0,
                left:win==='A'?0:"auto",right:win==='B'?0:"auto",
                width:3,height:"100%",
                background:win==='A'
                  ?`linear-gradient(180deg,${COL_A},${COL_A}44,transparent)`
                  :`linear-gradient(180deg,${COL_B},${COL_B}44,transparent)`,
                animation:"pulse 1.8s ease-in-out infinite",
              }}/>}

              {/* Score row */}
              <div style={{display:"flex",justifyContent:"space-between",marginBottom:8,alignItems:"center",gap:8}}>
                {/* A score */}
                <div style={{display:"flex",alignItems:"center",gap:5,flex:1}}>
                  {win==='A'&&<span style={{fontSize:12,lineHeight:1,
                    filter:`drop-shadow(0 0 8px ${COL_A})`,
                    animation:"crownBob 2.2s ease-in-out infinite",flexShrink:0}}>🏆</span>}
                  <div>
                    <div style={{
                      fontFamily:"'JetBrains Mono',monospace",fontWeight:900,
                      fontSize:win==='A'?18:12,lineHeight:1,
                      color:win==='A'?COL_A:win==='B'?"rgba(255,255,255,0.18)":"rgba(255,255,255,0.5)",
                      textShadow:win==='A'?`0 0 16px ${COL_A},0 0 32px ${COL_A}44`:"none",
                      transition:"all 0.4s",
                    }}>{fmt(sA)}</div>
                    {win==='A'&&diff>0&&<div style={{fontSize:7,color:`${COL_A}88`,
                      fontFamily:"'Orbitron',monospace",marginTop:2,fontWeight:700}}>
                      +{fmt(diff)} ahead
                    </div>}
                  </div>
                </div>

                {/* Center duty label */}
                <div style={{textAlign:"center",flexShrink:0}}>
                  <div style={{fontSize:14,lineHeight:1,marginBottom:2}}>{d.emoji}</div>
                  <div style={{fontSize:7,color:"rgba(255,255,255,0.3)",
                    fontFamily:"'Orbitron',monospace",fontWeight:700,letterSpacing:"0.1em",
                    whiteSpace:"nowrap"}}>{d.short}</div>
                </div>

                {/* B score */}
                <div style={{display:"flex",alignItems:"center",gap:5,flex:1,justifyContent:"flex-end",flexDirection:"row-reverse"}}>
                  {win==='B'&&<span style={{fontSize:12,lineHeight:1,
                    filter:`drop-shadow(0 0 8px ${COL_B})`,
                    animation:"crownBob 2.2s ease-in-out infinite",flexShrink:0}}>🏆</span>}
                  <div style={{textAlign:"right"}}>
                    <div style={{
                      fontFamily:"'JetBrains Mono',monospace",fontWeight:900,
                      fontSize:win==='B'?18:12,lineHeight:1,
                      color:win==='B'?COL_B:win==='A'?"rgba(255,255,255,0.18)":"rgba(255,255,255,0.5)",
                      textShadow:win==='B'?`0 0 16px ${COL_B},0 0 32px ${COL_B}44`:"none",
                      transition:"all 0.4s",
                    }}>{fmt(sB)}</div>
                    {win==='B'&&diff>0&&<div style={{fontSize:7,color:`${COL_B}88`,
                      fontFamily:"'Orbitron',monospace",marginTop:2,fontWeight:700,textAlign:"right"}}>
                      +{fmt(diff)} ahead
                    </div>}
                  </div>
                </div>
              </div>

              {/* THE BAR — BLUE left / RED right, winner gets shimmer + glow */}
              <div style={{height:12,borderRadius:6,overflow:"hidden",display:"flex",
                background:"rgba(0,0,0,0.5)",boxShadow:"inset 0 1px 4px rgba(0,0,0,0.7)"}}>
                {/* Blue A side */}
                <div style={{
                  width:`${pA}%`,
                  background:win==='A'
                    ?`linear-gradient(90deg,${COL_A}55,${COL_A}aa,${COL_A})`
                    :`linear-gradient(90deg,${COL_A}14,${COL_A}28)`,
                  transition:"width 1.3s cubic-bezier(0.2,0,0.05,1)",
                  borderRadius:"6px 0 0 6px",
                  boxShadow:win==='A'?`inset 0 0 10px ${COL_A}33,0 0 14px ${COL_A}55`:"none",
                  position:"relative",overflow:"hidden",flexShrink:0,
                }}>
                  {win==='A'&&pA>8&&(
                    <div style={{position:"absolute",inset:0,
                      background:"linear-gradient(90deg,transparent,rgba(255,255,255,0.3) 50%,transparent)",
                      backgroundSize:"200% 100%",
                      animation:"shimmer 1.6s linear infinite"}}/>
                  )}
                  {dominated&&win==='A'&&pA>18&&(
                    <div style={{position:"absolute",right:6,top:"50%",transform:"translateY(-50%)",
                      fontSize:8,filter:`drop-shadow(0 0 4px ${COL_A})`}}>⚡</div>
                  )}
                </div>
                {/* Red B side */}
                <div style={{
                  width:`${pB}%`,
                  background:win==='B'
                    ?`linear-gradient(90deg,${COL_B}55,${COL_B}aa,${COL_B})`
                    :`linear-gradient(90deg,${COL_B}14,${COL_B}28)`,
                  transition:"width 1.3s cubic-bezier(0.2,0,0.05,1)",
                  borderRadius:"0 6px 6px 0",
                  boxShadow:win==='B'?`inset 0 0 10px ${COL_B}33,0 0 14px ${COL_B}55`:"none",
                  position:"relative",overflow:"hidden",flexShrink:0,
                }}>
                  {win==='B'&&pB>8&&(
                    <div style={{position:"absolute",inset:0,
                      background:"linear-gradient(90deg,transparent,rgba(255,255,255,0.3) 50%,transparent)",
                      backgroundSize:"200% 100%",
                      animation:"shimmer 1.6s linear infinite"}}/>
                  )}
                  {dominated&&win==='B'&&pB>18&&(
                    <div style={{position:"absolute",left:6,top:"50%",transform:"translateY(-50%)",
                      fontSize:8,filter:`drop-shadow(0 0 4px ${COL_B})`}}>⚡</div>
                  )}
                </div>
              </div>

              {/* % labels */}
              <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginTop:5}}>
                <span style={{
                  fontSize:9,fontFamily:"'JetBrains Mono',monospace",fontWeight:700,
                  color:win==='A'?`${COL_A}dd`:win==='B'?"rgba(255,255,255,0.12)":"rgba(255,255,255,0.3)",
                  textShadow:win==='A'?`0 0 8px ${COL_A}`:"none",
                }}>{rawPctA}%</span>
                {win==='tie'
                  ?<span style={{fontSize:7,color:"rgba(255,255,255,0.2)",fontFamily:"'Orbitron',monospace",
                      fontWeight:700,letterSpacing:"0.12em"}}>EQUAL</span>
                  :<div style={{height:1,flex:1,margin:"0 8px",
                      background:`linear-gradient(90deg,${win==='A'?COL_A+"44":"rgba(255,255,255,0.04)"},${win==='B'?COL_B+"44":"rgba(255,255,255,0.04)"})`}}/>
                }
                <span style={{
                  fontSize:9,fontFamily:"'JetBrains Mono',monospace",fontWeight:700,
                  color:win==='B'?`${COL_B}dd`:win==='A'?"rgba(255,255,255,0.12)":"rgba(255,255,255,0.3)",
                  textShadow:win==='B'?`0 0 8px ${COL_B}`:"none",
                }}>{100-rawPctA}%</span>
              </div>
            </div>
          );
        })}

        {/* Overall verdict */}
        <div style={{marginTop:6,
          background:`linear-gradient(135deg,${overallCol}0d,rgba(3,8,16,0.9))`,
          border:`1px solid ${overallCol}40`,
          borderRadius:12,padding:"12px 18px",textAlign:"center",
          boxShadow:`0 0 30px ${overallCol}18`,position:"relative",overflow:"hidden"}}>
          <div style={{position:"absolute",top:0,left:0,right:0,height:1,
            background:`linear-gradient(90deg,transparent,${overallCol}88,transparent)`,
            animation:"pulse 2s ease-in-out infinite"}}/>
          {overallWin==='tie'
            ?<span style={{fontFamily:"'Orbitron',monospace",fontSize:10,
                color:"rgba(255,255,255,0.3)",fontWeight:700,letterSpacing:"0.15em"}}>
                ⚖️ PERFECTLY MATCHED — TOO CLOSE TO CALL
              </span>
            :<span style={{fontFamily:"'Orbitron',monospace",fontSize:11,fontWeight:900,
                letterSpacing:"0.08em",color:overallCol,textShadow:`0 0 16px ${overallCol}`}}>
                🏆 OVERALL WINNER: <span style={{color:"#fff",textShadow:`0 0 20px ${overallCol}`}}>{overallName}</span>
              </span>
          }
        </div>
      </div>
    </div>
  );
}

function ProfileModal({staff,onClose,onCompare}){
  const badges=getEarnedBadges(staff.scores);
  const top=getTopTier(badges);
  const tc=top?TC[top]:null;
  const dominantDk=getDominantDuty(staff.scores);
  const bs=badgeScore(staff.scores);
  const fired=useRef(false);

  useEffect(()=>{
    if(top==="God"&&!fired.current){
      fired.current=true;
      setTimeout(()=>spawnConfetti(true),350);
      SFX.play('god');
    } else {
      SFX.play('open');
    }
  },[]);

  return(
    <div style={{position:"fixed",inset:0,background:"rgba(0,0,0,0.92)",backdropFilter:"blur(24px)",
      display:"flex",alignItems:"center",justifyContent:"center",zIndex:1000,padding:20}}
      onClick={onClose}>
      <div style={{background:"linear-gradient(160deg,#060e1a,#030910)",
        border:`1px solid ${tc?tc.border+"44":"#0d1825"}`,borderRadius:22,padding:30,
        maxWidth:540,width:"100%",
        boxShadow:tc?`0 0 80px ${tc.glow},0 50px 120px rgba(0,0,0,0.99)`:"0 50px 120px rgba(0,0,0,0.99)",
        maxHeight:"88vh",overflowY:"auto",animation:"fadeUp 0.26s ease",position:"relative"}}
        onClick={e=>e.stopPropagation()}>
        {tc&&<div style={{position:"absolute",top:0,left:0,right:0,height:1,borderRadius:"22px 22px 0 0",
          background:`linear-gradient(90deg,transparent,${tc.border},transparent)`}}/>}

        <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:24}}>
          <div style={{display:"flex",alignItems:"center",gap:13}}>
            <div style={{width:52,height:52,borderRadius:13,
              background:tc?tc.bg:"#060e18",border:`2px solid ${tc?tc.border+"66":"#0d1825"}`,
              display:"flex",alignItems:"center",justifyContent:"center",
              fontSize:22,fontFamily:"'Orbitron',monospace",fontWeight:900,
              color:tc?tc.border:"#1a2535",boxShadow:tc?`0 0 26px ${tc.glow}`:"none",overflow:"hidden"}}>
              {staff.avatar_url ? <img src={staff.avatar_url} style={{width:"100%",height:"100%",objectFit:"cover"}} onError={(e)=>{e.target.style.display='none'}} alt=""/> : staff.name[0].toUpperCase()}
            </div>
            <div>
              <h2 style={{color:"#f0f4f8",fontFamily:"'Orbitron',monospace",fontWeight:900,fontSize:17,
                textShadow:tc?`0 0 20px ${tc.border}88`:"none",marginBottom:4}}>{staff.name}</h2>
              {staff.role&&<div style={{fontSize:9,color:"rgba(0,212,255,0.5)",fontFamily:"'Orbitron',monospace",
                letterSpacing:"0.18em",fontWeight:700,marginBottom:6}}>{staff.role.toUpperCase()}</div>}
              <div style={{display:"flex",gap:7,flexWrap:"wrap",alignItems:"center"}}>
                {top&&<TierPill tier={top} size="lg"/>}
                <span style={{fontSize:9,color:"#7d99bd",fontFamily:"'JetBrains Mono',monospace"}}>
                  {Object.keys(badges).length} badge{Object.keys(badges).length!==1?"s":""} earned
                </span>
              </div>
            </div>
          </div>
          <div style={{display:"flex",gap:8,alignItems:"center",flexShrink:0}}>
            <button onClick={()=>onCompare(staff)}
              onMouseEnter={e=>e.currentTarget.style.background="rgba(0,212,255,0.15)"}
              onMouseLeave={e=>e.currentTarget.style.background="rgba(0,212,255,0.07)"}
              style={{background:"rgba(0,212,255,0.07)",border:"1px solid rgba(0,212,255,0.25)",
                borderRadius:8,padding:"6px 11px",cursor:"pointer",color:"rgba(0,212,255,0.8)",
                fontFamily:"'Orbitron',monospace",fontSize:8,fontWeight:700,letterSpacing:"0.1em",
                transition:"all 0.15s",whiteSpace:"nowrap"}}>⚔ COMPARE</button>
            <ShareButton staff={staff}/>
            <button className="close-btn" onClick={onClose} style={{background:"#070d16",
              border:"1px solid #0d1825",borderRadius:8,color:"#7d99bd",
              cursor:"pointer",padding:"6px 11px",fontSize:14,lineHeight:1,transition:"all 0.15s"}}>✕</button>
          </div>
        </div>

        {/* ── Power Tier Badge ── */}
        {(()=>{
          const pt=getPowerTier(staff.scores);
          const nextPt=getNextPowerTier(staff.scores);
          if(!pt) return null;
          const ptc=TC[pt.tier];
          return(
            <div style={{marginBottom:16,background:`linear-gradient(135deg,${ptc.border}0c,rgba(3,8,16,0.9))`,
              border:`1px solid ${ptc.border}35`,borderRadius:12,padding:"12px 16px",
              animation:"fadeUp 0.35s ease both"}}>
              <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",gap:12}}>
                <div style={{display:"flex",alignItems:"center",gap:10}}>
                  <div style={{width:36,height:36,borderRadius:10,
                    background:`${ptc.border}18`,border:`1.5px solid ${ptc.border}55`,
                    display:"flex",alignItems:"center",justifyContent:"center",
                    fontSize:18,boxShadow:`0 0 12px ${ptc.glow}`}}>{ptc.icon}</div>
                  <div>
                    <div style={{fontFamily:"'Orbitron',monospace",fontWeight:900,fontSize:11,
                      color:ptc.border,letterSpacing:"0.12em",textShadow:`0 0 12px ${ptc.glow}`}}>
                      {pt.tier.toUpperCase()} POWER TIER
                    </div>
                    <div style={{fontSize:9,color:"rgba(255,255,255,0.35)",fontFamily:"'JetBrains Mono',monospace",marginTop:2}}>
                      Earned +{pt.waveReward} 🌊 Wave Points
                    </div>
                  </div>
                </div>
                <div style={{textAlign:"right"}}>
                  <div style={{fontFamily:"'Orbitron',monospace",fontWeight:900,fontSize:18,
                    color:ptc.border,textShadow:`0 0 16px ${ptc.glow}`}}>{bs}</div>
                  <div style={{fontSize:7,color:"rgba(255,255,255,0.2)",fontFamily:"'Orbitron',monospace",
                    letterSpacing:"0.12em"}}>PWR PTS</div>
                </div>
              </div>
              {nextPt&&(
                <div style={{marginTop:8,display:"flex",alignItems:"center",gap:6,
                  fontSize:8,color:"rgba(255,255,255,0.5)",fontFamily:"'JetBrains Mono',monospace"}}>
                  <div style={{flex:1,height:2,borderRadius:2,background:"rgba(10,20,34,0.9)",overflow:"hidden"}}>
                    <div style={{height:"100%",borderRadius:2,
                      width:`${Math.min(100,((bs-pt.minPts)/(nextPt.minPts-pt.minPts))*100)}%`,
                      background:`linear-gradient(90deg,${ptc.border}70,${TC[nextPt.tier].border})`,
                      transition:"width 1s ease"}}/>
                  </div>
                  <span>{nextPt.minPts-bs} pts → {TC[nextPt.tier].icon} {nextPt.tier}</span>
                </div>
              )}
            </div>
          );
        })()}

        <div style={{display:"flex",gap:8,marginBottom:20,flexWrap:"wrap"}}>
          <div style={{flex:1,minWidth:90,background:"rgba(3,8,16,0.85)",border:"1px solid #0d1825",
            borderRadius:10,padding:"10px 14px",textAlign:"center"}}>
            <div style={{fontFamily:"'Orbitron',monospace",fontWeight:900,fontSize:20,color:"#00d4ff",marginBottom:2}}>{bs}</div>
            <div style={{fontSize:7,color:"#1a2c3a",fontFamily:"'Orbitron',monospace",letterSpacing:"0.15em"}}>POWER SCORE</div>
          </div>
          <div style={{flex:1,minWidth:90,background:"rgba(3,8,16,0.85)",border:"1px solid #0d1825",
            borderRadius:10,padding:"10px 14px",textAlign:"center"}}>
            <div style={{fontFamily:"'Orbitron',monospace",fontWeight:900,fontSize:20,color:"#a78bfa",marginBottom:2}}>{Object.keys(badges).length}</div>
            <div style={{fontSize:7,color:"#1a2c3a",fontFamily:"'Orbitron',monospace",letterSpacing:"0.15em"}}>BADGES</div>
          </div>
          {dominantDk&&<div style={{flex:1,minWidth:90,background:"rgba(3,8,16,0.85)",
            border:`1px solid ${DUTIES[dominantDk].color}25`,borderRadius:10,padding:"10px 14px",textAlign:"center"}}>
            <div style={{fontSize:18,marginBottom:2}}>{DUTIES[dominantDk].emoji}</div>
            <div style={{fontSize:7,color:DUTIES[dominantDk].color,fontFamily:"'Orbitron',monospace",letterSpacing:"0.1em",fontWeight:700}}>DOMINANT</div>
          </div>}
          {staff.role&&<div style={{flex:1,minWidth:90,background:"rgba(0,212,255,0.04)",
            border:"1px solid rgba(0,212,255,0.15)",borderRadius:10,padding:"10px 14px",textAlign:"center"}}>
            <div style={{fontFamily:"'Orbitron',monospace",fontWeight:900,fontSize:10,
              color:"#00d4ff",lineHeight:1.3,marginBottom:4}}>{staff.role.toUpperCase()}</div>
            <div style={{fontSize:7,color:"#1a2c3a",fontFamily:"'Orbitron',monospace",letterSpacing:"0.15em"}}>ROLE</div>
          </div>}
        </div>

        <div style={{fontSize:8,color:"#00d4ff",fontFamily:"'Orbitron',monospace",fontWeight:700,
          letterSpacing:"0.22em",marginBottom:10,textShadow:"0 0 12px #00d4ff55"}}>◈ DUTY BREAKDOWN</div>

        {Object.entries(DUTIES).map(([dk,d],i)=>{
          const score=staff.scores[dk]||0;
          const tier=getDutyTier(score,dk);
          const tc2=tier?TC[tier]:null;
          const next=getNextTarget(score,dk);
          let pct=0;
          if(next){const ti=TIERS.indexOf(next.tier);const prev=ti>0?d.thresholds[TIERS[ti-1]]:0;pct=Math.min(100,((score-prev)/(next.needed-prev))*100);}
          else pct=100;
          const col=tier?tc2.border:d.color;
          const glow=tier?tc2.glow:d.color+"55";
          return(
            <div key={dk} style={{background:"rgba(3,7,14,0.85)",
              border:`1px solid ${tier?tc2.border+"2e":d.color+"18"}`,
              borderRadius:11,padding:"12px 14px",marginBottom:7,
              borderLeft:`3px solid ${tier?tc2.border:d.color+"45"}`,
              animation:`fadeUp 0.3s ${i*0.07}s ease both`}}>
              <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:4}}>
                <span style={{fontSize:12,color:d.color,fontFamily:"'Exo 2',sans-serif",fontWeight:800}}>
                  {d.emoji} {d.label}
                </span>
                <div style={{display:"flex",alignItems:"center",gap:7}}>
                  {tier&&<TierPill tier={tier}/>}
                  <span style={{fontSize:13,color:"rgba(255,255,255,0.8)",fontFamily:"'JetBrains Mono',monospace",fontWeight:700}}>
                    {score.toLocaleString()}
                  </span>
                </div>
              </div>
              <AnimatedBar pct={pct} col={col} glow={glow} delay={180+i*110}/>
              {next?(
                <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",
                  marginTop:6,background:`linear-gradient(90deg,${col}10,transparent)`,
                  border:`1px solid ${col}28`,borderRadius:7,padding:"5px 10px",
                  animation:`tipPop 0.35s ${340+i*110}ms ease both`}}>
                  <span style={{fontSize:10,fontFamily:"'JetBrains Mono',monospace",fontWeight:700,color:col}}>
                    {(next.needed-score).toLocaleString()} more needed
                  </span>
                  <span style={{display:"flex",alignItems:"center",gap:5,
                    fontFamily:"'Orbitron',monospace",fontWeight:700,fontSize:10,color:"rgba(255,255,255,0.75)"}}>
                    <span style={{fontSize:8,color:"rgba(255,255,255,0.3)"}}>NEXT:</span>
                    {TC[next.tier].icon} {next.tier.toUpperCase()}
                    <span style={{fontSize:9,background:`${col}20`,border:`1px solid ${col}40`,
                      borderRadius:4,padding:"1px 6px",color:col}}>{Math.round(pct)}%</span>
                  </span>
                </div>
              ):(
                <div style={{marginTop:6,background:"rgba(255,0,128,0.08)",
                  border:"1px solid rgba(255,0,128,0.3)",borderRadius:7,padding:"5px 10px",textAlign:"center",
                  animation:`tipPop 0.35s ${340+i*110}ms ease both`}}>
                  <span style={{fontSize:10,color:"#ff0080",fontFamily:"'Orbitron',monospace",
                    fontWeight:900,textShadow:"0 0 10px #ff008099",letterSpacing:"0.08em"}}>
                    👑 MAX TIER REACHED
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

const DEMO=[
  {name:"fleck.777",      role:"Head of Staff",  weekly:{message:1200,role:400,req:80,modlog:40},  scores:{message:12400,role:4800,req:980,modlog:620}},
  {name:"slaxmgmt",       role:"Senior Support", weekly:{message:700, role:400,req:200,modlog:30},  scores:{message:9800, role:6200,req:2400,modlog:430}},
  {name:"luan_fv.",       role:"Senior Support", weekly:{message:300, role:200,req:200,modlog:15},  scores:{message:6100, role:2900,req:3200, modlog:155}},
  {name:"ztrytytka",      role:"Support",        weekly:{message:500, role:200,req:20, modlog:8},   scores:{message:3500, role:1200,req:420, modlog:88}},
  {name:"blanket_god",    role:"Support",        weekly:{message:200, role:100,req:20, modlog:10},  scores:{message:2200, role:900, req:180, modlog:210}},
  {name:"meandme7634567", role:"Trial Support",  weekly:{message:200, role:50, req:15, modlog:7},   scores:{message:1100, role:400, req:95, modlog:62}},
  {name:"banana.lecl3rc", role:"Trial Support",  weekly:{message:200, role:50, req:15, modlog:6},   scores:{message:800,  role:310, req:45,  modlog:30}},
  {name:"joaco_t6",       role:"Trial Support",  weekly:{message:150, role:50, req:10, modlog:4},   scores:{message:500,  role:200, req:30,  modlog:12}},
];

function App(){
  const [staffList,setStaffList]=useState(DEMO);
  const [selected,setSelected]=useState(null);
  const [search,setSearch]=useState("");
  const [loaded,setLoaded]=useState(false);
  const [lastSync,setLastSync]=useState(null);
  const [dataSource,setDataSource]=useState("demo");
  const [activeTab,setActiveTab]=useState("all");
  const [sortMode,setSortMode]=useState("score");
  const [tierFilter,setTierFilter]=useState(null);
  const [compareA,setCompareA]=useState(null);
  const [comparePending,setComparePending]=useState(false);
  const searchRef=useRef(null);

  useEffect(()=>{
    (async()=>{
      try{
        const r=await fetch(DATA_URL+"?t="+Date.now());
        if(r.ok){
          const j=await r.json();
          const s=Object.entries(j).map(([name,entry])=>{
            // "role" in old JSON = Role Giver duty score (number)
            // "role" in new JSON = staff role string e.g. "Senior Support"
            // Distinguish by type: only treat it as staff role if it's a string
            const staffRole=typeof entry.role==='string'?entry.role:null;
            const staffAvatar=typeof entry.avatar_url==='string'?entry.avatar_url:null;
            const scores={},weekly={};
            for(const [k,v] of Object.entries(entry)){
              if(k==='role'&&typeof v==='string') continue; // staff role field, not a score
              if(k==='uid') continue;
              if(k==='avatar_url') continue;
              if(k==='purge'||k==='purge_weekly') continue; // skip purge duty (redundant, removed)
              if(k.endsWith('_weekly')) weekly[k.replace('_weekly','')]=v;
              else scores[k]=v;
            }
            return{name,scores,weekly,role:staffRole||"Staff",avatar_url:staffAvatar};
          });
          if(s.length>0){setStaffList(s);setLastSync(new Date().toISOString());setDataSource("github");setLoaded(true);return;}
        }
      }catch{}
      setLoaded(true);
    })();
  },[]);

  useEffect(()=>{
    const tabs=["all",...Object.keys(DUTIES),"rising"];
    const handler=(e)=>{
      if(e.target.tagName==="INPUT") return;
      if(e.key==="Escape"){setSelected(null);return;}
      const num=parseInt(e.key);
      if(num>=1&&num<=tabs.length) setActiveTab(tabs[num-1]);
    };
    window.addEventListener("keydown",handler);
    return()=>window.removeEventListener("keydown",handler);
  },[]);

  const uniqueRoles=[...new Set(staffList.map(s=>s.role).filter(Boolean))].sort();
  const baseFiltered=staffList.filter(s=>s.name.toLowerCase().includes(search.toLowerCase()));
  const tierFiltered=tierFilter
    ? baseFiltered.filter(s=>{
        if(activeTab==="all") return Object.values(getEarnedBadges(s.scores)).includes(tierFilter);
        return getDutyTier(s.scores[activeTab]||0,activeTab)===tierFilter;
      })
    : baseFiltered;
  const filtered=tierFiltered;

  const totalBadges=staffList.reduce((n,s)=>n+Object.keys(getEarnedBadges(s.scores)).length,0);
  const godCount=staffList.filter(s=>getTopTier(getEarnedBadges(s.scores))==="God").length;

  function applySort(arr, dk){
    const a=[...arr];
    if(sortMode==="alpha") return a.sort((x,y)=>x.name.localeCompare(y.name));
    if(sortMode==="tier") return a.sort((x,y)=>badgeScore(y.scores)-badgeScore(x.scores));
    return a.sort((x,y)=>(y.scores[dk]||0)-(x.scores[dk]||0));
  }

  function sortedByDuty(dk){return applySort(filtered,dk);}
  function handleViewAll(dk){setSearch("");setActiveTab(dk);window.scrollTo({top:0,behavior:"smooth"});}

  function handleCompare(staff){
    if(!compareA){
      setCompareA(staff);
      setComparePending(true);
      setSelected(null);
    } else if(compareA.name===staff.name){
      setCompareA(null);setComparePending(false);
    } else {
      setComparePending(false);
      setSelected({__compare:true,a:compareA,b:staff});
      setCompareA(null);
    }
  }

  function handleRowClick(staff){
    if(comparePending){
      handleCompare(staff);
    } else {
      setSelected(staff);
    }
  }

  if(!loaded) return(
    <div style={{minHeight:"100vh",display:"flex",alignItems:"center",justifyContent:"center",
      flexDirection:"column",gap:16,position:"relative",zIndex:2}}>
      <div style={{fontSize:36,animation:"glow 1.2s infinite"}}>⚡</div>
      <span style={{color:"#00d4ff",fontFamily:"'Orbitron',monospace",fontSize:11,
        letterSpacing:"0.3em",textShadow:"0 0 24px #00d4ff"}}>LOADING...</span>
    </div>
  );

  const dutyKeys=Object.keys(DUTIES);
  const tabs=["all",...dutyKeys,"rising","hof"];

  return(
    <div style={{minHeight:"100vh",padding:"22px 20px 90px",position:"relative",zIndex:2}}>
      <div style={{textAlign:"center",marginBottom:20,animation:"fadeDown 0.55s ease",maxWidth:860,margin:"0 auto 20px"}}>
        <div style={{display:"inline-flex",alignItems:"center",gap:8,
          background:"rgba(0,212,255,0.06)",border:"1px solid rgba(0,212,255,0.18)",
          borderRadius:100,padding:"5px 16px",marginBottom:14,position:"relative"}}>
          <div style={{position:"relative",width:7,height:7,flexShrink:0}}>
            <div style={{position:"absolute",inset:0,borderRadius:"50%",background:"#00ff88",
              boxShadow:"0 0 8px #00ff88"}}/>
            <div style={{position:"absolute",inset:0,borderRadius:"50%",background:"#00ff88",
              animation:"livePing 1.8s ease-out infinite"}}/>
          </div>
          <span style={{fontSize:9,color:"rgba(0,212,255,0.75)",fontFamily:"'Orbitron',monospace",
            letterSpacing:"0.18em",fontWeight:700}}>
            WAVE MANAGEMENT · LIVE
            {lastSync?` · ${new Date(lastSync).toLocaleDateString("en-GB",{day:"2-digit",month:"short"}).toUpperCase()}`:""}
          </span>
        </div>

        <h1 style={{fontSize:"clamp(40px,9vw,88px)",fontWeight:900,fontFamily:"'Orbitron',monospace",
          background:"linear-gradient(90deg,#00d4ff,#a0e8ff,#ffffff,#ff80c0,#ff0080)",
          backgroundSize:"200% auto",
          WebkitBackgroundClip:"text",WebkitTextFillColor:"transparent",backgroundClip:"text",
          letterSpacing:"-0.02em",lineHeight:0.95,marginBottom:8,
          animation:"titleShimmer 5s ease-in-out infinite",
          filter:"drop-shadow(0 0 40px rgba(0,212,255,0.6)) drop-shadow(0 0 80px rgba(255,0,128,0.15))"}}>
          LIFETIME
        </h1>

        <div style={{display:"flex",alignItems:"center",justifyContent:"center",gap:12,marginBottom:18}}>
          <div style={{height:1,width:60,background:"linear-gradient(90deg,transparent,rgba(255,255,255,0.42))"}}/>
          <div style={{fontSize:"clamp(10px,1.8vw,15px)",fontWeight:700,fontFamily:"'Orbitron',monospace",
            letterSpacing:"0.55em",
            background:"linear-gradient(90deg,rgba(0,212,255,0.6),rgba(255,255,255,0.5),rgba(255,0,128,0.6))",
            WebkitBackgroundClip:"text",WebkitTextFillColor:"transparent",backgroundClip:"text"}}>
            · ACTIVITY ·
          </div>
          <div style={{height:1,width:60,background:"linear-gradient(90deg,rgba(255,255,255,0.42),transparent)"}}/>
        </div>

        <div style={{display:"inline-flex",alignItems:"center",
          background:"rgba(5,12,22,0.88)",border:"1px solid #0d1825",
          borderRadius:10,overflow:"hidden",marginBottom:14}}>
          {[
            {label:"STAFF",val:staffList.length,col:"#00d4ff"},
            {label:"BADGES",val:totalBadges,col:"#a78bfa"},
            {label:"DUTIES",val:dutyKeys.length,col:"#00ff88"},
            {label:"GOD TIER",val:godCount,col:"#ff0080"},
          ].map((s,i)=>(
            <div key={s.label} style={{padding:"9px 20px",textAlign:"center",
              borderRight:i<3?"1px solid #0d1825":"none",position:"relative"}}>
              <div style={{position:"absolute",top:0,left:0,right:0,height:1,
                background:`linear-gradient(90deg,transparent,${s.col}44,transparent)`}}/>
              <div style={{fontFamily:"'Orbitron',monospace",fontWeight:900,fontSize:19,
                color:s.col,lineHeight:1,marginBottom:3,textShadow:`0 0 12px ${s.col}66`}}>
                <AnimatedNumber value={s.val}/>
              </div>
              <div style={{fontFamily:"'Orbitron',monospace",fontSize:7,color:"#7d99bd",
                letterSpacing:"0.2em"}}>{s.label}</div>
            </div>
          ))}
        </div>

        {dataSource==="demo"&&(
          <div><div style={{display:"inline-flex",alignItems:"center",gap:6,
            background:"rgba(255,170,0,0.04)",border:"1px solid rgba(255,170,0,0.14)",
            borderRadius:7,padding:"4px 12px",fontSize:9,color:"#ffaa00",
            fontFamily:"'JetBrains Mono',monospace"}}>
            ⚠️ DEMO DATA — bot syncs real scores automatically
          </div></div>
        )}
        {dataSource==="github"&&(
          <div><div style={{display:"inline-flex",alignItems:"center",gap:6,
            background:"rgba(0,255,136,0.03)",border:"1px solid rgba(0,255,136,0.14)",
            borderRadius:7,padding:"4px 12px",fontSize:9,color:"#00ff88",
            fontFamily:"'JetBrains Mono',monospace"}}>
            ✅ LIVE DATA · Updated {lastSync?new Date(lastSync).toLocaleTimeString("en-GB",{hour:"2-digit",minute:"2-digit"}):"--:--"}
          </div></div>
        )}
      </div>

      <HowItWorks/>

      {comparePending&&compareA&&(
        <div style={{maxWidth:860,margin:"0 auto 12px",
          background:"linear-gradient(90deg,rgba(0,212,255,0.07),rgba(0,212,255,0.03))",
          border:"1px solid rgba(0,212,255,0.28)",borderRadius:10,
          padding:"10px 18px",display:"flex",alignItems:"center",justifyContent:"space-between",
          animation:"fadeUp 0.3s ease"}}>
          <span style={{fontFamily:"'Orbitron',monospace",fontSize:9,color:"#00d4ff",
            fontWeight:700,letterSpacing:"0.1em"}}>
            ⚔ COMPARING: <span style={{color:"#fff"}}>{compareA.name}</span> — click another profile to compare
          </span>
          <button onClick={()=>{setCompareA(null);setComparePending(false);}} style={{
            background:"none",border:"1px solid rgba(0,212,255,0.2)",borderRadius:6,
            padding:"3px 10px",cursor:"pointer",color:"rgba(0,212,255,0.5)",
            fontFamily:"'Orbitron',monospace",fontSize:8}}>CANCEL</button>
        </div>
      )}

      <div style={{maxWidth:860,margin:"0 auto 18px"}}>
        <div style={{display:"flex",gap:8,alignItems:"center",marginBottom:14}}>
        <div className="search-wrap" style={{
          flex:1,position:"relative",
          background:"rgba(5,12,22,0.92)",
          border:"1px solid #0d1825",borderRadius:12,
          display:"flex",alignItems:"center",gap:0,
          transition:"border-color 0.2s",
        }}>
          <div style={{padding:"0 14px",color:"#1e3a52",fontSize:16,flexShrink:0,
            display:"flex",alignItems:"center"}}>🔍</div>
          <input
            ref={searchRef}
            value={search}
            onChange={e=>setSearch(e.target.value)}
            placeholder="Search staff by name..."
            style={{flex:1,background:"transparent",border:"none",color:"#c0d4e0",padding:"12px 0",
              fontSize:13,fontFamily:"'Exo 2',sans-serif",fontWeight:600,
              outline:"none",letterSpacing:"0.02em"}}
          />
          {search&&(
            <button onClick={()=>{setSearch("");searchRef.current?.focus();}} style={{
              background:"none",border:"none",cursor:"pointer",
              padding:"0 14px",color:"#7d99bd",fontSize:16,
              display:"flex",alignItems:"center",transition:"color 0.15s"}}
              onMouseEnter={e=>e.target.style.color="#ccc"}
              onMouseLeave={e=>e.target.style.color="#7d99bd"}
            >✕</button>
          )}
          {!search&&(
            <div style={{padding:"0 14px",fontSize:9,color:"#1a2c3a",
              fontFamily:"'Orbitron',monospace",letterSpacing:"0.1em",flexShrink:0}}>
              {filtered.length} / {staffList.length}
            </div>
          )}
        </div>
        <SoundToggle/>
        </div>

        <div style={{display:"flex",gap:5,flexWrap:"wrap",justifyContent:"center",marginBottom:10}}>
          {tabs.map(t=>{
            const isAll=t==="all", isHof=t==="hof", isRising=t==="rising";
            const d=(!isAll&&!isHof&&!isRising)?DUTIES[t]:null;
            const active=activeTab===t;
            const col=isAll?"#00d4ff":isHof?"#ff0080":isRising?"#ffaa00":d.color;
            const glowCol=isAll?"rgba(0,212,255,0.55)":isHof?"rgba(255,0,128,0.55)":isRising?"rgba(255,170,0,0.55)":`${d.color}88`;
            return(
              <button key={t} className={`tab-btn duty-btn`}
                onClick={()=>{SFX.play('tab');setActiveTab(t);setSearch("");setTierFilter(null);}}
                style={{
                  '--gc': glowCol,
                  background: active ? `linear-gradient(135deg,${col}22,${col}0a)` : "rgba(6,13,26,0.9)",
                  border: `1px solid ${active ? col+"88" : col+"28"}`,
                  borderRadius:8,padding:"7px 14px",
                  color: active ? col : col+"88",
                  fontFamily:"'Orbitron',monospace",fontWeight:700,fontSize:8,letterSpacing:"0.12em",
                  display:"flex",alignItems:"center",gap:5,
                  boxShadow: active ? `0 0 18px ${glowCol}, 0 0 40px ${glowCol}55, inset 0 0 12px ${col}12` : `0 0 0 0 transparent`,
                  textShadow: active ? `0 0 10px ${col}` : "none",
                  filter: active ? "brightness(1.2)" : "brightness(0.9)",
                }}>
                {isAll&&<><span style={{fontSize:10}}>◈</span> ALL</>}
                {isHof&&<><span style={{fontSize:10}}>👑</span> HALL OF FAME</>}
                {isRising&&<><span style={{fontSize:10}}>📈</span> RISING</>}
                {d&&<><span style={{fontSize:12}}>{d.emoji}</span> {d.short}</>}
              </button>
            );
          })}
        </div>

      </div>

      <div style={{maxWidth:860,margin:"0 auto"}}>
        {activeTab==="hof"&&(
          <div style={{animation:"fadeUp 0.35s ease both"}}>
            <HallOfFame staffList={staffList} onSelect={handleRowClick}/>
          </div>
        )}

        {activeTab==="all"&&(
          <div style={{animation:"fadeUp 0.35s ease both"}}>
            <div style={{
              position:"relative",overflow:"hidden",
              background:"linear-gradient(135deg,rgba(3,8,16,0.98),rgba(0,212,255,0.04))",
              border:"1px solid rgba(0,212,255,0.2)",
              borderRadius:"14px 14px 0 0",padding:"20px 22px 18px",marginBottom:0,
            }}>
              <div style={{position:"absolute",top:0,left:0,right:0,height:1,
                background:"linear-gradient(90deg,transparent,#00d4ffdd 50%,transparent)"}}/>
              <div style={{position:"absolute",top:0,left:0,bottom:0,width:3,
                background:"linear-gradient(180deg,#00d4ff,#00d4ff33,transparent)",borderRadius:"14px 0 0 0"}}/>
              <div style={{display:"flex",alignItems:"center",gap:12}}>
                <div style={{width:42,height:42,borderRadius:11,flexShrink:0,
                  background:"rgba(0,212,255,0.1)",border:"1px solid rgba(0,212,255,0.25)",
                  display:"flex",alignItems:"center",justifyContent:"center",fontSize:20,
                  boxShadow:"0 0 14px rgba(0,212,255,0.2)"}}>⭐</div>
                <div>
                  <h2 style={{fontFamily:"'Orbitron',monospace",fontWeight:900,fontSize:"clamp(13px,2vw,18px)",
                    color:"#00d4ff",textShadow:"0 0 16px #00d4ff88",marginBottom:3,letterSpacing:"0.03em"}}>
                    POWER SCORE LEADERBOARD
                  </h2>
                  <p style={{fontSize:11,color:"rgba(255,255,255,0.5)",fontFamily:"'Exo 2',sans-serif"}}>
                    Ranked by total badge points across all duties
                  </p>
                </div>
              </div>
            </div>

            <div style={{background:"rgba(2,5,12,0.7)",
              borderLeft:"1px solid rgba(0,212,255,0.1)",borderRight:"1px solid rgba(0,212,255,0.1)",
              borderBottom:"1px solid rgba(0,212,255,0.1)",
              borderRadius:"0 0 14px 14px",padding:"10px 14px 14px",marginBottom:16}}>
              <div style={{display:"flex",gap:6,justifyContent:"flex-end",flexWrap:"wrap"}}>
                {TIERS.map(t=>(
                  <div key={t} style={{display:"flex",alignItems:"center",gap:4,
                    fontSize:8,fontFamily:"'JetBrains Mono',monospace",color:TC[t].border}}>
                    {TC[t].icon} {t} = {({Bronze:1,Silver:2,Gold:4,Legend:8,God:16})[t]}pt
                  </div>
                ))}
              </div>
            </div>

            {search&&filtered.length===0&&(
              <div style={{textAlign:"center",padding:60,color:"#1a2c3a",
                fontFamily:"'Orbitron',monospace",fontSize:10,letterSpacing:"0.22em"}}>
                NO STAFF MATCH "{search.toUpperCase()}"
              </div>
            )}

            <div style={{display:"flex",flexDirection:"column",gap:7}}>
              {[...filtered].sort((a,b)=>badgeScore(b.scores)-badgeScore(a.scores)).map((s,i)=>{
                const bs=badgeScore(s.scores);
                const badges=getEarnedBadges(s.scores);
                const top=getTopTier(badges);
                const tc=top?TC[top]:null;
                const rCol=i===0?"#ffd700":i===1?"#b8c4d0":i===2?"#cd7f32":null;
                return(
                  <div key={s.name} className="row-card" onClick={()=>handleRowClick(s)} style={{
                    display:"grid",gridTemplateColumns:"46px 1fr auto",
                    alignItems:"center",gap:16,
                    background:tc?`linear-gradient(90deg,${tc.border}09,rgba(3,8,16,0.72))`:"rgba(5,11,20,0.72)",
                    border:`1px solid ${tc?tc.border+"2a":"#0d1825"}`,
                    borderRadius:12,padding:"13px 18px",cursor:"pointer",
                    animation:`fadeUp 0.36s ${i<10?i*0.04:0}s ease both`,
                  }}>
                    <div style={{textAlign:"center",flexShrink:0}}>
                      {rCol
                        ? <div style={{width:34,height:34,borderRadius:9,background:`${rCol}18`,
                            border:`1px solid ${rCol}55`,display:"flex",alignItems:"center",
                            justifyContent:"center",fontSize:i===0?16:14,
                            boxShadow:`0 0 10px ${rCol}40`,margin:"0 auto"}}>
                            {i===0?"🥇":i===1?"🥈":"🥉"}
                          </div>
                        : <div style={{width:34,height:34,borderRadius:9,background:"rgba(10,20,34,0.8)",
                            border:"1px solid #0d1825",display:"flex",alignItems:"center",
                            justifyContent:"center",fontSize:9,fontFamily:"'Orbitron',monospace",
                            fontWeight:700,color:"#7d99bd",margin:"0 auto"}}>{i+1}</div>
                      }
                    </div>
                    <div style={{minWidth:0}}>
                      <div style={{display:"flex",alignItems:"center",gap:7,marginBottom:4,flexWrap:"wrap"}}>
                        {s.avatar_url && (
                          <img src={s.avatar_url} style={{width:24,height:24,borderRadius:"50%",
                            border:`1.5px solid ${tc?tc.border:"#7d99bd"}`,objectFit:"cover",flexShrink:0}}
                            onError={(e)=>{e.target.style.display='none'}} alt=""/>
                        )}
                        <span style={{color:tc?"#fff":"#aec1d6",fontFamily:"'Exo 2',sans-serif",
                          fontWeight:800,fontSize:14,
                          textShadow:tc?`0 0 12px ${tc.border}50`:"none",
                          whiteSpace:"nowrap",overflow:"hidden",textOverflow:"ellipsis",maxWidth:160}}>
                          {s.name}
                        </span>
                        {(()=>{
                          const pt=getPowerTier(s.scores);
                          return pt ? <TierPill tier={pt.tier}/> : null;
                        })()}
                      </div>
                      {s.role&&<div style={{fontSize:8,color:"rgba(0,212,255,0.6)",fontFamily:"'Orbitron',monospace",
                        letterSpacing:"0.12em",marginBottom:6}}>{s.role.toUpperCase()}</div>}
                      <div style={{display:"flex",gap:5,flexWrap:"wrap"}}>
                        {Object.entries(DUTIES).map(([dk,d])=>{
                          const tier=badges[dk];
                          if(!tier) return(
                            <div key={dk} title={`${d.label}: no badge`} style={{
                              width:22,height:22,borderRadius:6,
                              background:"rgba(10,20,34,0.6)",border:"1px solid #0d1825",
                              display:"flex",alignItems:"center",justifyContent:"center",
                              fontSize:10,opacity:0.45,
                            }}>{d.emoji}</div>
                          );
                          const tc2=TC[tier];
                          return(
                            <div key={dk} title={`${d.label}: ${tier}`} style={{
                              width:22,height:22,borderRadius:6,
                              background:`${tc2.border}18`,border:`1px solid ${tc2.border}50`,
                              display:"flex",alignItems:"center",justifyContent:"center",
                              fontSize:10,boxShadow:`0 0 6px ${tc2.glow}`,
                            }}>{d.emoji}</div>
                          );
                        })}
                        <span style={{fontSize:9,color:"rgba(255,255,255,0.42)",
                          fontFamily:"'JetBrains Mono',monospace",alignSelf:"center",marginLeft:4}}>
                          {Object.keys(badges).length}/{Object.keys(DUTIES).length} badges
                        </span>
                      </div>
                    </div>
                    <div style={{textAlign:"right",flexShrink:0}}>
                      <div style={{fontFamily:"'Orbitron',monospace",fontWeight:900,fontSize:24,
                        lineHeight:1,marginBottom:3,
                        color:tc?tc.border:"#1a2c3a",
                        textShadow:tc?`0 0 20px ${tc.glow}`:"none"}}>
                        {bs}
                      </div>
                      <div style={{fontSize:7,color:"rgba(255,255,255,0.42)",
                        fontFamily:"'Orbitron',monospace",letterSpacing:"0.15em"}}>PWR PTS</div>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* ── RISING THIS WEEK ── */}
            {(()=>{
              const withWeekly=[...staffList].map(s=>({
                ...s,totalWeekly:Object.values(s.weekly||{}).reduce((n,v)=>n+v,0)
              })).filter(s=>s.totalWeekly>0).sort((a,b)=>b.totalWeekly-a.totalWeekly).slice(0,5);
              if(withWeekly.length===0) return null;
              return(
                <div style={{marginTop:24}}>
                  <div style={{
                    background:"linear-gradient(135deg,rgba(255,170,0,0.06),rgba(3,8,16,0.95))",
                    border:"1px solid rgba(255,170,0,0.2)",borderRadius:"14px 14px 0 0",
                    padding:"16px 22px 14px",
                  }}>
                    <div style={{display:"flex",alignItems:"center",justifyContent:"space-between"}}>
                      <div style={{display:"flex",alignItems:"center",gap:10}}>
                        <span style={{fontSize:20}}>📈</span>
                        <div>
                          <div style={{fontFamily:"'Orbitron',monospace",fontWeight:900,fontSize:12,
                            color:"#ffaa00",letterSpacing:"0.18em",textShadow:"0 0 16px #ffaa0066"}}>
                            RISING THIS WEEK
                          </div>
                          <div style={{fontSize:8,color:"rgba(255,170,0,0.4)",fontFamily:"'JetBrains Mono',monospace",marginTop:2}}>
                            top 5 by weekly actions
                          </div>
                        </div>
                      </div>
                      <button onClick={()=>{SFX.play('tab');setActiveTab('rising');}}
                        style={{background:"rgba(255,170,0,0.08)",border:"1px solid rgba(255,170,0,0.25)",
                          borderRadius:7,padding:"5px 12px",cursor:"pointer",
                          color:"#ffaa00",fontFamily:"'Orbitron',monospace",fontSize:7,fontWeight:700,
                          letterSpacing:"0.1em"}}>VIEW ALL →</button>
                    </div>
                  </div>
                  <div style={{background:"rgba(2,5,12,0.7)",border:"1px solid rgba(255,170,0,0.1)",
                    borderTop:"none",borderRadius:"0 0 14px 14px",overflow:"hidden"}}>
                    {withWeekly.map((s,i)=>{
                      const rCol=i===0?"#ffd700":i===1?"#b8c4d0":i===2?"#cd7f32":null;
                      const badges=getEarnedBadges(s.scores);
                      const top=getTopTier(badges);
                      const tc2=top?TC[top]:null;
                      return(
                        <div key={s.name} onClick={()=>handleRowClick(s)} style={{
                          display:"grid",gridTemplateColumns:"42px 1fr auto",
                          alignItems:"center",gap:14,
                          padding:"11px 18px",cursor:"pointer",
                          borderBottom:i<withWeekly.length-1?"1px solid rgba(255,170,0,0.06)":"none",
                          transition:"background 0.15s",
                        }}
                        onMouseEnter={e=>e.currentTarget.style.background="rgba(255,170,0,0.04)"}
                        onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
                          <div style={{textAlign:"center"}}>
                            {rCol
                              ? <div style={{width:30,height:30,borderRadius:8,background:`${rCol}18`,
                                  border:`1px solid ${rCol}55`,display:"flex",alignItems:"center",
                                  justifyContent:"center",fontSize:14,margin:"0 auto"}}>
                                  {i===0?"🥇":i===1?"🥈":"🥉"}
                                </div>
                              : <div style={{width:30,height:30,borderRadius:8,background:"rgba(10,20,34,0.8)",
                                  border:"1px solid #0d1825",display:"flex",alignItems:"center",
                                  justifyContent:"center",fontSize:9,fontFamily:"'Orbitron',monospace",
                                  fontWeight:700,color:"#7d99bd",margin:"0 auto"}}>{i+1}</div>
                            }
                          </div>
                          <div style={{minWidth:0}}>
                            <div style={{display:"flex",alignItems:"center",gap:6,marginBottom:2}}>
                              <span style={{color:"#c0d4e0",fontFamily:"'Exo 2',sans-serif",fontWeight:800,fontSize:13,
                                whiteSpace:"nowrap",overflow:"hidden",textOverflow:"ellipsis",maxWidth:160}}>
                                {s.name}
                              </span>
                              {top&&<TierPill tier={top}/>}
                            </div>
                            {s.role&&<div style={{fontSize:7,color:"rgba(0,212,255,0.6)",fontFamily:"'Orbitron',monospace",
                              letterSpacing:"0.12em"}}>{s.role.toUpperCase()}</div>}
                          </div>
                          <div style={{textAlign:"right",flexShrink:0}}>
                            <div style={{fontFamily:"'Orbitron',monospace",fontWeight:900,fontSize:16,
                              color:"#ffaa00",textShadow:"0 0 12px #ffaa0055"}}>
                              +{s.totalWeekly.toLocaleString()}
                            </div>
                            <div style={{fontSize:7,color:"rgba(255,170,0,0.35)",fontFamily:"'Orbitron',monospace",
                              letterSpacing:"0.1em"}}>THIS WEEK</div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })()}
          </div>
        )}

        {activeTab==="rising"&&(()=>{
          const withWeekly=[...filtered].map(s=>({
            ...s,totalWeekly:Object.values(s.weekly||{}).reduce((n,v)=>n+v,0)
          })).filter(s=>s.totalWeekly>0).sort((a,b)=>b.totalWeekly-a.totalWeekly);
          return(
            <div style={{animation:"fadeUp 0.35s ease both"}}>
              <div style={{
                background:"linear-gradient(135deg,rgba(255,170,0,0.06),rgba(3,8,16,0.95))",
                border:"1px solid rgba(255,170,0,0.2)",borderRadius:14,
                padding:"20px 22px 16px",marginBottom:12,
              }}>
                <div style={{display:"flex",alignItems:"center",gap:10}}>
                  <span style={{fontSize:22}}>📈</span>
                  <div>
                    <div style={{fontFamily:"'Orbitron',monospace",fontWeight:900,fontSize:13,
                      color:"#ffaa00",letterSpacing:"0.18em",textShadow:"0 0 16px #ffaa0066"}}>
                      MOST IMPROVED THIS WEEK
                    </div>
                    <div style={{fontSize:8,color:"rgba(255,170,0,0.4)",fontFamily:"'JetBrains Mono',monospace",marginTop:3}}>
                      sorted by total actions this week across all duties
                    </div>
                  </div>
                </div>
              </div>
              {withWeekly.length===0&&(
                <div style={{textAlign:"center",padding:60,color:"#1a2c3a",
                  fontFamily:"'Orbitron',monospace",fontSize:10,letterSpacing:"0.22em"}}>
                  NO WEEKLY DATA YET — AVAILABLE AFTER FIRST FULL SYNC
                </div>
              )}
              <div style={{display:"flex",flexDirection:"column",gap:7}}>
                {withWeekly.map((s,i)=>{
                  const rCol=i===0?"#ffd700":i===1?"#b8c4d0":i===2?"#cd7f32":null;
                  const badges=getEarnedBadges(s.scores);
                  const top=getTopTier(badges);
                  const tc=top?TC[top]:null;
                  return(
                    <div key={s.name} className="row-card" onClick={()=>handleRowClick(s)} style={{
                      display:"grid",gridTemplateColumns:"46px 1fr auto",alignItems:"center",gap:16,
                      background:"rgba(255,170,0,0.03)",
                      border:`1px solid ${rCol?rCol+"33":"rgba(255,170,0,0.1)"}`,
                      borderRadius:12,padding:"13px 18px",cursor:"pointer",
                      animation:`fadeUp 0.36s ${i<10?i*0.04:0}s ease both`,
                    }}>
                      <div style={{textAlign:"center",flexShrink:0}}>
                        {rCol
                          ? <div style={{width:34,height:34,borderRadius:9,background:`${rCol}18`,
                              border:`1px solid ${rCol}55`,display:"flex",alignItems:"center",
                              justifyContent:"center",fontSize:i===0?16:14,
                              boxShadow:`0 0 10px ${rCol}40`,margin:"0 auto"}}>
                              {i===0?"🥇":i===1?"🥈":"🥉"}
                            </div>
                          : <div style={{width:34,height:34,borderRadius:9,background:"rgba(10,20,34,0.8)",
                              border:"1px solid #0d1825",display:"flex",alignItems:"center",
                              justifyContent:"center",fontSize:9,fontFamily:"'Orbitron',monospace",
                              fontWeight:700,color:"#7d99bd",margin:"0 auto"}}>{i+1}</div>
                        }
                      </div>
                      <div style={{minWidth:0}}>
                        <div style={{display:"flex",alignItems:"center",gap:7,marginBottom:3,flexWrap:"wrap"}}>
                          <span style={{color:"#fff",fontFamily:"'Exo 2',sans-serif",fontWeight:800,fontSize:14,
                            whiteSpace:"nowrap",overflow:"hidden",textOverflow:"ellipsis",maxWidth:180}}>
                            {s.name}
                          </span>
                          {top&&<TierPill tier={top}/>}
                        </div>
                        {s.role&&<div style={{fontSize:8,color:"rgba(0,212,255,0.6)",fontFamily:"'Orbitron',monospace",
                          letterSpacing:"0.12em",marginBottom:6}}>{s.role.toUpperCase()}</div>}
                        <div style={{display:"flex",gap:5,flexWrap:"wrap"}}>
                          {Object.entries(s.weekly||{}).filter(([,v])=>v>0).map(([dk,v])=>(
                            <div key={dk} style={{display:"flex",alignItems:"center",gap:3,
                              background:"rgba(0,255,136,0.06)",border:"1px solid rgba(0,255,136,0.15)",
                              borderRadius:5,padding:"2px 7px",
                              fontSize:8,color:"#00ff88",fontFamily:"'JetBrains Mono',monospace"}}>
                              {DUTIES[dk]?.emoji} +{v.toLocaleString()}
                            </div>
                          ))}
                        </div>
                      </div>
                      <div style={{textAlign:"right",flexShrink:0}}>
                        <div style={{fontFamily:"'Orbitron',monospace",fontWeight:900,fontSize:22,
                          lineHeight:1,color:"#ffaa00",textShadow:"0 0 16px #ffaa0066",marginBottom:3}}>
                          +{s.totalWeekly.toLocaleString()}
                        </div>
                        <div style={{fontSize:7,color:"rgba(255,170,0,0.4)",fontFamily:"'Orbitron',monospace",
                          letterSpacing:"0.15em"}}>THIS WEEK</div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })()}

        {activeTab!=="all"&&activeTab!=="hof"&&activeTab!=="rising"&&(()=>{
          const dk=activeTab;
          const ranked=sortedByDuty(dk);
          return(
            <div style={{animation:"fadeUp 0.35s ease both"}}>
              <DutyHeader dk={dk}/>
              <TierBreakdown dk={dk}/>
              {!search&&!tierFilter&&ranked.length>=3&&(
                <div style={{marginBottom:8}}>
                  <div style={{fontSize:8,color:DUTIES[dk].color,fontFamily:"'Orbitron',monospace",
                    fontWeight:700,letterSpacing:"0.22em",textAlign:"center",marginBottom:4,opacity:0.6}}>
                    ◈ TOP PERFORMERS
                  </div>
                  <PodiumSection staffList={staffList} dk={dk} onSelectStaff={setSelected}/>
                </div>
              )}
              <div style={{display:"flex",gap:6,flexWrap:"wrap",alignItems:"center",
                justifyContent:"space-between",marginBottom:10}}>
                <div style={{display:"flex",gap:4,alignItems:"center"}}>
                  <span style={{fontSize:7,color:"#1a2c3a",fontFamily:"'Orbitron',monospace",
                    letterSpacing:"0.15em",marginRight:4}}>SORT</span>
                  {[["score","📊 SCORE"],["alpha","🔤 A–Z"],["tier","⭐ POWER"]].map(([mode,label])=>(
                    <button key={mode} onClick={()=>setSortMode(mode)} style={{
                      background:sortMode===mode?"rgba(0,212,255,0.1)":"rgba(5,11,20,0.7)",
                      border:`1px solid ${sortMode===mode?"rgba(0,212,255,0.6)":"#0d1825"}`,
                      borderRadius:6,padding:"5px 10px",cursor:"pointer",
                      color:sortMode===mode?"#00d4ff":"#1e3248",
                      fontFamily:"'Orbitron',monospace",fontSize:7,fontWeight:700,
                      letterSpacing:"0.1em",opacity:sortMode===mode?1:0.6,
                    }}>{label}</button>
                  ))}
                </div>
                <div style={{display:"flex",gap:4,alignItems:"center",flexWrap:"wrap"}}>
                  <span style={{fontSize:7,color:"#1a2c3a",fontFamily:"'Orbitron',monospace",
                    letterSpacing:"0.15em",marginRight:4}}>FILTER</span>
                  <button onClick={()=>setTierFilter(null)} style={{
                    background:!tierFilter?"rgba(255,255,255,0.07)":"rgba(5,11,20,0.7)",
                    border:`1px solid ${!tierFilter?"rgba(255,255,255,0.2)":"#0d1825"}`,
                    borderRadius:6,padding:"5px 8px",cursor:"pointer",
                    color:!tierFilter?"#fff":"#1e3248",
                    fontFamily:"'Orbitron',monospace",fontSize:7,fontWeight:700,letterSpacing:"0.1em",
                  }}>ALL</button>
                  {TIERS.map(t=>(
                    <button key={t} onClick={()=>setTierFilter(tierFilter===t?null:t)} style={{
                      background:tierFilter===t?`${TC[t].border}18`:"rgba(5,11,20,0.7)",
                      border:`1px solid ${tierFilter===t?TC[t].border+"60":"#0d1825"}`,
                      borderRadius:6,padding:"5px 8px",cursor:"pointer",
                      color:tierFilter===t?TC[t].border:"#1e3248",
                      fontFamily:"'Orbitron',monospace",fontSize:7,fontWeight:700,letterSpacing:"0.08em",
                    }}>{TC[t].icon} {t.toUpperCase()}</button>
                  ))}
                </div>
              </div>
              <div style={{display:"flex",flexDirection:"column",gap:7}}>
                {ranked.map((s,i)=>(
                  <StaffRow key={s.name} staff={s} rank={i+1} dk={dk}
                    compact={false} delay={i<8?i*0.03:0} onClick={()=>handleRowClick(s)}/>
                ))}
                {ranked.length===0&&(
                  <div style={{textAlign:"center",color:"#0d1825",fontFamily:"'Orbitron',monospace",
                    padding:50,fontSize:9,letterSpacing:"0.24em"}}>
                    {search?`NO STAFF MATCH "${search.toUpperCase()}"`:tierFilter?`NO ${tierFilter.toUpperCase()} TIER STAFF`:'NO DATA YET'}
                  </div>
                )}
              </div>
            </div>
          );
        })()}
      </div>

      <div style={{maxWidth:860,margin:"20px auto 0",textAlign:"center"}}>
        <div style={{fontSize:7,color:"#0d1825",fontFamily:"'JetBrains Mono',monospace",letterSpacing:"0.15em"}}>
          ⌨ PRESS 1-6 TO SWITCH TABS · ESC TO CLOSE · CLICK ANY ROW FOR PROFILE
        </div>
      </div>

      <div style={{maxWidth:860,margin:"24px auto 0",textAlign:"center",
        padding:"18px 28px",
        background:"linear-gradient(135deg,rgba(5,11,20,0.7),rgba(20,8,0,0.5))",
        border:"1px solid rgba(255,170,0,0.09)",borderRadius:13,
        backdropFilter:"blur(12px)",position:"relative",overflow:"hidden"}}>
        <div style={{position:"absolute",top:0,left:0,right:0,height:1,
          background:"linear-gradient(90deg,transparent,rgba(255,170,0,0.35),transparent)"}}/>
        <span style={{fontSize:13,color:"#1e2e3e",fontFamily:"'Exo 2',sans-serif",fontWeight:600}}>Use Code </span>
        <span style={{fontSize:17,fontFamily:"'Orbitron',monospace",fontWeight:900,
          background:"linear-gradient(90deg,#ffaa00,#ffd700,#ffee88,#ffd700,#ffaa00)",
          backgroundSize:"200% auto",
          WebkitBackgroundClip:"text",WebkitTextFillColor:"transparent",backgroundClip:"text",
          animation:"shimmer 2.5s linear infinite",
          filter:"drop-shadow(0 0 16px rgba(255,170,0,0.5))",
          letterSpacing:"0.04em"}}>wavedropmaps</span>
        <span style={{fontSize:13,color:"#1e2e3e",fontFamily:"'Exo 2',sans-serif",fontWeight:600}}> in the Item Shop!</span>
      </div>

      {selected&&!selected.__compare&&<ProfileModal staff={selected} onClose={()=>setSelected(null)} onCompare={handleCompare}/>}
      {selected&&selected.__compare&&<CompareModal staffA={selected.a} staffB={selected.b} onClose={()=>setSelected(null)}/>}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
