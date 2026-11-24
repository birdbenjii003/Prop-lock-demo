'use strict';
// Deployed-site acceptance against simulated schedule API responses.
// External provider uptime and background scheduling are not certified by fixtures.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const BASE=process.env.LIVE_DATA_URL||'https://birdbenjii003.github.io/Prop-lock-demo/';
fs.mkdirSync('test-results',{recursive:true});
const checks=[],errors=[],providerDiagnostics=[];
let browser,page,requests=0,providerStatus=200,retryAfter='',providerEvents=[];
async function check(name,fn){
 try{await fn();checks.push({name,status:'PASS'});console.log('PASS',name)}
 catch(e){const detail=String(e.stack||e);checks.push({name,status:'FAIL',detail});console.error('FAIL',name,detail);
  await page?.screenshot({path:'test-results/v3-failure-'+checks.length+'.png',fullPage:false}).catch(()=>{});
 }
}
async function waitIdle(){
 await page.waitForFunction(()=>!plScheduleRefreshing,null,{timeout:20000});
}
async function main(){
 browser=await chromium.launch({headless:true});
 const ctx=await browser.newContext({viewport:{width:390,height:844}});
 page=await ctx.newPage();page.setDefaultTimeout(20000);
 page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.route('**/apis/site/v2/sports/football/nfl/scoreboard?**',async route=>{
   requests++;
   await route.fulfill({status:providerStatus,contentType:'application/json',
    headers:{'access-control-allow-origin':'*',...(retryAfter?{'retry-after':retryAfter}:{})},
    body:JSON.stringify({events:providerEvents})});
  });
  await check('Open deployed site with v3 refresh controls',async()=>{
   const response=await page.goto(BASE,{waitUntil:'domcontentloaded',timeout:45000});
   assert.equal(response?.status(),200);
   await page.locator('#liveToggleAutomatic').waitFor();
   await page.locator('#liveRefreshNflSchedule').waitFor();
   assert.match(await page.locator('#liveFeedMonitor').innerText(),/browser only|page is open/i);
  });
  await check('Initial state is opt-in, no schedule polling without user activation',async()=>{
   await page.evaluate(()=>{
    localStorage.removeItem(PL_AUTO_KEY);localStorage.removeItem(PL_CACHE_KEY);localStorage.removeItem(PL_POLICY_KEY);
    plAutoRefresh=false;plRefreshState={successAt:0,blockedUntil:0,failures:0};plRefreshHistory=[];
    plLiveStore.delete('NFL|schedule|ESPN|scoreboard-window');plScheduleTick();renderLiveFeedMonitor();
   });
   assert.equal(requests,0);
   assert.match(await page.locator('#liveToggleAutomatic').innerText(),/Enable automatic/);
  });
  await check('Manual request stores cache and records refresh history',async()=>{
   providerEvents=[{id:'nfl-v3-fixture',date:new Date(Date.now()+86400000).toISOString()}];
   await page.locator('#liveRefreshNflSchedule').click();
   await page.waitForFunction(()=>!plScheduleRefreshing&&plRefreshHistory.length>0,null,{timeout:20000});
   const value=await page.evaluate(()=>({
    status:plRefreshHistory.at(-1).status,cache:JSON.parse(localStorage.getItem(PL_CACHE_KEY)||'null'),
    state:plFeedSummary(plLiveStore,'NFL').find(x=>x.type==='schedule').state
   }));
   assert.equal(value.status,'SUCCESS');
   assert.equal(value.cache.record.payload.count,1);
   assert.equal(value.state,'CURRENT');
   assert.equal(requests,1);
  });
  await check('Automatic checks reuse fresh schedule and do not repeat provider requests',async()=>{
   await page.locator('#liveToggleAutomatic').click();
   await waitIdle();
   assert.equal(requests,1);
   const status=await page.evaluate(()=>({
    enabled:plAutoRefresh,policy:plSchedulePolicy(plRefreshState),history:plRefreshHistory.length
   }));
   assert.equal(status.enabled,true);
   assert.equal(status.policy.action,'REUSE');
  });
  await check('A simulated stale snapshot triggers a single scheduled refresh',async()=>{
   providerEvents=[{id:'nfl-v3-updated',date:new Date(Date.now()+86400000).toISOString()}];
   await page.evaluate(()=>{
    const record=plLiveStore.get('NFL|schedule|ESPN|scoreboard-window');
    record.retrievedAt=new Date(Date.now()-13*3600000).toISOString();
    plRefreshState.successAt=Date.now()-13*3600000;
    plScheduleTick();
   });
   await page.waitForFunction(()=>!plScheduleRefreshing&&plRefreshHistory.at(-1)?.status==='SUCCESS'&&plLiveStore.get('NFL|schedule|ESPN|scoreboard-window')?.payload.events?.[0]?.id==='nfl-v3-updated',null,{timeout:25000});
   assert.equal(requests,2);
  });
  await check('HTTP 429 respects Retry-After and blocks immediate repeat requests',async()=>{
   providerStatus=429;retryAfter='900';
   await page.locator('#liveRefreshNflSchedule').click();
   await page.waitForFunction(()=>!plScheduleRefreshing&&plRefreshHistory.at(-1)?.status==='FAILED',null,{timeout:20000});
   const blocked=await page.evaluate(()=>({
    failures:plRefreshState.failures,cooldown:plRefreshState.blockedUntil-Date.now(),
    last:plRefreshHistory.at(-1).detail
   }));
   assert.equal(blocked.failures,1);
   assert.ok(blocked.cooldown>=800000);
   assert.match(blocked.last,/HTTP 429/);
   assert.equal(requests,3);
   await page.locator('#liveRefreshNflSchedule').click();
   assert.equal(requests,3);
   assert.match(await page.locator('#liveScheduleRefreshStatus').innerText(),/PROVIDER_COOLDOWN/);
  });
  await check('Reload preserves cache and cooldown without new provider fetch',async()=>{
   await page.reload({waitUntil:'domcontentloaded',timeout:45000});
   await page.locator('#liveToggleAutomatic').waitFor();
   await waitIdle();
   assert.equal(requests,3);
   const state=await page.evaluate(()=>({
    enabled:plAutoRefresh,blocked:plRefreshState.blockedUntil>Date.now(),
    cache:plLiveStore.get('NFL|schedule|ESPN|scoreboard-window')?.payload?.events?.[0]?.id,
    history:plRefreshHistory.length
   }));
   assert.equal(state.enabled,true);
   assert.equal(state.blocked,true);
   assert.equal(state.cache,'nfl-v3-updated');
   assert.ok(state.history>=3);
  });
  await check('Disabled automatic checks do not schedule page refresh timers',async()=>{
   await page.locator('#liveToggleAutomatic').click();
   const state=await page.evaluate(()=>({
    enabled:plAutoRefresh,timer:plRefreshTimer,stored:localStorage.getItem(PL_AUTO_KEY)
   }));
   assert.equal(state.enabled,false);
   assert.equal(state.timer,null);
   assert.equal(state.stored,'no');
   assert.equal(requests,3);
  });
  await check('No errors or unsupported verification claims',async()=>{
   assert.deepEqual(errors,[]);
   const rows=await page.evaluate(()=>plFeedSummary(plLiveStore,'NFL'));
   assert.equal(rows.find(x=>x.type==='schedule').verification,'unverified');
   assert.ok(rows.filter(x=>x.state==='NOT_CONNECTED').length>=4);
  });
  await page.unrouteAll({behavior:'wait'});
  try{
   const url=await page.evaluate(()=>scenarioScheduleUrl());
   const r=await page.request.get(url,{timeout:10000});
   providerDiagnostics.push({source:'ESPN schedule',status:r.ok()?'HTTP_OK':'HTTP_'+r.status()});
  }catch(e){providerDiagnostics.push({source:'ESPN schedule',status:'NETWORK_UNAVAILABLE',detail:String(e)})}
 }finally{
  await page.screenshot({path:'test-results/live-v3-mobile.png',fullPage:false}).catch(()=>{});
  fs.writeFileSync('test-results/live-v3-assertions.json',JSON.stringify({
   base:BASE,checks,errors,requests,providerDiagnostics,mockedProvider:true,
   limitations:['only open-browser opt-in polling','no server-side refresh','fixture results not live data validation','no persistent multi-user backend','provider quotas unconfirmed']
  },null,2));
  await browser.close();
 }
 const failed=checks.filter(x=>x.status==='FAIL');
 if(failed.length)throw Error(failed.length+' v3 browser checks failed: see saved screenshots and assertion report');
 console.log('LIVE_V3_PAGE_OPEN_AUTO_REFRESH_FIXTURES_PASS');
}
main().catch(e=>{console.error(e);process.exitCode=1});
