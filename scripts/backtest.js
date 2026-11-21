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

// V2.2: predeclared candidate estimators, selected on earlier weeks only.
// A single global temporal split prevents later-season records of other players
// from influencing which model is selected for an earlier evaluation week.
function candidateEstimates(history){
 const a=history.filter(Number.isFinite),last10=a.slice(-10),last5=a.slice(-5);
 if(a.length<5)return null;
 return {
  'Prior mean':mean(a),
  'Recent L5 mean':mean(last5),
  'Historical blend':.55*mean(last10)+.30*mean(last5)+.15*mean(a),
  'Recent L10 median':median(last10)
 };
}
function independentValidation(profiles,holdoutWeeks=2){
 const valid=profiles.filter(p=>Array.isArray(p.records)&&p.records.length>0);
 const dates=valid.flatMap(p=>p.records.map(r=>r.season*100+r.week)).filter(Number.isFinite);
 const uniq=[...new Set(dates)].sort((a,b)=>a-b);
 if(uniq.length<holdoutWeeks+6)return {ready:false,reason:'Insufficient distinct weeks for development and holdout.',groups:[],cutoff:null,holdoutWeeks};
 const cutoff=uniq[uniq.length-holdoutWeeks];
 const grouped=new Map(),models=['Prior mean','Recent L5 mean','Historical blend','Recent L10 median'];
 for(const p of valid){
  const games=[...p.records].sort((a,b)=>a.season-b.season||a.week-b.week);
  if(!grouped.has(p.stat))grouped.set(p.stat,{stat:p.stat,development:[],holdout:[]});
  const group=grouped.get(p.stat);
  for(let i=5;i<games.length;i++){
   const target=games[i],date=target.season*100+target.week;
   if(!Number.isFinite(target.value)||!Number.isFinite(date))continue;
   const past=games.slice(0,i).map(x=>x.value),candidate=candidateEstimates(past);
   if(!candidate)continue;
   const entry={player:p.playerKey||p.id,season:target.season,week:target.week,actual:target.value,candidates:candidate};
   // Cross-group model selection uses only dates strictly before the global cutoff.
   (date<cutoff?group.development:group.holdout).push(entry);
  }
 }
 const groups=[...grouped.values()].map(group=>{
  const devPlayers=new Set(group.development.map(x=>x.player)).size;
  const holdPlayers=new Set(group.holdout.map(x=>x.player)).size;
  const enoughDev=group.development.length>=30&&devPlayers>=10;
  const enoughHold=group.holdout.length>=20&&holdPlayers>=10;
  const developmentScores=models.map(name=>({name,mae:group.development.length?mean(group.development.map(x=>Math.abs(x.candidates[name]-x.actual))):null}));
  // Stable candidate order resolves equal errors; no holdout feedback used here.
  const best=enoughDev?[...developmentScores].sort((a,b)=>a.mae-b.mae)[0].name:null;
  const evaluate=(model,rows)=>rows.length?mean(rows.map(x=>Math.abs(x.candidates[model]-x.actual))):null;
  const chosenHoldout=best?evaluate(best,group.holdout):null;
  const naiveHoldout=evaluate('Prior mean',group.holdout);
  const delta=chosenHoldout!==null&&naiveHoldout>0?(1-chosenHoldout/naiveHoldout)*100:null;
  return {stat:group.stat,devTests:group.development.length,devPlayers,holdTests:group.holdout.length,holdPlayers,selected:best,
   devMae:best?developmentScores.find(x=>x.name===best).mae:null,holdoutMae:chosenHoldout,holdoutNaiveMae:naiveHoldout,
   delta,ready:enoughDev&&enoughHold,developmentScores,
   status:!enoughDev?'NOT SELECTED — development sample too small':!enoughHold?'HOLDOUT TOO SMALL':'EVALUATED — NOT CALIBRATED'};
 }).sort((a,b)=>b.holdTests-a.holdTests||a.stat.localeCompare(b.stat));
 return {ready:true,cutoff,holdoutWeeks,groups,
  selectedGroups:groups.filter(g=>g.selected).length,evaluatedGroups:groups.filter(g=>g.ready).length};
}

