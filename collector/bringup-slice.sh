#!/bin/bash
# graphs1090 migration slice — non-destructive bring-up on Debian/Ubuntu/Raspbian.
# Installs Telegraf + InfluxDB v1.x + Grafana ALONGSIDE the existing collectd/RRD
# stack (Phase A). Nothing about the old pipeline is touched or removed.
#
# Usage:  sudo bash collector/bringup-slice.sh
set -e
trap 'echo "[ERROR] line $LINENO: $BASH_COMMAND"' ERR

ipath=/usr/share/graphs1090
here="$(cd "$(dirname "$0")/.." && pwd)"

echo "== 1. APT repos (InfluxData + Grafana) =="
install -d /etc/apt/keyrings
if [ ! -f /etc/apt/keyrings/influxdata-archive.key ]; then
    wget -q https://repos.influxdata.com/influxdata-archive_compat.key -O /etc/apt/keyrings/influxdata-archive.key
    echo "deb [signed-by=/etc/apt/keyrings/influxdata-archive.key] https://repos.influxdata.com/debian stable main" \
        > /etc/apt/sources.list.d/influxdata.list
fi
if [ ! -f /etc/apt/keyrings/grafana.key ]; then
    wget -q https://apt.grafana.com/gpg.key -O /etc/apt/keyrings/grafana.key
    echo "deb [signed-by=/etc/apt/keyrings/grafana.key] https://apt.grafana.com stable main" \
        > /etc/apt/sources.list.d/grafana.list
fi
apt-get update

echo "== 2. Install packages (InfluxDB pinned to v1.x) =="
# influxdb (NOT influxdb2) is the v1 line. Pin so v2/v3 is never pulled.
apt-get install -y telegraf 'influxdb' grafana
apt-get install -y python3 || true

echo "== 3. Start InfluxDB and create database =="
systemctl enable --now influxdb
# wait for the HTTP API
for i in $(seq 1 30); do
    influx -execute 'SHOW DATABASES' >/dev/null 2>&1 && break
    sleep 1
done
influx -import -path="$here/influxdb/retention.iql" -precision=ns 2>/dev/null \
    || influx < "$here/influxdb/retention.iql"

echo "== 4. Install collector =="
install -d "$ipath"
install -m 0755 "$here/collector/adsb_telegraf.py" "$ipath/adsb_telegraf.py"
install -m 0644 "$here/collector/adsb_stats.py"    "$ipath/adsb_stats.py"
if [ ! -f "$ipath/adsb_collector.conf" ]; then
    install -m 0644 "$here/collector/adsb_collector.conf.example" "$ipath/adsb_collector.conf"
    echo "  -> wrote $ipath/adsb_collector.conf (edit 'url=' if your decoder differs)"
fi

echo "== 5. Install Telegraf config =="
install -m 0644 "$here/telegraf/telegraf.conf" /etc/telegraf/telegraf.conf
install -d /etc/telegraf/telegraf.d
install -m 0644 "$here/telegraf/telegraf.d/10-adsb.conf" /etc/telegraf/telegraf.d/10-adsb.conf
systemctl enable --now telegraf
systemctl restart telegraf

echo "== 6. Provision Grafana =="
install -d /etc/grafana/provisioning/datasources /etc/grafana/provisioning/dashboards
install -d /var/lib/grafana/dashboards/graphs1090
install -m 0644 "$here/grafana/provisioning/datasources/influxdb.yaml" /etc/grafana/provisioning/datasources/influxdb.yaml
install -m 0644 "$here/grafana/provisioning/dashboards/provider.yaml"   /etc/grafana/provisioning/dashboards/provider.yaml
install -m 0644 "$here/grafana/provisioning/dashboards/adsb.json"       /var/lib/grafana/dashboards/graphs1090/adsb.json
systemctl enable --now grafana-server
systemctl restart grafana-server

echo
echo "== Done (Phase A, non-destructive) =="
echo "Verify data is flowing:"
echo "  influx -database graphs1090 -execute 'SELECT count(\"total\") FROM adsb_aircraft'"
echo "Grafana:  http://$(hostname -I 2>/dev/null | awk '{print $1}'):3000  (admin/admin)"
echo "Dashboard: graphs1090 -> 'graphs1090 — ADS-B (slice)'"
echo "The old collectd/RRD graphs keep running unchanged."
