#!/usr/bin/env python3
"""graphs1090 Telegraf collector (migration slice).

Fetches the same dump1090/readsb JSON the legacy collectd plugin used and emits
InfluxDB line protocol on stdout. Two run modes:

  execd (default): Telegraf drives it via STDIN — one collection per newline.
      [[inputs.execd]] command=["python3", ".../adsb_telegraf.py"] signal="STDIN"
  exec (--once):   collect a single batch, print, exit. Fallback for platforms
      where execd misbehaves:  [[inputs.exec]] commands=["... --once"]

Slice scope: adsb_aircraft + adsb_messages only. Remaining measurements
(range, signal, cpu, tracks, gain, 978, airspy, system) follow once this
vertical is proven on real hardware.
"""

import os
import sys
import json
from contextlib import closing

try:
    from urllib.request import urlopen
except ImportError:  # py2 safety, unlikely on target
    from urllib2 import urlopen

from adsb_stats import compute_aircraft_stats


# ── config ────────────────────────────────────────────────────────────────────

DEFAULT_CONF = '/usr/share/graphs1090/adsb_collector.conf'


def load_config():
    conf = {
        'instance':   os.environ.get('ADSB_INSTANCE', 'localhost'),
        'url':        os.environ.get('ADSB_URL', ''),
        'url_978':    os.environ.get('ADSB_URL_978', ''),
        'url_airspy': os.environ.get('ADSB_URL_AIRSPY', ''),
        'url_signal': os.environ.get('ADSB_URL_1090_SIGNAL', ''),
    }
    path = os.environ.get('ADSB_COLLECTOR_CONF', DEFAULT_CONF)
    if os.path.isfile(path):
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, val = line.split('=', 1)
                key = key.strip().lower()
                val = val.strip().strip('"').strip("'")
                if key == 'instance':
                    conf['instance'] = val
                elif key == 'url':
                    conf['url'] = val
                elif key == 'url_978':
                    conf['url_978'] = val
                elif key == 'url_airspy':
                    conf['url_airspy'] = val
                elif key in ('url_1090_signal', 'url_signal'):
                    conf['url_signal'] = val
    return conf


# ── line protocol helpers ───────────────────────────────────────────────────

def esc_tag(value):
    """Escape an InfluxDB tag value (commas, spaces, equals)."""
    return (str(value)
            .replace('\\', '\\\\')
            .replace(',', '\\,')
            .replace(' ', '\\ ')
            .replace('=', '\\='))


def messages_line(total, instance):
    """Build the adsb_messages line from stats.json['total']; None if unusable."""
    if not total or 'end' not in total:
        return None
    fields = []
    if 'local' in total and 'accepted' in total['local']:
        fields.append('local_accepted=%di' % int(sum(total['local']['accepted'])))
    if 'remote' in total and 'accepted' in total['remote']:
        rt = sum(total['remote']['accepted'])
        if 'basestation' in total['remote']:
            rt += total['remote']['basestation']
        fields.append('remote_accepted=%di' % int(rt))
    try:
        pos = total['cpr']['global_ok'] + total['cpr']['local_ok']
    except (KeyError, TypeError):
        pos = 0
    if pos == 0 and 'position_count_total' in total:
        pos = total['position_count_total']
    fields.append('positions=%di' % int(pos))
    if 'local' in total and 'strong_signals' in total['local']:
        fields.append('strong_signals=%di' % int(total['local']['strong_signals']))
    if not fields:
        return None
    ts = int(float(total['end']) * 1e9)
    return 'adsb_messages,instance=%s %s %d' % (esc_tag(instance), ','.join(fields), ts)


def aircraft_line(aircraft_json, rlat, rlon, instance):
    """Build the adsb_aircraft line from aircraft.json; None if unusable."""
    if not aircraft_json or 'aircraft' not in aircraft_json or 'now' not in aircraft_json:
        return None
    ac = compute_aircraft_stats(aircraft_json['aircraft'], rlat, rlon)
    fields = 'total=%di,with_pos=%di,mlat=%di,tisb=%di,gps=%di' % (
        ac['total'], ac['with_pos'], ac['mlat'], ac['tisb'], ac['gps'])
    ts = int(float(aircraft_json['now']) * 1e9)
    return 'adsb_aircraft,instance=%s %s %d' % (esc_tag(instance), fields, ts)


def build_lines(stats, receiver, aircraft_json, instance):
    """Pure: assemble all line-protocol strings for one poll. Testable."""
    rlat = rlon = None
    if receiver and 'lat' in receiver:
        rlat = float(receiver['lat'])
        rlon = float(receiver['lon'])
    out = []
    m = messages_line((stats or {}).get('total'), instance)
    if m:
        out.append(m)
    a = aircraft_line(aircraft_json, rlat, rlon, instance)
    if a:
        out.append(a)
    return out


# ── I/O ──────────────────────────────────────────────────────────────────────

def fetch_json(url, timeout=5.0):
    with closing(urlopen(url, None, timeout)) as fh:
        return json.load(fh)


def collect(conf):
    url = conf['url']
    if not url:
        return []
    try:
        stats = fetch_json(url + '/data/stats.json')
        receiver = fetch_json(url + '/data/receiver.json')
        aircraft_json = fetch_json(url + '/data/aircraft.json')
    except Exception:
        # Decoder transient / not ready: emit nothing, never crash Telegraf.
        return []
    return build_lines(stats, receiver, aircraft_json, conf['instance'])


def emit(lines):
    if lines:
        sys.stdout.write('\n'.join(lines) + '\n')
    sys.stdout.flush()


def main():
    conf = load_config()
    if '--once' in sys.argv:
        emit(collect(conf))
        return
    # execd: one collection per line Telegraf writes to our stdin.
    for _ in sys.stdin:
        emit(collect(conf))


if __name__ == '__main__':
    main()
