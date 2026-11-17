const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
function fixture() {
    const elements = new Map();
    const group = [{disabled:false},{disabled:false},{disabled:true}];
    const errors = []; const calls = [];
    const context = vm.createContext({console, document:{
        querySelectorAll:()=>group,
        getElementById:(id)=>{
            if(!elements.has(id)) elements.set(id,{style:{},checked:false});
            return elements.get(id);
        }
    }, API:{post:async (url,data)=>{calls.push({url,data});return {code:0,message:'accepted',data:{}};}},
       showToast:(message,kind)=>errors.push({message,kind}),loadDeviceStatus:()=>{},parseInt});
    vm.runInContext(fs.readFileSync(path.join(root,'static/js/environment_controls.js'),'utf8'),context);
    const template = fs.readFileSync(path.join(root,'templates/device_control.html'),'utf8');
    for(const name of ['envModeLabel','updateDeviceUI','sendEnvRequest','setEnvControl','setLightBrightness','setFanSpeed']){
        const match=template.match(new RegExp('(?:async )?function '+name+'\\([^]*?\\n}'));
        assert.ok(match,name);vm.runInContext(match[0],context);
    }
    return {context,group,errors,calls,elements};
}
test('pending request disables same-device controls and drops duplicate clicks',async()=>{
    const {context:c,group}=fixture();let finish;let sent=0;
    const first=c.EnvControls.run('fan',()=>{sent++;return new Promise(r=>finish=r);},()=>{});
    assert.ok(group.every(x=>x.disabled));
    assert.equal(await c.EnvControls.run('fan',()=>{sent++;},()=>{}),false);
    assert.equal(sent,1);finish();await first;
    assert.deepEqual(group.map(x=>x.disabled),[false,false,true]);
});
test('failure restores controls and permits a subsequent request',async()=>{
    const {context:c,group}=fixture();let errors=0;
    assert.equal(await c.EnvControls.run('light',()=>Promise.reject(new Error('timeout')),()=>errors++),false);
    assert.equal(errors,1);assert.equal(group[0].disabled,false);
    assert.equal(await c.EnvControls.run('light',async()=>{},()=>{}),true);
});
test('actual UI handlers send explicit ON OFF and brightness with no toggle',async()=>{
    const {context:c,calls}=fixture();
    await c.setEnvControl('fan','on');await c.setEnvControl('fan','off');
    await c.setEnvControl('light','on');await c.setEnvControl('light','off');
    await c.setFanSpeed(0);await c.setLightBrightness(50);
    assert.equal(calls.length,6);assert.ok(calls.every(x=>!x.url.includes('toggle')));
    assert.deepEqual(calls.slice(0,4).map(x=>x.data.status),['on','off','on','off']);
    assert.equal(calls[4].data.status,'off');assert.equal(calls[5].data.brightness,50);
});
test('ACK UI checked/text updates, EVT correction wins over stale responses',()=>{
    const {context:c,elements}=fixture();
    for(const device of ['fan','light']) {
        c.updateDeviceUI(device,{on:true,speed:2,brightness:50,revision:1,state_source:'ack'});
        assert.equal(elements.get(device+'Switch').checked,true);
        c.updateDeviceUI(device,{on:false,speed:0,brightness:0,revision:3,state_source:'event'});
        assert.equal(elements.get(device+'Switch').checked,false);
        c.updateDeviceUI(device,{on:true,speed:2,brightness:50,revision:2,state_source:'ack'});
        assert.equal(elements.get(device+'Switch').checked,false);
    }
    assert.equal(elements.get('fanSpeedDisplay').textContent,'关闭');
    assert.equal(elements.get('lightBrightnessDisplay').textContent,'0%');
    assert.match(elements.get('fanAutoText').textContent,/板端输出回报/);
});
test('API failure shows error, does not fabricate ON, and restores control',async()=>{
    const {context:c,group,errors,elements}=fixture();
    c.updateDeviceUI('fan',{on:false,revision:1,speed:0});
    c.API.post=async()=>({code:1,message:'timeout'});
    assert.equal(await c.setEnvControl('fan','on'),false);
    assert.equal(elements.get('fanSwitch').checked,false);
    assert.equal(group[0].disabled,false);assert.equal(errors.at(-1).kind,'error');
});
test('server reconnect resets revision ordering',()=>{
    const {context:c}=fixture();
    assert.equal(c.EnvControls.accept('fan',{revision:8}),true);
    assert.equal(c.EnvControls.accept('fan',{revision:1}),false);
    c.EnvControls.reset();assert.equal(c.EnvControls.accept('fan',{revision:1}),true);
});
