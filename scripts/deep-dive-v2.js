'use strict';
// V3.1 Deep Dive-only research: no upcoming opponent, game-script or market inputs.
// Estimates and observed historical bands are descriptive, NOT calibrated intervals.
function ddMean(a){return a.length?a.reduce((s,v)=>s+v,0)/a.length:null}
function ddMedian(a){if(!a.length)return null;const b=[...a].sort((x,y)=>x-y);return b.length%2?b[(b.length-1)/2]:(b[b.length/2-1]+b[b.length/2])/2}
function ddQuantile(a,q){if(!a.length)return null;const s=[...a].sort((x,y)=>x-y),p=(s.length-1)*q,i=Math.floor(p);return s[i]+(s[Math.min(i+1,s.length-1)]-s[i])*(p-i)}
function ddStatKey(r){return String(r.season)+':'+String(r.week)}
const DD_VOLUME={'Passing Yards':'Passing Attempts','Passing TDs':'Passing Attempts','Interceptions':'Passing Attempts','Rushing Yards':'Carries','Rushing TDs':'Carries','Receiving Yards':'Targets','Receptions':'Targets','Receiving TDs':'Targets'};
function deepDiveAlternatives(p,allProfiles,line){
 const raw=Array.isArray(p.records)?p.records.filter(r=>Number.isFinite(r.value)).sort((a,b)=>a.season-b.season||a.week-b.week):
   Array.isArray(p.logs)?p.logs.filter(Number.isFinite).map((value,i)=>({season:0,week:i+1,value})):[];
 const vals=raw.map(r=>r.value),n=vals.length,last=vals.slice(-10),last5=vals.slice(-5);
 const historical=n?(.55*ddMean(last)+.30*ddMean(last5)+.15*ddMean(vals)):null;
 const vlabel=DD_VOLUME[p.stat]||null;
 const sister=Array.isArray(allProfiles)?allProfiles.find(x=>x.playerKey&&x.playerKey===p.playerKey&&x.stat===vlabel&&Array.isArray(x.records)):null;
 const volumes=new Map((sister?.records||[]).filter(r=>Number.isFinite(r.value)).map(r=>[ddStatKey(r),r.value]));
 const paired=raw.map(r=>({value:r.value,volume:volumes.get(ddStatKey(r))})).filter(r=>Number.isFinite(r.volume)&&r.volume>0).slice(-10);
 const recentPaired=paired.slice(-5),sumVolume=paired.reduce((s,r)=>s+r.volume,0);
 const opp=paired.length>=5&&recentPaired.length>=5&&sumVolume>0?ddMean(recentPaired.map(r=>r.volume))*paired.reduce((s,r)=>s+r.value,0)/sumVolume:null;
 const past5=n>=10?ddMean(vals.slice(-10,-5)):null,recent5=n>=5?ddMean(last5):null;
 const volumeBefore=paired.length>=10?ddMean(paired.slice(-10,-5).map(r=>r.volume)):null;
 const volumeNow=paired.length>=5?ddMean(recentPaired.map(r=>r.volume)):null;
 const rateBefore=paired.length>=10?paired.slice(-10,-5).reduce((s,r)=>s+r.value,0)/paired.slice(-10,-5).reduce((s,r)=>s+r.volume,0):null;
 const rateNow=paired.length>=5?recentPaired.reduce((s,r)=>s+r.value,0)/recentPaired.reduce((s,r)=>s+r.volume,0):null;
 const qs=n>=8?{low:ddQuantile(last,.20),high:ddQuantile(last,.80)}:null;
 const estimates=[{key:'historical',label:'Weighted historical',value:historical,note:'L10, L5 and all recorded games'}];
 if(opp!==null)estimates.push({key:'opportunity',label:'Historical opportunity-based',value:opp,note:'Recent recorded opportunities × historical output per opportunity'});
 const conflicts=[];
 if(n>=10&&past5>0&&recent5!==null&&Math.abs(recent5/past5-1)>=.20)
  conflicts.push({key:'recent_form',severity:'review',title:'Large recent production change',detail:'Last five average '+recent5.toFixed(1)+' versus previous five '+past5.toFixed(1)+' (change '+((recent5/past5-1)*100).toFixed(1)+'%).'});
 if(volumeBefore!==null&&volumeNow!==null&&volumeBefore>0&&past5>0&&recent5!==null){
  const productionChange=recent5/past5-1,volumeChange=volumeNow/volumeBefore-1;
  if((productionChange>=.15&&volumeChange<=-.15)||(productionChange<=-.15&&volumeChange>=.15)){
   conflicts.push({key:'volume',severity:'warning',title:'Production and opportunity trends disagree',
    detail:'L5 production '+recent5.toFixed(1)+' versus prior L5 '+past5.toFixed(1)+'; '+vlabel+' L5 '+volumeNow.toFixed(1)+' versus prior L5 '+volumeBefore.toFixed(1)+'.'});
  }
 }
 if(rateBefore!==null&&rateNow!==null&&rateBefore>0&&Math.abs(rateNow/rateBefore-1)>=.30){
  conflicts.push({key:'efficiency',severity:'review',title:'Per-opportunity efficiency changed substantially',
   detail:'Recent production per opportunity '+rateNow.toFixed(2)+' versus prior '+rateBefore.toFixed(2)+'.'});
 }
 if(opp!==null&&historical!==null){
  const discrepancy=Math.abs(historical-opp),comparison=Math.max(1,historical);
  if(discrepancy/comparison>=.15){
   conflicts.push({key:'estimates',severity:'warning',title:'Historical and opportunity estimates disagree',
    detail:'Historical '+historical.toFixed(1)+' versus opportunity-based '+opp.toFixed(1)+' ('+(100*discrepancy/comparison).toFixed(1)+'% relative gap).'});
  }
 }
 const countOver=Number.isFinite(line)?vals.filter(v=>v>line).length:null;
 const countUnder=Number.isFinite(line)?vals.filter(v=>v<line).length:null;
 const countEqual=Number.isFinite(line)?n-countOver-countUnder:null;
 const band=qs?{...qs,type:'Observed L10 20th–80th percentile band',coverage:'Not a calibrated future prediction interval'}:null;
 const conservative=band?band.low:null,optimistic=band?band.high:null;
 if(band){
  estimates.push({key:'lower',label:'Observed lower reference',value:conservative,note:'L10 20th percentile; not a low-game scenario forecast'});
  estimates.push({key:'upper',label:'Observed upper reference',value:optimistic,note:'L10 80th percentile; not a high-game scenario forecast'});
 }
 let reliability=n<5?'INSUFFICIENT DATA':n<10?'LIMITED DATA':'DESCRIPTIVE EVIDENCE';
 if(conflicts.length&&reliability==='DESCRIPTIVE EVIDENCE')reliability='CONFLICTING EVIDENCE';
 const limitations=[];
 if(!vlabel)limitations.push('No standard opportunity mapping exists for this statistic in the current adapter.');
 else if(!sister)limitations.push('Opportunity records unavailable for '+vlabel+'.');
 else if(paired.length<5)limitations.push('Fewer than five valid paired production/opportunity games.');
 if(n<10)limitations.push('Fewer than 10 recorded games; historical range is limited.');
 limitations.push('No independent calibrated prediction intervals, true over/under probabilities, or verified next-game inputs.');
 const lineRelation=band&&Number.isFinite(line)?line<band.low?'Below observed band':line>band.high?'Above observed band':'Within observed band':null;
 return {games:n,volumeLabel:vlabel,pairedGames:paired.length,estimates,conflicts,band,reliability,limitations,line,
  historical,opportunity:opp,over:countOver,under:countUnder,equal:countEqual,lineRelation,
  recentMean:recent5,previousMean:past5,recentVolume:volumeNow,previousVolume:volumeBefore,efficiency:rateNow};
}
