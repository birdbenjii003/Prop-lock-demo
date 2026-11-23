'use strict';
// Phase 5 GSIS -> ESPN ID bridge, from a published nflverse cross-ID dataset.
// A crosswalk + ESPN roster ID match is corroborated identity, not guaranteed eligibility.
const SCENARIO_CROSSWALK_URL='https://github.com/nflverse/nflverse-data/releases/download/players/players.csv';
function scenarioGsisId(p){
 const key=String(p?.playerKey||'');
 const match=/^(?:id:|gsis:)(00-\d{7})$/.exec(key);
 return match?match[1]:null;
}
function scenarioCrosswalkRows(csvRows){
 if(!Array.isArray(csvRows)||csvRows.length<2)return {status:'INVALID_CROSSWALK',reason:'Missing CSV records',entries:[]};
 const headers=csvRows[0].map(x=>String(x).trim().toLowerCase());
 const col=name=>headers.indexOf(name);
 const gs=col('gsis_id'),es=col('espn_id'),nm=col('display_name'),pos=col('position');
 if(gs<0||es<0||nm<0)return {status:'INVALID_CROSSWALK',reason:'Required gsis_id, espn_id, display_name columns missing',entries:[]};
 const entries=csvRows.slice(1).map(r=>({gsisId:String(r[gs]||'').trim(),espnId:String(r[es]||'').trim(),
  name:String(r[nm]||'').trim(),position:pos>=0?String(r[pos]||'').trim():''}))
  .filter(x=>/^00-\d{7}$/.test(x.gsisId)&&/^\d+$/.test(x.espnId)&&x.name);
 return {status:'CROSSWALK_PARSED',entries};
}
function scenarioResolveEspnId(player,crosswalk){
 const gsis=scenarioGsisId(player);
 if(!gsis)return {status:'MISSING_GSIS_ID',reason:'Historical profile does not have a canonical GSIS ID'};
 if(crosswalk?.status!=='CROSSWALK_PARSED')return {status:'CROSSWALK_UNAVAILABLE',reason:'Valid nflverse identifier export unavailable'};
 const entries=crosswalk.entries.filter(row=>row.gsisId===gsis);
 if(!entries.length)return {status:'ID_NOT_MAPPED',reason:'No ESPN identifier for historical GSIS ID'};
 const ids=[...new Set(entries.map(x=>x.espnId))];
 if(ids.length!==1)return {status:'CONFLICTING_CROSSWALK',reason:'One GSIS ID maps to several ESPN IDs'};
 // Fail closed for a reused ESPN ID (including reuse across 2026 rookie/old player records).
 if(crosswalk.entries.some(x=>x.espnId===ids[0]&&x.gsisId!==gsis))
  return {status:'CONFLICTING_CROSSWALK',reason:'ESPN ID maps to multiple GSIS IDs'};
 const row=entries[0];
 if(typeof scenarioNormalizePersonName==='function'&&
    scenarioNormalizePersonName(row.name)!==scenarioNormalizePersonName(player.name))
  return {status:'NAME_CONFLICT',reason:'Crosswalk name and historical player name disagree'};
 const historicalPosition=String(player.position||'').toUpperCase();
 const crossPosition=String(row.position||'').toUpperCase();
 if(['QB','RB','WR','TE'].includes(historicalPosition)&&crossPosition&&
    crossPosition!==historicalPosition)return {status:'POSITION_CONFLICT',reason:'Crosswalk position and historical position disagree'};
 return {status:'CROSSWALK_ID_RESOLVED',gsisId:gsis,espnId:ids[0],source:SCENARIO_CROSSWALK_URL,
   reason:'Unique GSIS-to-ESPN mapping with name check, not independently authenticated by the league'};
}
function scenarioVerifyRosterById(resolved,roster,player,team,atMs=Date.now()){
 const requestedTeam=String(team||'').toUpperCase();
 const base={status:'IDENTITY_UNVERIFIED',team:requestedTeam,checkedAt:new Date(atMs).toISOString()};
 if(resolved?.status!=='CROSSWALK_ID_RESOLVED')return {...base,reason:resolved?.reason||'Crosswalk unresolved'};
 if(!Array.isArray(roster?.athletes))return {...base,reason:'No valid roster payload'};
 const matches=scenarioRosterCandidates(roster).filter(a=>String(a.id||'')===resolved.espnId);
 if(matches.length!==1)return {...base,status:matches.length?'AMBIGUOUS_ESPN_ID':'PLAYER_NOT_ON_TEAM_ROSTER',
   reason:'ESPN ID must appear exactly once on the requested team roster'};
 const athlete=matches[0];
 if(scenarioNormalizePersonName(athlete.fullName||athlete.displayName)!==scenarioNormalizePersonName(player.name))
  return {...base,status:'NAME_CONFLICT',reason:'ESPN athlete name disagrees with historical player'};
 const hist=String(player.position||'').toUpperCase(),curr=String(athlete.position?.abbreviation||'').toUpperCase();
 if(['QB','RB','WR','TE'].includes(hist)&&curr&&hist!==curr)
  return {...base,status:'POSITION_CONFLICT',reason:'Current roster role differs from historical player'};
 return {...base,status:'ID_CORROBORATED',gsisId:resolved.gsisId,espnId:resolved.espnId,
  matchedName:athlete.fullName||athlete.displayName,
  source:'nflverse players.csv GSIS/ESPN mapping + ESPN historical-team roster',
  reason:'Same persistent ESPN ID on roster and in crosswalk; team association corroborated at check time, not guaranteed for kickoff'};
}
