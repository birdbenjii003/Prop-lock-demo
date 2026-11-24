'use strict';
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const api=vm.runInNewContext(fs.readFileSync('scripts/live-data-refresh.js','utf8')+
'\n({plSchedulePolicy,plRetryAfterMs,plNextFailure,plLimitedHistory,plSafeScheduleCache})',{Date});
const now=Date.parse('2026-11-23T19:00:00Z');
assert.equal(api.plSchedulePolicy({},now).action,'FETCH');
assert.equal(api.plSchedulePolicy({successAt:now-3600000},now).action,'REUSE');
assert.equal(api.plSchedulePolicy({successAt:now-13*3600000},now).action,'FETCH');
assert.equal(api.plSchedulePolicy({successAt:now-1000},now,true).action,'FETCH');
assert.equal(api.plSchedulePolicy({inFlight:true},now,true).reason,'IN_FLIGHT');
assert.equal(api.plSchedulePolicy({blockedUntil:now+60000},now,true).reason,'PROVIDER_COOLDOWN');
assert.equal(api.plRetryAfterMs('120',now),120000);
assert.equal(api.plRetryAfterMs(new Date(now+120000).toUTCString(),now),120000);
assert.equal(api.plRetryAfterMs('oops',now),null);
const error=api.plNextFailure({failures:0},429,'1200',now);
assert.ok(error.blockedUntil>=now+1200000);
assert.equal(api.plNextFailure({failures:1},503,null,now).blockedUntil,now+30*60000);
assert.ok(api.plNextFailure({failures:8},503,null,now).blockedUntil<=now+6*3600000);
let history=[];
for(let i=0;i<18;i++)history=api.plLimitedHistory(history,{at:new Date(now+i).toISOString(),status:'OK',detail:'test'});
assert.equal(history.length,12);
assert.equal(history[0].detail,'test');
const record={sport:'NFL',type:'schedule',source:'ESPN',id:'scoreboard-window',
retrievedAt:new Date(now).toISOString(),verification:'unverified',payload:{count:1,events:[{id:'1'}]}};
assert.equal(api.plSafeScheduleCache({savedAt:now,record},now).payload.count,1);
assert.equal(api.plSafeScheduleCache({savedAt:now-13*3600000,record},now),null);
assert.equal(api.plSafeScheduleCache({savedAt:now,record:{...record,verification:'verified'}},now),null);
assert.equal(api.plSafeScheduleCache({savedAt:now,record:{...record,payload:{count:12,events:new Array(101).fill({})}}},now),null);
console.log('Rate limit/backoff, cache, refresh, history and fail-closed policy PASS');
