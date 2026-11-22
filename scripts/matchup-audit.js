// V2.8. Opponent context ablation. Uses strictly earlier dated outcomes only.
function historicalMatchupAudit(profiles,holdoutWeeks=2){
 const eligible=profiles.filter(p=>p.source==='imported'&&Array.isArray(p.records)&&p.playerKey);
 const dates=[...new Set(eligible.flatMap(p=>p.records.map(r=>Number(r.season)*100+Number(r.week))).filter(Number.isFinite))].sort((a,b)=>a-b);
 if(dates.length<holdoutWeeks+6)return {ready:false,reason:'Not enough completed weeks for chronological opponent-context comparison.',groups:[]};
 const cutoff=dates[dates.length-holdoutWeeks],byRoleStat=new Map();
 for(const p of eligible){
  const key=p.position+'|'+p.stat;if(!byRoleStat.has(key))byRoleStat.set(key,[]);
  for(const r of p.records){const date=Number(r.season)*100+Number(r.week);
   if(Number.isFinite(date)&&Number.isFinite(r.value)&&r.opp&&r.opp!=='Opponent unavailable')
    byRoleStat.get(key).push({date,opponent:r.opp,value:r.value,player:p.playerKey});
  }
 }
 for(const records of byRoleStat.values())records.sort((a,b)=>a.date-b.date);
 const grouped=new Map();
 for(const p of eligible){
  const pool=byRoleStat.get(p.position+'|'+p.stat)||[];
  const games=[...p.records].filter(r=>Number.isFinite(r.value)).sort((a,b)=>a.season-b.season||a.week-b.week);
  if(!grouped.has(p.stat))grouped.set(p.stat,{stat:p.stat,development:[],holdout:[]});
  const group=grouped.get(p.stat);
  for(let i=5;i<games.length;i++){
   const game=games[i],date=Number(game.season)*100+Number(game.week);
   if(!game.opp||game.opp==='Opponent unavailable')continue;
   const history=games.slice(0,i).map(r=>r.value),recent=history.slice(-10),recent5=history.slice(-5);
   const baseline=.55*researchMean(recent)+.30*researchMean(recent5)+.15*researchMean(history);
   const earlier=pool.filter(r=>r.date<date&&r.player!==p.playerKey);
   const comparable=earlier.filter(r=>r.opponent===game.opp);
   const playerCount=new Set(comparable.map(r=>r.player)).size;
   const defenseWeeks=new Set(comparable.map(r=>r.date)).size;
   if(comparable.length<8||playerCount<3||defenseWeeks<3||earlier.length<30)continue;
   const leagueAvg=researchMean(earlier.map(r=>r.value)),defenseAvg=researchMean(comparable.map(r=>r.value));
   if(!(leagueAvg>0))continue;
   const ratio=Math.min(1.25,Math.max(.75,defenseAvg/leagueAvg));
   // Shrink and cap context: candidate only, not an accepted improvement.
   const adjusted=baseline*(1+.35*(ratio-1));
   const row={player:p.playerKey,actual:game.value,baseline,adjusted,date};
   (date<cutoff?group.development:group.holdout).push(row);
  }
 }
 const groups=[...grouped.values()].map(g=>{
  const devPlayers=new Set(g.development.map(x=>x.player)).size,holdPlayers=new Set(g.holdout.map(x=>x.player)).size;
  const metric=(rows,key)=>rows.length?researchMean(rows.map(x=>Math.abs(x.actual-x[key]))):null;
  const developmentBase=metric(g.development,'baseline'),developmentAdjusted=metric(g.development,'adjusted');
  const holdBase=metric(g.holdout,'baseline'),holdAdjusted=metric(g.holdout,'adjusted');
  const devReady=g.development.length>=30&&devPlayers>=10,holdReady=g.holdout.length>=20&&holdPlayers>=10;
  const improvement=holdAdjusted!==null&&holdBase>0?(1-holdAdjusted/holdBase)*100:null;
  return {stat:g.stat,devTests:g.development.length,devPlayers,holdTests:g.holdout.length,holdPlayers,developmentBase,developmentAdjusted,holdBase,holdAdjusted,improvement,ready:devReady&&holdReady,status:!devReady?'INSUFFICIENT DEVELOPMENT':!holdReady?'INSUFFICIENT HOLDOUT':'DESCRIPTIVE TEST ONLY'};
 }).sort((a,b)=>b.holdTests-a.holdTests||a.stat.localeCompare(b.stat));
 return {ready:true,cutoff,holdoutWeeks,groups,evaluated:groups.filter(x=>x.ready).length};
}
