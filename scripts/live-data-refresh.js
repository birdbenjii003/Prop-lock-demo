'use strict';
// Page-open refresh policy only; never implies a server-side cron or guaranteed provider freshness.
const PL_SCHEDULE_TTL_MS=12*3600000;
const PL_FAILURE_BASE_MS=15*60000;
const PL_FAILURE_MAX_MS=6*3600000;
const PL_HISTORY_LIMIT=12;
function plSchedulePolicy(state,now=Date.now(),force=false){
 if(state?.inFlight)return {action:'SKIP',reason:'IN_FLIGHT'};
 const hold=Number(state?.blockedUntil)||0;
 if(hold>now)return {action:'SKIP',reason:'PROVIDER_COOLDOWN',nextAt:hold};
 const last=Number(state?.successAt)||0;
 if(!force&&last>now+60000)return {action:'SKIP',reason:'INVALID_CLOCK'};
 if(!force&&last&&now-last<PL_SCHEDULE_TTL_MS)
  return {action:'REUSE',reason:'FRESH_CACHE',nextAt:last+PL_SCHEDULE_TTL_MS};
 return {action:'FETCH',reason:force?'MANUAL_REFRESH':last?'STALE_CACHE':'NO_CACHE'};
}
function plRetryAfterMs(value,now=Date.now()){
 if(value==null||value==='')return null;
 const seconds=Number(value);
 if(Number.isFinite(seconds)&&seconds>=0)return Math.min(PL_FAILURE_MAX_MS,Math.ceil(seconds*1000));
 const date=Date.parse(value);
 if(!Number.isFinite(date))return null;
 return Math.min(PL_FAILURE_MAX_MS,Math.max(0,date-now));
}
function plNextFailure(state,status,retryAfter,now=Date.now()){
 const failures=Math.min(8,Math.max(0,Number(state?.failures)||0)+1);
 const exponential=Math.min(PL_FAILURE_MAX_MS,PL_FAILURE_BASE_MS*Math.pow(2,failures-1));
 const delay=plRetryAfterMs(retryAfter,now);
 // Never retry earlier than base safety cooldown, even when upstream Retry-After is smaller.
 const wait=Math.max(exponential,delay??0);
 return {failures,blockedUntil:now+Math.min(PL_FAILURE_MAX_MS,wait),
  failureAt:now,lastHttpStatus:Number.isInteger(status)?status:null};
}
function plLimitedHistory(history,entry){
 const list=Array.isArray(history)?history.filter(x=>x&&typeof x==='object'):[];
 return [...list,{at:entry.at,status:String(entry.status||'UNKNOWN').slice(0,32),
  detail:String(entry.detail||'').slice(0,180)}].slice(-PL_HISTORY_LIMIT);
}
function plSafeScheduleCache(candidate,now=Date.now()){
 if(!candidate||typeof candidate!=='object')return null;
 const saved=Number(candidate.savedAt);
 if(!Number.isFinite(saved)||saved>now+60000||saved<now-PL_SCHEDULE_TTL_MS)return null;
 const record=candidate.record;
 if(record?.sport!=='NFL'||record.type!=='schedule'||record.source!=='ESPN'||
    record.id!=='scoreboard-window'||record.verification!=='unverified')return null;
 if(!Number.isInteger(record.payload?.count)||record.payload.count<0||record.payload.count>1000)return null;
 if(!Array.isArray(record.payload?.events)||record.payload.events.length>100)return null;
 const at=Date.parse(record.retrievedAt);
 if(!Number.isFinite(at)||Math.abs(at-saved)>60000)return null;
 return record;
}
