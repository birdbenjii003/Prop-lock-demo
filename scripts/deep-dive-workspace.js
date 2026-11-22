'use strict';
// Deep Dive 3.2 — player-history-only research workspace.
// A sport adapter may provide additional columns; missing inputs are never inferred.
const DEEP_DIVE_TABS=[
 ['overview','Overview'],['performance','Performance'],['trends','Trends'],['volume','Volume'],
 ['quality','Opportunity quality'],['role','Role & usage'],['efficiency','Efficiency'],
 ['expected','Expected production'],['sustainability','Sustainability'],['stability','Stability'],
 ['weighting','Weighting'],['tendencies','Tendencies'],['projection','Projection'],
 ['validation','Validation'],['evidence','Evidence quality'],['h2h','H2H history']
];
function ddwMean(a){return a.length?a.reduce((s,x)=>s+x,0)/a.length:null}
function ddwStd(a){if(a.length<2)return null;const m=ddwMean(a);return Math.sqrt(a.reduce((s,x)=>s+(x-m)**2,0)/(a.length-1))}
function ddwMedian(a){if(!a.length)return null;const b=[...a].sort((x,y)=>x-y),n=b.length;return n%2?b[(n-1)/2]:(b[n/2-1]+b[n/2])/2}
function ddwId(r){return String(r.season)+':'+String(r.week)}
function ddwRounded(x){return x===null||!Number.isFinite(x)?null:Math.round(x*100)/100}
// Fixed chronological diagnostic: earlier forecast errors set the radius;
// later errors evaluate coverage, never re-fit the radius.
function ddwRollingRangeAudit(backtest){
 const eligible=backtest.filter(r=>Number.isFinite(r.historyPrediction)&&Number.isFinite(r.actual)&&Number.isFinite(r.historyError));
 if(eligible.length<30)return {available:false,reason:'At least 30 chronological prior-only forecasts are required (20 calibration, 10 evaluation).',count:eligible.length};
 const calibration=eligible.slice(0,20),evaluation=eligible.slice(20);
 const errors=calibration.map(r=>r.historyError).sort((a,b)=>a-b);
 const rank=Math.ceil((errors.length+1)*0.8),radius=errors[Math.min(errors.length-1,rank-1)];
 const covered=evaluation.filter(r=>Math.abs(r.actual-r.historyPrediction)<=radius).length;
 const width=2*radius,observedCoverage=covered/evaluation.length;
 return {available:true,calibrationCount:calibration.length,evaluationCount:evaluation.length,
  radius,width,covered,observedCoverage,targetCoverage:0.8,
  status:observedCoverage>=0.8?'MET_IN_THIS_SAMPLE':'BELOW_TARGET_IN_THIS_SAMPLE',
  warning:'Retrospective sequential diagnostic only; profile selection and data provenance are not independently frozen. This is not a validated next-game interval or a line probability.'};
}
function deepDiveWorkspace(p,profiles,line){
 const imported=p?.source==='imported'&&Array.isArray(p.records),rows=imported?
  [...p.records].filter(r=>Number.isFinite(r.value)).sort((a,b)=>a.season-b.season||a.week-b.week):[];
 const values=rows.map(r=>r.value),l10=values.slice(-10),l5=values.slice(-5);
 const alternatives=imported?deepDiveAlternatives(p,profiles,line):null;
 const volumeLabel=alternatives?.volumeLabel||null;
 const opportunity=volumeLabel?profiles.find(q=>q.playerKey===p.playerKey&&q.stat===volumeLabel&&Array.isArray(q.records)):null;
 const volumeIndex=new Map((opportunity?.records||[]).filter(r=>Number.isFinite(r.value)).map(r=>[ddwId(r),r.value]));
 const paired=rows.map(r=>({...r,volume:volumeIndex.get(ddwId(r))})).filter(r=>Number.isFinite(r.volume)&&r.volume>0);
 const lastPaired=paired.slice(-10),production=lastPaired.reduce((s,r)=>s+r.value,0),opportunities=lastPaired.reduce((s,r)=>s+r.volume,0);
 const rate=lastPaired.length>=5&&opportunities>0?production/opportunities:null;
 const recentVolume=paired.length>=5?ddwMean(paired.slice(-5).map(r=>r.volume)):null;
 const previousVolume=paired.length>=10?ddwMean(paired.slice(-10,-5).map(r=>r.volume)):null;
 const lastShares=rows.filter(r=>Number.isFinite(r.opportunityShare)).slice(-5);
 const priorShares=rows.filter(r=>Number.isFinite(r.opportunityShare)).slice(-10,-5);
 const recentShare=lastShares.length>=3?ddwMean(lastShares.map(r=>r.opportunityShare)):null;
 const previousShare=priorShares.length>=3?ddwMean(priorShares.map(r=>r.opportunityShare)):null;
 const h2h=new Map();
 for(const r of rows){if(!r.opp||r.opp==='Opponent unavailable')continue;
  if(!h2h.has(r.opp))h2h.set(r.opp,[]);h2h.get(r.opp).push({season:r.season,week:r.week,value:r.value,volume:volumeIndex.get(ddwId(r))??null})}
 const opponentHistory=[...h2h.entries()].map(([opponent,games])=>({opponent,games,
  mean:ddwMean(games.map(r=>r.value)),median:ddwMedian(games.map(r=>r.value)),over:games.filter(r=>r.value>line).length,
  under:games.filter(r=>r.value<line).length,meanVolume:ddwMean(games.filter(r=>r.volume!==null).map(r=>r.volume))})).sort((a,b)=>b.games.length-a.games.length||a.opponent.localeCompare(b.opponent));
 // Rolling, strictly prior-only one-game forecasts. Profile eligibility itself remains retrospectively selected.
 const backtest=[];
 for(let i=5;i<rows.length;i++){
  const past=rows.slice(0,i),pastVals=past.map(r=>r.value),recent=pastVals.slice(-10);
  const prediction=.55*ddwMean(recent)+.30*ddwMean(pastVals.slice(-5))+.15*ddwMean(pastVals);
  const pv=past.map(r=>({value:r.value,volume:volumeIndex.get(ddwId(r))})).filter(r=>Number.isFinite(r.volume)&&r.volume>0).slice(-10);
  const pvSum=pv.reduce((s,r)=>s+r.volume,0);
  const opportunityPrediction=pv.length>=5&&pvSum>0?ddwMean(pv.slice(-5).map(r=>r.volume))*pv.reduce((s,r)=>s+r.value,0)/pvSum:null;
  backtest.push({season:rows[i].season,week:rows[i].week,actual:rows[i].value,historyPrediction:prediction,opportunityPrediction,
   historyError:Math.abs(prediction-rows[i].value),oppError:opportunityPrediction===null?null:Math.abs(opportunityPrediction-rows[i].value)});
 }
 const dev=backtest.slice(0,-2),hold=backtest.slice(-2);
 const rollingRangeAudit=ddwRollingRangeAudit(backtest);
 const mae=(a,key)=>a.length?ddwMean(a.filter(r=>r[key]!==null).map(r=>r[key])):null;
 // Only report an interval if frozen calibration has enough unseen errors; today's data is not sufficient.
 const futureInterval={available:false,reason:'A fixed independent evaluation period, pre-declared model and sufficient out-of-time residuals are required; not currently verified.'};
 const seasonMean=ddwMean(values),previous=values.length>=10?ddwMean(values.slice(-10,-5)):null;
 const latestTeam=rows.length?rows[rows.length-1].team:null;
 const missing=[];
 if(!imported)missing.push('Historical imported player-game records');
 if(!opportunity)missing.push('Paired '+(volumeLabel||'opportunity')+' weekly data');
 if(values.length<10)missing.push('At least ten observed games for stable descriptive comparisons');
 missing.push('Advanced role data: snap or minutes share, routes, high-value chances, status changes');
 if(new Set(rows.map(r=>r.season)).size<2)missing.push('Multi-season history for this specific player/statistic not available');
 missing.push('Frozen independent calibration and validated future prediction intervals');
 return {sport:p?.sport||'NFL',stat:p?.stat||'',source:imported?'imported':'demo',n:values.length,
  rows,values,seasonMean,last5:ddwMean(l5),last10:ddwMean(l10),median:ddwMedian(l10),std:ddwStd(l10),
  recentChange:previous===null?null:ddwMean(l5)-previous,previous5:previous,
  wins:values.filter(v=>v>line).length,losses:values.filter(v=>v<line).length,ties:values.filter(v=>v===line).length,
  line,alternatives,volumeLabel,paired,lastPaired,recentVolume,previousVolume,rate,
  perGameRates:lastPaired.map(r=>({week:r.week,season:r.season,rate:r.value/r.volume})),
  latestTeam,opponentHistory,recentShare,previousShare,shareGames:rows.filter(r=>Number.isFinite(r.opportunityShare)).length,seasonCount:new Set(rows.map(r=>r.season)).size,backtest,development:dev,holdout:hold,developmentMae:mae(dev,'historyError'),holdoutMae:mae(hold,'historyError'),
  holdoutOpportunityMae:mae(hold,'oppError'),rollingRangeAudit,futureInterval,missing,
  warnings:['The imported profile set is selected using season-wide activity; this can introduce retrospective selection bias.',
  'The recent-two-test holdout is not a separately frozen evaluation dataset. Historical thresholds are not sportsbook odds.']};
}
