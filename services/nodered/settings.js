// Ajustes de Node-RED para el tablero de eventos de la web de facturación.
// Los secretos llegan como archivos en /run/secrets (compose "secrets"), nunca en el repo.
const fs = require('fs');
const crypto = require('crypto');

const secret = (name) => {
  try {
    return fs.readFileSync(`/run/secrets/${name}`, 'utf8').trim();
  } catch {
    return '';
  }
};

process.env.MQTT_USERNAME = process.env.MQTT_USERNAME || 'nodered';
process.env.MQTT_PASSWORD = secret('mqtt_nodered_password');
// Node-RED solo sustituye ${VAR} cuando es el valor completo de la propiedad: el tópico se arma aquí.
process.env.MQTT_SUBSCRIBE_TOPIC = `${process.env.MQTT_TOPIC_PREFIX || 'paxia'}/#`;

// Credenciales del nodo broker. Node-RED las busca en <userDir>/flows_cred.json (no junto al
// flowFile), así que se reescriben en cada arranque. Solo llevan referencias ${VAR}: Node-RED las
// resuelve con las variables de arriba y el secreto nunca queda en disco.
const userDir = process.env.NODE_RED_USER_DIR || '/data';
fs.writeFileSync(
  `${userDir}/flows_cred.json`,
  JSON.stringify({ 'broker-mosquitto': { user: '${MQTT_USERNAME}', password: '${MQTT_PASSWORD}' } }, null, 4),
);

// Un apagado brusco (OOM, corte de luz) a mitad de un guardado deja el JSON del contexto truncado,
// y con eso Node-RED se niega a arrancar (bucle de reinicios). Se apartan los archivos dañados
// como *.corrupt-<fecha>: el tablero arranca en cero en vez de quedarse caído.
const quarantineBrokenContext = (dir) => {
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    const file = `${dir}/${entry.name}`;
    if (entry.isDirectory()) {
      quarantineBrokenContext(file);
    } else if (entry.name.endsWith('.json')) {
      try {
        JSON.parse(fs.readFileSync(file, 'utf8') || '{}');
      } catch {
        fs.renameSync(file, `${file}.corrupt-${Date.now()}`);
        console.warn(`[settings] Contexto dañado apartado: ${file}`);
      }
    }
  }
};
quarantineBrokenContext(`${userDir}/context`);

const adminPassword = secret('nodered_admin_password');
const sameSecret = (a, b) => {
  const ha = crypto.createHash('sha256').update(a).digest();
  const hb = crypto.createHash('sha256').update(b).digest();
  return crypto.timingSafeEqual(ha, hb);
};
const admin = { username: 'admin', permissions: '*' };

module.exports = {
  uiPort: 1880,
  // Flujo del repo (copiado en la imagen). Cambios hechos en el editor se pierden al recrear:
  // exportarlos y pasarlos a tools/gen_flows.py.
  flowFile: '/opt/nodered/flows.json',
  // flows_cred.json en texto plano: solo contiene referencias ${VAR}, no secretos.
  credentialSecret: false,
  flowFilePretty: true,

  // Editor (/:1880) protegido con usuario "admin" y el secreto nodered_admin_password.
  // El tablero (/dashboard) es de solo lectura y queda abierto.
  adminAuth: {
    type: 'credentials',
    users: (username) => Promise.resolve(username === 'admin' ? admin : null),
    authenticate: (username, password) =>
      Promise.resolve(
        adminPassword && username === 'admin' && sameSecret(String(password), adminPassword) ? admin : null,
      ),
  },

  // Contexto en disco (/data/context): los acumulados del tablero sobreviven reinicios del contenedor.
  contextStorage: {
    default: { module: 'localfilesystem', config: { flushInterval: 5 } },
  },

  diagnostics: { enabled: false },
  telemetry: { enabled: false },
  externalModules: { palette: { allowInstall: false } },
  logging: { console: { level: 'info', metrics: false, audit: false } },
  editorTheme: {
    projects: { enabled: false },
    tours: false,
    header: { title: 'Sistema Distribuido · Node-RED' },
  },
};
