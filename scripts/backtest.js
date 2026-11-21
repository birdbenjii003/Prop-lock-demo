'use strict';
// Rolling one-game-ahead error audit; no future weeks enter a training window.
function rollingBacktest(p,minHistory=5){
 const games=Array.isArray(p.records)?[...p.records].sort((a,b)=>a.season-b.season||a.week-b.week):p.logs.map((v,i)=>({season:0,week:i+1,value:v}));
 const rows=[];
 for(let i=minHistory;i<games.length;i++){
  const past=games.slice(0,i).map(x=>x.value).filter(Number.isFinite),actual=games[i].value;
  if(past.length<minHistory||!Number.isFinite(actual))continue;
  const last10=past.slice(-10),last5=past.slice(-5);
  const estimate=.55*mean(last10)+.30*mean(last5)+.15*mean(past);
  const benchmark=mean(past);
  const threshold=Math.max(.5,Math.floor(median(last10))+.5);
  rows.push({season:games[i].season,week:games[i].week,actual,estimate,benchmark,threshold,absError:Math.abs(estimate-actual),naiveError:Math.abs(benchmark-actual),signedError:estimate-actual});
 }
 const n=rows.length;
 const mae=n?mean(rows.map(r=>r.absError)):null;
 const benchmarkMae=n?mean(rows.map(r=>r.naiveError)):null;
 const bias=n?mean(rows.map(r=>r.signedError)):null;
 const improvement=n&&benchmarkMae>0?(1-mae/benchmarkMae)*100:null;
 return {rows,n,mae,benchmarkMae,bias,improvement};
}
function validationPanel(p){
 const x=rollingBacktest(p),fmtOr=v=>v===null?'N/A':fmt(v);
 const change=x.improvement===null?'N/A':(x.improvement>=0?'+':'')+fmt(x.improvement)+'%';
 const status=x.n<5?'LIMITED TEST SAMPLE':x.mae<x.benchmarkMae?'LOWER ERROR THAN NAIVE BENCHMARK':'NO IMPROVEMENT OVER NAIVE BENCHMARK';
 return '<div class="validation-panel"><div class="panel-head"><h3>04 · Historical Validation</h3><span class="metricchip">V2.0 · WALK-FORWARD</span></div>'+
 '<p class="validation-copy">Each tested game uses only this player’s <b>earlier</b> recorded games. A past-average benchmark is tested on the same games. These are numerical errors, not betting outcomes.</p>'+
 '<div class="validation-grid"><div><b>'+x.n+'</b><span>One-step-ahead test games</span></div><div><b>'+fmtOr(x.mae)+'</b><span>Historical blend MAE</span></div><div><b>'+fmtOr(x.benchmarkMae)+'</b><span>Past-mean benchmark MAE</span></div><div><b>'+change+'</b><span>Difference in MAE vs benchmark</span></div></div>'+
 '<p class="validation-copy"><strong>'+status+'</strong> · Signed prediction error: '+fmtOr(x.bias)+'. Lower MAE is better.</p>'+
 '<details class="validation-detail"><summary>Show '+x.n+' audited historical tests</summary><div style="overflow-x:auto"><table><thead><tr><th>Game</th><th>Actual</th><th>Blend</th><th>Prior mean</th><th>Prior threshold</th></tr></thead><tbody>'+
 x.rows.map(r=>'<tr><td>'+escapeHtml(r.season)+' W'+escapeHtml(r.week)+'</td><td>'+fmt(r.actual)+'</td><td>'+fmt(r.estimate)+'</td><td>'+fmt(r.benchmark)+'</td><td>'+fmt(r.threshold)+'</td></tr>').join('')+'</tbody></table></div></details>'+
 '<p class="validation-warning">'+(x.n<5?'Only '+x.n+' historical test games were available. ':'')+'The blend is exploratory and has not been validated on an independent season. Player-role filtering may introduce selection bias. No true historical sportsbook lines, upcoming game features, or calibrated probabilities are provided. Better MAE is not a win rate.</p></div>';
}

// Aggregation is weighted by one out-of-sample player-game test, not by player.
// Groups represent already-eligible imported profiles; this is not all NFL players.
function aggregateBacktests(profiles){
 const groups=new Map();let totalTests=0;
 for(const p of profiles){
  const test=rollingBacktest(p);if(!test.n)continue;
  if(!groups.has(p.stat))groups.set(p.stat,{stat:p.stat,players:new Set(),tests:0,blendError:0,benchmarkError:0,bias:0,improvedPlayers:0,playerProfiles:0});
  const g=groups.get(p.stat);g.players.add(p.playerKey||p.id);g.tests+=test.n;totalTests+=test.n;
  g.blendError+=test.rows.reduce((n,r)=>n+r.absError,0);
  g.benchmarkError+=test.rows.reduce((n,r)=>n+r.naiveError,0);
  g.bias+=test.rows.reduce((n,r)=>n+r.signedError,0);
  g.playerProfiles++;if(test.mae<test.benchmarkMae)g.improvedPlayers++;
 }
 const data=[...groups.values()].map(g=>{
  const mae=g.blendError/g.tests,benchmarkMae=g.benchmarkError/g.tests;
  const count=g.players.size;
  const enough=g.tests>=30&&count>=10;
  const improvement=benchmarkMae>0?(1-mae/benchmarkMae)*100:null;
  return {stat:g.stat,players:count,tests:g.tests,mae,benchmarkMae,bias:g.bias/g.tests,improvement,improvedPlayers:g.improvedPlayers,playerProfiles:g.playerProfiles,
    readiness:enough?'DESCRIPTIVE SAMPLE':'LIMITED SAMPLE',enough};
 }).sort((a,b)=>b.tests-a.tests||a.stat.localeCompare(b.stat));
 return {groups:data,totalTests,totalProfiles:profiles.length,testedProfiles:data.reduce((n,g)=>n+g.playerProfiles,0)};
}
