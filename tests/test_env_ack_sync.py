import threading
import time
import unittest
from unittest.mock import Mock, patch
from flask import Flask
from flask_socketio import SocketIO
from services.device_manager import DeviceManager
from services.hardware_service import HardwareService
from services.serial_bridge import Message, CommandResult
import routes.api as api


class OldFirmwareAckTests(unittest.TestCase):
    def setUp(self):
        self.app=Flask(__name__)
        self.app.config.update(TESTING=True,SECRET_KEY='test',SERIAL_ENV_ENABLED=True,SIMULATION_MODE=False)
        self.app.register_blueprint(api.api_bp)
        self.socket=SocketIO(self.app,async_mode='threading')
        self.socket_client=self.socket.test_client(self.app)
        self.addCleanup(self.socket_client.disconnect)
        self.dm=DeviceManager(self.app);self.dm.set_socketio(self.socket)
        self.hw=HardwareService();self.hw.init_app(self.app);self.hw.set_device_manager(self.dm);self.hw.set_socketio(self.socket)
        self.dm.set_hardware_bridge(self.hw)
        self.bridge=Mock()
        self.bridge.status.return_value={'protocol':'1','boot_count':1,'firmware':''}
        self.hw.env_bridge=self.bridge
        self.bridge.send.side_effect=self.ack
        p=patch.object(api,'device_manager',self.dm);p.start();self.addCleanup(p.stop)
        self.client=self.app.test_client()
        self.socket_client.get_received()

    def ack(self,name,*args):
        return CommandResult(True,name,reply=Message('ACK',name,list(map(str,args))),attempts=1)

    def control(self,device,status,**extra):
        return self.client.post('/api/devices/'+device+'/control',json=dict(status=status,**extra))

    def test_fan_ack_only_on_then_off_sends_one_then_zero(self):
        for status,on in [('on',True),('off',False)]:
            response=self.control('fan',status)
            self.assertEqual(response.status_code,200)
            state=response.get_json()['data']['state']
            self.assertEqual(state['on'],on)
            self.assertEqual(state['commanded_state']['on'],on)
            self.assertEqual(state['state_source'],'ack')
            self.assertFalse(state['physical_confirmed'])
        self.assertEqual([c.args for c in self.bridge.send.call_args_list],[('FAN',1),('FAN',0)])

    def test_lamp_ack_only_on_then_off(self):
        on=self.control('light','on',value=50).get_json()['data']['state']
        off=self.control('light','off').get_json()['data']['state']
        self.assertTrue(on['on']);self.assertEqual(on['brightness'],50)
        self.assertFalse(off['on']);self.assertEqual(off['brightness'],0)
        self.assertEqual([c.args for c in self.bridge.send.call_args_list],[('LAMP',1,50),('LAMP',0)])

    def test_short_lamp_ack_uses_requested_level(self):
        self.bridge.send.side_effect=lambda name,*args: self.ack(name,args[0])
        state=self.control('light','on',value=60).get_json()['data']['state']
        self.assertTrue(state['on']);self.assertEqual(state['brightness'],60)

    def test_failure_keeps_state_and_publishes_no_success(self):
        for device in ('fan','light'):
            self.bridge.send.side_effect=self.ack
            self.control(device,'on')
            before=self.dm.get_device(device)
            self.socket_client.get_received()
            self.bridge.send.side_effect=lambda name,*args: CommandResult(False,name,error='timeout')
            self.assertEqual(self.control(device,'off').status_code,503)
            self.assertEqual(self.dm.get_device(device),before)
            self.assertEqual([m for m in self.socket_client.get_received() if m['name']=='device_update'],[])

    def test_wrong_ack_or_no_reply_does_not_fabricate_state(self):
        for reply in [None,Message('ACK','OTHER',['1']),Message('ACK','FAN',[])]:
            self.bridge.send.side_effect=lambda name,*args: CommandResult(True,name,reply=reply)
            self.control('fan','on')
            self.assertFalse(self.dm.get_device('fan')['on'])

    def test_evt_overrides_ack_and_no_echo(self):
        for device,wire in [('fan','FAN'),('light','LAMP')]:
            self.control(device,'on')
            count=self.bridge.send.call_count
            self.hw._on_env_event(Message('EVT',wire,['OFF','0']))
            state=self.dm.get_device(device)
            self.assertFalse(state['on']);self.assertEqual(state['state_source'],'event')
            self.assertTrue(state['commanded_state']['on'])
            self.assertFalse(state['reported_state']['on'])
            self.assertEqual(self.bridge.send.call_count,count)

    def test_newer_evt_before_send_returns_wins_over_old_ack(self):
        def send(name,*args):
            ack=self.ack(name,*args)
            self.hw._on_env_event(Message('EVT','FAN',['OFF'],ts=ack.reply.ts+1))
            return ack
        self.bridge.send.side_effect=send
        state=self.control('fan','on').get_json()['data']['state']
        self.assertFalse(state['on']);self.assertEqual(state['state_source'],'event')
        self.assertTrue(state['commanded_state']['on'])

    def test_websocket_on_off_payloads_for_both_devices(self):
        for device in ('fan','light'):
            self.control(device,'on');self.control(device,'off')
            messages=[m['args'][0] for m in self.socket_client.get_received() if m['name']=='device_update']
            self.assertEqual([m['state']['on'] for m in messages],[True,False])
            self.assertTrue(all(m['device']==device for m in messages))
            self.assertLess(messages[0]['state']['revision'],messages[1]['state']['revision'])

    def test_real_toggle_rejected_without_any_send(self):
        for device in ('fan','light'):
            response=self.client.post('/api/devices/'+device+'/toggle')
            self.assertEqual(response.status_code,409)
            self.assertEqual(response.get_json()['data']['error_code'],'explicit_target_required')
        self.bridge.send.assert_not_called()

    def test_concurrent_explicit_commands_serialized_through_state_update(self):
        entered=threading.Event();release=threading.Event();calls=[];results=[]
        def send(name,*args):
            calls.append((name,)+args)
            if args[0]==1:
                entered.set();release.wait(2)
            return self.ack(name,*args)
        self.bridge.send.side_effect=send
        def request(status):results.append(self.dm.set_device('fan',status))
        first=threading.Thread(target=request,args=('on',));second=threading.Thread(target=request,args=('off',))
        first.start();self.assertTrue(entered.wait(1));second.start()
        try:
            time.sleep(0.03);self.assertEqual(calls,[('FAN',1)])
        finally:
            release.set();first.join(2);second.join(2)
        self.assertFalse(first.is_alive());self.assertFalse(second.is_alive())
        self.assertEqual(calls,[('FAN',1),('FAN',0)])
        self.assertFalse(self.dm.get_device('fan')['on']);self.assertEqual(len(results),2)

    def test_mock_toggle_still_available(self):
        dm=DeviceManager()
        self.assertTrue(dm.toggle_device('fan')['state']['on'])
        self.assertFalse(dm.toggle_device('fan')['state']['on'])

    def test_hardware_status_event_contains_ack_result(self):
        self.control('fan','on')
        reports=[m['args'][0] for m in self.socket_client.get_received() if m['name']=='hardware_status']
        self.assertTrue(reports)
        self.assertTrue(reports[-1]['last_command']['ok'])
        self.assertEqual(reports[-1]['last_command']['ack']['args'],['1'])
