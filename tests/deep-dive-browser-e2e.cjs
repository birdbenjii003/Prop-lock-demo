'use strict';
// Runs a real Chromium session against deployed GitHub Pages.
// Do not confuse passing static asset checks with actual user interactions.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const BASE=process.env.DEEP_DIVE_URL||'https://birdbenjii003.github.io/Prop-lock-demo/';
const TABS=['overview','performance','trends','volume','quality','role','efficiency','expected','sustainability','stability','weighting','tendencies','projection','validation','evidence','h2h'];
fs.mkdirSync('test-results',{recursive:true});
let failures=[],browser;
let activePage=null;
async function step(label,callback){
 try{await callback();console.log('PASS',label)}
 catch(error){
  const message=label+': '+String(error.stack||error);
  failures.push(message);
  console.error('FAIL',message);
  if(activePage){
   const safe=label.toLowerCase().replace(/[^a-z0-9]+/g,'-').slice(0,45);
   await activePage.screenshot({path:'test-results/failure-'+safe+'.png',fullPage:false}).catch(()=>{});
   const state=await activePage.evaluate(()=>({
    cards:document.querySelectorAll('#cards [data-profile]').length,
    selectedProfile:document.querySelector('#cards [data-profile].selected')?.getAttribute('data-profile')||null,
    statButtons:document.querySelectorAll('#research [data-stat-id]').length,
    deepDiveTabs:document.querySelectorAll('[data-deep-dive-tab]').length,
    activeTab:document.querySelector('[data-deep-dive-tab][aria-pressed="true"]')?.getAttribute('data-deep-dive-tab')||null,
    status:document.getElementById('importStatus')?.textContent?.slice(0,350)
   })).catch(e=>({diagnosticError:String(e)}));
   console.error('BROWSER_STATE',JSON.stringify(state));
  }
 }
}
async function tabs(page){
 for(const id of TABS){
  await page.locator('[data-deep-dive-tab="'+id+'"]').click();
  await page.locator('.dd3-tabs [data-deep-dive-tab="'+id+'"][aria-pressed="true"]').waitFor({timeout:10000});
  const content=await page.locator('.dd3-content').innerText();
  assert.ok(content.trim().length>35,'Empty tab: '+id);
  assert.ok(!content.includes('undefined'),'Undefined content in '+id);
 }
 assert.equal(await page.locator('[data-deep-dive-tab]').count(),16);
}
async function main(){
 try { browser=await chromium.launch({headless:true}); }
 catch(error){
  fs.writeFileSync('test-results/browser-assertions.json',JSON.stringify({url:BASE,phase:'browser_launch',failures:[String(error.stack||error)]},null,2));
  throw error;
 }
 const context=await browser.newContext({viewport:{width:390,height:844},deviceScaleFactor:1});
 const page=await context.newPage();
 activePage=page;
 page.setDefaultTimeout(30000);
 const problems=[];
 page.on('pageerror',e=>problems.push(e.message));
 try{
  await step('Load deployed Pages in mobile viewport',async()=>{
   const response=await page.goto(BASE,{waitUntil:'domcontentloaded',timeout:45000});
   assert.equal(response?.status(),200);
   await page.locator('#cards').waitFor();
  });
  await step('Sample player opens all 16 tabs with honest evidence labels',async()=>{
   await page.locator('#demoMode').click();
   await page.locator('#cards [data-id]').first().click();
   await page.locator('.dd3-tabs').waitFor();
   assert.match(await page.locator('#research').innerText(),/FICTIONAL DEMO/);
   await tabs(page);
   assert.match(await page.locator('.dd3-footer').innerText(),/No certified player-specific future interval/i);
  });
  await step('Load hosted NFL player history',async()=>{
   await page.locator('#autoNFL').click();
   await page.waitForFunction(()=>document.querySelector('#autoNFL')?.disabled===false,null,{timeout:90000});
   const status=await page.locator('#importStatus').innerText();
   assert.match(status,/NFL 2023–2026 weekly stats/);
   assert.match(status,/public site|device cache/);
   await page.locator('#cards [data-profile]').first().waitFor({timeout:20000});
  });
  await step('Select actual player and stat, change research line',async()=>{
   await page.locator('#cards [data-profile]').first().click({timeout:30000});
   await page.locator('#research [data-stat-id]').first().waitFor({timeout:30000});
   await page.locator('#research [data-stat-id]').first().click();
   assert.match(await page.locator('#research .sourcechip').innerText(),/NFLVERSE PUBLIC SNAPSHOT/);
   const line=page.locator('#lineNumber');
   await line.fill('50.5');
   await line.dispatchEvent('change');
   assert.equal(await page.locator('#lineNumber').inputValue(),'50.5');
   // The active H2H tab need not repeat the line; verify the actual chart updated.
   assert.match(await page.locator('#research .graphbox svg').getAttribute('aria-label'),/50\\.5/);
  });
  await step('All 16 tabs render with hosted NFL player evidence',async()=>{
   assert.equal(await page.locator('#research [data-stat-id]').count()>0,true,'Hosted player selection did not complete; preceding step must pass before tab checks');
   await tabs(page);
   await page.locator('[data-deep-dive-tab="projection"]').click();
   const text=await page.locator('.dd3-content').innerText();
   assert.match(text,/No calibrated next-game prediction|NOT a certified player-specific|reference|interval evidence unavailable/i);
   await page.locator('[data-deep-dive-tab="quality"]').click();
   assert.match(await page.locator('.dd3-content').innerText(),/opportunit|unavailable/i);
   await page.locator('[data-deep-dive-tab="role"]').click();
   assert.match(await page.locator('.dd3-content').innerText(),/snap|participation|unavailable/i);
  });
  await step('No runtime JavaScript errors',async()=>{assert.deepEqual(problems,[])});
 } finally{
  await page.screenshot({path:'test-results/deep-dive-mobile.png',fullPage:false}).catch(()=>{});
  fs.writeFileSync('test-results/browser-assertions.json',JSON.stringify({url:BASE,checks:6,failures,consoleErrors:problems},null,2));
  await browser.close();
 }
 if(failures.length)throw Error(failures.length+' browser checks failed: '+failures.join(' | '));
 console.log('STAGE4_BROWSER_INTERACTIONS_PASS — 16 tabs, real player, threshold, evidence warnings.');
 console.log('NOT PROVEN: certified future probabilities, independent calibration, all possible player profiles.');
}
main().catch(e=>{console.error(e);process.exitCode=1});
