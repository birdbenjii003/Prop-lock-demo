'use strict';
// V2.4 diagnostic audit of the ELIGIBLE imported player/stat profiles.
// This is not a validation of the original provider file or player participation.
function qualityAudit(profiles){
 const valid=profiles.filter(p=>p.source==='imported'&&Array.isArray(p.records));
 const players=new Set(),weeks=new Set(),categories=new Set(),roles=new Map();
 let records=0,invalidValues=0,missingOpp=0,duplicateWeeks=0,missingOpportunityProfiles=0,shortProfiles=0;
 const byStat=new Map();
 for(const p of valid){
  const player=p.playerKey||p.id,role=p.position||'Unknown';
  players.add(player);categories.add(p.stat);
  const label=p.stat;
  if(!byStat.has(label))byStat.set(label,{stat:label,profiles:0,records:0,invalid:0,missingOpp:0,duplicates:0});
  const g=byStat.get(label);g.profiles++;
  if(p.records.length<10)shortProfiles++;
  const seen=new Set();
  for(const r of p.records){
   records++;g.records++;
   const date=r.season+':'+r.week;
   if(seen.has(date)){duplicateWeeks++;g.duplicates++}seen.add(date);
   weeks.add(date);
   if(!Number.isFinite(r.value)){invalidValues++;g.invalid++}
   if(!r.opp||r.opp==='Opponent unavailable'){missingOpp++;g.missingOpp++}
  }
  if(!roles.has(role))roles.set(role,{role,profiles:0,players:new Set()});
  roles.get(role).profiles++;roles.get(role).players.add(player);
 }
 const lookup=new Map();for(const p of valid){
  const key=p.playerKey||p.id;
  if(!lookup.has(key))lookup.set(key,new Set());lookup.get(key).add(p.stat);
 }
 const opportunityNeeds={'Passing Yards':'Passing Attempts','Passing TDs':'Passing Attempts','Interceptions':'Passing Attempts','Rushing Yards':'Carries','Rushing TDs':'Carries','Receiving Yards':'Targets','Receptions':'Targets','Receiving TDs':'Targets'};
 for(const p of valid){const required=opportunityNeeds[p.stat];if(required&&!lookup.get(p.playerKey||p.id).has(required))missingOpportunityProfiles++}
 const roleRows=[...roles.values()].map(x=>({role:x.role,profiles:x.profiles,players:x.players.size})).sort((a,b)=>b.profiles-a.profiles);
 const statRows=[...byStat.values()].sort((a,b)=>b.records-a.records);
 return {profiles:valid.length,players:players.size,records,weeks:weeks.size,categories:categories.size,invalidValues,missingOpp,duplicateWeeks,missingOpportunityProfiles,shortProfiles,roleRows,statRows};
}
function roleBacktestAudit(profiles){
 const groups=new Map();
 for(const p of profiles.filter(p=>p.source==='imported'&&Array.isArray(p.records))){
  const x=rollingBacktest(p),role=p.position||'Unknown',key=role+'|'+p.stat;
  if(!groups.has(key))groups.set(key,{role,stat:p.stat,players:new Set(),tests:0,sumError:0,naiveError:0});
  const g=groups.get(key);if(!x.n)continue;
  g.players.add(p.playerKey||p.id);g.tests+=x.n;
  for(const r of x.rows){g.sumError+=r.absError;g.naiveError+=r.naiveError}
 }
 return [...groups.values()].filter(x=>x.tests).map(g=>({role:g.role,stat:g.stat,players:g.players.size,tests:g.tests,mae:g.sumError/g.tests,benchmarkMae:g.naiveError/g.tests,
   enough:g.tests>=30&&g.players.size>=10})).sort((a,b)=>b.tests-a.tests||a.role.localeCompare(b.role));
}
