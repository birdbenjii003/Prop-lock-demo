'use strict';
// Verified offline GSIS-to-PFR snap join results only. No guessing based on names.
function deepDiveParseVerifiedSnapCsv(text,parse){
 const rows=parse(text.replace(/^\uFEFF/,''));if(rows.length<2)return [];
 const head=rows[0].map(x=>x.trim());
 const fields=['player_id','season','week','team','offense_snaps','offense_pct'];
 if(fields.some(f=>!head.includes(f)))throw Error('Missing verified snap columns');
 const idx=Object.fromEntries(fields.map(f=>[f,head.indexOf(f)]));
 const result=[],seen=new Set();
 for(const r of rows.slice(1)){
  const playerId=r[idx.player_id],season=Number(r[idx.season]),week=Number(r[idx.week]),team=r[idx.team],snaps=Number(r[idx.offense_snaps]),pct=Number(r[idx.offense_pct]);
  if(!playerId||!team||![2023,2024,2025].includes(season)||!Number.isInteger(week)||week<1||week>22||!Number.isFinite(snaps)||snaps<0||snaps>200||!Number.isFinite(pct)||pct<0||pct>1.001)throw Error('Unverified snap record');
  const key=[playerId,season,week,team].join('|');if(seen.has(key))throw Error('Duplicate snap player-week');seen.add(key);
  result.push({playerId,season,week,team,snaps,pct});
 }
 if(result.length<500)throw Error('Verified snap evidence below minimum 500 player-weeks');
 return result;
}
function deepDiveMatchedSnaps(p,all){
 if(!p||p.source!=='imported'||!p.playerKey?.startsWith('id:')||!Array.isArray(p.records)||!Array.isArray(all))return [];
 const id=p.playerKey.slice(3),games=new Set(p.records.map(r=>[r.season,r.week,r.team].join('|')));
 return all.filter(s=>s.playerId===id&&games.has([s.season,s.week,s.team].join('|'))).sort((a,b)=>a.season-b.season||a.week-b.week);
}
function deepDiveSnapSummary(p,all){
 const matched=deepDiveMatchedSnaps(p,all),last=matched.slice(-5);
 const avg=key=>last.length?last.reduce((n,r)=>n+r[key],0)/last.length:null;
 return {matched:matched.length,lastSeason:matched.length?matched[matched.length-1].season:null,avgSnaps:avg('snaps'),avgPct:avg('pct'),recent:matched.slice(-10)};
}
