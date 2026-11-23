'use strict';
// Exercises real published Scenarios UI using deterministic roster responses.
// A fixture pass does not certify live roster/team identity or provider uptime.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const BASE=process.env.SCENARIOS_URL||'https://birdbenjii003.github.io/Prop-lock-demo/';
fs.mkdirSync('test-results',{recursive:true});
const checks=[],pageErrors=[],providerDiagnostics=[];
let browser,page,candidate;
async function check(name,fn){
 try{await fn();checks.push({name,status:'PASS'});console.log('PASS',name)}
 catch(e){
  const detail=String(e.stack||e);checks.push({name,status:'FAIL',detail});
  console.error('FAIL',name,detail);
  await page?.screenshot({path:'test-results/roster-failure-'+checks.length+'.png',fullPage:false}).catch(()=>{});
 }
}
function rosterEntries(entries){return {athletes:[{position:'Offense',items:entries}]}}
function playerEntry(name,position,id='espn-fixture-1'){
 return {id,fullName:name,position:{abbreviation:position||candidate.position||'RB'}};
}
async function mockRoster(entries,{status=200,delayMs=0}={}){
 await page.unroute('**/apis/site/v2/sports/football/nfl/teams/*/roster');
 let calls=0;
 await page.route('**/apis/site/v2/sports/football/nfl/teams/*/roster',async route=>{
  calls++;
  if(delayMs)await new Promise(resolve=>setTimeout(resolve,delayMs));
  await route.fulfill({status,contentType:'application/json',
    headers:{'access-control-allow-origin':'*'},
    body:status===200?JSON.stringify(rosterEntries(entries)):'unavailable'});
 });
 return ()=>calls;
}
async function clickRoster(){
 await page.locator('#scenarioCheckRoster').click({timeout:20000});
 await page.waitForFunction(()=>!document.querySelector('#scenarioRosterStatus')?.textContent?.includes('Loading current team roster'),
   null,{timeout:20000});
 return page.locator('#scenarioRosterStatus').innerText();
}
async function main(){
 browser=await chromium.launch({headless:true});
 const context=await browser.newContext({viewport:{width:390,height:844},deviceScaleFactor:1});
 page=await context.newPage();page.setDefaultTimeout(30000);
 page.on('pageerror',e=>pageErrors.push(e.message));
 try{
  await check('Load deployed website and hosted NFL profiles',async()=>{
   const response=await page.goto(BASE,{waitUntil:'domcontentloaded',timeout:45000});
   assert.equal(response?.status(),200);
   await page.waitForFunction(()=>nflSource==='hosted'&&useImported&&importedProps.length>0,null,{timeout:90000});
   await page.locator('#cards [data-profile]').first().waitFor();
  });
  await check('Select historical player and show provisional roster gate',async()=>{
   candidate=await page.evaluate(()=>{
    const match={'Rushing Yards':'Carries','Receiving Yards':'Targets','Receptions':'Targets','Passing Yards':'Passing Attempts'};
    for(const p of importedProps){
      if(!match[p.stat]||!p.playerKey||!p.team||!/^[A-Z]{2,3}$/.test(p.team))continue;
      const peer=importedProps.find(x=>x.playerKey===p.playerKey&&x.stat===match[p.stat]);
      if(!peer?.records?.length)continue;
      const weeks=new Set(peer.records.filter(r=>Number(r.value)>0).map(r=>r.season+':'+r.week));
      if(p.records?.filter(r=>weeks.has(r.season+':'+r.week)).length>=10)
       return {name:p.name,team:p.team,position:p.position,playerKey:p.playerKey,stat:p.stat};
    }
    return null;
   });
   assert.ok(candidate,'No eligible hosted NFL player with team and matched opportunities');
   await page.locator('#cards [data-profile]').filter({hasText:candidate.name}).first().click();
   await page.locator('#research [data-stat-id]').filter({hasText:candidate.stat}).first().click();
   await page.locator('#scenarioCheckRoster').waitFor();
   assert.match(await page.locator('#scenarioRosterStatus').innerText(),/ROSTER_UNVERIFIED/);
   assert.match(await page.locator('#research').innerText(),/NOT treat a matching name as a verified athlete identity/);
   console.log('HISTORICAL_PLAYER',JSON.stringify(candidate));
  });
  const baseline=()=>page.locator('#research .validation-overflow table').allInnerTexts();
  await check('Unique roster name remains PROVISIONAL_ONLY and does not alter production',async()=>{
   const table=await baseline();
   const calls=await mockRoster([playerEntry(candidate.name,candidate.position)]);
   const result=await clickRoster();
   assert.match(result,/PROVISIONAL_ONLY/);
   assert.doesNotMatch(result,/VERIFIED_PLAYER_MATCH/);
   assert.equal(calls(),1);
   assert.deepEqual(await baseline(),table);
  });
  await check('Missing player on team roster is not confirmed',async()=>{
   await mockRoster([playerEntry('Some Other Player',candidate.position)]);
   assert.match(await clickRoster(),/PLAYER_TEAM_NOT_CONFIRMED/);
   assert.match(await page.locator('#scenarioRosterStatus').innerText(),/No exact normalized name match/);
  });
  await check('Multiple same-name athletes are rejected as ambiguous',async()=>{
   await mockRoster([playerEntry(candidate.name,candidate.position,'a'),playerEntry(candidate.name,candidate.position,'b')]);
   assert.match(await clickRoster(),/PLAYER_TEAM_NOT_CONFIRMED/);
   assert.match(await page.locator('#scenarioRosterStatus').innerText(),/Multiple players share/);
  });
  await check('Conflicting roster role is not a verified identity',async()=>{
   // Only meaningful where the imported role was inferred and is not UNKNOWN.
   if(!candidate.position||candidate.position==='Unknown'){console.log('SKIP position unknown');return}
   const different=candidate.position==='QB'?'RB':'QB';
   await mockRoster([playerEntry(candidate.name,different)]);
   assert.match(await clickRoster(),/PLAYER_TEAM_NOT_CONFIRMED/);
   assert.match(await page.locator('#scenarioRosterStatus').innerText(),/Roster position differs/);
  });
  await check('Provider failure gives unavailable status without retaining a previous match',async()=>{
   await mockRoster([],{status:503});
   const text=await clickRoster();
   assert.match(text,/PLAYER_TEAM_NOT_CONFIRMED/);
   assert.match(text,/Roster provider HTTP 503/);
  });
  await check('Stale cached roster evidence cannot become verified',async()=>{
   await mockRoster([playerEntry(candidate.name,candidate.position)]);
   assert.match(await clickRoster(),/PROVISIONAL_ONLY/);
   const status=await page.evaluate(()=>{
    scenarioRosterEvidence.result.checkedAt=new Date(Date.now()-7*3600000).toISOString();
    renderResearch();
    return document.querySelector('#scenarioRosterStatus')?.textContent;
   });
   assert.match(status,/ROSTER_UNVERIFIED/);
  });
  await check('Roster evidence is scoped to selected player rather than another profile',async()=>{
   // Inject an unrelated identity result and verify that rendering does not reuse it.
   const status=await page.evaluate(()=>{
    const saved=scenarioRosterEvidence;
    scenarioRosterEvidence={...saved,playerKey:'different-player-id'};
    renderResearch();
    const display=document.querySelector('#scenarioRosterStatus')?.textContent;
    scenarioRosterEvidence=saved;renderResearch();
    return display;
   });
   assert.match(status,/ROSTER_UNVERIFIED/);
  });
  await check('Research methods and uncalibrated projections stay separate',async()=>{
   const text=await page.locator('#research').innerText();
   assert.match(text,/01 · Deep Dive/);
   assert.match(text,/02 · Scenarios/);
   assert.match(text,/03 · Trait Match/);
   assert.match(text,/UNAVAILABLE — NOT CALIBRATED/);
   assert.deepEqual(pageErrors,[]);
  });
  await page.unrouteAll({behavior:'wait'});
  // Independent diagnostic: real ESPN availability does not determine fixture acceptance.
  try{
   const path=await page.evaluate(team=>scenarioRosterUrl(team),candidate?.team||'');
   if(path){
    const r=await page.request.get(path,{timeout:12000});
    providerDiagnostics.push({name:'ESPN roster endpoint',status:r.ok()?'HTTP_OK':'HTTP_'+r.status()});
   }
  }catch(e){providerDiagnostics.push({name:'ESPN roster endpoint',status:'NETWORK_UNAVAILABLE',detail:String(e)})}
 }finally{
  await page.screenshot({path:'test-results/scenarios-phase4-final.png',fullPage:false}).catch(()=>{});
  fs.writeFileSync('test-results/scenarios-phase4-assertions.json',JSON.stringify({
   site:BASE,candidate,checks,pageErrors,providerDiagnostics,fixturesSimulated:true,
   notEstablished:['current player-team identity','GSIS-to-ESPN ID join','actual player upcoming opponent','roster provider reliability','calibrated betting probabilities']
  },null,2));
  await browser.close();
 }
 const failures=checks.filter(c=>c.status==='FAIL');
 if(failures.length)throw Error(failures.length+' Phase 4 browser checks failed; see artifacts');
 console.log('PHASE4_ROSTER_BROWSER_FIXTURE_ACCEPTANCE_PASS: no live identity guarantee');
}
main().catch(e=>{console.error(e);process.exitCode=1});
