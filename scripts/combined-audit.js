'use strict';
// V2.9: three-method historical ablation on strictly identical player-game rows.
// Deep Dive = historical blend; Scenarios = previous opportunity volume × previous efficiency;
// Trait Match = shrunk earlier-opponent allowance ratio. We do not observe future game scripts.
// Fixed 50/30/20 combination is a research candidate, not a tuned forecasting model.
function combinedResearchAudit(profiles,holdoutWeeks=2){
 const candidates=profiles.filter(p=>p.source==='imported'&&p.playerKey&&Array.isArray(p.records));
 const dates=[...new Set(candidates.flatMap(p=>p.records.map(r=>Number(r.season)*100+Number(r.week))).filter(Number.isFinite))].sort((a,b)=>a-b);
 if(dates.length<holdoutWeeks+6)return {ready:false,reason:'Not enough recorded NFL weeks for a temporal holdout.',groups:[]};
 const cutoff=dates[dates.length-holdoutWeeks];
 const byPlayer=new Map(),byRoleStat=new Map();
 for(const p of candidates){
  if(!byPlayer.has(p.playerKey))byPlayer.set(p.playerKey,new Map());byPlayer.get(p.playerKey).set(p.stat,p);
  const key=p.position+'|'+p.stat;
  if(!byRoleStat.has(key))byRoleStat.set(key,[]);
  for(const r of p.records){const date=Number(r.season)*100+Number(r.week);
   if(Number.isFinite(date)&&Number.isFinite(r.value)&&r.opp&&r.opp!=='Opponent unavailable')
    byRoleStat.get(key).push({date,player:p.playerKey,opponent:r.opp,value:r.value});
  }
 }
 for(const rows of byRoleStat.values())rows.sort((a,b)=>a.date-b.date);
 const volumeMap={'Passing Yards':'Passing Attempts','Passing TDs':'Passing Attempts','Interceptions':'Passing Attempts','Rushing Yards':'Carries','Rushing TDs':'Carries','Receiving Yards':'Targets','Receptions':'Targets','Receiving TDs':'Targets'};
 const groups=new Map();
 for(const p of candidates){
  const volumeStat=volumeMap[p.stat];if(!volumeStat)continue;
  const counterpart=byPlayer.get(p.playerKey)?.get(volumeStat);if(!counterpart?.records)continue;
  const volumes=new Map(counterpart.records.filter(r=>Number.isFinite(r.value)).map(r=>[Number(r.season)*100+Number(r.week),r.value]));
  const games=[...p.records].filter(r=>Number.isFinite(r.value)).sort((a,b)=>a.season-b.season||a.week-b.week);
  const rolePool=byRoleStat.get(p.position+'|'+p.stat)||[];
  if(!groups.has(p.stat))groups.set(p.stat,{stat:p.stat,volumeStat,development:[],holdout:[],missingVolume:0,missingTrait:0});
  const group=groups.get(p.stat);
  for(let i=5;i<games.length;i++){
   const game=games[i],date=Number(game.season)*100+Number(game.week);
   if(!game.opp||game.opp==='Opponent unavailable')continue;
   const hist=games.slice(0,i),values=hist.map(r=>r.value),recent=values.slice(-10);
   const deep=.55*researchMean(recent)+.30*researchMean(values.slice(-5))+.15*researchMean(values);
   const paired=hist.map(r=>({value:r.value,volume:volumes.get(Number(r.season)*100+Number(r.week))})).filter(r=>Number.isFinite(r.volume)&&r.volume>0).slice(-10);
   if(paired.length<5){group.missingVolume++;continue}
   const last5=paired.slice(-5),sumVolume=paired.reduce((a,r)=>a+r.volume,0);
   if(sumVolume<=0){group.missingVolume++;continue}
   const scenario=Math.max(0,researchMean(last5.map(r=>r.volume))*paired.reduce((a,r)=>a+r.value,0)/sumVolume);
   // Exclude all same-week outcomes and this player's outcomes from opponent context.
   const earlier=rolePool.filter(r=>r.date<date&&r.player!==p.playerKey),opponents=earlier.filter(r=>r.opponent===game.opp);
   if(earlier.length<30||opponents.length<8||new Set(opponents.map(r=>r.player)).size<3||new Set(opponents.map(r=>r.date)).size<3){group.missingTrait++;continue}
   const baseOpp=researchMean(earlier.map(r=>r.value));
   if(!(baseOpp>0)){group.missingTrait++;continue}
   const ratio=Math.max(.75,Math.min(1.25,researchMean(opponents.map(r=>r.value))/baseOpp));
   const trait=deep*(1+.35*(ratio-1));
   const combined=.50*deep+.30*scenario+.20*trait;
   const row={player:p.playerKey,date,actual:game.value,deep,scenario,trait,combined};
   (date<cutoff?group.development:group.holdout).push(row);
  }
 }
 const keys=['deep','scenario','trait','combined'];
 const result=[...groups.values()].map(g=>{
  const devPlayers=new Set(g.development.map(r=>r.player)).size,holdPlayers=new Set(g.holdout.map(r=>r.player)).size;
  const calc=(rows,key)=>rows.length?researchMean(rows.map(r=>Math.abs(r[key]-r.actual))):null;
  const dev=Object.fromEntries(keys.map(k=>[k,calc(g.development,k)]));
  const hold=Object.fromEntries(keys.map(k=>[k,calc(g.holdout,k)]));
  const enoughDev=g.development.length>=30&&devPlayers>=10,enoughHold=g.holdout.length>=20&&holdPlayers>=10;
  const change=hold.deep>0?(1-hold.combined/hold.deep)*100:null;
  return {stat:g.stat,volumeStat:g.volumeStat,devTests:g.development.length,devPlayers,holdTests:g.holdout.length,holdPlayers,missingVolume:g.missingVolume,missingTrait:g.missingTrait,dev,hold,change,
   ready:enoughDev&&enoughHold,status:!enoughDev?'LIMITED DEVELOPMENT':!enoughHold?'LIMITED HOLDOUT':'DESCRIPTIVE COMPARISON ONLY'};
 }).sort((a,b)=>b.holdTests-a.holdTests||a.stat.localeCompare(b.stat));
 return {ready:true,cutoff,holdoutWeeks,groups:result,eligibleGroups:result.filter(x=>x.ready).length,
  modelFormula:'0.50 × Deep Dive + 0.30 × prior-opportunity scenario + 0.20 × prior-opponent trait'};
}
