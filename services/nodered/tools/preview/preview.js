// Vista previa local del tablero, sin Docker:
//   1. Broker MQTT de prueba (aedes) en 127.0.0.1:1883 con los mismos usuarios/ACL que mosquitto.
//   2. Node-RED con el flows.json del repo (broker apuntando a 127.0.0.1).
//   3. Simulador que publica ventas, devoluciones, stock bajo, abonos y cierres como la web.
// Uso: npm install && npm start   →   http://localhost:1880/dashboard
const fs = require('fs');
const net = require('net');
const path = require('path');
const { spawn } = require('child_process');
const mqtt = require('mqtt');
const aedes = require('aedes')();

const PREFIX = process.env.MQTT_TOPIC_PREFIX || 'paxia';
const BUSINESS = 'negocio-demo';
const INTERVAL_MS = Number(process.env.PREVIEW_INTERVAL_MS) || 3000;
const UI_PORT = Number(process.env.PREVIEW_PORT) || 1880;
const MQTT_PORT = Number(process.env.PREVIEW_MQTT_PORT) || 1883;
const DATA = process.env.PREVIEW_DATA_DIR || path.join(__dirname, '.data');

// ── 1. Broker de prueba (mismo modelo de permisos que mosquitto) ──
const users = { facturacion: 'preview', nodered: 'preview' };
aedes.authenticate = (client, user, pass, cb) => {
  const ok = users[user] === String(pass || '');
  if (ok) client.user = user;
  cb(null, ok);
};
aedes.authorizePublish = (client, packet, cb) =>
  cb(client.user === 'facturacion' && packet.topic.startsWith(`${PREFIX}/`) ? null : new Error('no autorizado'));
aedes.authorizeSubscribe = (client, sub, cb) => cb(null, client.user === 'nodered' ? sub : null);
net.createServer(aedes.handle).listen(MQTT_PORT, '127.0.0.1', () => console.log(`[preview] broker MQTT en 127.0.0.1:${MQTT_PORT}`));

// ── 2. Node-RED con el flujo del repo ──
fs.mkdirSync(DATA, { recursive: true });
const flows = fs.readFileSync(path.join(__dirname, '..', '..', 'flows.json'), 'utf8')
  .replace('"broker": "mosquitto"', '"broker": "127.0.0.1"')
  .replace('"port": "1883"', `"port": "${MQTT_PORT}"`);
fs.writeFileSync(path.join(DATA, 'flows.json'), flows);

const nodeRed = spawn(
  process.execPath,
  [require.resolve('node-red/red.js'), '--userDir', DATA, '--settings', path.join(__dirname, 'preview-settings.js')],
  { stdio: 'inherit', env: { ...process.env, PREVIEW_DATA_DIR: DATA, PREVIEW_PORT: String(UI_PORT), MQTT_TOPIC_PREFIX: PREFIX, META_DIARIA: process.env.META_DIARIA || '500000' } },
);
const stop = () => { nodeRed.kill(); process.exit(0); };
process.on('SIGINT', stop);
process.on('SIGTERM', stop);

// ── 3. Simulador de la web de facturación ──
const products = [
  { id: 'p1', nombre: 'Arroz Diana 1kg', precio: 4800, stock: 14, minimo: 5 },
  { id: 'p2', nombre: 'Aceite Premier 1L', precio: 12500, stock: 9, minimo: 3 },
  { id: 'p3', nombre: 'Café Sello Rojo 250g', precio: 9800, stock: 7, minimo: 4 },
  { id: 'p4', nombre: 'Leche Alquería 1L', precio: 4200, stock: 20, minimo: 6 },
  { id: 'p5', nombre: 'Huevos x30', precio: 17900, stock: 6, minimo: 2 },
];
const clients = ['Cliente de mostrador', 'María Gómez', 'Tienda La 14', 'Carlos Ruiz', 'Ana Torres'];
const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
let invoice = 1000;
const sales = [];

const publisher = mqtt.connect(`mqtt://127.0.0.1:${MQTT_PORT}`, { username: 'facturacion', password: 'preview', clientId: 'preview-facturacion' });
const publish = (topic, payload) => {
  publisher.publish(
    `${PREFIX}/${BUSINESS}/${topic}`,
    JSON.stringify({ evento: topic, negocioId: BUSINESS, ...payload, ts: new Date().toISOString() }),
    { qos: 1 },
  );
  console.log(`[preview] → ${topic}`);
};

function sale() {
  const tipo = Math.random() < 0.7 ? 'contado' : Math.random() < 0.8 ? 'credito' : 'cotizacion';
  const items = Array.from({ length: 1 + Math.floor(Math.random() * 3) }, () => {
    const p = pick(products);
    const cantidad = 1 + Math.floor(Math.random() * 3);
    return { p, cantidad, total: p.precio * cantidad };
  });
  const total = items.reduce((s, i) => s + i.total, 0);
  const number = ++invoice;
  publish('ventas/nueva', {
    id: `s${number}`, factura: number, tipo, total, pagado: tipo === 'credito' ? 0 : total,
    cliente: pick(clients), usuario: 'caja1', unidades: items.reduce((s, i) => s + i.cantidad, 0),
    productos: items.map((i) => ({ nombre: i.p.nombre, cantidad: i.cantidad, total: i.total })),
  });
  if (tipo === 'cotizacion') return;
  if (tipo === 'contado') sales.push({ number, total });
  for (const { p, cantidad } of items) {
    p.stock = Math.max(0, p.stock - cantidad);
    if (p.stock <= p.minimo) {
      publish('inventario/stock-bajo', { productoId: p.id, producto: p.nombre, sku: '', stock: p.stock, minimo: p.minimo });
      p.stock += 15; // "reabastece" para que la demo siga
    }
  }
}

const others = [
  () => {
    const s = sales.length && pick(sales);
    if (!s) return sale();
    const monto = Math.round(s.total * 0.3);
    publish('ventas/devolucion', { id: `s${s.number}`, factura: s.number, monto, nota: 'Producto en mal estado', totalVenta: s.total, totalDevuelto: monto, cliente: pick(clients) });
  },
  () => publish('creditos/abono', { cliente: pick(clients.slice(1)), monto: 10000 * (1 + Math.floor(Math.random() * 5)), usuario: 'caja1' }),
  () => {
    const esperado = 150000 + Math.floor(Math.random() * 100000);
    const diferencia = pick([0, 0, -2000, 1000]);
    publish('caja/cierre', { fecha: new Date().toISOString().slice(0, 10), base: 100000, esperado, contado: esperado + diferencia, diferencia, usuario: 'caja1' });
  },
];

publisher.on('connect', () => {
  console.log(`[preview] simulando un evento cada ${INTERVAL_MS} ms (Ctrl+C para salir)`);
  console.log(`[preview] Tablero: http://localhost:${UI_PORT}/dashboard   Editor: http://localhost:${UI_PORT} (admin / admin)`);
  setTimeout(() => {
    setInterval(() => (Math.random() < 0.8 ? sale() : pick(others)()), INTERVAL_MS);
  }, 5000); // deja arrancar a Node-RED
});
