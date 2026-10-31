"""Genera el flujo de Node-RED del tablero de ventas en tiempo real (Dashboard 2.0).

La web de facturación publica eventos JSON en Mosquitto (<prefijo>/<businessId>/<evento>);
este flujo se suscribe a <prefijo>/#, acumula el día en contexto persistente y alimenta el tablero.

El tablero es un solo ui-template (Vue) con su propia grilla responsive: los grupos de
Dashboard 2.0 saltan de fila en anchos intermedios y dejan huecos; aquí el layout lo deciden
container queries según el ancho real disponible.

Uso (desde la raíz del repo):
    python services/nodered/tools/gen_flows.py services/nodered/flows.json
Luego: ./manage.sh up nodered   (reconstruye la imagen con el flujo nuevo)
Vista previa sin Docker: services/nodered/tools/preview (npm start)
"""
import json, sys

TAB = "tab-ventas"
BASE = "ui-base-paxia"

# ── Lógica central: un solo nodo función mantiene el estado del día ──────────
FN_TABLERO = r"""
const TZ = 'America/Bogota';
const META = Number(env.get('META_DIARIA')) || 1000000;
const ahora = Date.now();
const hoy = new Intl.DateTimeFormat('en-CA', { timeZone: TZ }).format(new Date(ahora));
const hora = new Intl.DateTimeFormat('es-CO', {
    timeZone: TZ, hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
}).format(new Date(ahora));
const cop = (n) => '$ ' + Math.round(Number(n) || 0).toLocaleString('es-CO');
const num = (n) => Number(n) || 0;

const nuevo = () => ({
    fecha: hoy, seq: 0, ventas: 0, total: 0, cotizaciones: 0, devoluciones: 0, montoDevuelto: 0,
    abonos: 0, montoAbonos: 0, stockBajo: 0, cierres: 0, metaAlcanzada: false,
    porTipo: { contado: 0, credito: 0 }, productos: {}, serie: [], eventos: [], ultimo: null,
});

// Contexto en disco (settings.js → localfilesystem): sobrevive reinicios del contenedor.
let s = context.get('estado');
let reiniciado = false;
if (!s || !('seq' in s) || s.fecha !== hoy || msg.topic === 'reset') {
    s = nuevo();   // Día nuevo (o reinicio manual): contadores en cero
    reiniciado = true;
}
// "tick" (cada minuto) solo sirve para detectar el cambio de día sin esperar un evento.
if (msg.topic === 'tick' && !reiniciado) return null;

let aviso = null;
const registrar = (tipo, titulo, detalle, monto) => {
    s.seq++;
    s.eventos.unshift({ id: s.seq, tipo, titulo, detalle, monto, hora });
    s.eventos = s.eventos.slice(0, 20);
    s.ultimo = ahora;
};
const avisar = (tipo, titulo, mensaje) => {
    aviso = { id: `${hoy}-${s.seq}`, tipo, titulo, mensaje, at: ahora };
};

const e = (msg.payload && typeof msg.payload === 'object') ? msg.payload : {};
switch (e.evento) {
    case 'ventas/nueva': {
        if (e.tipo === 'cotizacion') {
            s.cotizaciones++;
            registrar('cotizacion', `Cotización #${e.factura}`, e.cliente || '', num(e.total));
            break;
        }
        const credito = e.tipo === 'credito';
        s.ventas++;
        s.total += num(e.total);
        s.porTipo[credito ? 'credito' : 'contado'] += num(e.total);
        for (const p of Array.isArray(e.productos) ? e.productos : []) {
            const acc = s.productos[p.nombre] || { cantidad: 0, total: 0 };
            acc.cantidad += num(p.cantidad);
            acc.total += num(p.total);
            s.productos[p.nombre] = acc;
        }
        s.serie.push({ x: ahora, y: s.total });
        s.serie = s.serie.slice(-500);
        registrar(credito ? 'credito' : 'venta', `Venta ${credito ? 'a crédito' : 'de contado'} #${e.factura}`,
            `${e.cliente || 'Cliente'} · ${num(e.unidades)} und`, num(e.total));
        if (!s.metaAlcanzada && s.total >= META) {
            s.metaAlcanzada = true;
            registrar('meta', 'Meta diaria alcanzada', `Meta de ${cop(META)}`, null);
            avisar('meta', '¡Meta del día alcanzada!', `Ya se vendieron ${cop(s.total)} hoy.`);
        }
        break;
    }
    case 'ventas/devolucion':
        s.devoluciones++;
        s.montoDevuelto += num(e.monto);
        registrar('devolucion', `Devolución · factura #${e.factura}`, e.nota || e.cliente || '', -num(e.monto));
        avisar('devolucion', 'Devolución registrada',
            `${cop(e.monto)} en la factura #${e.factura}${e.nota ? ' · ' + e.nota : ''}`);
        break;
    case 'inventario/stock-bajo':
        s.stockBajo++;
        registrar('stock', 'Stock bajo', `${e.producto} · quedan ${num(e.stock)} (mín. ${num(e.minimo)})`, null);
        avisar('stock', 'Stock bajo', `${e.producto}: quedan ${num(e.stock)} unidades (mínimo ${num(e.minimo)}).`);
        break;
    case 'caja/cierre': {
        s.cierres++;
        const dif = num(e.diferencia);
        const estado = dif === 0 ? 'caja cuadrada' : `${dif > 0 ? 'sobrante' : 'faltante'} de ${cop(Math.abs(dif))}`;
        registrar('cierre', 'Cierre de caja', `${e.usuario || ''} · ${estado}`, num(e.contado));
        avisar('cierre', 'Cierre de caja', `Contado ${cop(e.contado)} · ${estado}.`);
        break;
    }
    case 'creditos/abono':
        s.abonos++;
        s.montoAbonos += num(e.monto);
        registrar('abono', 'Abono a crédito', e.cliente || '', num(e.monto));
        break;
    default:
        if (!['restore', 'broker', 'reset', 'tick'].includes(msg.topic)) {
            node.warn(`Evento desconocido en ${msg.topic}`);
            return null;
        }
}
context.set('estado', s);

const top = Object.entries(s.productos)
    .map(([nombre, p]) => ({ nombre, cantidad: p.cantidad, total: p.total }))
    .sort((a, b) => b.total - a.total)
    .slice(0, 5);

return {
    payload: {
        broker: flow.get('broker') === true,
        meta: META, pct: (s.total / META) * 100,
        ventas: s.ventas, total: s.total, neto: s.total - s.montoDevuelto,
        ticket: s.ventas ? s.total / s.ventas : 0, cotizaciones: s.cotizaciones,
        devoluciones: s.devoluciones, montoDevuelto: s.montoDevuelto,
        abonos: s.abonos, montoAbonos: s.montoAbonos, stockBajo: s.stockBajo, cierres: s.cierres,
        porTipo: s.porTipo, serie: s.serie, eventos: s.eventos.slice(0, 12), top,
        ultimo: s.ultimo, aviso,
    },
};
""".strip()

