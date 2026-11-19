const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'../..');
const read=p=>fs.readFileSync(path.join(root,p),'utf8');
function fixture(file){
 const elements=new Map(),charts=[];
 const c=vm.createContext({console,document:{addEventListener(){},getElementById(id){
  if(!elements.has(id))elements.set(id,{textContent:'',innerHTML:'',value:24,getContext(){return {};}});
  return elements.get(id);
 }},socket:{on(){}},setInterval(){},formatTime:s=>s,escapeHtml:s=>s,API:{get:async()=>({code:0,data:{}})},
 Chart:function(ctx,opts){charts.push(opts);this.destroy=()=>{};}});
 vm.runInContext(read('static/js/analytics_display.js'),c);
 const source=read(file);
 vm.runInContext(file.endsWith('.html')?[...source.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m=>m[1]).join('\n'):source,c);
 return {c,elements,charts};
}
test('duration preserves seconds and uses readable units',()=>{
 const {c}=fixture('templates/data_analysis.html');
 for(const [v,t] of [[0,'0 秒'],[.75,'0.75 秒'],[90,'1.5 分钟'],[7200,'2 小时']])assert.equal(c.formatRecordedDuration(v),t);
});
test('summary uses response counts and excludes AC/window',()=>{
 const {c,charts}=fixture('templates/data_analysis.html');
 c.renderDeviceStatusChart({light:{on_count:2,off_count:1,total_logs:3},door:{unknown_count:2,total_logs:2},ac:{on_count:99}});
 assert.deepEqual(Array.from(charts[0].data.labels),['灯光','风扇','门锁']);
 assert.deepEqual(Array.from(charts[0].data.datasets[0].data),[2,0,0]);
 assert.deepEqual(Array.from(charts[0].data.datasets[2].data),[0,0,2]);
});
test('empty summary renders zero and no-data message',()=>{
 const {c,elements,charts}=fixture('templates/data_analysis.html');c.renderDeviceStatusChart({});c.renderDeviceSummaryTable({});
 assert.deepEqual(Array.from(charts[0].data.datasets[0].data),[0,0,0]);assert.match(elements.get('deviceStatsNote').textContent,/暂无/);
});
test('lighting API still populates brightness and operation history',async()=>{
 const {c,elements,charts}=fixture('templates/data_analysis.html');
 const history=[{time:'2026-11-18 10:00:00',status:'on',brightness:30,source:'hardware'},{time:'2026-11-18 10:00:01',status:'off',brightness:0,source:'hardware'}];
 c.API.get=async url=>({code:0,data:url.includes('daily-summary')?[]:{total_on_seconds:.8,pending_on:true,avg_brightness:30,total_energy_wh:0,total_operations:2,brightness_chart:history,sources:{hardware:2}}});
 await c.loadLightingAnalysis();assert.equal(elements.get('lightTotalHours').textContent,'0.8 秒');assert.match(elements.get('lightDurationNote').textContent,/尾段未计入/);
 assert.match(elements.get('lightDetailBody').innerHTML,/30%/);assert.match(elements.get('lightDetailBody').innerHTML,/关灯/);
 assert.deepEqual(Array.from(charts[0].data.datasets[0].data),[30,0]);
});
test('detection advertises exactly three project labels',()=>{
 const {c,elements}=fixture('templates/object_detection.html');c.loadClassList();
 assert.deepEqual([...elements.get('classList').innerHTML.matchAll(/>([^<]+)<\/span>/g)].map(m=>m[1]),['fire extinguisher','DR','light bulb']);
 assert.ok(!read('templates/object_detection.html').includes('80 类'));
});
test('dashboard ignores removed device events',()=>{
 const {c,elements}=fixture('static/js/dashboard.js');c.updateAllDevices({light:{on:true,brightness:30},fan:{on:false,speed:0},door:{locked:true}});
 c.updateDeviceDisplay('ac',{on:true});c.updateDeviceDisplay('window',{closed:true});
 assert.equal(elements.get('lightValue').textContent,'30%');assert.ok(![...elements.keys()].some(k=>/^(ac|window)/.test(k)));
});
test('templates remove obsolete modules and preserve control handlers',()=>{
 const dash=read('templates/dashboard.html'),controls=read('templates/device_control.html');
 for(const source of [dash,controls])assert.ok(!/空调|窗户|acSwitch|windowBadge/.test(source));
 assert.equal((dash.match(/class="stat-card"/g)||[]).length,6);
 assert.equal((dash.match(/class="grid-3" style="margin-bottom:20px;"/g)||[]).length,2);
 assert.equal((controls.match(/class="grid-3"/g)||[]).length,1);
 for(const name of ['setLightBrightness','setFanSpeed','controlDoor','sendEnvRequest'])assert.ok(controls.includes('function '+name+'('));
});