// V2.3: volume × efficiency estimator, evaluated with preceding weeks only.
// Targets/carries/pass attempts are opportunity proxies, not snaps/routes/air yards.
const OPPORTUNITY_MARKETS={'Passing Yards':'Passing Attempts','Passing TDs':'Passing Attempts','Interceptions':'Passing Attempts','Rushing Yards':'Carries','Rushing TDs':'Carries','Receiving Yards':'Targets','Receptions':'Targets','Receiving TDs':'Targets'};
function opportunityBacktest(profiles,holdoutWeeks=2){
 const profileLookup=new Map();
 for(const p of profiles){
  if(!p.records||!p.playerKey)continue;
  if(!profileLookup.has(p.playerKey))profileLookup.set(p.playerKey,new Map());
  profileLookup.get(p.playerKey).set(p.stat,p);
 }
 const allWeeks=[...new Set(profiles.flatMap(p=>(p.records||[]).map(r=>r.season*100+r.week)).filter(Number.isFinite))].sort((a,b)=>a-b);
 if(allWeeks.length<holdoutWeeks+6)return {ready:false,reason:'Not enough dated NFL weeks for a separate comparison.',groups:[]};
 const cutoff=allWeeks[allWeeks.length-holdoutWeeks];
 const groups=new Map();let pairedProfiles=0;
 for(const p of profiles){
  const oppName=OPPORTUNITY_MARKETS[p.stat];if(!oppName||!p.records||!p.playerKey)continue;
  const opp=profileLookup.get(p.playerKey)?.get(oppName);if(!opp?.records)continue;
  const lookup=new Map(opp.records.map(r=>[r.season+':'+r.week,r.value]));
  const series=[...p.records].sort((a,b)=>a.season-b.season||a.week-b.week).map(r=>({season:r.season,week:r.week,actual:r.value,volume:lookup.get(r.season+':'+r.week)}));
  if(series.filter(r=>Number.isFinite(r.volume)&&r.volume>0).length<6)continue;
  pairedProfiles++;
  if(!groups.has(p.stat))groups.set(p.stat,{stat:p.stat,opportunity:oppName,development:[],holdout:[],players:new Set()});
  const group=groups.get(p.stat);group.players.add(p.playerKey);
  for(let i=5;i<series.length;i++){
   const current=series[i];if(!Number.isFinite(current.actual))continue;
   const previous=series.slice(0,i).filter(r=>Number.isFinite(r.actual)&&Number.isFinite(r.volume)&&r.volume>0);
   if(previous.length<5)continue;
   const ten=previous.slice(-10),five=previous.slice(-5);
   const sumVolume=ten.reduce((n,r)=>n+r.volume,0);if(sumVolume<=0)continue;
   const rate=ten.reduce((n,r)=>n+r.actual,0)/sumVolume;
   const projectedVolume=mean(five.map(r=>r.volume));
   const estimate=Math.max(0,rate*projectedVolume);
   const benchmark=mean(previous.map(r=>r.actual));
   const date=current.season*100+current.week;
   const record={player:p.playerKey,date,actual:current.actual,estimate,benchmark,rate,projectedVolume};
   (date<cutoff?group.development:group.holdout).push(record);
  }
 }
 const summarized=[...groups.values()].map(g=>{
  const devPlayers=new Set(g.development.map(r=>r.player)).size;
  const holdPlayers=new Set(g.holdout.map(r=>r.player)).size;
  const errors=(a,key)=>a.length?mean(a.map(r=>Math.abs(r[key]-r.actual))):null;
  const devMae=errors(g.development,'estimate'),devBenchmarkMae=errors(g.development,'benchmark');
  const holdoutMae=errors(g.holdout,'estimate'),holdoutBenchmarkMae=errors(g.holdout,'benchmark');
  const developmentEnough=g.development.length>=30&&devPlayers>=10;
  const holdoutEnough=g.holdout.length>=20&&holdPlayers>=10;
  const holdoutChange=holdoutMae!==null&&holdoutBenchmarkMae>0?(1-holdoutMae/holdoutBenchmarkMae)*100:null;
  return {stat:g.stat,opportunity:g.opportunity,players:g.players.size,devTests:g.development.length,devPlayers,holdTests:g.holdout.length,holdPlayers,devMae,devBenchmarkMae,holdoutMae,holdoutBenchmarkMae,holdoutChange,
   ready:developmentEnough&&holdoutEnough,status:!developmentEnough?'DEVELOPMENT SAMPLE LIMITED':!holdoutEnough?'HOLDOUT SAMPLE LIMITED':'DESCRIPTIVE COMPARISON'};
 }).sort((a,b)=>b.holdTests-a.holdTests||a.stat.localeCompare(b.stat));
 return {ready:true,cutoff,holdoutWeeks,pairedProfiles,groups:summarized,evaluatedGroups:summarized.filter(g=>g.ready).length};
}
