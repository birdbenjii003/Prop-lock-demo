'use strict';
// Scenario research v2.0: conditional opportunity sensitivity, not a forecast or bet decision.
const SCENARIO_OPPORTUNITY_STAT={'Rushing Yards':'Carries','Rushing TDs':'Carries','Receiving Yards':'Targets','Receiving TDs':'Targets','Receptions':'Targets','Passing Yards':'Passing Attempts','Passing TDs':'Passing Attempts','Interceptions':'Passing Attempts'};
const SCENARIO_SCRIPTS=[
 {id:'competitive',label:'Competitive',volume:1,efficiency:1,pace:1},
 {id:'leading',label:'Playing ahead',volume:1.20,efficiency:1.0,pace:.97},
 {id:'trailing',label:'Playing behind',volume:.78,efficiency:1.0,pace:1.04},
 {id:'limited',label:'Reduced participation',volume:.65,efficiency:1.0,pace:1}
];
function scenarioOpportunity(p,profiles){
 const type=SCENARIO_OPPORTUNITY_STAT[p.stat];
 const own=Array.isArray(p.records)?p.records.filter(r=>Number.isFinite(r.value)):[];
 if(!type||!own.length)return {status:'UNAVAILABLE',reason:'No matched recorded player opportunities',type};
 const peer=(profiles||[]).find(x=>x.playerKey===p.playerKey&&x.stat===type&&x.sport===p.sport);
 if(!peer?.records?.length)return {status:'UNAVAILABLE',reason:'Missing matched '+type+' game records',type};
 const lookup=new Map(peer.records.map(r=>[r.season+':'+r.week,r.value]));
 const paired=own.map(r=>({production:r.value,opportunities:lookup.get(r.season+':'+r.week)}))
   .filter(r=>Number.isFinite(r.opportunities)&&r.opportunities>0);
 if(paired.length<5)return {status:'INSUFFICIENT',reason:'Fewer than five matched game opportunities',type,n:paired.length};
 const recent=paired.slice(-10);
 const opportunity=recent.reduce((a,r)=>a+r.opportunities,0)/recent.length;
 const efficiency=recent.reduce((a,r)=>a+r.production,0)/recent.reduce((a,r)=>a+r.opportunities,0);
 const production=recent.reduce((a,r)=>a+r.production,0)/recent.length;
 return {status:'DESCRIPTIVE_ONLY',type,n:recent.length,opportunity,efficiency,production};
}
function scenarioWeather(input,nowMs=Date.now()){
 if(!input)return {status:'NO_FEED',reason:'No stadium weather feed connected'};
 const {temperatureF,windMph,observedAt,source,venueVerified}=input;
 const observed=Date.parse(observedAt);
 if(!source||!Number.isFinite(temperatureF)||!Number.isFinite(windMph)||windMph<0||
    !Number.isFinite(observed)||observed>nowMs+5*60*1000||nowMs-observed>90*60*1000)
  return {status:'UNVERIFIED_OR_STALE',reason:'Missing venue identity, timestamp, valid measurements or fresh observation'};
 return {status:venueVerified?'CURRENT_CONDITIONS':'CURRENT_UNVERIFIED_VENUE',temperatureF,windMph,observedAt,source,
  reason:'Observed conditions at confirmed venue; NOT a game-time forecast unless timestamps match kickoff'};
}
function scenarioStudy(p,profiles,line,weather=null){
 const base=scenarioOpportunity(p,profiles);
 const evidence=scenarioWeather(weather);
 if(base.status!=='DESCRIPTIVE_ONLY')return {status:'INSUFFICIENT_OPPORTUNITY_EVIDENCE',base,weather:evidence,scenarios:[],scenarioProbabilities:null,overallProbability:null};
 // All script multipliers below are transparent stress-test assumptions, NOT historically calibrated.
 const passing=['Passing Yards','Passing TDs','Passing Attempts','Interceptions','Receiving Yards','Receptions','Targets','Receiving TDs'].includes(p.stat);
 const scripts=SCENARIO_SCRIPTS.map(script=>{
  const volume=script.id==='leading'?(passing?.88:1.20):script.id==='trailing'?(passing?1.20:.78):script.volume;
  const count=base.opportunity*volume*script.pace;
  const outcome=count*base.efficiency*script.efficiency;
  const need=base.efficiency>0?line/base.efficiency:null;
  return {id:script.id,label:script.label,opportunities:count,estimate:outcome,
   difference:outcome-line,requiredOpportunities:need,
   assessment:outcome>line?'ABOVE_LINE_IN_ASSUMPTION':outcome<line?'BELOW_LINE_IN_ASSUMPTION':'AT_LINE_IN_ASSUMPTION'};
 });
 const low=Math.min(...scripts.map(s=>s.estimate)),high=Math.max(...scripts.map(s=>s.estimate));
 const competitive=scripts[0].estimate;
 const sensitivity=(scripts.find(s=>s.id==='leading').estimate-scripts.find(s=>s.id==='trailing').estimate);
 return {status:'ILLUSTRATIVE_NOT_CALIBRATED',base,weather:evidence,scenarios:scripts,
  estimatedRange:{low,high},sensitivityDelta:sensitivity,
  failurePoint:base.efficiency>0?{requiredOpportunities:line/base.efficiency,type:base.type}:null,
  links:['Pace, volume, participation and efficiency are connected assumptions; avoid multiplying independent worst cases.'],
  scenarioProbabilities:null,overallProbability:null,
  validation:'NOT_HISTORICALLY_VALIDATED',
  warning:'Scenario likelihoods and multipliers have not been calibrated. No Over/Under or betting recommendation.'};
}
function scenarioWeatherFromOpenMeteo(payload,venueVerified,observedAt){
 const c=payload?.current;
 if(!c)return null;
 const temp=Number(c.temperature_2m),wind=Number(c.wind_speed_10m);
 // Open-Meteo current values are requested with temperature_unit=fahrenheit and wind_speed_unit=mph.
 if(!Number.isFinite(temp)||!Number.isFinite(wind))return null;
 return {temperatureF:temp,windMph:wind,observedAt:observedAt||c.time,source:'Open-Meteo current observation/model estimate',venueVerified};
}
