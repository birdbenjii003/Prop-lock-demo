'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const api=vm.runInNewContext(fs.readFileSync('scripts/scenarios-game-weather.js','utf8')+'\n({scenarioUpcomingGame,scenarioKickoffForecast,scenarioScheduleUrl,scenarioKickoffWeatherUrl})',{Date,URLSearchParams});
const now=Date.parse('2026-11-23T12:00:00Z');
const kickoff='2026-11-25T18:00:00Z';
const game=(venue,indoor=false)=>({id:'game1',date:kickoff,status:{type:{state:'pre'}},competitions:[{date:kickoff,
 competitors:[{team:{abbreviation:'GB'},homeAway:'home'},{team:{abbreviation:'CHI'},homeAway:'away'}],
 venue:{fullName:venue,indoor}}]});
const schedule=ev=>({events:[ev]});
const outdoor=api.scenarioUpcomingGame(schedule(game('Lambeau Field')), 'GB',now);
assert.equal(outdoor.status,'OUTDOOR_VENUE_MATCHED');
assert.ok(api.scenarioKickoffWeatherUrl(outdoor).includes('temperature_unit=fahrenheit'));
assert.equal(api.scenarioUpcomingGame(schedule(game('Lambeau Field')),'NYJ',now).status,'NO_UPCOMING_GAME');
assert.equal(api.scenarioUpcomingGame(schedule(game('Imaginary Stadium')),'GB',now).status,'VENUE_UNMAPPED');
assert.equal(api.scenarioUpcomingGame(schedule(game('Ford Field',true)),'GB',now).status,'INDOOR_NO_WEATHER');
assert.equal(api.scenarioUpcomingGame(schedule(game('Mercedes-Benz Stadium')),'GB',now).status,'ROOF_UNCONFIRMED');
assert.equal(api.scenarioUpcomingGame(schedule(game('Lambeau Field',true)),'GB',now).status,'INDOOR_NO_WEATHER');
assert.equal(api.scenarioUpcomingGame(schedule(game('Lambeau Field')),'GB',now+20*86400000).status,'NO_UPCOMING_GAME');
assert.equal(api.scenarioKickoffWeatherUrl({status:'ROOF_UNCONFIRMED'}),null);
const hour=Math.floor(Date.parse(kickoff)/3600000);
const weather={hourly:{time:[hour*3600],temperature_2m:[90],wind_speed_10m:[3],precipitation_probability:[11]}};
const projection=api.scenarioKickoffForecast(weather,outdoor,now);
assert.equal(projection.status,'KICKOFF_FORECAST_UNVERIFIED');
assert.equal(projection.temperatureF,90);
assert.equal(projection.windMph,3);
assert.equal(api.scenarioKickoffForecast(weather,{status:'ROOF_UNCONFIRMED',reason:'Closed roof'},now).status,'BLOCKED_VENUE');
assert.equal(api.scenarioKickoffForecast({hourly:{time:[],temperature_2m:[],wind_speed_10m:[]}},outdoor,now).status,'FORECAST_TIME_MISMATCH');
assert.equal(api.scenarioKickoffForecast({hourly:{time:[hour*3600],temperature_2m:[null],wind_speed_10m:[3]}},outdoor,now).status,'FORECAST_UNAVAILABLE');
console.log('Game identity, unknown venues, indoor/roof blocking, kickoff timestamps and weather safeguards PASS');
