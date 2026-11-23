'use strict';
// Shared multi-sport live-feed foundation. Data quality and freshness; no wagering recommendations.
const PL_SPORTS=['NFL','NBA','MLB','NHL','NCAAB','NCAAF'];
const PL_TYPES=['schedule','roster','injury','weather','game_status','player_stats','historical_stats','opponent_stats'];
const PL_TTLS={schedule:12*3600000,roster:12*3600000,injury:3600000,weather:3600000,
 game_status:300000,player_stats:300000,historical_stats:72*3600000,opponent_stats:72*3600000};
function plCleanId(x){return typeof x==='string'&&/^[A-Za-z0-9:_\-.]{1,128}$/.test(x)?x:null}
function plIso(value){const t=Date.parse(value);return Number.isFinite(t)?new Date(t).toISOString():null}
function plEnvelope(input,now=Date.now()){
 if(!input||!PL_SPORTS.includes(input.sport)||!PL_TYPES.includes(input.type))return {ok:false,error:'UNKNOWN_SPORT_OR_TYPE'};
 const source=plCleanId(input.source),id=plCleanId(input.id);
 const eventAt=plIso(input.eventAt),retrievedAt=plIso(input.retrievedAt);
 if(!source||!id||!retrievedAt)return {ok:false,error:'MISSING_PROVENANCE'};
 const received=Date.parse(retrievedAt),event=eventAt?Date.parse(eventAt):null;
 if(received>now+60000||event!==null&&event>now+32*86400000)return {ok:false,error:'INVALID_TIMESTAMP'};
 if(now-received>90*86400000)return {ok:false,error:'TOO_OLD_FOR_LIVE_FEED'};
 const teamId=input.teamId==null?null:plCleanId(input.teamId);
 const playerId=input.playerId==null?null:plCleanId(input.playerId);
 const gameId=input.gameId==null?null:plCleanId(input.gameId);
 if((input.teamId!=null&&!teamId)||(input.playerId!=null&&!playerId)||(input.gameId!=null&&!gameId))
  return {ok:false,error:'INVALID_ID'};
 if(input.type==='player_stats'&&!playerId)return {ok:false,error:'PLAYER_ID_REQUIRED'};
 if(input.type==='game_status'&&!gameId)return {ok:false,error:'GAME_ID_REQUIRED'};
 // Snapshot and stale/available state are separate from verified contents.
 const verified=input.verification==='verified'?'verified':input.verification==='corroborated'?'corroborated':'unverified';
 const record={sport:input.sport,type:input.type,source,id,teamId,playerId,gameId,
  eventAt,retrievedAt,verification:verified,payload:input.payload??null};
 return {ok:true,record};
}
function plFreshness(record,now=Date.now()){
 if(!record)return {state:'MISSING',ageMs:null,ttlMs:null};
 const t=Date.parse(record.retrievedAt),ttl=PL_TTLS[record.type];
 if(!Number.isFinite(t)||!ttl||t>now+60000)return {state:'INVALID',ageMs:null,ttlMs:ttl||null};
 const age=Math.max(0,now-t);
 return {state:age<=ttl?'CURRENT':'STALE',ageMs:age,ttlMs:ttl};
}
function plKey(record){return [record.sport,record.type,record.source,record.id].join('|')}
function plIngest(store,input,now=Date.now()){
 const valid=plEnvelope(input,now);
 if(!valid.ok)return valid;
 const record=valid.record,key=plKey(record),previous=store.get(key);
 if(previous&&Date.parse(previous.retrievedAt)>=Date.parse(record.retrievedAt))
  return {ok:false,error:'DUPLICATE_OR_OLDER'};
 // Keep no more than the most recent snapshot for a given type/source/record identity.
 store.set(key,record);
 return {ok:true,record};
}
function plFeedSummary(store,sport,now=Date.now()){
 return PL_TYPES.map(type=>{
  const records=[...store.values()].filter(r=>r.sport===sport&&r.type===type);
  if(!records.length)return {type,state:'NOT_CONNECTED',lastRetrieved:null,count:0,verification:'unverified'};
  const current=records.filter(r=>plFreshness(r,now).state==='CURRENT');
  const newest=records.reduce((a,b)=>Date.parse(a.retrievedAt)>Date.parse(b.retrievedAt)?a:b);
  return {type,state:current.length?'CURRENT':'STALE',lastRetrieved:newest.retrievedAt,count:records.length,
   verification:current.some(r=>r.verification==='verified')?'verified':current.some(r=>r.verification==='corroborated')?'corroborated':'unverified'};
 });
}
function plRefreshDecision(record,type,now=Date.now()){
 const status=plFreshness(record,now);
 if(!PL_TYPES.includes(type))return {action:'BLOCK',reason:'UNKNOWN_TYPE'};
 if(status.state==='CURRENT')return {action:'REUSE',reason:'FRESH_CACHE'};
 return {action:'FETCH',reason:status.state};
}
