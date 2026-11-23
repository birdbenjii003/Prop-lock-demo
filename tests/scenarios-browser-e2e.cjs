'use strict';
// Scenarios Phase 2 — real published Pages interactions in headless Chromium.
// The actual weather-provider check is separate from the deterministic display test.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const BASE=process.env.SCENARIOS_URL||'https://birdbenjii003.github.io/Prop-lock-demo/';
fs.mkdirSync('test-results',{recursive:true});
const checks=[],failures=[],errors=[];
const externalDiagnostics=[];
let page,browser;

async function check(name,fn){
  try {await fn();checks.push({name,status:'PASS'});console.log('PASS',name);}
  catch(e){
    const detail=String(e.stack||e);
    checks.push({name,status:'FAIL',detail});failures.push(detail);
    console.error('FAIL',name,detail);
    if(page)await page.screenshot({path:'test-results/scenarios-'+checks.length+'.png',fullPage:false}).catch(()=>{});
  }
}
async function pickOpportunityPlayer(){
  // Use *hosted* player weeks, not fabricated test data. Find matching production and
  // opportunity records, then click the corresponding real player profile.
  const candidate=await page.evaluate(()=>{
    const match={'Rushing Yards':'Carries','Receiving Yards':'Targets','Receptions':'Targets','Passing Yards':'Passing Attempts'};
    for(const production of importedProps){
      const stat=match[production.stat];
      if(!stat||production.sport!=='NFL'||!production.playerKey||!Array.isArray(production.records))continue;
      const opp=importedProps.find(p=>p.playerKey===production.playerKey&&p.stat===stat);
      if(!opp?.records?.length)continue;
      const weeks=new Set(opp.records.filter(r=>Number(r.value)>0).map(r=>r.season+':'+r.week));
      const count=production.records.filter(r=>weeks.has(r.season+':'+r.week)).length;
      if(count>=10)return {key:production.playerKey,stat:production.stat,count};
    }
    return null;
  });
  assert.ok(candidate,'Hosted NFL data has no eligible matched player opportunity sample');
  const profile=page.locator('#cards [data-profile]').filter({hasText:await page.evaluate(key=>{const x=importedProps.find(p=>p.playerKey===key);return x?.name||''},candidate.key)}).first();
  await profile.click({timeout:30000});
  await page.locator('#research [data-stat-id]').filter({hasText:candidate.stat}).first().click({timeout:30000});
  await page.locator('#scenarioLoadWeather').waitFor();
  return candidate;
}
async function main(){
  browser=await chromium.launch({headless:true});
  const context=await browser.newContext({viewport:{width:390,height:844},deviceScaleFactor:1});
  page=await context.newPage();page.setDefaultTimeout(30000);
  page.on('pageerror',error=>errors.push(error.message));
  let initialLine='';
  try {
    await check('Open deployed mobile research site',async()=>{
      const r=await page.goto(BASE,{waitUntil:'domcontentloaded',timeout:45000});
      assert.equal(r?.status(),200);
      await page.locator('#cards').waitFor();
    });
    await check('Load hosted NFL player-week dataset',async()=>{
      // The application starts its own NFL download on page load, disabling #autoNFL.
      // Do not click a disabled control or start a redundant forced refresh.
      await page.waitForFunction(()=>nflSource==='hosted'&&useImported&&importedProps.length>0||
        (!autoInProgress&&!document.querySelector('#autoNFL')?.disabled),
        null,{timeout:90000});
      const alreadyLoaded=await page.evaluate(()=>nflSource==='hosted'&&useImported&&importedProps.length>0);
      if(!alreadyLoaded){
        await page.locator('#autoNFL').click();
        await page.waitForFunction(()=>!autoInProgress,null,{timeout:90000});
      }
      await page.locator('#cards [data-profile]').first().waitFor({timeout:20000});
      const hosted=await page.evaluate(()=>({source:nflSource,profiles:importedProps.length,years:[...new Set(importedProps.flatMap(p=>(p.records||[]).map(r=>Number(r.season))))]}));
      assert.equal(hosted.source,'hosted','Data must come from published NFL archive, not a device cache or demo');
      assert.ok(hosted.profiles>0,'Hosted NFL profiles are empty');
      assert.ok([2023,2024,2025,2026].every(y=>hosted.years.includes(y)),'Missing required historical seasons');
    });
    await check('Choose real player with matched opportunity history',async()=>{
      const candidate=await pickOpportunityPlayer();
      console.log('HOSTED_PLAYER',JSON.stringify(candidate));
      assert.match(await page.locator('#research .sourcechip').innerText(),/NFLVERSE PUBLIC SNAPSHOT/);
      const scenario=page.locator('#research').getByText('V2.0 · EXPERIMENTAL');
      await scenario.waitFor();
      const output=await page.locator('#research').innerText();
      assert.match(output,/Historical matched opportunity sample:/);
      assert.match(output,/Minimum opportunities at recorded efficiency/);
      assert.match(output,/UNAVAILABLE — NOT CALIBRATED/);
      assert.match(output,/Playing ahead/);
      assert.match(output,/Playing behind/);
      initialLine=await page.locator('#lineNumber').inputValue();
    });
    await check('Different research threshold updates scenario failure point',async()=>{
      const before=await page.locator('#research').innerText();
      const newLine=String(Math.round((Number(initialLine)+10)*2)/2);
      const threshold=page.locator('#lineNumber');
      await threshold.fill(newLine);
      await threshold.dispatchEvent('change');
      assert.equal(await page.locator('#lineNumber').inputValue(),Number(newLine).toFixed(1));
      const after=await page.locator('#research').innerText();
      assert.notEqual(before.match(/Minimum opportunities at recorded efficiency[^\n]*/)?.[0],
                      after.match(/Minimum opportunities at recorded efficiency[^\n]*/)?.[0]);
    });
    await check('Missing venue coordinates are refused',async()=>{
      await page.locator('#scenarioLoadWeather').click();
      assert.match(await page.locator('#scenarioWeatherStatus').innerText(),/latitude and longitude are required/i);
    });
    await check('Live weather data renders without modifying scenario estimates',async()=>{
      // Browser-level provider response fixture. Tests the app's CORS fetch/display pipeline,
      // not the actual reliability of a real weather provider.
      const sampleTime=new Date(Date.now()-10*60000).toISOString().slice(0,16);
      await page.route('https://api.open-meteo.com/v1/forecast?**',async route=>{
        await route.fulfill({status:200,contentType:'application/json',
          body:JSON.stringify({current:{temperature_2m:90,wind_speed_10m:3,time:sampleTime}})});
      });
      const baseline=await page.locator('#research .validation-overflow table').allInnerTexts();
      await page.locator('#scenarioLat').fill('33.75');
      await page.locator('#scenarioLon').fill('-84.39');
      await page.locator('#scenarioLoadWeather').click();
      await page.waitForFunction(()=>document.querySelector('#scenarioWeatherStatus')?.textContent?.includes('Current venue weather:'),null,{timeout:15000});
      const reading=await page.locator('#scenarioWeatherStatus').innerText();
      assert.match(reading,/90\.0°F/);
      assert.match(reading,/3\.0 mph/);
      assert.match(reading,/user-supplied, not independently verified/);
      assert.match(reading,/Heat flag/);
      assert.deepEqual(await page.locator('#research .validation-overflow table').allInnerTexts(),baseline,
        'Weather must not silently alter unvalidated estimates');
      await page.unrouteAll({behavior:'wait'});
    });
    // External provider availability is monitored separately from deterministic browser acceptance.
    // Distinguish DNS/CORS/rate-limit outages from failures in our own website logic.
    {
      let providerStatus='UNVERIFIED';
      const params=new URLSearchParams({latitude:'33.75',longitude:'-84.39',current:'temperature_2m,wind_speed_10m',
        temperature_unit:'fahrenheit',wind_speed_unit:'mph',timezone:'UTC'});
      const url='https://api.open-meteo.com/v1/forecast?'+params;
      try{
        const response=await page.request.get(url,{timeout:12000});
        if(!response.ok()){providerStatus='HTTP_'+response.status();} else {
        const data=await response.json();
        const valid=Number.isFinite(data.current?.temperature_2m)&&Number.isFinite(data.current?.wind_speed_10m)&&!!data.current?.time;
        providerStatus=valid?'REACHABLE':'MALFORMED_RESPONSE';
        if(valid)console.log('PROVIDER_REACHABLE',JSON.stringify({time:data.current.time}));
        else console.warn('PROVIDER_UNAVAILABLE malformed response');
        }
      }catch(error){providerStatus='NETWORK_ERROR';console.warn('PROVIDER_UNAVAILABLE',String(error));}
      externalDiagnostics.push({name:'Open-Meteo direct network probe',status:providerStatus});
      // This diagnostic does not count as an application acceptance pass.
    }
    await check('Scenarios, Deep Dive and Trait Match remain separately present',async()=>{
      const research=await page.locator('#research').innerText();
      assert.match(research,/02 · Scenarios/);
      assert.match(research,/01 · Deep Dive/);
      assert.match(research,/03 · Trait Match/);
    });
    await check('No page runtime errors',async()=>assert.deepEqual(errors,[]));
  } finally{
    await page.screenshot({path:'test-results/scenarios-final-mobile.png',fullPage:false}).catch(()=>{});
    fs.writeFileSync('test-results/scenarios-browser-assertions.json',
      JSON.stringify({url:BASE,checks,failures,errors,externalDiagnostics,networkWeatherIsIndependentFromFixture:true},null,2));
    await browser.close();
  }
  if(failures.length)throw Error(failures.length+' Scenarios acceptance checks failed; see artifact for details.');
  console.log('SCENARIOS_PHASE2_BROWSER_ACCEPTANCE_PASS');
  console.log('Not established: stadium identification, kickoff forecast, calibrated script probabilities or predictive accuracy.');
}
main().catch(e=>{console.error(e);process.exitCode=1});
