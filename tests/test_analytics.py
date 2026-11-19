import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as Row
from unittest.mock import patch
from flask import Flask
from models import db, DeviceStatusLog, LightingRecord
from services.analytics import recorded_state, device_summary, lighting_intervals, lighting_totals, lighting_daily
import routes.api as api

NOW = datetime(2026, 11, 18, 12)

def light(seconds, status, brightness=50, **extra):
    return Row(recorded_at=NOW+timedelta(seconds=seconds), status=status,
               brightness=brightness, **extra)

class AnalyticsTests(unittest.TestCase):
    def duration(self, rows, start=-3600, end=0):
        segments, pending = lighting_intervals(rows, NOW+timedelta(seconds=start), NOW+timedelta(seconds=end))
        return lighting_totals(segments)[0], pending

    def test_json_and_legacy_states(self):
        for status, device, expected in [('on','fan',True), ('off','light',False),
            ('{"on":true}','light',True), ('{"on":false}','fan',False),
            ('{"locked":true}','door',False), ('{"locked":false}','door',True)]:
            self.assertIs(recorded_state(Row(status=status),device),expected)

    def test_unknown_accepted_and_failed_are_not_physical_states(self):
        rows=[Row(device_name='door', status='{"locked":null,"command_state":"unlocked_accepted"}', value='accepted'),
              Row(device_name='door', status='{"locked":false}', value='command_failed')]
        result=device_summary(rows,[])['door']
        self.assertEqual((result['on_count'], result['off_count'], result['unknown_count']), (0,0,2))
        self.assertEqual((result['accepted_count'],result['failed_count']),(1,1))

    def test_unsupported_devices_and_bad_json_excluded(self):
        rows=[Row(device_name='ac',status='on'),Row(device_name='fan',status='{broken')]
        result=device_summary(rows,[])
        self.assertEqual(set(result),{'light','fan','door'})
        self.assertEqual(result['fan']['unknown_count'],1)

    def test_lighting_fallback_without_double_counting(self):
        lights=[light(-2,'on'),light(-1,'off')]
        self.assertEqual(device_summary([],lights)['light']['total_logs'],2)
        row=Row(device_name='light',status='{"on":true}')
        self.assertEqual(device_summary([row],lights)['light']['total_logs'],1)

    def test_subsecond_intervals_are_not_truncated(self):
        self.assertEqual(self.duration([light(-1,'on'),light(-0.25,'off')]),(.75,False))

    def test_repeated_on_and_brightness_do_not_double_count(self):
        self.assertEqual(self.duration([light(-100,'on',20),light(-60,'on',80),light(-10,'off')]),(90,False))

    def test_window_clips_preceding_on(self):
        self.assertEqual(self.duration([light(-7200,'on'),light(-1800,'off')]),(1800,False))

    def test_missing_on_or_off_never_extrapolates_now(self):
        self.assertEqual(self.duration([light(-200,'off')]),(0,False))
        self.assertEqual(self.duration([light(-200,'on')]),(0,True))
        self.assertEqual(self.duration([light(-200,'on'),light(-100,'on')]),(100,True))

    def test_unknown_record_breaks_continuity(self):
        self.assertEqual(self.duration([light(-200,'on'),light(-100,'unknown'),light(-10,'off')]),(0,False))

    def test_future_records_are_not_counted(self):
        self.assertEqual(self.duration([light(-20,'on'),light(20,'off')]),(0,True))

    def test_long_interval_and_midnight_split(self):
        rows=[light(-90000,'on'),light(-600,'off')]
        total,_=self.duration(rows,start=-100000)
        self.assertEqual(total,89400)
        daily=lighting_daily(rows,NOW-timedelta(seconds=100000),NOW)
        self.assertEqual(sum(d['total_on_seconds'] for d in daily),total)
        self.assertEqual(len(daily),2)

    def test_empty_logs_give_zero(self):
        self.assertEqual(self.duration([]),(0,False))
        self.assertTrue(all(s['total_logs']==0 for s in device_summary([],[]).values()))

class AnalyticsAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.app=Flask(__name__)
        self.app.config.update(TESTING=True,SQLALCHEMY_DATABASE_URI='sqlite:///'+str(Path(self.tmp.name)/'hardware-test.db'))
        db.init_app(self.app); self.app.register_blueprint(api.api_bp)
        with self.app.app_context(): db.create_all()
        self.client=self.app.test_client()
        clock=patch.object(api,'datetime'); self.clock=clock.start(); self.addCleanup(clock.stop)
        self.clock.now.return_value=NOW

    def add(self,*rows):
        with self.app.app_context(): db.session.add_all(rows); db.session.commit()

    def get(self,path):
        result=self.client.get('/api/'+path)
        self.assertEqual(result.status_code,200)
        return result.get_json()['data']

    def test_summary_uses_json_history_and_only_kept_devices(self):
        self.add(DeviceStatusLog(device_name='fan',status='{"on":true}',recorded_at=NOW),
                 DeviceStatusLog(device_name='window',status='open',recorded_at=NOW))
        result=self.get('history/devices/summary')
        self.assertEqual(set(result),{'light','fan','door'})
        self.assertEqual(result['fan']['on_count'],1)

    def test_empty_db_api(self):
        self.assertEqual(self.get('lighting/stats')['total_on_seconds'],0)
        self.assertEqual(self.get('lighting/daily-summary'),[])
        self.assertEqual(self.get('history/devices/summary')['door']['total_logs'],0)

    def test_lighting_api_preserves_chart_and_counts_and_does_not_write(self):
        self.add(LightingRecord(status='on',brightness=30,source='hardware',recorded_at=NOW-timedelta(seconds=1)),
                 LightingRecord(status='off',brightness=0,source='hardware',recorded_at=NOW-timedelta(seconds=.2)))
        result=self.get('lighting/stats')
        self.assertEqual(result['total_on_seconds'],.8)
        self.assertEqual(result['total_operations'],2)
        self.assertEqual([p['brightness'] for p in result['brightness_chart']],[30,0])
        self.assertEqual([p['status'] for p in result['brightness_chart']],['on','off'])
        self.assertEqual(result['sources'],{'hardware':2})
        self.assertEqual(self.get('history/devices/summary')['light']['on_count'],1)
        with self.app.app_context():
            self.assertEqual(LightingRecord.query.count(),2)
            self.assertEqual([x.duration_seconds for x in LightingRecord.query.all()],[0,0])

    def test_previous_window_record_and_daily_agree(self):
        self.add(LightingRecord(status='on',brightness=50,recorded_at=NOW-timedelta(hours=25)),
                 LightingRecord(status='off',brightness=0,recorded_at=NOW-timedelta(hours=23)))
        self.assertEqual(self.get('lighting/stats?hours=24')['total_on_seconds'],3600)
        self.assertEqual(sum(d['total_on_seconds'] for d in self.get('lighting/daily-summary?days=1')),3600)

    def test_old_open_tail_never_increases_with_wall_clock(self):
        self.add(LightingRecord(status='on',brightness=50,recorded_at=NOW-timedelta(hours=2)))
        first=self.get('lighting/stats')
        self.clock.now.return_value=NOW+timedelta(hours=2)
        second=self.get('lighting/stats')
        self.assertTrue(first['pending_on'])
        self.assertEqual(first['total_on_seconds'],second['total_on_seconds'])

    def test_out_of_range_records_not_shown_in_brightness_or_operations(self):
        self.add(LightingRecord(status='on',brightness=50,recorded_at=NOW-timedelta(days=3)))
        result=self.get('lighting/stats?hours=24')
        self.assertEqual(result['brightness_chart'],[])
        self.assertEqual(result['total_operations'],0)
