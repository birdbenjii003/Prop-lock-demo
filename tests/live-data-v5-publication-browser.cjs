'use strict';
// Deployed-site validation of published schedule with real snapshot and simulated failure paths.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const url=process.env.PROP_LOCK_URL||'https://birdbenjii003.github.io/Prop-lock-demo/';
fs.mkdirSync('test-results',{recursive:true});
const checks=[],errors=[];
let browser,page;
async function check(name,fn){
 try{await fn();checks.push({name,status:'PASS'});console.log('PASS',name)}
 catch(e){const detail=String(e.stack||e);checks.push({name,status:'FAIL',detail});
  console.error('FAIL',name,detail);
  await page?.screenshot({path:'test-results/v5-error-'+checks.length+'.png'}).catch(()=>{});
 }
}
async function main(){
 browser=await chromium.launch({headless:true});
 page=await browser.newPage({viewport:{width:390,height:844}});
 page.on('pageerror',e=>errors.push(e.message));
 try{
  await check('Deployed site loads publication monitor',async()=>{
   const response=await page.goto(url,{waitUntil:'domcontentloaded',timeout:45000});
   assert.equal(response?.status(),200);
   await page.locator('#publishedScheduleStatus').waitFor();
   await page.waitForFunction(()=>!document.querySelector('#publishedScheduleStatus')?.textContent.includes('not checked'),null,{timeout:30000});
  });
  await check('Real published schedule has fetchedAt and unverified status',async()=>{
   const state=await page.evaluate(()=>({
    text:document.querySelector('#publishedScheduleStatus')?.textContent,
    published:[...plLiveStore.values()].find(x=>x.id==='server-snapshot')
   }));
   assert.ok(state.published,'Expected published snapshot available on hosted site');
   assert.equal(state.published.verification,'unverified');
   assert.equal(state.published.source,'ESPN-PUBLISHED');
   assert.ok(state.published.payload.count>=0);
   assert.match(state.text,/collected \d{4}-\d{2}-\d{2}T/);
   assert.match(state.text,/accuracy not independently verified/);
  });
  await check('Missing schedule fails visibly without removing historical data',async()=>{
   await page.route('**/data/live/nfl_schedule.json',route=>route.fulfill({status:404,body:'missing'}));
   await page.evaluate(()=>loadPublishedNflSchedule());
   const displayed=await page.locator('#publishedScheduleStatus').innerText();
   assert.match(displayed,/Server snapshot unavailable: HTTP 404/);
   assert.ok(await page.evaluate(()=>typeof importedProps!=='undefined'));
   await page.unroute('**/data/live/nfl_schedule.json');
  });
  await check('Malformed schedule reports invalid schema instead of inventing data',async()=>{
   await page.route('**/data/live/nfl_schedule.json',route=>route.fulfill({
    status:200,contentType:'application/json',body:'{"schemaVersion":1,"events":[{"bad":true}]}' }));
   await page.evaluate(()=>loadPublishedNflSchedule());
   assert.match(await page.locator('#publishedScheduleStatus').innerText(),/Unexpected published snapshot schema/);
   await page.unroute('**/data/live/nfl_schedule.json');
  });
  await check('Roster pilot fails visibly when unpublished, without impacting schedule',async()=>{
   await page.route('**/data/live/nfl_roster_pilot_ATL.json',route=>route.fulfill({status:404,body:'missing'}));
   await page.evaluate(()=>loadPublishedNflRosterPilot());
   assert.match(await page.locator('#publishedRosterStatus').innerText(),/ATL roster pilot unavailable: HTTP 404/);
   assert.ok(await page.evaluate(()=>[...plLiveStore.values()].some(r=>r.id==='server-snapshot')));
   await page.unroute('**/data/live/nfl_roster_pilot_ATL.json');
  });
  await check('Independent roster pilot fixture is labeled unverified',async()=>{
   const data={schemaVersion:1,sport:'NFL',type:'roster',source:'ESPN',verification:'unverified',
    team:'ATL',scope:'single_team_pilot',fetchedAt:new Date().toISOString(),count:1,
    athletes:[{espnId:'123456',displayName:'Example Person',position:'RB'}]};
   await page.route('**/data/live/nfl_roster_pilot_ATL.json',route=>route.fulfill({
    status:200,contentType:'application/json',body:JSON.stringify(data)}));
   await page.evaluate(()=>loadPublishedNflRosterPilot());
   const text=await page.locator('#publishedRosterStatus').innerText();
   assert.match(text,/ATL only: 1 roster names/);
   assert.match(text,/player-team assignment unverified/);
   await page.unroute('**/data/live/nfl_roster_pilot_ATL.json');
  });
  await check('Research methods remain unchanged and browser has no JS exceptions',async()=>{
   assert.deepEqual(errors,[]);
   assert.equal(await page.evaluate(()=>typeof scenarioPanel),'function');
   assert.equal(await page.evaluate(()=>typeof renderLiveFeedMonitor),'function');
  });
 }finally{
  await page.screenshot({path:'test-results/live-v5-mobile.png',fullPage:false}).catch(()=>{});
  fs.writeFileSync('test-results/live-v5-assertions.json',JSON.stringify({
   site:url,checks,errors,realPublishedScheduleRequested:true,rosterFixtureSimulated:true,
   notEstablished:['real roster pilot operation','live player ID reconciliation','roster accuracy','provider uptime','injury feeds']
  },null,2));
  await browser.close();
 }
 const failed=checks.filter(c=>c.status==='FAIL');
 if(failed.length)throw Error(failed.length+' browser acceptance failures');
 console.log('LIVE_V5_PUBLICATION_ACCEPTANCE_PASS');
}
main().catch(e=>{console.error(e);process.exitCode=1});
