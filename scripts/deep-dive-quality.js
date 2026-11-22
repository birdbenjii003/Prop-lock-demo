'use strict';
// Observed player-role opportunity quality; no inferred route maps or tracking.
function deepDiveParseQualityCSV(raw,parse){
 const csv=parse(raw.replace(/^\uFEFF/,''));if(csv.length<2)return [];
 const head=csv.shift(),fields=['player_id','season','week','team','rush_attempts','red_zone_carries','goal_line_carries','targets','red_zone_targets','deep_targets','air_yards'];
 if(fields.some(f=>!head.includes(f)))throw Error('Opportunity quality source schema mismatch');
 const idx=Object.fromEntries(fields.map(f=>[f,head.indexOf(f)])),seen=new Set(),out=[];
 for(const r of csv){
  const playerId=r[idx.player_id],season=Number(r[idx.season]),week=Number(r[idx.week]),team=r[idx.team];
  const n=Object.fromEntries(fields.slice(4).map(k=>[k,Number(r[idx[k]])]));
  if(!playerId||!team||!Number.isInteger(season)||season<2023||season>2026||!Number.isInteger(week)||week<1||week>22)throw Error('Invalid quality player-week identity');
  if(fields.slice(4).some(k=>!Number.isFinite(n[k])||(k==='air_yards'?Math.abs(n[k])>10000:n[k]<0||n[k]>200)))throw Error('Invalid opportunity count');
  if(n.red_zone_carries>n.rush_attempts||n.goal_line_carries>n.red_zone_carries||n.red_zone_targets>n.targets||n.deep_targets>n.targets)throw Error('Impossible opportunity counts');
  const key=[playerId,season,week,team].join('|');if(seen.has(key))throw Error('Duplicate quality player-week');seen.add(key);
  out.push({playerId,season,week,team,...n});
 }
 if(out.length<500)throw Error('Insufficient quality records');
 return out;
}
const ddQualityIndexCache=new WeakMap();
function ddQualityPlayerIndex(all){
 let index=ddQualityIndexCache.get(all);
 if(!index){index=new Map();for(const r of all){let list=index.get(r.playerId);if(!list){list=[];index.set(r.playerId,list)}list.push(r)}ddQualityIndexCache.set(all,index)}
 return index;
}
function deepDiveQualitySummary(p,all){
 if(p?.source!=='imported'||!p.playerKey?.startsWith('id:')||!Array.isArray(all)||!Array.isArray(p.records))return null;
 const id=p.playerKey.slice(3),observed=new Set(p.records.map(r=>[r.season,r.week,r.team].join('|')));
 const match=(ddQualityPlayerIndex(all).get(id)||[]).filter(r=>observed.has([r.season,r.week,r.team].join('|'))).sort((a,b)=>a.season-b.season||a.week-b.week);
 const role=p.stat.includes('Rushing')||p.stat==='Carries'?'rush':p.stat.includes('Receiving')||p.stat==='Receptions'||p.stat==='Targets'?'receive':null;
 if(!role||!match.length)return null;
 const recent=match.slice(-5),sum=k=>recent.reduce((a,r)=>a+r[k],0),metrics=role==='rush'?{chances:sum('rush_attempts'),redZone:sum('red_zone_carries'),goalLine:sum('goal_line_carries'),deep:null,air:null}:{chances:sum('targets'),redZone:sum('red_zone_targets'),goalLine:null,deep:sum('deep_targets'),air:sum('air_yards')};
 return {games:match.length,recentGames:recent.length,role,metrics,seasonCount:new Set(match.map(r=>r.season)).size};
}