FN_BROKER = r"""
// Estado de la conexión del nodo "mqtt in" → indicador del tablero.
flow.set('broker', msg.status && msg.status.fill === 'green');
return { topic: 'broker' };
""".strip()

# ── Tablero completo (Vue, Dashboard 2.0) ────────────────────────────────────
TABLERO = r"""
<template>
  <div class="paxia-ops">
    <header class="px-top">
      <div class="px-brand">
        <div class="px-logo">P</div>
        <div>
          <div class="px-title">Centro de operaciones</div>
          <div class="px-subtitle">PAXIA · ventas en tiempo real vía MQTT</div>
        </div>
      </div>
      <div class="px-status">
        <span class="px-live" :class="d.broker ? 'on' : 'off'"><i></i>{{ d.broker ? 'EN VIVO' : 'SIN CONEXIÓN' }}</span>
        <span class="px-chip">Último evento <b>{{ hace(d.ultimo) }}</b></span>
        <span class="px-clock">{{ reloj }}</span>
      </div>
    </header>

    <section class="px-kpis">
      <article v-for="k in kpis" :key="k.key" class="px-card px-kpi" :style="{ '--c': k.color }">
        <div class="px-kpi-head"><span class="px-ico" v-html="icons[k.icon]"></span>{{ k.label }}</div>
        <div class="px-kpi-value">{{ k.value }}</div>
        <div class="px-kpi-sub">{{ k.sub }}</div>
      </article>
    </section>

    <section class="px-grid">
      <article class="px-card px-chart">
        <div class="px-card-head">
          <h3>Ventas acumuladas hoy</h3>
          <span class="px-muted">{{ plural(d.ventas, 'venta', 'ventas') }} · ritmo {{ ritmo }}</span>
        </div>
        <div class="px-plot">
          <div class="px-ylabels"><span v-for="t in chart.ticks" :key="t.v" :style="{ top: t.pct + '%' }">{{ copCorto(t.v) }}</span></div>
          <div class="px-canvas">
            <svg viewBox="0 0 1000 300" preserveAspectRatio="none">
              <defs>
                <linearGradient id="pxArea" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stop-color="#3b8cff" stop-opacity="0.45" />
                  <stop offset="1" stop-color="#3b8cff" stop-opacity="0" />
                </linearGradient>
              </defs>
              <line v-for="t in chart.ticks" :key="'g' + t.v" x1="0" x2="1000" :y1="t.y" :y2="t.y" class="px-gridline" />
              <line x1="0" x2="1000" :y1="chart.goalY" :y2="chart.goalY" class="px-goal" />
              <path v-if="chart.area" :d="chart.area" fill="url(#pxArea)" />
              <path v-if="chart.line" :d="chart.line" class="px-line" />
            </svg>
            <span class="px-goal-label" :style="{ top: chart.goalPct + '%' }">Meta {{ copCorto(d.meta) }}</span>
            <span v-if="chart.line" class="px-dot" :style="{ top: chart.lastPct + '%' }"></span>
            <div v-if="!chart.line" class="px-empty">Esperando la primera venta del día…</div>
          </div>
        </div>
        <div class="px-xlabels"><span v-for="(l, i) in chart.xlabels" :key="i">{{ l }}</span></div>
      </article>

      <article class="px-card px-meta">
        <div class="px-card-head"><h3>Meta diaria</h3><span class="px-muted">{{ cop(d.meta) }}</span></div>
        <div class="px-ring" :class="{ done: (d.pct || 0) >= 100 }">
          <svg viewBox="0 0 120 120">
            <defs>
              <linearGradient id="pxRing" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stop-color="#3b8cff" /><stop offset="1" stop-color="#22d3ee" />
              </linearGradient>
              <linearGradient id="pxRingDone" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stop-color="#22c55e" /><stop offset="1" stop-color="#facc15" />
              </linearGradient>
            </defs>
            <circle cx="60" cy="60" r="52" class="px-ring-track" />
            <circle cx="60" cy="60" r="52" class="px-ring-prog" :stroke-dasharray="ring" />
          </svg>
          <div class="px-ring-center">
            <b>{{ Math.round(vis.pct || 0) }}%</b>
            <span>{{ cop(vis.total) }}</span>
          </div>
        </div>
        <div class="px-faltan">{{ faltan }}</div>
        <div class="px-split">
          <div class="px-split-bar">
            <i class="contado" :style="{ width: split.contado + '%' }"></i>
            <i class="credito" :style="{ width: split.credito + '%' }"></i>
          </div>
          <div class="px-split-legend">
            <span><i class="contado"></i>Contado <b>{{ split.contado }}%</b></span>
            <span><i class="credito"></i>Crédito <b>{{ split.credito }}%</b></span>
          </div>
        </div>
      </article>

      <article class="px-card px-feed">
        <div class="px-card-head"><h3>Actividad en vivo</h3><span class="px-muted">{{ (d.eventos || []).length ? 'últimos ' + d.eventos.length : '' }}</span></div>
        <transition-group name="px-feed" tag="ul" class="px-feed-list">
          <li v-for="e in (d.eventos || [])" :key="e.id" :style="{ '--c': color(e.tipo) }">
            <span class="px-ev-ico" v-html="icons[iconFor(e.tipo)]"></span>
            <div class="px-ev-body">
              <div class="px-ev-title">{{ e.titulo }}</div>
              <div class="px-ev-detail">{{ e.detalle }}</div>
            </div>
            <div class="px-ev-side">
              <div v-if="e.monto !== null" class="px-ev-monto" :class="{ neg: e.monto < 0 }">{{ cop(e.monto) }}</div>
              <div class="px-ev-time">{{ e.hora }}</div>
            </div>
          </li>
        </transition-group>
        <div v-if="!(d.eventos || []).length" class="px-empty static">Sin actividad todavía.</div>
      </article>

      <article class="px-card px-top-card">
        <div class="px-card-head"><h3>Productos más vendidos</h3><span class="px-muted">por monto</span></div>
        <ol class="px-top-list">
          <li v-for="(p, i) in (d.top || [])" :key="p.nombre">
            <span class="px-rank">{{ i + 1 }}</span>
            <div class="px-top-body">
              <div class="px-top-row"><span class="px-top-name">{{ p.nombre }}</span><b>{{ cop(p.total) }}</b></div>
              <div class="px-top-bar"><i :style="{ width: (p.total / topMax * 100) + '%' }"></i></div>
              <div class="px-top-qty">{{ plural(p.cantidad, 'unidad', 'unidades') }}</div>
            </div>
          </li>
        </ol>
        <div v-if="!(d.top || []).length" class="px-empty static">Aún no hay ventas.</div>
      </article>
    </section>

    <div class="px-toasts">
      <transition-group name="px-toast">
        <div v-for="t in toasts" :key="t.id" class="px-toast" :style="{ '--c': color(t.tipo) }">
          <span class="px-toast-ico" v-html="icons[iconFor(t.tipo)]"></span>
          <div class="px-toast-body"><b>{{ t.titulo }}</b><p>{{ t.mensaje }}</p></div>
          <button class="px-toast-close" @click="cerrar(t.id)" aria-label="Cerrar">×</button>
          <i class="px-toast-bar"></i>
        </div>
      </transition-group>
    </div>
  </div>
</template>

<script>
// Dashboard 2.0 exige que el script sea SOLO "export default {...}" y evalúa cada propiedad por
// separado: no hay constantes de módulo, así que todo lo compartido vive en data().
export default {
  data () {
    const svg = (body) => '<svg viewBox="0 0 24 24">' + body + '</svg>'
    return {
      now: Date.now(),
      vis: {},
      toasts: [],
      seen: {},
      tz: 'America/Bogota',
      toastMs: 6500,
      animated: ['ventas', 'total', 'neto', 'ticket', 'devoluciones', 'montoDevuelto', 'abonos', 'montoAbonos', 'stockBajo', 'cierres', 'cotizaciones', 'pct'],
      colors: {
        venta: '#22c55e', credito: '#3b8cff', cotizacion: '#94a3b8', devolucion: '#f43f5e',
        stock: '#f59e0b', cierre: '#a78bfa', abono: '#22d3ee', meta: '#facc15'
      },
      iconOf: { venta: 'cart', credito: 'card', cotizacion: 'file', devolucion: 'undo', stock: 'alert', cierre: 'box', abono: 'money', meta: 'target' },
      icons: {
        cart: svg('<circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.7 13.4a2 2 0 0 0 2 1.6h9.7a2 2 0 0 0 2-1.6L23 6H6"/>'),
        money: svg('<path d="M12 1v22M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>'),
        trend: svg('<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>'),
        undo: svg('<polyline points="1 4 1 10 7 10"/><path d="M3.5 15a9 9 0 1 0 2.1-9.4L1 10"/>'),
        card: svg('<rect x="1" y="4" width="22" height="16" rx="2"/><line x1="1" y1="10" x2="23" y2="10"/>'),
        alert: svg('<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h16.9a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>'),
        file: svg('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>'),
        box: svg('<polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/>'),
        target: svg('<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>')
      }
    }
  },
  computed: {
    d () { return (this.msg && this.msg.payload) || {} },
    reloj () {
      return new Intl.DateTimeFormat('es-CO', { timeZone: this.tz, hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(new Date(this.now))
    },
    kpis () {
      const v = this.vis
      const d = this.d
      return [
        { key: 'ventas', label: 'Ventas hoy', icon: 'cart', color: '#3b8cff', value: this.fmtInt(v.ventas), sub: this.plural(d.cotizaciones, 'cotización', 'cotizaciones') },
        { key: 'total', label: 'Total vendido', icon: 'money', color: '#22c55e', value: this.cop(v.total), sub: `Neto ${this.cop(v.neto)}` },
        { key: 'ticket', label: 'Ticket promedio', icon: 'trend', color: '#22d3ee', value: this.cop(v.ticket), sub: 'por venta' },
        { key: 'dev', label: 'Devoluciones', icon: 'undo', color: '#f43f5e', value: this.fmtInt(v.devoluciones), sub: this.cop(v.montoDevuelto) },
        { key: 'abonos', label: 'Abonos a crédito', icon: 'card', color: '#a78bfa', value: this.cop(v.montoAbonos), sub: this.plural(d.abonos, 'abono', 'abonos') },
        { key: 'stock', label: 'Alertas de stock', icon: 'alert', color: '#f59e0b', value: this.fmtInt(v.stockBajo), sub: this.plural(d.cierres, 'cierre de caja', 'cierres de caja') }
      ]
    },
    chart () {
      const W = 1000
      const H = 300
      const pts = this.d.serie || []
      const meta = this.d.meta || 1
      const total = pts.length ? pts[pts.length - 1].y : 0
      // Escala con escalones redondos (1, 2, 2.5 o 5 × 10^n) que cubre meta y total.
      const raw = Math.max(meta, total) * 1.1 / 4
      const mag = Math.pow(10, Math.floor(Math.log10(raw || 1)))
      const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((v) => v >= raw)
      const maxY = step * 4
      const end = Math.max(this.now, pts.length ? pts[pts.length - 1].x : 0)
      // Ventana ajustada a los datos: desde poco antes de la primera venta (mínimo 10 min).
      const span = Math.max(pts.length ? (end - pts[0].x) * 1.08 : 0, 10 * 60e3)
      const start = end - span
      const sx = (x) => ((x - start) / span) * W
      const sy = (y) => H - (y / maxY) * H
      let line = ''
      if (pts.length) {
        line = `M 0 ${H}`
        for (const p of pts) line += ` H ${sx(p.x).toFixed(1)} V ${sy(p.y).toFixed(1)}`
        line += ` H ${W}`
      }
      const ticks = [0, 1, 2, 3, 4].map((i) => {
        const v = step * i
        return { v, y: sy(v), pct: (sy(v) / H) * 100 }
      })
      const fmt = new Intl.DateTimeFormat('es-CO', { timeZone: this.tz, hour: '2-digit', minute: '2-digit', hour12: false })
      const xlabels = [0, 1, 2, 3, 4].map((i) => fmt.format(new Date(start + (span * i) / 4)))
      return {
        line,
        area: line ? `${line} V ${H} H 0 Z` : '',
        ticks,
        xlabels,
        goalY: sy(meta),
        goalPct: (sy(meta) / H) * 100,
        lastPct: (sy(total) / H) * 100
      }
    },
    ring () {
      const c = 2 * Math.PI * 52
      return `${(c * Math.min(this.vis.pct || 0, 100)) / 100} ${c}`
    },
    faltan () {
      const d = this.d
      if (!d.meta) return ''
      return d.total >= d.meta ? '🎯 ¡Meta del día superada!' : `Faltan ${this.cop(d.meta - (d.total || 0))} para la meta`
    },
    ritmo () {
      const pts = this.d.serie || []
      if (!pts.length) return '—'
      const horas = Math.max((this.now - pts[0].x) / 3600e3, 0.25)
      return `${this.copCorto(this.d.total / horas)}/h`
    },
    split () {
      const t = this.d.porTipo || {}
      const sum = (t.contado || 0) + (t.credito || 0)
      if (!sum) return { contado: 0, credito: 0 }
      const contado = Math.round((t.contado / sum) * 100)
      return { contado, credito: 100 - contado }
    },
    topMax () {
      const top = this.d.top || []
      return top.length ? top[0].total || 1 : 1
    }
  },
  watch: {
    msg (m) { this.onMsg(m) }
  },
  mounted () {
    this.clock = setInterval(() => { this.now = Date.now() }, 1000)
    this.onMsg(this.msg)
  },
  unmounted () {
    clearInterval(this.clock)
    cancelAnimationFrame(this.raf)
  },
  methods: {
    onMsg (m) {
      const p = m && m.payload
      if (!p) return
      this.animate(p)
      const a = p.aviso
      // El último mensaje se reenvía al recargar la página: solo se muestran avisos recientes.
      if (a && !this.seen[a.id] && Date.now() - a.at < 15000) {
        this.seen[a.id] = true
        this.toasts.push({ ...a })
        this.toasts = this.toasts.slice(-3)
        setTimeout(() => this.cerrar(a.id), this.toastMs)
      }
    },
    animate (p) {
      const from = { ...this.vis }
      const t0 = performance.now()
      cancelAnimationFrame(this.raf)
      const step = (t) => {
        const k = Math.min(1, (t - t0) / 700)
        const e = 1 - Math.pow(1 - k, 3)
        const v = {}
        for (const key of this.animated) {
          const a = Number(from[key]) || 0
          const b = Number(p[key]) || 0
          v[key] = a + (b - a) * e
        }
        this.vis = v
        if (k < 1) this.raf = requestAnimationFrame(step)
      }
      this.raf = requestAnimationFrame(step)
    },
    cerrar (id) { this.toasts = this.toasts.filter((t) => t.id !== id) },
    color (tipo) { return this.colors[tipo] || '#94a3b8' },
    iconFor (tipo) { return this.iconOf[tipo] || 'file' },
    plural (n, uno, varios) {
      const v = Math.round(Number(n) || 0)
      return `${v.toLocaleString('es-CO')} ${v === 1 ? uno : varios}`
    },
    fmtInt (n) { return Math.round(Number(n) || 0).toLocaleString('es-CO') },
    cop (n) {
      return new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 }).format(Number(n) || 0)
    },
    copCorto (n) {
      return new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', notation: 'compact', maximumFractionDigits: 1 }).format(Number(n) || 0)
    },
    hace (ts) {
      if (!ts) return '—'
      const s = Math.max(0, Math.round((this.now - ts) / 1000))
      if (s < 60) return `hace ${s} s`
      if (s < 3600) return `hace ${Math.floor(s / 60)} min`
      return `hace ${Math.floor(s / 3600)} h`
    }
  }
}
</script>

<style>
/* Sin "scoped": los íconos entran por v-html y no recibirían el atributo de scope.
   Todo va bajo .paxia-ops para no tocar el resto del dashboard. */
.paxia-ops {
  --bg: #071530; --card: #0c1f45; --card2: #0f2752; --line: rgba(148, 178, 230, .12);
  --text: #e8eefa; --muted: #8ea3c4; --brand: #3b8cff;
  container-type: inline-size;
  color: var(--text);
  font-family: Inter, 'Segoe UI', system-ui, -apple-system, sans-serif;
  font-variant-numeric: tabular-nums;
  width: 100%;
}
.paxia-ops * { box-sizing: border-box; }
.paxia-ops h3 { margin: 0; font-size: 15px; font-weight: 600; letter-spacing: .01em; }
.paxia-ops svg { display: block; }
.paxia-ops .px-ico svg, .paxia-ops .px-ev-ico svg, .paxia-ops .px-toast-ico svg {
  width: 100%; height: 100%; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round;
}
.paxia-ops .px-muted { color: var(--muted); font-size: 13px; }

/* Encabezado */
.paxia-ops .px-top { display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap; margin-bottom: 18px; }
.paxia-ops .px-brand { display: flex; align-items: center; gap: 14px; }
.paxia-ops .px-logo {
  width: 44px; height: 44px; border-radius: 12px; display: grid; place-items: center;
  font-weight: 800; font-size: 22px; color: #fff;
  background: linear-gradient(135deg, #0370fb, #22d3ee); box-shadow: 0 8px 24px rgba(3, 112, 251, .35);
}
.paxia-ops .px-title { font-size: 22px; font-weight: 700; letter-spacing: -.01em; }
.paxia-ops .px-subtitle { color: var(--muted); font-size: 13px; }
.paxia-ops .px-status { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.paxia-ops .px-live, .paxia-ops .px-chip, .paxia-ops .px-clock {
  border: 1px solid var(--line); background: var(--card); border-radius: 999px; padding: 7px 14px; font-size: 13px;
}
.paxia-ops .px-live { display: inline-flex; align-items: center; gap: 8px; font-weight: 700; letter-spacing: .08em; }
.paxia-ops .px-live i { width: 9px; height: 9px; border-radius: 50%; background: currentColor; }
.paxia-ops .px-live.on { color: #4ade80; border-color: rgba(74, 222, 128, .35); }
.paxia-ops .px-live.on i { animation: px-pulse 1.6s infinite; }
.paxia-ops .px-live.off { color: #fb7185; border-color: rgba(251, 113, 133, .4); }
.paxia-ops .px-chip { color: var(--muted); }
.paxia-ops .px-chip b { color: var(--text); font-weight: 600; }
.paxia-ops .px-clock { font-weight: 600; min-width: 92px; text-align: center; }

/* Tarjetas */
.paxia-ops .px-card {
  background: linear-gradient(180deg, var(--card2), var(--card)); border: 1px solid var(--line);
  border-radius: 16px; padding: 18px; min-width: 0;
}
.paxia-ops .px-card-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; margin-bottom: 14px; }

/* KPIs */
.paxia-ops .px-kpis { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 14px; margin-bottom: 14px; }
.paxia-ops .px-kpi { position: relative; overflow: hidden; }
.paxia-ops .px-kpi::before {
  content: ''; position: absolute; inset: 0 auto 0 0; width: 3px; background: var(--c); box-shadow: 0 0 18px var(--c);
}
.paxia-ops .px-kpi::after {
  content: ''; position: absolute; right: -40px; top: -40px; width: 120px; height: 120px; border-radius: 50%;
  background: radial-gradient(circle, color-mix(in srgb, var(--c) 22%, transparent), transparent 70%);
}
.paxia-ops .px-kpi-head { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 12.5px; text-transform: uppercase; letter-spacing: .06em; }
.paxia-ops .px-kpi-head .px-ico { width: 26px; height: 26px; padding: 5px; border-radius: 8px; color: var(--c); background: color-mix(in srgb, var(--c) 16%, transparent); }
.paxia-ops .px-kpi-value { font-size: 26px; font-weight: 700; margin: 10px 0 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.paxia-ops .px-kpi-sub { color: var(--muted); font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* Grilla principal: 12 columnas, cada fila suma 12 en todos los anchos (sin huecos) */
.paxia-ops .px-grid {
  display: grid; gap: 14px; grid-template-columns: repeat(12, minmax(0, 1fr));
  grid-template-areas:
    "chart chart chart chart chart chart chart chart meta meta meta meta"
    "feed feed feed feed feed feed feed top top top top top";
}
.paxia-ops .px-chart { grid-area: chart; }
.paxia-ops .px-meta { grid-area: meta; }
.paxia-ops .px-feed { grid-area: feed; }
.paxia-ops .px-top-card { grid-area: top; }

/* Gráfica de área */
/* Fila fija: sin esto el SVG crece por su proporción (1000×300) en pantallas anchas y se sale de la tarjeta. */
.paxia-ops .px-plot { display: grid; grid-template-columns: 64px 1fr; grid-template-rows: minmax(0, 1fr); height: 260px; }
.paxia-ops .px-ylabels { position: relative; }
.paxia-ops .px-ylabels span { position: absolute; right: 10px; transform: translateY(-50%); font-size: 11.5px; color: var(--muted); white-space: nowrap; }
.paxia-ops .px-canvas { position: relative; min-height: 0; }
.paxia-ops .px-canvas svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
.paxia-ops .px-gridline { stroke: var(--line); stroke-width: 1; vector-effect: non-scaling-stroke; }
.paxia-ops .px-goal { stroke: #facc15; stroke-width: 1.5; stroke-dasharray: 6 6; vector-effect: non-scaling-stroke; opacity: .8; }
.paxia-ops .px-line { fill: none; stroke: #3b8cff; stroke-width: 2.5; vector-effect: non-scaling-stroke; filter: drop-shadow(0 0 6px rgba(59, 140, 255, .6)); }
.paxia-ops .px-goal-label {
  position: absolute; left: 8px; transform: translateY(-120%); font-size: 11.5px; font-weight: 600; color: #facc15;
}
.paxia-ops .px-dot {
  position: absolute; right: 0; width: 12px; height: 12px; border-radius: 50%; background: #3b8cff;
  transform: translate(50%, -50%); box-shadow: 0 0 0 4px rgba(59, 140, 255, .25); animation: px-pulse 1.6s infinite;
}
.paxia-ops .px-xlabels { display: flex; justify-content: space-between; margin: 8px 0 0 64px; font-size: 11.5px; color: var(--muted); }
.paxia-ops .px-empty { position: absolute; inset: 0; display: grid; place-items: center; color: var(--muted); font-size: 14px; }
.paxia-ops .px-empty.static { position: static; padding: 24px 0; text-align: center; }

/* Meta */
.paxia-ops .px-meta { display: flex; flex-direction: column; }
.paxia-ops .px-ring { position: relative; width: min(100%, 210px); aspect-ratio: 1; margin: 4px auto 10px; }
.paxia-ops .px-ring svg { width: 100%; height: 100%; transform: rotate(-90deg); }
.paxia-ops .px-ring-track { fill: none; stroke: rgba(148, 178, 230, .12); stroke-width: 11; }
.paxia-ops .px-ring-prog {
  fill: none; stroke: url(#pxRing); stroke-width: 11; stroke-linecap: round;
  transition: stroke-dasharray .7s cubic-bezier(.2, .8, .2, 1); filter: drop-shadow(0 0 8px rgba(34, 211, 238, .45));
}
.paxia-ops .px-ring.done .px-ring-prog { stroke: url(#pxRingDone); filter: drop-shadow(0 0 10px rgba(250, 204, 21, .5)); }
.paxia-ops .px-ring-center { position: absolute; inset: 0; display: grid; place-content: center; text-align: center; }
.paxia-ops .px-ring-center b { font-size: 38px; font-weight: 800; line-height: 1; }
.paxia-ops .px-ring-center span { color: var(--muted); font-size: 13px; margin-top: 6px; }
.paxia-ops .px-faltan { text-align: center; color: var(--muted); font-size: 13px; margin-bottom: 16px; }
.paxia-ops .px-split { margin-top: auto; }
.paxia-ops .px-split-bar { display: flex; height: 10px; border-radius: 999px; overflow: hidden; background: rgba(148, 178, 230, .12); }
.paxia-ops .px-split-bar i { transition: width .7s ease; }
.paxia-ops i.contado { background: #22c55e; }
.paxia-ops i.credito { background: #3b8cff; }
.paxia-ops .px-split-legend { display: flex; justify-content: space-between; margin-top: 10px; font-size: 13px; color: var(--muted); }
.paxia-ops .px-split-legend i { display: inline-block; width: 9px; height: 9px; border-radius: 3px; margin-right: 6px; }
.paxia-ops .px-split-legend b { color: var(--text); margin-left: 4px; }

/* Actividad */
.paxia-ops .px-feed-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; max-height: 452px; overflow: hidden; }
.paxia-ops .px-feed-list li {
  display: grid; grid-template-columns: 36px 1fr auto; align-items: center; gap: 12px;
  padding: 10px 12px; border-radius: 12px; background: rgba(148, 178, 230, .05); border: 1px solid transparent;
}
.paxia-ops .px-feed-list li:first-child { border-color: color-mix(in srgb, var(--c) 40%, transparent); background: color-mix(in srgb, var(--c) 8%, transparent); }
.paxia-ops .px-ev-ico { width: 36px; height: 36px; padding: 8px; border-radius: 10px; color: var(--c); background: color-mix(in srgb, var(--c) 16%, transparent); }
.paxia-ops .px-ev-body { min-width: 0; }
.paxia-ops .px-ev-title { font-weight: 600; font-size: 14px; }
.paxia-ops .px-ev-detail { color: var(--muted); font-size: 12.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.paxia-ops .px-ev-side { text-align: right; }
.paxia-ops .px-ev-monto { font-weight: 700; font-size: 14px; }
.paxia-ops .px-ev-monto.neg { color: #fb7185; }
.paxia-ops .px-ev-time { color: var(--muted); font-size: 12px; }
.px-feed-enter-active { transition: all .5s cubic-bezier(.2, .8, .2, 1); }
.px-feed-enter-from { opacity: 0; transform: translateY(-14px) scale(.98); }
.px-feed-move { transition: transform .5s ease; }
.px-feed-leave-active { display: none; }

/* Top productos */
.paxia-ops .px-top-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 14px; }
.paxia-ops .px-top-list li { display: grid; grid-template-columns: 28px 1fr; gap: 12px; align-items: start; }
.paxia-ops .px-rank {
  width: 28px; height: 28px; border-radius: 8px; display: grid; place-items: center; font-weight: 700; font-size: 13px;
  background: rgba(59, 140, 255, .15); color: #8bbcff;
}
.paxia-ops .px-top-list li:first-child .px-rank { background: linear-gradient(135deg, #facc15, #f59e0b); color: #1a1300; }
.paxia-ops .px-top-row { display: flex; justify-content: space-between; gap: 10px; font-size: 14px; }
.paxia-ops .px-top-name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.paxia-ops .px-top-bar { height: 6px; border-radius: 999px; background: rgba(148, 178, 230, .12); margin: 7px 0 4px; overflow: hidden; }
.paxia-ops .px-top-bar i { display: block; height: 100%; border-radius: 999px; background: linear-gradient(90deg, #0370fb, #22d3ee); transition: width .7s ease; }
.paxia-ops .px-top-qty { color: var(--muted); font-size: 12px; }

/* Avisos */
.paxia-ops .px-toasts { position: fixed; bottom: 20px; right: 20px; z-index: 2000; display: flex; flex-direction: column; gap: 10px; width: min(380px, calc(100vw - 40px)); }
.paxia-ops .px-toast {
  position: relative; overflow: hidden; display: grid; grid-template-columns: 40px 1fr 24px; gap: 12px; align-items: start;
  padding: 14px 14px 16px; border-radius: 14px; color: var(--text);
  background: rgba(12, 31, 69, .92); backdrop-filter: blur(12px);
  border: 1px solid color-mix(in srgb, var(--c) 45%, transparent);
  box-shadow: 0 18px 40px rgba(0, 0, 0, .45), 0 0 24px color-mix(in srgb, var(--c) 25%, transparent);
}
.paxia-ops .px-toast-ico { width: 40px; height: 40px; padding: 9px; border-radius: 12px; color: var(--c); background: color-mix(in srgb, var(--c) 18%, transparent); }
.paxia-ops .px-toast-body b { font-size: 14.5px; }
.paxia-ops .px-toast-body p { margin: 3px 0 0; color: var(--muted); font-size: 13px; line-height: 1.4; }
.paxia-ops .px-toast-close { background: none; border: 0; color: var(--muted); font-size: 20px; line-height: 1; cursor: pointer; padding: 0; }
.paxia-ops .px-toast-close:hover { color: var(--text); }
.paxia-ops .px-toast-bar { position: absolute; left: 0; bottom: 0; height: 3px; width: 100%; background: var(--c); transform-origin: left; animation: px-toastbar 6.5s linear forwards; }
.px-toast-enter-active { transition: all .45s cubic-bezier(.2, .9, .2, 1.2); }
.px-toast-leave-active { transition: all .3s ease; }
.px-toast-enter-from { opacity: 0; transform: translateY(30px) scale(.96); }
.px-toast-leave-to { opacity: 0; transform: translateX(60px); }
.px-toast-move { transition: transform .35s ease; }

@keyframes px-pulse { 0% { box-shadow: 0 0 0 0 rgba(74, 222, 128, .55); } 70% { box-shadow: 0 0 0 10px rgba(74, 222, 128, 0); } 100% { box-shadow: 0 0 0 0 rgba(74, 222, 128, 0); } }
@keyframes px-toastbar { from { transform: scaleX(1); } to { transform: scaleX(0); } }

/* Responsive según el ancho REAL del tablero (container queries) */
@container (max-width: 1180px) {
  .paxia-ops .px-kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .paxia-ops .px-grid {
    grid-template-areas:
      "chart chart chart chart chart chart chart chart chart chart chart chart"
      "meta meta meta meta meta meta top top top top top top"
      "feed feed feed feed feed feed feed feed feed feed feed feed";
  }
}
@container (max-width: 640px) {
  .paxia-ops .px-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .paxia-ops .px-kpi-value { font-size: 21px; }
  .paxia-ops .px-grid { grid-template-columns: minmax(0, 1fr); grid-template-areas: "chart" "meta" "top" "feed"; }
  .paxia-ops .px-plot { height: 200px; grid-template-columns: 52px 1fr; }
  .paxia-ops .px-xlabels { margin-left: 52px; }
  .paxia-ops .px-title { font-size: 18px; }
}
</style>
""".strip()


