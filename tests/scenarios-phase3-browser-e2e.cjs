'use strict';
// Phase 3: Verify hosted Scenarios UI with controlled schedule and forecast fixtures.
// Real provider diagnostics are separate; mocked fixtures never certify live providers.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const BASE=process.env.SCENARIOS_URL||'https://birdbenjii003.github.io/Prop-lock-demo/';
fs.mkdirSync('test-results',{recursive:true});
const checks=[],errors=[],externalDiagnostics=[];
let browser,page;
async function test(name,fn){
 try{await fn();checks.push({name,status:'PASS'});console.log('PASS',name)}
 catch(e){
  const detail=String(e.stack||e);
  checks.push({name,status:'FAIL',detail});
  console.error('FAIL',name,detail);
  await page?.screenshot({path:'test-results/scenarios-phase3-failure-'+checks.length+'.png',fullPage:false}).catch(()=>{});
 }
}
const kickoff=new Date(Date.now()+48*3600000).toISOString();
let team='';
function scheduledEvent(venue,indoor){
 return {events:[{id:'phase3-fixture-1',date:kickoff,status:{type:{state:'pre'}},competitions:[{
  date:kickoff,status:{type:{state:'pre'}},venue:{fullName:venue,indoor},
  competitors:[{team:{abbreviation:team},homeAway:'home'},{team:{abbreviation:'ZZZ'},homeAway:'away'}]
 }]}]};
}
function mockHourly(){
 const epoch=Math.floor(Date.parse(kickoff)/3600000)*3600;
 return {hourly:{time:[epoch],temperature_2m:[90],wind_speed_10m:[3],precipitation_probability:[20]}};
}
async function setupRoutes(venue,indoor){
 await page.unrouteAll({behavior:'wait'});
 const traffic={schedule:0,weather:0};
 await page.route('**/apis/site/v2/sports/football/nfl/scoreboard?**',async route=>{
  traffic.schedule++;
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(scheduledEvent(venue,indoor)),
   headers:{'access-control-allow-origin':'*'}});
 });
 await page.route('**/api.open-meteo.com/v1/forecast?**',async route=>{
  traffic.weather++;
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(mockHourly()),
   headers:{'access-control-allow-origin':'*'}});
 });
 return traffic;
}
async function lookup(){
 await page.locator('#scenarioLookupGame').click();
 await page.waitForFunction(()=>!document.querySelector('#scenarioGameStatus')?.textContent?.includes('Loading next scheduled'),null,{timeout:15000});
 return page.locator('#scenarioGameStatus').innerText();
}
async function scenarioTable(){
 // Protect against silently changing estimates based on unvalidated weather context.
 return page.locator('#research .validation-overflow table').allInnerTexts();
}
async function main(){
 browser=await chromium.launch({headless:true});
 const context=await browser.newContext({viewport:{width:390,height:844},deviceScaleFactor:1});
 page=await context.newPage();page.setDefaultTimeout(30000);
 page.on('pageerror',e=>errors.push(e.message));
 try{
  await test('Load live deployed Scenarios and NFL history',async()=>{
   const response=await page.goto(BASE,{waitUntil:'domcontentloaded',timeout:45000});
   assert.equal(response?.status(),200);
   await page.waitForFunction(()=>nflSource==='hosted'&&useImported&&importedProps.length>0,null,{timeout:90000});
   await page.locator('#cards [data-profile]').first().waitFor();
  });
  await test('Choose a hosted player and preserve historical-team disclaimer',async()=>{
   const candidate=await page.evaluate(()=>{
    const match={'Rushing Yards':'Carries','Receiving Yards':'Targets','Receptions':'Targets','Passing Yards':'Passing Attempts'};
    for(const valid of importedProps){
      const opportunity=match[valid.stat];
      if(!opportunity||valid.sport!=='NFL'||!valid.playerKey||!valid.team)continue;
      const peer=importedProps.find(p=>p.playerKey===valid.playerKey&&p.stat===opportunity);
      if(!peer?.records?.length)continue;
      const keys=new Set(peer.records.filter(r=>Number.isFinite(r.value)&&r.value>0).map(r=>r.season+':'+r.week));
      if(valid.records?.filter(r=>keys.has(r.season+':'+r.week)).length>=10)
        return {key:valid.playerKey,name:valid.name,team:valid.team,stat:valid.stat};
    }
    return null;
   });
   assert.ok(candidate?.team,'Hosted data has no team identity');
   team=candidate.team.toUpperCase();
   await page.locator('#cards [data-profile]').filter({hasText:candidate.name}).first().click();
   await page.locator('#research [data-stat-id]').filter({hasText:candidate.stat}).first().click();
   await page.locator('#scenarioLookupGame').waitFor();
   assert.match(await page.locator('#research').innerText(),/historical and is NOT verified as a current roster assignment/);
   console.log('HISTORICAL_TEAM_LABEL',team);
  });
  await test('Matched outdoor stadium shows timestamped kickoff forecast, without changing estimates',async()=>{
   const traffic=await setupRoutes('Lambeau Field',false);
   const baseline=await scenarioTable();
   const status=await lookup();
   assert.match(status,/OUTDOOR_VENUE_MATCHED/);
   assert.match(status,/KICKOFF_FORECAST_UNVERIFIED/);
   const research=await page.locator('#research').innerText();
   assert.match(research,/Kickoff forecast \(not observed\):/);
   assert.match(research,/90(?:\.0)?°F/);
   assert.match(research,/3(?:\.0)? mph wind/);
   assert.match(research,/Open-Meteo hourly forecast/);
   assert.equal(traffic.schedule,1);
   assert.equal(traffic.weather,1);
   assert.deepEqual(await scenarioTable(),baseline,'Forecast must not modify unsupported player estimates');
  });
  await test('Indoor stadium blocks all kickoff-weather fetches',async()=>{
   const traffic=await setupRoutes('Ford Field',true);
   const status=await lookup();
   assert.match(status,/INDOOR_NO_WEATHER/);
   assert.equal(traffic.weather,0,'Indoor stadium must not request an outdoor kickoff forecast');
   assert.doesNotMatch(await page.locator('#research').innerText(),/Kickoff forecast \(not observed\):/);
  });
  await test('Retractable roof with unknown status blocks weather',async()=>{
   const traffic=await setupRoutes('Mercedes-Benz Stadium',false);
   const status=await lookup();
   assert.match(status,/ROOF_UNCONFIRMED/);
   assert.equal(traffic.weather,0);
  });
  await test('Unmapped stadium does not invent weather coordinates',async()=>{
   const traffic=await setupRoutes('Stadium Not In Registry',false);
   const status=await lookup();
   assert.match(status,/VENUE_UNMAPPED/);
   assert.equal(traffic.weather,0);
  });
  await test('No scheduled game blocks kickoff forecast',async()=>{
   await page.unrouteAll({behavior:'wait'});
   let weatherCalls=0;
   await page.route('**/apis/site/v2/sports/football/nfl/scoreboard?**',async route=>{
    await route.fulfill({status:200,contentType:'application/json',body:'{"events":[]}',headers:{'access-control-allow-origin':'*'}});
   });
   await page.route('**/api.open-meteo.com/v1/forecast?**',async route=>{
    weatherCalls++;await route.abort();
   });
   assert.match(await lookup(),/NO_UPCOMING_GAME/);
   assert.equal(weatherCalls,0);
  });
  await test('Provider failure reports unavailable and clears old forecast',async()=>{
   await page.unrouteAll({behavior:'wait'});
   await page.route('**/apis/site/v2/sports/football/nfl/scoreboard?**',async route=>route.fulfill({
    status:503,body:'unavailable',headers:{'access-control-allow-origin':'*'}}));
   assert.match(await lookup(),/Schedule or forecast unavailable: Schedule HTTP 503/);
   assert.doesNotMatch(await page.locator('#research').innerText(),/Kickoff forecast \(not observed\):/);
  });
  await test('No JavaScript errors or calibrated probability claims',async()=>{
   assert.deepEqual(errors,[]);
   assert.match(await page.locator('#research').innerText(),/UNAVAILABLE — NOT CALIBRATED/);
  });
  // Diagnostic only: avoid treating intermittent third-party access as an application failure.
  await page.unrouteAll({behavior:'wait'});
  for(const [name,url] of [
   ['ESPN schedule',await page.evaluate(()=>scenarioScheduleUrl())],
   ['Open-Meteo forecast','https://api.open-meteo.com/v1/forecast?latitude=44.5013&longitude=-88.0622&hourly=temperature_2m,wind_speed_10m&forecast_days=2']
  ]){
   try{
    const r=await page.request.get(url,{timeout:12000});
    externalDiagnostics.push({name,status:r.ok()?'HTTP_OK':'HTTP_'+r.status()});
   }catch(e){externalDiagnostics.push({name,status:'NETWORK_UNAVAILABLE',detail:String(e)})}
  }
 }finally{
  await page.screenshot({path:'test-results/scenarios-phase3-mobile.png',fullPage:false}).catch(()=>{});
  fs.writeFileSync('test-results/scenarios-phase3-assertions.json',JSON.stringify({
   url:BASE,checks,errors,externalDiagnostics,fixturesAreSimulated:true,
   notValidated:['actual roster team','real upcoming matchup','current retractable roof state','calibrated scenario likelihood','future forecast accuracy']
  },null,2));
  await browser.close();
 }
 const failed=checks.filter(c=>c.status==='FAIL');
 if(failed.length)throw Error(failed.length+' Phase 3 browser acceptance checks failed; see saved test artifact.');
 console.log('SCENARIOS_PHASE3_BROWSER_FIXTURE_ACCEPTANCE_PASS — not a certification of live game/weather provider data');
}
main().catch(e=>{console.error(e);process.exitCode=1});
