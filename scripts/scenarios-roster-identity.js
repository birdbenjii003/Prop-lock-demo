'use strict';
// Phase 4: fail-closed roster identity checks. A name match is never an identity join.
const SCENARIO_ROSTER_MAX_AGE_MS=6*60*60*1000;
function scenarioRosterUrl(team){
 if(!/^[A-Z]{2,3}$/.test(String(team||'').toUpperCase()))return null;
 return 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/'+encodeURIComponent(team.toLowerCase())+'/roster';
}
function scenarioNormalizePersonName(s){
 return String(s||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase()
  .replace(/\b(jr|sr|ii|iii|iv)\b\.?/g,'').replace(/[^a-z0-9]/g,'');
}
function scenarioRosterCandidates(payload){
 const groups=Array.isArray(payload?.athletes)?payload.athletes:[];
 return groups.flatMap(g=>{
  if(Array.isArray(g?.items))return g.items;
  if(g?.displayName||g?.fullName)return [g];
  return [];
 });
}
function scenarioCheckRoster(payload,player,requestedTeam,atMs=Date.now()){
 const team=String(requestedTeam||'').toUpperCase();
 const result={team,source:'ESPN team roster (unofficial, subject to change)',checkedAt:new Date(atMs).toISOString(),
  status:'ROSTER_UNAVAILABLE',reason:'No verifiable roster data; cannot confirm current player team'};
 if(!scenarioRosterUrl(team)||!player?.name||!payload||!Array.isArray(payload.athletes))return result;
 const athletes=scenarioRosterCandidates(payload);
 if(!athletes.length)return {...result,status:'ROSTER_EMPTY'};
 const normalized=scenarioNormalizePersonName(player.name);
 const matches=athletes.filter(a=>scenarioNormalizePersonName(a.fullName||a.displayName)===normalized);
 if(matches.length===0)return {...result,status:'NOT_FOUND_ON_TEAM_ROSTER',reason:'No exact normalized name match on historical team roster; player may have moved, or source may be incomplete'};
 if(matches.length>1)return {...result,status:'AMBIGUOUS_NAME_MATCH',reason:'Multiple players share the matched name; cannot establish identity'};
 const match=matches[0],position=match.position?.abbreviation||match.position?.name||'';
 const historicalPosition=String(player.position||'').toUpperCase();
 if(historicalPosition&&historicalPosition!=='UNKNOWN'&&position&&historicalPosition!==position.toUpperCase())
  return {...result,status:'POSITION_CONFLICT',reason:'Roster position differs from historical inferred role; no identity confirmation'};
 return {...result,status:'PROVISIONAL_NAME_MATCH',rosterId:String(match.id||''),matchedName:match.fullName||match.displayName,
  reason:'Unique normalized roster name on historical team, NOT a verified GSIS-to-ESPN identity match. Current team assignment remains provisional'};
}
function scenarioRosterIsFresh(result,nowMs=Date.now()){
 const stamp=Date.parse(result?.checkedAt);
 return Number.isFinite(stamp)&&stamp<=nowMs+60000&&nowMs-stamp<=SCENARIO_ROSTER_MAX_AGE_MS;
}
function scenarioPlayerGameGate(result,player,team,nowMs=Date.now()){
 if(!scenarioRosterIsFresh(result,nowMs))return {status:'ROSTER_UNVERIFIED',reason:'Roster check missing or older than six hours'};
 if(result.team!==String(team||'').toUpperCase())return {status:'TEAM_MISMATCH',reason:'Roster check is not for the selected team'};
 if(result.status!=='PROVISIONAL_NAME_MATCH'||result.matchedName&&scenarioNormalizePersonName(result.matchedName)!==scenarioNormalizePersonName(player?.name))
  return {status:'PLAYER_TEAM_NOT_CONFIRMED',reason:result.reason||'Roster evidence insufficient'};
 return {status:'PROVISIONAL_ONLY',reason:'One unique name match is not a stable cross-provider identity. Scheduled game context remains TEAM-ONLY, not an established player matchup'};
}