flows = [
    {"id": TAB, "type": "tab", "label": "Tablero de ventas",
     "info": "Eventos MQTT de la web de facturación → tablero en tiempo real (/dashboard).\n"
             "Generado por tools/gen_flows.py: los cambios del editor se pierden al recrear el contenedor."},

    # ── Configuración: broker, dashboard, tema, página y grupo ──
    {"id": "broker-mosquitto", "type": "mqtt-broker", "name": "Mosquitto (red-interna)",
     "broker": "mosquitto", "port": "1883", "clientid": "nodered-tablero", "autoConnect": True,
     "usetls": False, "protocolVersion": 4, "keepalive": 60, "cleansession": True, "autoUnsubscribe": True,
     "birthTopic": "", "birthQos": "0", "birthRetain": "false", "birthPayload": "", "birthMsg": {},
     "closeTopic": "", "closeQos": "0", "closeRetain": "false", "closePayload": "", "closeMsg": {},
     "willTopic": "", "willQos": "0", "willRetain": "false", "willPayload": "", "willMsg": {},
     "userProps": "", "sessionExpiry": ""},
    {"id": BASE, "type": "ui-base", "name": "PAXIA · Centro de operaciones", "path": "/dashboard",
     "appIcon": "", "includeClientData": True, "acceptsClientConfig": ["ui-notification", "ui-control"],
     "showPathInSidebar": False, "headerContent": "page", "navigationStyle": "none",
     "titleBarStyle": "hidden", "showReconnectNotification": True, "notificationDisplayTime": 1,
     "showDisconnectNotification": True, "allowInstall": False},
    # Página y grupo del mismo color que el tablero: el template dibuja sus propias tarjetas.
    {"id": "ui-theme-paxia", "type": "ui-theme", "name": "PAXIA oscuro",
     "colors": {"surface": "#071530", "primary": "#3b8cff", "bgPage": "#071530",
                "groupBg": "#071530", "groupOutline": "#071530"},
     "sizes": {"density": "default", "pagePadding": "20px", "groupGap": "0px",
               "groupBorderRadius": "0px", "widgetGap": "0px"}},
    {"id": "ui-page-ventas", "type": "ui-page", "name": "Centro de operaciones", "ui": BASE,
     "path": "/ventas", "icon": "chart-line", "layout": "grid", "theme": "ui-theme-paxia",
     "breakpoints": [{"name": "Default", "px": 0, "cols": 3}, {"name": "Tablet", "px": 576, "cols": 6},
                     {"name": "Small Desktop", "px": 768, "cols": 9}, {"name": "Desktop", "px": 1024, "cols": 12}],
     "order": 1, "className": "", "visible": "true", "disabled": "false"},
    {"id": "grp-tablero", "type": "ui-group", "name": "Tablero", "page": "ui-page-ventas", "width": 12,
     "height": 1, "order": 1, "showTitle": False, "className": "", "visible": "true",
     "disabled": "false", "groupType": "default"},

    # ── Entrada: suscripción MQTT + estado de la conexión + temporizadores ──
    {"id": "mqtt-eventos", "type": "mqtt in", "z": TAB, "name": "Eventos de facturación",
     "topic": "${MQTT_SUBSCRIBE_TOPIC}", "qos": "1", "datatype": "json", "broker": "broker-mosquitto",
     "nl": False, "rap": True, "rh": 0, "inputs": 0, "x": 160, "y": 120,
     "wires": [["fn-tablero", "debug-eventos"]]},
    {"id": "debug-eventos", "type": "debug", "z": TAB, "name": "Eventos recibidos", "active": True,
     "tosidebar": True, "console": False, "tostatus": True, "complete": "payload", "targetType": "msg",
     "statusVal": "payload.evento", "statusType": "msg", "x": 440, "y": 60, "wires": []},
    {"id": "status-broker", "type": "status", "z": TAB, "name": "Estado del broker",
     "scope": ["mqtt-eventos"], "x": 150, "y": 200, "wires": [["fn-broker"]]},
    {"id": "fn-broker", "type": "function", "z": TAB, "name": "¿Conectado?", "func": FN_BROKER,
     "outputs": 1, "timeout": 0, "noerr": 0, "initialize": "", "finalize": "", "libs": [],
     "x": 340, "y": 200, "wires": [["fn-tablero"]]},
    {"id": "inject-restaurar", "type": "inject", "z": TAB, "name": "Restaurar al iniciar",
     "props": [{"p": "topic", "vt": "str"}], "repeat": "", "crontab": "", "once": True, "onceDelay": "1",
     "topic": "restore", "x": 170, "y": 260, "wires": [["fn-tablero"]]},
    {"id": "inject-tick", "type": "inject", "z": TAB, "name": "Cambio de día (cada minuto)",
     "props": [{"p": "topic", "vt": "str"}], "repeat": "60", "crontab": "", "once": False, "onceDelay": "",
     "topic": "tick", "x": 190, "y": 320, "wires": [["fn-tablero"]]},
    {"id": "inject-reset", "type": "inject", "z": TAB, "name": "Reiniciar contadores",
     "props": [{"p": "topic", "vt": "str"}], "repeat": "", "crontab": "", "once": False, "onceDelay": "",
     "topic": "reset", "x": 170, "y": 380, "wires": [["fn-tablero"]]},

    # ── Procesamiento → tablero ──
    {"id": "fn-tablero", "type": "function", "z": TAB, "name": "Acumular día", "func": FN_TABLERO,
     "outputs": 1, "timeout": 0, "noerr": 0, "initialize": "", "finalize": "", "libs": [],
     "x": 560, "y": 220, "wires": [["ui-tablero"]]},
    {"id": "ui-tablero", "type": "ui-template", "z": TAB, "group": "grp-tablero", "page": "", "ui": "",
     "name": "Centro de operaciones", "order": 1, "width": 12, "height": 0, "head": "", "format": TABLERO,
     "storeOutMessages": True, "passthru": False, "resendOnRefresh": True, "templateScope": "local",
     "className": "", "x": 790, "y": 220, "wires": [[]]},
]

with open(sys.argv[1], "w", encoding="utf-8", newline="\n") as f:
    json.dump(flows, f, ensure_ascii=False, indent=4)
    f.write("\n")
