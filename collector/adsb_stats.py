"""Pure ADS-B aircraft statistics — no collectd, no I/O.

These functions are lifted verbatim (logic-identical) from lib/dump1090.py so the
Telegraf collector produces numbers identical to the legacy collectd pipeline.
During the migration both copies coexist; Phase D consolidates them into this one.
"""

import math


def greatcircle(lat0, lon0, lat1, lon1):
    lat0 = lat0 * math.pi / 180.0
    lon0 = lon0 * math.pi / 180.0
    lat1 = lat1 * math.pi / 180.0
    lon1 = lon1 * math.pi / 180.0
    return 6371e3 * math.acos(
        math.sin(lat0) * math.sin(lat1)
        + math.cos(lat0) * math.cos(lat1) * math.cos(abs(lon0 - lon1))
    )


def perc(p, values):
    l = len(values)
    x = p * (l - 1)
    d = x - int(x)
    x = int(x)
    if x + 1 < l:
        res = values[x] + d * (values[x + 1] - values[x])
    else:
        res = values[x]
    return res


def _quartile_dict(values):
    return {
        'min':    values[0],
        'q1':     perc(0.25, values),
        'median': perc(0.50, values),
        'q3':     perc(0.75, values),
        'max':    values[-1],
    }


def compute_aircraft_stats(aircraft, rlat, rlon, mode='1090'):
    total = 0
    with_pos = 0
    mlat = 0
    tisb = 0
    gps = 0
    ranges = []
    signals = []

    for a in aircraft:
        if a['seen'] < 60:
            total += 1
        if 'seen_pos' in a and a['seen_pos'] < 60:
            with_pos += 1
            if rlat is not None:
                distance = greatcircle(rlat, rlon, a['lat'], a['lon'])
            else:
                distance = 0

            if 'lat' in a.get('mlat', ()):
                mlat += 1
            elif 'lat' in a.get('tisb', ()):
                tisb += 1
            else:
                gps += 1
                if mode == '978':
                    if distance < 350 * 1852:
                        ranges.append(distance)
                else:
                    if a.get('type') in ('adsb_icao', 'adsr_icao', None):
                        ranges.append(distance)

        if ('rssi' in a and a['messages'] > (2 if mode == '978' else 4)
                and a['seen'] < 60
                and a['rssi'] > -49.4
                and not a.get('type', '').startswith('tisb')
                and not a.get('type', '').startswith('adsr')):
            rssi = a['rssi']
            if mode == '978' and rssi > 0:
                rssi = 0
            signals.append(rssi)

    ranges.sort()
    signals.sort()

    return {
        'total': total,
        'with_pos': with_pos,
        'mlat': mlat,
        'tisb': tisb,
        'gps': gps,
        'range_quartiles': _quartile_dict(ranges) if ranges else None,
        'signal_quartiles': _quartile_dict(signals) if signals else None,
    }
