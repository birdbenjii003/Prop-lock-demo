'use strict';
// Research engine V2.7. Only completed weekly NFL records; nothing here claims
// upcoming-game context, official roster positions, probabilities, or market odds.
const RESEARCH_VOLUME={'Passing Yards':'Passing Attempts','Passing TDs':'Passing Attempts','Interceptions':'Passing Attempts','Rushing Yards':'Carries','Rushing TDs':'Carries','Receiving Yards':'Targets','Receptions':'Targets','Receiving TDs':'Targets'};
function researchMean(xs){return xs.length?xs.reduce((s,x)=>s+x,0)/xs.length:null}
function researchMedian(xs){if(!xs.length)return null;const a=[...xs].sort((x,y)=>x-y),n=a.length;return n%2?a[(n-1)/2]:(a[n/2-1]+a[n/2])/2}
function researchKey(r){return String(r.season)+':'+String(r.week)}
function researchSamples(p,allProfiles){
 if(!p||!Array.isArray(p.records))return {games:0,volumeLabel:null,paired:[],recentVolume:null,recentEfficiency:null,efficiencyRange:null,trend:null,baseline:null,productionStd:null,availability:'No actual game logs'};
 const valid=[...p.records].filter(r=>Number.isFinite(r.value)).sort((a,b)=>a.season-b.season||a.week-b.week);
 const n=valid.length,values=valid.map(r=>r.value),last10=values.slice(-10),last5=values.slice(-5);
 const baseline=n?(0.55*researchMean(last10)+0.30*researchMean(last5)+0.15*researchMean(values)):null;
 const trend=n>=10?researchMean(last5)-researchMean(values.slice(-10,-5)):null;
 const volumeLabel=RESEARCH_VOLUME[p.stat]||null;
 const sister=volumeLabel?allProfiles.find(x=>x.playerKey===p.playerKey&&x.stat===volumeLabel):null;
 const volumes=new Map((sister?.records||[]).filter(r=>Number.isFinite(r.value)).map(r=>[researchKey(r),r.value]));
 const paired=valid.map(r=>({date:researchKey(r),volume:volumes.get(researchKey(r)),output:r.value})).filter(r=>Number.isFinite(r.volume)&&r.volume>0).slice(-10);
 const recent=paired.slice(-5),sumVolume=paired.reduce((s,r)=>s+r.volume,0),rate=sumVolume>0?paired.reduce((s,r)=>s+r.output,0)/sumVolume:null;
 const recentVolume=recent.length>=5?researchMean(recent.map(r=>r.volume)):null;
 const recentEfficiency=paired.length>=5?rate:null;
 const effRates=paired.map(r=>r.output/r.volume),efficiencyRange=paired.length>=5?[Math.min(...effRates),Math.max(...effRates)]:null;
 const productionStd=last10.length>1?Math.sqrt(last10.reduce((s,x)=>s+(x-researchMean(last10))**2,0)/(last10.length-1)):null;
 return {games:n,volumeLabel,paired,recentVolume,recentEfficiency,efficiencyRange,trend,baseline,productionStd,
 availability:!volumeLabel?'No directly comparable opportunity field for this statistic':!sister?'Required opportunity field is absent':paired.length<5?'Fewer than five valid paired game logs':'Historical volume and production coverage available'};
}
function researchTeamEnvironment(p,allProfiles){
 if(!p||!Array.isArray(p.records))return {games:0,passing:null,rushing:null,targets:null,notes:'No data'};
 // Only last five unique completed team-week records available in this snapshot.
 const team=p.team,teamWeeks=new Map();
 for(const x of allProfiles){
  if(!['Passing Attempts','Carries','Targets'].includes(x.stat)||!Array.isArray(x.records))continue;
  for(const r of x.records){
   if(r.team!==team||!Number.isFinite(r.value))continue;
   const key=researchKey(r);if(!teamWeeks.has(key))teamWeeks.set(key,{season:r.season,week:r.week,passing:0,rushing:0,targets:0,passKnown:false,rushKnown:false,targetKnown:false});
   const w=teamWeeks.get(key);
   if(x.stat==='Passing Attempts'){w.passing+=r.value;w.passKnown=true}
   if(x.stat==='Carries'){w.rushing+=r.value;w.rushKnown=true}
   if(x.stat==='Targets'){w.targets+=r.value;w.targetKnown=true}
  }
 }
 const weeks=[...teamWeeks.values()].sort((a,b)=>a.season-b.season||a.week-b.week).slice(-5);
 const avg=(prop,flag)=>{const rows=weeks.filter(w=>w[flag]);return rows.length>=3?researchMean(rows.map(w=>w[prop])):null};
 return {games:weeks.length,passing:avg('passing','passKnown'),rushing:avg('rushing','rushKnown'),targets:avg('targets','targetKnown'),
 notes:'Team-level recorded volume, not pace per possession or an upcoming game forecast'};
}
function researchOpponentContext(p,allProfiles,opponent){
 const same=allProfiles.filter(x=>x.stat===p.stat&&x.position===p.position&&Array.isArray(x.records));
 const matched=[],league=[];let opponentWeeks=new Set();
 for(const x of same){
  for(const r of x.records){
   if(!Number.isFinite(r.value)||!r.opp||r.opp==='Opponent unavailable')continue;
   const item={player:x.playerKey||x.id,value:r.value,season:r.season,week:r.week};
   league.push(item);
   if(r.opp===opponent){matched.push(item);opponentWeeks.add(researchKey(r))}
  }
 }
 const people=new Set(matched.map(x=>x.player)).size;
 const enough=matched.length>=8&&people>=3&&opponentWeeks.size>=3;
 const avg=matched.length?researchMean(matched.map(x=>x.value)):null;
 const leagueAvg=league.length?researchMean(league.map(x=>x.value)):null;
 const difference=enough&&leagueAvg>0?100*(avg/leagueAvg-1):null;
 return {opponent,stat:p.stat,role:p.position,playerGames:matched.length,players:people,teamWeeks:opponentWeeks.size,average:avg,leagueAverage:leagueAvg,difference,enough,
 note:'Historical allowance to eligible players of inferred role. Includes multiple players per defense game; not coverage assignments or adjusted matchup forecasts.'};
}
function researchIntegration(p,allProfiles,opponent,multiplier){
 const deep=researchSamples(p,allProfiles),team=researchTeamEnvironment(p,allProfiles),trait=researchOpponentContext(p,allProfiles,opponent);
 const factor=Number.isFinite(multiplier)?Math.max(.6,Math.min(1.4,multiplier)):1;
 const opportunityScenario=deep.recentVolume!==null&&deep.recentEfficiency!==null?
   {available:true,volume:deep.recentVolume*factor,efficiency:deep.recentEfficiency,illustration:deep.recentVolume*factor*deep.recentEfficiency}:
   {available:false,illustration:null};
 const blockers=[];
 if(deep.games<10)blockers.push('Fewer than ten historical games');
 if(!opportunityScenario.available)blockers.push('No sufficiently paired opportunities and output');
 if(!trait.enough)blockers.push('Sparse opponent-role comparison');
 if(team.passing===null)blockers.push('Verified team passing attempts not present');
 blockers.push('No upcoming defensive personnel, projected snaps, injuries or pace forecast');
 blockers.push('No independent full-method forecast validation');
 return {deep,team,trait,opportunityScenario,blockers,status:'RESEARCH ONLY — NOT A VERIFIED FUTURE-GAME PROJECTION',projection:null,overProbability:null};
}
