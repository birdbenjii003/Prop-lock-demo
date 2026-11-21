'use strict';
// V2.5 gates: DO NOT treat historical medians or manually entered thresholds as
// authentic market lines. Calibration requires timestamped, pregame market evidence.
const CALIBRATION_MARKET_FIELDS=['event_id','player_id','market','line','captured_at_utc','game_start_utc','source','outcome','event_date'];
function calibrationReadiness(profiles,marketRecords=[]){
 const imported=profiles.filter(p=>p.source==='imported'&&Array.isArray(p.records));
 const historicalGames=new Set(imported.flatMap(p=>p.records.map(r=>r.season+':'+r.week)));
 const market=Array.isArray(marketRecords)?marketRecords:[];
 let valid=0,invalid=0,preGame=0,uniqueEvents=new Set(),distinctDates=new Set();
 for(const r of market){
  if(!CALIBRATION_MARKET_FIELDS.every(k=>r[k]!==undefined&&r[k]!==null&&String(r[k]).trim()!=='')){invalid++;continue}
  const capture=Date.parse(r.captured_at_utc),start=Date.parse(r.game_start_utc);
  const line=Number(r.line);
  if(!Number.isFinite(capture)||!Number.isFinite(start)||capture>=start||!Number.isFinite(line)||line<0||!['over','under','push'].includes(String(r.outcome).toLowerCase())){invalid++;continue}
  valid++;preGame++;uniqueEvents.add(r.event_id);distinctDates.add(r.event_date);
 }
 // These are readiness checks only. They do not assert true market provenance
 // or guarantee the independence of observed records.
 const checks=[
  {name:'Historical player game logs',passed:imported.length>0&&historicalGames.size>=8,detail:imported.length+' eligible profiles across '+historicalGames.size+' distinct weeks'},
  {name:'Timestamped authentic market lines',passed:valid>=200&&uniqueEvents.size>=40,detail:valid+' structurally valid pregame line records; source authenticity must still be verified'},
  {name:'Resolved market outcomes',passed:valid>=200,detail:'Must use final graded over/under/push results matched to each original line'},
  {name:'Frozen out-of-time evaluation split',passed:false,detail:'Current moving two-week holdout is not an independently preserved evaluation period'},
  {name:'Pre-event feature snapshots',passed:false,detail:'Require verified as-of-game-start feature availability and archived model outputs'},
  {name:'Probability scoring and calibration',passed:false,detail:'Brier score, log loss, calibration-by-bin, uncertainty and baseline comparison are not implemented'}
 ];
 return {status:'NOT READY — NO CALIBRATED PROBABILITIES',checks,passed:checks.filter(x=>x.passed).length,required:checks.length,
 marketRows:market.length,validMarketRows:valid,invalidMarketRows:invalid,distinctEvents:uniqueEvents.size,distinctDates:distinctDates.size,
 historicalWeeks:historicalGames.size,profiles:imported.length,fields:CALIBRATION_MARKET_FIELDS,canPublishProbabilities:false};
}
function marketTemplateCsv(){
 return CALIBRATION_MARKET_FIELDS.join(',')+'\r\n';
}
