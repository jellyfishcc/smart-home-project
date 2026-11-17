"""Read-only Linux inventory. Never imports the application or constructs Serial.

Only sysfs enumeration, permission checks and GET /api/hardware/status are used.
Configured mode and running server mode are deliberately reported separately.
"""
import argparse
import getpass
import json
import os
import sys
from urllib.request import urlopen


def serial_inventory():
    try:
        import serial
        from serial.tools import list_ports
    except Exception as exc:
        return {'importable': False, 'error': str(exc)}, []
    info = {'importable': True, 'version': serial.__version__}
    try:
        return info, list(list_ports.comports())
    except Exception as exc:
        return dict(info, enumeration_error=str(exc)), []


def dialout_membership():
    try:
        import grp
        group = grp.getgrnam('dialout')
        return {'member': group.gr_gid in (os.getgroups() + [os.getegid()]),
                'user': getpass.getuser()}
    except (ImportError, KeyError, AttributeError) as exc:
        return {'member': False, 'error': str(exc), 'user': getpass.getuser()}


def running_status(url):
    try:
        with urlopen(url, timeout=3) as response:
            data = json.load(response)
        mode = data['data']['mode']
        if data.get('code') != 0 or mode not in ('mock', 'serial', 'hardware', 'unavailable'):
            raise ValueError('invalid hardware status response')
        return {'reachable': True, 'mode': 'hardware' if mode in ('serial', 'hardware') else mode}
    except Exception as exc:
        return {'reachable': False, 'mode': 'unknown', 'error': str(exc)}


def build_report(environ, dependency, ports, membership, runtime, access=os.access):
    boards = {}
    for role, variable in [('door', 'SMART_HOME_DOOR_USB_SERIAL'),
                           ('environment', 'SMART_HOME_ENVIRONMENT_USB_SERIAL')]:
        serial_number = environ.get(variable, '').strip()
        matches = [p.device for p in ports if serial_number and p.serial_number == serial_number]
        board = {'usb_serial': serial_number or None, 'devices': matches,
                 'state': 'unconfigured' if not serial_number else
                          'missing' if not matches else 'present' if len(matches) == 1 else 'ambiguous',
                 'readable': False, 'writable': False}
        if len(matches) == 1:
            board.update(readable=access(matches[0], os.R_OK), writable=access(matches[0], os.W_OK))
        boards[role] = board
    duplicate = bool(boards['door']['usb_serial'] and
                     boards['door']['usb_serial'] == boards['environment']['usb_serial'])
    enabled = any(environ.get(key, '0').lower() in ('1', 'true')
                  for key in ('SMART_HOME_SERIAL_ENABLED', 'SMART_HOME_SERIAL_ENV_ENABLED'))
    configured_mode = ('hardware' if enabled else
                       'unavailable' if environ.get('SMART_HOME_SIMULATION_MODE', 'true').lower() in ('0', 'false', 'no')
                       else 'mock')
    ready = (dependency['importable'] and membership['member'] and not duplicate and
             all(b['state'] == 'present' and b['readable'] and b['writable'] for b in boards.values()))
    return {'read_only': True, 'python': sys.executable, 'python_version': sys.version.split()[0],
            'pyserial': dependency, 'dialout': membership, 'boards': boards,
            'duplicate_mapping': duplicate, 'configured_mode': configured_mode,
            'running_application': runtime,
            'mode_matches': runtime['mode'] == configured_mode if runtime['reachable'] else None,
            'inventory_ready': bool(ready),
            'note': 'Inventory only; no port opened, no commands sent, no actuator approval implied.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--status-url', default='http://127.0.0.1:5000/api/hardware/status')
    args = parser.parse_args(argv)
    dependency, ports = serial_inventory()
    report = build_report(os.environ, dependency, ports, dialout_membership(), running_status(args.status_url))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['inventory_ready'] and report['mode_matches'] is True else 1


if __name__ == '__main__':
    sys.exit(main())
