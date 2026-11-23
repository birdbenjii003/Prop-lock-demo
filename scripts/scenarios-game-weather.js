'use strict';
// Scenarios Phase 3: free, best-effort scheduled-game context. No betting decisions.
// Exact-name stadium registry is intentionally incomplete: UNKNOWN blocks weather.
const SCENARIO_VENUES={
 'Lambeau Field':{lat:44.5013,lon:-88.0622,roof:'outdoor'},
 'Soldier Field':{lat:41.8623,lon:-87.6167,roof:'outdoor'},
 'GEHA Field at Arrowhead Stadium':{lat:39.0489,lon:-94.4839,roof:'outdoor'},
 'Arrowhead Stadium':{lat:39.0489,lon:-94.4839,roof:'outdoor'},
 'MetLife Stadium':{lat:40.8135,lon:-74.0745,roof:'outdoor'},
 'Lincoln Financial Field':{lat:39.9008,lon:-75.1675,roof:'outdoor'},
 'Highmark Stadium':{lat:42.7738,lon:-78.7870,roof:'outdoor'},
 'Ford Field':{roof:'indoor'},
 'U.S. Bank Stadium':{roof:'indoor'},
 'Allegiant Stadium':{roof:'indoor'},
 'Caesars Superdome':{roof:'indoor'},
 'Mercedes-Benz Stadium':{roof:'retractable'},
 'AT&T Stadium':{roof:'retractable'},
 'NRG Stadium':{roof:'retractable'},
 'Lucas Oil Stadium':{roof:'retractable'},
 'State Farm Stadium':{roof:'retractable'}
};
function scenarioUpcomingGame(payload,team,nowMs=Date.now()){
 if(!team||!Array.isArray(payload?.events))return {status:'SCHEDULE_UNAVAILABLE',reason:'No authenticated upcoming schedule for player team'};
 const entries=payload.events.flatMap(event=>{
  const comp=event.competitions?.[0],dateMs=Date.parse(comp?.date||event.date);
  const competitors=comp?.competitors||[];
  if(!Number.isFinite(dateMs)||!competitors.length||!event.id)return [];
  if(dateMs<nowMs-2*60*60*1000||dateMs>nowMs+16*86400000)return [];
  const status=comp?.status?.type?.state||event.status?.type?.state;
  if(status&&status!=='pre'&&status!=='in')return [];
  const teams=competitors.map(c=>({abbreviation:c.team?.abbreviation||'',homeAway:c.homeAway}));
  if(!teams.some(c=>c.abbreviation.toUpperCase()===String(team).toUpperCase()))return [];
  const venue=comp?.venue||{};
  return [{eventId:String(event.id),date:new Date(dateMs).toISOString(),teams,venueName:venue.fullName||'',
    indoor:venue.indoor,source:'ESPN scoreboard (third-party schedule; independently unverified)'}];
 }).sort((a,b)=>Date.parse(a.date)-Date.parse(b.date));
 if(!entries.length)return {status:'NO_UPCOMING_GAME',reason:'No scheduled team game found in returned window'};
 const game=entries[0],registered=SCENARIO_VENUES[game.venueName];
 if(!game.venueName||!registered)return {status:'VENUE_UNMAPPED',game,reason:'No exact stadium registry match'};
 if(registered.roof==='indoor'||game.indoor===true&&registered.roof!=='retractable')
  return {status:'INDOOR_NO_WEATHER',game,reason:'Indoor venue: outdoor conditions cannot be applied'};
 if(registered.roof==='retractable')return {status:'ROOF_UNCONFIRMED',game,reason:'Retractable roof status unknown: no field-weather assumption'};
 if(game.indoor!==false)return {status:'VENUE_TYPE_UNVERIFIED',game,reason:'Outdoor classification not explicitly confirmed by schedule'};
 return {status:'OUTDOOR_VENUE_MATCHED',game,coords:{lat:registered.lat,lon:registered.lon},
  reason:'Exact stadium name match, approximate registry coordinates; roof state and event source still require verification'};
}
function scenarioKickoffForecast(payload,gameContext,nowMs=Date.now()){
 if(gameContext?.status!=='OUTDOOR_VENUE_MATCHED')return {status:'BLOCKED_VENUE',reason:gameContext?.reason||'No verified outdoor venue'};
 const kick=Date.parse(gameContext.game.date),h=payload?.hourly;
 if(!Number.isFinite(kick)||kick<nowMs-3*3600000||kick>nowMs+16*86400000)return {status:'OUTSIDE_WINDOW'};
 if(!Array.isArray(h?.time)||!Array.isArray(h.temperature_2m)||!Array.isArray(h.wind_speed_10m))return {status:'FORECAST_UNAVAILABLE'};
 const times=h.time.map(t=>typeof t==='number'?t*1000:Date.parse(t));
 let best=-1,diff=Infinity;
 for(let i=0;i<times.length;i++){const delta=Math.abs(times[i]-kick);if(Number.isFinite(delta)&&delta<diff){best=i;diff=delta}}
 if(best<0||diff>60*60000)return {status:'FORECAST_TIME_MISMATCH',reason:'No hourly forecast within one hour of kickoff'};
 const temp=h.temperature_2m[best],wind=h.wind_speed_10m[best],rain=h.precipitation_probability?.[best]??null;
 if(!Number.isFinite(temp)||!Number.isFinite(wind)||wind<0)return {status:'FORECAST_UNAVAILABLE'};
 return {status:'KICKOFF_FORECAST_UNVERIFIED',temperatureF:temp,windMph:wind,precipProbability:typeof rain==='number'?rain:null,
   validAt:new Date(times[best]).toISOString(),kickoff:gameContext.game.date,
   source:'Open-Meteo hourly forecast',forecastIssuedAt:new Date(nowMs).toISOString(),
   warning:'Forecast conditions are not observations. ESPN schedule and stadium lookup are third-party; no estimated yardage adjustment.'};
}
function scenarioScheduleUrl(nowMs=Date.now()){
 const from=new Date(nowMs).toISOString().slice(0,10).replace(/-/g,'');
 const to=new Date(nowMs+14*86400000).toISOString().slice(0,10).replace(/-/g,'');
 return 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates='+from+'-'+to+'&limit=100';
}
function scenarioKickoffWeatherUrl(ctx){
 if(ctx?.status!=='OUTDOOR_VENUE_MATCHED')return null;
 const p=new URLSearchParams({latitude:String(ctx.coords.lat),longitude:String(ctx.coords.lon),
   hourly:'temperature_2m,wind_speed_10m,precipitation_probability',temperature_unit:'fahrenheit',
   wind_speed_unit:'mph',timeformat:'unixtime',timezone:'UTC',forecast_days:'16'});
 return 'https://api.open-meteo.com/v1/forecast?'+p;
}
