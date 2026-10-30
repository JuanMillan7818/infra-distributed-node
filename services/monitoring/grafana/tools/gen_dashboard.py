"""Genera el dashboard de Grafana a partir de las métricas de Glances.

Uso (desde la raíz del repo):
    python services/monitoring/grafana/tools/gen_dashboard.py \
        services/monitoring/grafana/dashboards/glances-host.json
Luego: ./manage.sh restart grafana
"""
import json, sys

DS = {"type": "prometheus", "uid": "prometheus"}
pid = 0


def nid():
    global pid
    pid += 1
    return pid


def tgt(expr, legend="", ref="A"):
    return {"datasource": DS, "expr": expr, "legendFormat": legend, "refId": ref}


def stat(title, expr, unit, x, y, w=6, h=4, thresholds=(70, 90), maxv=100):
    return {
        "id": nid(), "type": "gauge", "title": title, "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [tgt(expr)],
        "fieldConfig": {"defaults": {
            "unit": unit, "min": 0, "max": maxv, "decimals": 1,
            "thresholds": {"mode": "absolute", "steps": [
                {"color": "green", "value": None},
                {"color": "orange", "value": thresholds[0]},
                {"color": "red", "value": thresholds[1]}]}},
            "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "showThresholdMarkers": True},
    }


def ts(title, targets, unit, x, y, w=12, h=8, stack=False, maxv=None):
    d = {"unit": unit, "custom": {"fillOpacity": 15, "lineWidth": 2, "showPoints": "never",
                                  "stacking": {"mode": "normal" if stack else "none"}}}
    if maxv is not None:
        d["min"], d["max"] = 0, maxv
    return {
        "id": nid(), "type": "timeseries", "title": title, "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [tgt(e, l, chr(65 + i)) for i, (e, l) in enumerate(targets)],
        "fieldConfig": {"defaults": d, "overrides": []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"},
                    "tooltip": {"mode": "multi"}},
    }


# Glances v4 exporta una métrica por campo y el ítem va en una etiqueta:
#   glances_network_bytes_recv_rate_per_sec{interface_name="eth0"}
#   glances_diskio_read_bytes_rate_per_sec{disk_name="sda"}
#   glances_fs_percent{mnt_point="/rootfs"}
# Solo discos completos (sda, vda, xvda, nvme0n1), sin particiones ni CD-ROM.
DISKS = 'disk_name=~"(sd|vd|xvd)[a-z]+|nvme[0-9]+n[0-9]+"'


panels = [
    stat("CPU", "glances_cpu_total", "percent", 0, 0),
    stat("Memoria RAM", "glances_mem_percent", "percent", 6, 0),
    stat("Swap", "glances_memswap_percent", "percent", 12, 0),
    stat("Carga (1 min) / núcleos", "glances_load_min1 / glances_load_cpucore * 100",
         "percent", 18, 0, thresholds=(70, 100), maxv=150),

    ts("CPU por tipo (%)", [("glances_cpu_user", "user"), ("glances_cpu_system", "system"),
                            ("glances_cpu_iowait", "iowait"), ("glances_cpu_steal", "steal")],
       "percent", 0, 4, stack=True, maxv=100),
    ts("Memoria", [("glances_mem_used", "usada"), ("glances_mem_available", "disponible"),
                   ("glances_mem_total", "total")], "bytes", 12, 4),

    ts("Carga del sistema", [("glances_load_min1", "1 min"), ("glances_load_min5", "5 min"),
                             ("glances_load_min15", "15 min"), ("glances_load_cpucore", "núcleos")],
       "short", 0, 12),
    ts("Red (bytes/s)", [("glances_network_bytes_recv_rate_per_sec", "{{interface_name}} rx"),
                         ("glances_network_bytes_sent_rate_per_sec", "{{interface_name}} tx")],
       "Bps", 12, 12),

    ts("Uso de disco por montaje (%)", [("glances_fs_percent", "{{mnt_point}}")],
       "percent", 0, 20, maxv=100),
    ts("Disco E/S (bytes/s)", [(f"glances_diskio_read_bytes_rate_per_sec{{{DISKS}}}", "{{disk_name}} lectura"),
                               (f"glances_diskio_write_bytes_rate_per_sec{{{DISKS}}}", "{{disk_name}} escritura")],
       "Bps", 12, 20),

    ts("Procesos", [("glances_processcount_total", "total"), ("glances_processcount_running", "running"),
                    ("glances_processcount_sleeping", "sleeping")], "short", 0, 28),
    ts("Estado del exporter (1 = arriba)", [('up{job="glances"}', "glances")], "short", 12, 28, maxv=1),
]

dash = {
    "uid": "glances-host",
    "title": "Servidor - Métricas en tiempo real (Glances)",
    "tags": ["glances", "host", "sistema-distribuido"],
    "timezone": "browser",
    "refresh": "5s",
    "time": {"from": "now-15m", "to": "now"},
    "timepicker": {"refresh_intervals": ["5s", "10s", "30s", "1m", "5m"]},
    "schemaVersion": 39,
    "version": 1,
    "editable": True,
    "panels": panels,
}

with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(dash, f, ensure_ascii=False, indent=2)
    f.write("\n")
