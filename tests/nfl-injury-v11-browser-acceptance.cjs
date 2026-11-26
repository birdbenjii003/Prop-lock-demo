'use strict';
// Acceptance against the actual app HTML served locally at this branch revision.
// Source fixtures are deterministic, not claims of ESPN injury accuracy.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const URL=process.env.INJURY_SITE_URL||'http://127.0.0.1:8765/';
fs.mkdirSync('test-results',{recursive:true});
const results=[],pageErrors=[];
const stamp=(ms)=>new Date(ms).toISOString();
let browser,page,context;
async function check(name,fn){
  try{await fn(); results.push({name,status:'PASS'});console.log('PASS:',name);}
  catch(e){
    results.push({name,status:'FAIL',error:String(e.stack||e)});
    console.error('FAIL:',name,e);
    await page.screenshot({path:'test-results/injury-v11-failure-'+results.length+'.png'}).catch(()=>{});
  }
}
const now=Date.now();
const fixture={
  schemaVersion:1,sport:'NFL',type:'injury_refresh_health',source:'ESPN',
  verification:'unverified',state:'SUCCESS_CHANGED',lastAttemptAt:stamp(now-60000),
  lastSuccessfulCheckAt:stamp(now-60000),lastContentChangedAt:stamp(now-60000),
  countAtLastAttempt:1,teamGroupsAtLastAttempt:1
};
const injury={
  schemaVersion:1,sport:'NFL',type:'injuries',scope:'league_injury_pilot',
  source:'ESPN',verification:'unverified',fetchedAt:stamp(now-60000),
  count:1,teamsReported:['ATL'],injuries:[{
    espnId:null,sourceInjuryId:'sha256:'+'a'.repeat(64),
    team:'ATL',displayName:'Fixture Athlete',designation:'Questionable',
    rosterEvidence:'TEAM_UNVERIFIED'
  }]
};
let responseHealth=fixture,responseInjury=injury,healthHttp=200,injuryHttp=200;
function bodyFor(payload,status){
  return {status,contentType:'application/json',
    body:status===200?JSON.stringify(payload):JSON.stringify({error:'unavailable'})};
}
async function update(){
  await page.evaluate(async()=>{
    await loadPublishedNflInjuryPilot();
    await loadPublishedNflInjuryHealth();
  });
  return page.evaluate(()=>({
    injury:document.getElementById('injuryPilotStatus')?.textContent||'',
    health:document.getElementById('injuryRefreshHealth')?.textContent||'',
    tabs:document.body.textContent.includes('Deep Dive')&&
      document.body.textContent.includes('Scenarios')&&
      document.body.textContent.includes('Trait Match')
  }));
}
async function main(){
  browser=await chromium.launch({headless:true});
  context=await browser.newContext({viewport:{width:390,height:844}});
  page=await context.newPage(); page.setDefaultTimeout(20000);
  page.on('pageerror',e=>pageErrors.push(e.message));
  await page.route('**/data/live/nfl_injury_health.json',r=>r.fulfill(bodyFor(responseHealth,healthHttp)));
  await page.route('**/data/live/nfl_injuries.json',r=>r.fulfill(bodyFor(responseInjury,injuryHttp)));
  try{
    await check('Actual app displays linked status and fresh source-check separately',async()=>{
      const response=await page.goto(URL,{waitUntil:'domcontentloaded',timeout:45000});
      assert.equal(response?.status(),200);
      await page.locator('#liveFeedMonitor').waitFor({state:'attached'});
      const state=await update();
      assert.match(state.health,/SUCCESS_CHANGED/);
      assert.match(state.health,/last successful check within 12h/);
      assert.match(state.health,/unverified third-party source/i);
      assert.match(state.injury,/1 without verified player ID/);
      assert.match(state.injury,/source unverified/i);
      assert.equal(state.tabs,true);
    });
    await check('Unchanged result retains old source report timestamp, new check timestamp',async()=>{
      responseHealth={...fixture,state:'SUCCESS_UNCHANGED',lastContentChangedAt:stamp(now-48*3600000)};
      const state=await update();
      assert.match(state.health,/SUCCESS_UNCHANGED/);
      assert.ok(state.health.includes(responseHealth.lastContentChangedAt));
      assert.match(state.health,/last successful check within 12h/);
    });
    await check('Provider failure clearly shown although previous report remains',async()=>{
      responseHealth={...fixture,state:'FAILED',failureCode:'INVALID_PROVIDER_SCHEMA_OR_PAYLOAD',
        lastAttemptAt:stamp(now-60000),lastSuccessfulCheckAt:stamp(now-20*3600000),
        lastContentChangedAt:stamp(now-24*3600000)};
      const state=await update();
      assert.match(state.health,/LATEST CHECK FAILED/);
      assert.match(state.health,/CHECK STALE/);
      assert.match(state.injury,/Fixture Athlete|1 reported entries/);
    });
    await check('Future timestamps are rejected rather than falsely called fresh',async()=>{
      responseHealth={...fixture,lastAttemptAt:stamp(now+3600000),
        lastSuccessfulCheckAt:stamp(now+3600000)};
      const state=await update();
      assert.match(state.health,/audit unavailable/i);
      assert.doesNotMatch(state.health,/within 12h/i);
    });
    await check('HTTP 503 audit failure cannot claim a successful check',async()=>{
      healthHttp=503;const state=await update();healthHttp=200;
      assert.match(state.health,/audit unavailable/i);
    });
    await check('Missing injury payload cannot be treated as proof player is healthy',async()=>{
      injuryHttp=503;const state=await update();injuryHttp=200;
      assert.match(state.injury,/unavailable/i);
      assert.match(state.injury,/No health or availability assumptions/i);
    });
    await check('Browser has no JavaScript exceptions',async()=>{
      assert.deepEqual(pageErrors,[]);
    });
  }finally{
    await page.screenshot({path:'test-results/injury-v11-mobile.png'}).catch(()=>{});
    fs.writeFileSync('test-results/injury-v11-browser-results.json',JSON.stringify({
      tests:results,pageErrors,fixtureBased:true,
      caveat:'Fixture tests validate UI rendering and failure isolation, not accuracy of real ESPN player identity or GitHub scheduled execution.'
    },null,2));
    await browser.close();
  }
  const failures=results.filter(x=>x.status==='FAIL');
  if(failures.length)throw Error(failures.length+' injury live-site browser checks failed');
  console.log('NFL_INJURY_V11_BROWSER_ACCEPTANCE_PASS — mocked source fixtures only');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
