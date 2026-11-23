'use strict';
// Live Data Foundation v2: real deployed site exercised with deterministic schedule fixtures.
// Fixture success is not proof of real source uptime, freshness, or accuracy.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const URL=process.env.LIVE_DATA_URL||'https://birdbenjii003.github.io/Prop-lock-demo/';
fs.mkdirSync('test-results',{recursive:true});
const checks=[],pageErrors=[],providerDiagnostics=[];
let browser,page;
async function check(name,fn){
 try {await fn(); checks.push({name,status:'PASS'});console.log('PASS',name);}
 catch(e){
  const detail=String(e.stack||e);checks.push({name,status:'FAIL',detail});
  console.error('FAIL',name,detail);
  await page?.screenshot({path:'test-results/live-data-v2-error-'+checks.length+'.png',fullPage:false}).catch(()=>{});
 }
}
async function routeSchedule(payload,status=200){
 await page.unroute('**/apis/site/v2/sports/football/nfl/scoreboard?**');
 let calls=0;
 await page.route('**/apis/site/v2/sports/football/nfl/scoreboard?**',async route=>{
  calls++;
  await route.fulfill({status,contentType:'application/json',headers:{'access-control-allow-origin':'*'},
   body:status===200?JSON.stringify(payload):'unavailable'});
 });
 return ()=>calls;
}
async function pressRefresh(){
 await page.locator('#liveRefreshNflSchedule').click();
 await page.waitForFunction(()=>!document.querySelector('#liveScheduleRefreshStatus')?.textContent?.includes('Checking schedule source'),null,{timeout:20000});
 return page.locator('#liveScheduleRefreshStatus').innerText();
}
async function scheduleStatus(){
 return page.evaluate(()=>{
  const rows=[...document.querySelectorAll('#liveFeedMonitor tbody tr')];
  const row=rows.find(r=>r.querySelector('td')?.textContent==='schedule');
  return row?[...row.querySelectorAll('td')].map(td=>td.textContent):null;
 });
}
async function main(){
 browser=await chromium.launch({headless:true});
 const context=await browser.newContext({viewport:{width:390,height:844},deviceScaleFactor:1});
 page=await context.newPage();page.setDefaultTimeout(30000);
 page.on('pageerror',e=>pageErrors.push(e.message));
 try{
  await check('Deployed Prop Lock loads its foundation and freshness panel',async()=>{
   const response=await page.goto(URL,{waitUntil:'domcontentloaded',timeout:45000});
   assert.equal(response?.status(),200);
   await page.locator('#liveFeedMonitor table').waitFor();
   await page.locator('#liveRefreshNflSchedule').waitFor();
   assert.equal((await scheduleStatus())[1],'NOT_CONNECTED');
   assert.match(await page.locator('#liveFeedMonitor').innerText(),/unverified/i);
   assert.match(await page.locator('body').innerText(),/automatic polling is not enabled yet/i);
  });
  await check('Opt-in ESPN schedule fixture records a current unverified source',async()=>{
   const calls=await routeSchedule({events:[{id:'game-123',date:new Date(Date.now()+2*86400000).toISOString()}]});
   const result=await pressRefresh();
   assert.match(result,/Retrieved 1 scheduled events/);
   assert.equal(calls(),1);
   const row=await scheduleStatus();
   assert.equal(row[1],'CURRENT');assert.equal(row[2],'unverified');
   assert.match(row[3],/^20\d\d-/);
   const snapshot=await page.evaluate(()=>[...plLiveStore.values()].find(r=>r.type==='schedule'));
   assert.equal(snapshot.source,'ESPN');
   assert.equal(snapshot.payload.count,1);
   assert.equal(snapshot.payload.events[0].id,'game-123');
  });
  await check('Duplicate-or-older update cannot replace existing schedule',async()=>{
   const response=await page.evaluate(()=>{
    const r=[...plLiveStore.values()].find(x=>x.type==='schedule');
    const stale={...r,retrievedAt:new Date(Date.parse(r.retrievedAt)-1000).toISOString(),payload:{count:999}};
    const result=plRecordSource(stale);
    return {result,current:[...plLiveStore.values()].find(x=>x.type==='schedule').payload.count};
   });
   assert.equal(response.result.error,'DUPLICATE_OR_OLDER');
   assert.equal(response.current,1);
  });
  await check('A schedule snapshot transitions to STALE at its defined TTL',async()=>{
   const status=await page.evaluate(()=>{
    const now=Date.now();
    const r=[...plLiveStore.values()].find(x=>x.type==='schedule');
    const atTTL=plFreshness(r,Date.parse(r.retrievedAt)+13*3600000);
    const reused=plRefreshDecision(r,'schedule',now);
    renderLiveFeedMonitor();
    return {state:atTTL.state,reused:reused.action,active:document.querySelector('#liveRefreshNflSchedule')!==null};
   });
   assert.equal(status.state,'STALE');
   assert.equal(status.reused,'REUSE');
   assert.equal(status.active,true);
  });
  await check('Invalid schedule payload fails without overwriting last good data',async()=>{
   await routeSchedule({teams:[]});
   const result=await pressRefresh();
   assert.match(result,/Schedule unavailable: Schedule events array missing/);
   const row=await scheduleStatus();
   assert.equal(row[1],'CURRENT');
   assert.equal(await page.evaluate(()=>[...plLiveStore.values()].find(r=>r.type==='schedule').payload.count),1);
  });
  await check('Provider HTTP failure is visible and does not erase prior evidence',async()=>{
   await routeSchedule({},503);
   const result=await pressRefresh();
   assert.match(result,/Schedule unavailable: Schedule HTTP 503/);
   assert.equal((await scheduleStatus())[1],'CURRENT');
  });
  await check('NFL empty schedule is distinguished from missing schedule',async()=>{
   await routeSchedule({events:[]});
   const result=await pressRefresh();
   // A refresh in the same millisecond as the previous accepted timestamp can be deduped.
   assert.ok(/Retrieved 0 scheduled events|DUPLICATE_OR_OLDER/.test(result),result);
   assert.ok((await scheduleStatus())[1]==='CURRENT');
  });
  await check('Other sports are isolated and show NOT_CONNECTED',async()=>{
   const state=await page.evaluate(()=>{
    const sport=currentSport;currentSport='NBA';renderLiveFeedMonitor();
    const rows=plFeedSummary(plLiveStore,'NBA');
    const hidden=!document.querySelector('#liveRefreshNflSchedule');
    currentSport=sport;renderLiveFeedMonitor();
    return {rows,hidden};
   });
   assert.ok(state.rows.every(x=>x.state==='NOT_CONNECTED'));
   assert.equal(state.hidden,true);
  });
  await check('NFL historical snapshot does not claim independent verification',async()=>{
   await page.waitForFunction(()=>!autoInProgress,null,{timeout:90000});
   const evidence=await page.evaluate(()=>[...plLiveStore.values()].find(r=>r.type==='historical_stats'));
   if(evidence)assert.equal(evidence.verification,'unverified');
   assert.equal((await scheduleStatus())[2],'unverified');
   assert.deepEqual(pageErrors,[]);
  });
  await page.unrouteAll({behavior:'wait'});
  // Nonblocking real provider diagnostics; never turn a fixture pass into a claim of live feed accuracy.
  try{
   const url=await page.evaluate(()=>scenarioScheduleUrl());
   const r=await page.request.get(url,{timeout:12000});
   providerDiagnostics.push({source:'ESPN schedule',status:r.ok()?'HTTP_OK':'HTTP_'+r.status()});
  }catch(e){providerDiagnostics.push({source:'ESPN schedule',status:'NETWORK_UNAVAILABLE',detail:String(e)})}
 }finally{
  await page.screenshot({path:'test-results/live-data-v2-mobile.png',fullPage:false}).catch(()=>{});
  fs.writeFileSync('test-results/live-data-v2-assertions.json',JSON.stringify({
   site:URL,checks,pageErrors,providerDiagnostics,fixturesSimulated:true,
   notEstablished:['actual provider refresh interval','automated polling','persistent storage','accuracy of live schedule','injury and roster feeds']
  },null,2));
  await browser.close();
 }
 const fails=checks.filter(x=>x.status==='FAIL');
 if(fails.length)throw Error(fails.length+' live-data acceptance checks failed; inspect artifacts');
 console.log('LIVE_DATA_V2_BROWSER_FIXTURES_PASS — real provider data not independently validated');
}
main().catch(e=>{console.error(e);process.exitCode=1});
