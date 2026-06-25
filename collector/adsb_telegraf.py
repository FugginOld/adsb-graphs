#!/usr/bin/env python3
"""graphs1090 Telegraf collector.

Fetches the same dump1090/readsb JSON the legacy collectd plugin used and emits
InfluxDB line protocol on stdout. Two run modes:

  execd (default): Telegraf drives it via STDIN — one collection per newline.
      [[inputs.execd]] command=["python3", ".../adsb_telegraf.py"] signal="STDIN"
  exec (--once):   collect a single batch, print, exit. Fallback for platforms
      where execd misbehaves:  [[inputs.exec]] commands=["... --once"]

Phase B: adsb_aircraft, adsb_messages, adsb_range, adsb_signal, adsb_cpu,
         adsb_tracks, adsb_gain (all 1090 measurements).
Remaining: 978, airspy, system metrics.
"""

import os
import sys
import json
from contextlib import closing

try:
    from urllib.request import urlopen
except ImportError:
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


# ── line protocol helpers ─────────────────────────────────────────────────────

def esc_tag(value):
    """Escape an InfluxDB tag value (commas, spaces, equals)."""
    return (str(value)
            .replace('\\', '\\\\')
            .replace(',', '\\,')
            .replace(' ', '\\ ')
            .replace('=', '\\='))


def _ff(v):
    """Format a float for InfluxDB line protocol (no i suffix, always has decimal)."""
    s = '%g' % float(v)
    if '.' not in s and 'e' not in s.lower():
        s += '.0'
    return s


# ── line builders ─────────────────────────────────────────────────────────────

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


def aircraft_line(ac_stats, aircraft_ts, instance, band='1090'):
    """Build the adsb_aircraft line from pre-computed ac_stats; None if unusable."""
    if not ac_stats:
        return None
    fields = 'total=%di,with_pos=%di,mlat=%di,tisb=%di,gps=%di' % (
        ac_stats['total'], ac_stats['with_pos'], ac_stats['mlat'],
        ac_stats['tisb'], ac_stats['gps'])
    ts = int(float(aircraft_ts) * 1e9)
    return 'adsb_aircraft,instance=%s,band=%s %s %d' % (
        esc_tag(instance), esc_tag(band), fields, ts)


def range_line(ac_stats, last1min, aircraft_ts, instance, band='1090'):
    """Build adsb_range: quartiles from aircraft table + max_range from last1min."""
    rq = (ac_stats or {}).get('range_quartiles')
    max_range = 0.0
    if last1min and 'max_distance' in last1min:
        max_range = float(last1min['max_distance'])
    elif rq:
        max_range = float(rq['max'])
    fields = ['max_range=%s' % _ff(max_range)]
    if rq:
        fields += [
            'median=%s' % _ff(rq['median']),
            'q1=%s' % _ff(rq['q1']),
            'q3=%s' % _ff(rq['q3']),
            'min=%s' % _ff(rq['min']),
        ]
    ts = int(float(aircraft_ts) * 1e9)
    return 'adsb_range,instance=%s,band=%s %s %d' % (
        esc_tag(instance), esc_tag(band), ','.join(fields), ts)


def signal_line(ac_stats, last1min, aircraft_ts, instance, band='1090'):
    """Build adsb_signal: last1min stats signal/noise + aircraft-table quartiles."""
    fields = []
    sq = (ac_stats or {}).get('signal_quartiles')
    if last1min:
        loc = last1min.get('local') or {}
        if 'signal' in loc:
            fields.append('signal=%s' % _ff(loc['signal']))
        if 'noise' in loc:
            fields.append('noise=%s' % _ff(loc['noise']))
    if sq:
        fields += [
            'median=%s' % _ff(sq['median']),
            'q1=%s' % _ff(sq['q1']),
            'q3=%s' % _ff(sq['q3']),
            'peak_signal=%s' % _ff(sq['max']),
            'min_signal=%s' % _ff(sq['min']),
        ]
    if not fields:
        return None
    ts = int(float(aircraft_ts) * 1e9)
    return 'adsb_signal,instance=%s,band=%s %s %d' % (
        esc_tag(instance), esc_tag(band), ','.join(fields), ts)


def cpu_line(total, instance):
    """Build adsb_cpu from stats.json total.cpu counters; None if missing."""
    if not total or 'cpu' not in total or 'end' not in total:
        return None
    cpu = total['cpu']
    fields = ['%s=%di' % (k, int(v)) for k, v in sorted(cpu.items())
              if isinstance(v, (int, float))]
    if not fields:
        return None
    ts = int(float(total['end']) * 1e9)
    return 'adsb_cpu,instance=%s %s %d' % (esc_tag(instance), ','.join(fields), ts)


def tracks_line(total, instance):
    """Build adsb_tracks from stats.json total.tracks counters; None if missing."""
    if not total or 'tracks' not in total or 'end' not in total:
        return None
    tracks = total['tracks']
    if 'all' not in tracks:
        return None
    fields = 'all=%di,single_message=%di' % (
        int(tracks['all']), int(tracks.get('single_message', 0)))
    ts = int(float(total['end']) * 1e9)
    return 'adsb_tracks,instance=%s %s %d' % (esc_tag(instance), fields, ts)


def gain_line(stats, instance):
    """Build adsb_gain with multi-fallback path matching legacy handle_signal_stuff."""
    if not stats:
        return None
    gain_db = None
    ts = None
    last1min = stats.get('last1min') or {}
    end = last1min.get('end')
    adaptive = last1min.get('adaptive')
    if end and isinstance(adaptive, dict) and 'gain_db' in adaptive:
        gain_db = adaptive['gain_db']
        ts = end
    elif end and 'gain_db' in last1min:
        gain_db = last1min['gain_db']
        ts = end
    elif 'gain_db' in stats and 'now' in stats:
        gain_db = stats['gain_db']
        ts = stats['now']
    elif end and 'gain_db' in (last1min.get('local') or {}):
        gain_db = last1min['local']['gain_db']
        ts = end
    if gain_db is None or ts is None:
        return None
    return 'adsb_gain,instance=%s gain_db=%s %d' % (
        esc_tag(instance), _ff(gain_db), int(float(ts) * 1e9))


def build_lines(stats, receiver, aircraft_json, instance):
    """Pure: assemble all 1090 line-protocol strings for one poll. Testable."""
    rlat = rlon = None
    if receiver and 'lat' in receiver:
        rlat = float(receiver['lat'])
        rlon = float(receiver['lon'])

    total = (stats or {}).get('total')
    last1min = (stats or {}).get('last1min')

    ac_stats = None
    aircraft_ts = None
    if aircraft_json and 'aircraft' in aircraft_json and 'now' in aircraft_json:
        ac_stats = compute_aircraft_stats(aircraft_json['aircraft'], rlat, rlon)
        aircraft_ts = aircraft_json['now']

    out = []

    m = messages_line(total, instance)
    if m:
        out.append(m)

    if ac_stats is not None:
        a = aircraft_line(ac_stats, aircraft_ts, instance)
        if a:
            out.append(a)

        r = range_line(ac_stats, last1min, aircraft_ts, instance)
        if r:
            out.append(r)

        s = signal_line(ac_stats, last1min, aircraft_ts, instance)
        if s:
            out.append(s)

    c = cpu_line(total, instance)
    if c:
        out.append(c)

    tr = tracks_line(total, instance)
    if tr:
        out.append(tr)

    g = gain_line(stats, instance)
    if g:
        out.append(g)

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
    for _ in sys.stdin:
        emit(collect(conf))


if __name__ == '__main__':
    main()
