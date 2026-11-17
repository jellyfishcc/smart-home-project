import unittest
from unittest.mock import patch, Mock
from flask import Flask
from services.device_manager import DeviceManager
from services.hardware_service import HardwareService
from services.serial_bridge import Message, CommandResult
import routes.api as api


class EnvTristateTests(unittest.TestCase):
    def setUp(self):
        self.app=Flask(__name__)
        self.app.config.update(SERIAL_ENV_ENABLED=True,SIMULATION_MODE=False)
        self.app.register_blueprint(api.api_bp)
        self.dm=DeviceManager(self.app)
        self.hw=HardwareService();self.hw.init_app(self.app);self.hw.set_device_manager(self.dm)
        self.dm.set_hardware_bridge(self.hw)
        self.bridge=Mock()
        self.bridge.status.return_value={'protocol':'1','boot_count':1,'firmware':'env-tristate-1'}
        self.hw.env_bridge=self.bridge
        self.mode={'FAN':'AUTO','LAMP':'AUTO'}
        self.output={'FAN':False,'LAMP':False}
        def send(name,*args):
            if args[0]=='AUTO': self.mode[name]='AUTO'
            else:
                self.output[name]=bool(args[0])
                self.mode[name]='MANUAL_ON' if args[0] else 'MANUAL_OFF'
            self.hw._on_env_event(Message('EVT','CTL',[self.mode[name],name]))
            values=['ON' if self.output[name] else 'OFF']
            if name=='LAMP': values.append(str(args[1] if len(args)>1 and self.output[name] else 0))
            self.hw._on_env_event(Message('EVT',name,values))
            return CommandResult(True,name,reply=Message('ACK',name,list(map(str,args))),attempts=1)
        self.bridge.send.side_effect=send
        p=patch.object(api,'device_manager',self.dm);p.start();self.addCleanup(p.stop)
        self.client=self.app.test_client()

    def control(self,device,status):
        return self.client.post('/api/devices/'+device+'/control',json={'status':status})

    def test_manual_on_off_and_auto_through_api(self):
        for device,wire in [('fan','FAN'),('light','LAMP')]:
            for status,mode,on in [('on','manual_on',True),('off','manual_off',False),('auto','auto',False)]:
                r=self.control(device,status)
                self.assertEqual(r.status_code,200,r.get_json())
                state=r.get_json()['data']['state']
                self.assertEqual(state['mode'],mode)
                self.assertEqual(state['on'],on)
            self.assertIn(((wire,'AUTO'),),[(c.args,) for c in self.bridge.send.call_args_list])

    def test_output_event_remains_authoritative_without_command_echo(self):
        self.control('fan','off');count=self.bridge.send.call_count
        self.hw._on_env_event(Message('EVT','FAN',['ON']))
        self.assertTrue(self.dm.get_device('fan')['on'])
        self.assertEqual(self.bridge.send.call_count,count)

    def test_old_firmware_auto_rejected_without_send(self):
        self.bridge.status.return_value={'protocol':'1','boot_count':1}
        for device in ('fan','light'):
            self.assertEqual(self.control(device,'auto').status_code,503)
        self.bridge.send.assert_not_called()

    def test_failure_does_not_fabricate_manual_off(self):
        self.control('fan','on')
        self.bridge.send.side_effect=lambda *a: CommandResult(False,'FAN',error='timeout')
        self.assertEqual(self.control('fan','off').status_code,503)
        self.assertTrue(self.dm.get_device('fan')['on'])
        self.assertEqual(self.dm.get_device('fan')['mode'],'manual_on')

    def test_invalid_control_rejected_without_send(self):
        self.assertEqual(self.control('fan','release').status_code,400)
        self.bridge.send.assert_not_called()

    def test_real_toggle_rejected_even_with_ack_only_firmware(self):
        self.bridge.send.side_effect=lambda *a: CommandResult(True,a[0],attempts=1)
        for device in ('fan','light'):
            result=self.client.post('/api/devices/'+device+'/toggle')
            self.assertEqual(result.status_code,409)
        self.bridge.send.assert_not_called()

    def test_new_events_explicit_on_then_off(self):
        self.control('fan','on');self.control('fan','off')
        self.assertEqual([c.args for c in self.bridge.send.call_args_list],[('FAN',1),('FAN',0)])

    def test_page_switches_send_explicit_intent_and_has_auto(self):
        from pathlib import Path
        page=(Path(__file__).resolve().parents[1]/'templates/device_control.html').read_text()
        for device in ('fan','light'):
            self.assertIn("setEnvControl('%s', this.checked ? 'on' : 'off')" % device,page)
            self.assertIn("setEnvControl('%s', 'auto')" % device,page)

    def test_mock_manual_off_blocks_simulated_temperature_control(self):
        dm=DeviceManager()
        dm.set_device('fan','off')
        dm.auto_fan_control(40)
        self.assertFalse(dm.get_device('fan')['on'])
        dm.set_device('fan','auto')
        dm.auto_fan_control(40)
        self.assertTrue(dm.get_device('fan')['on'])
