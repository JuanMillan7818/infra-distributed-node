// Ajustes de la vista previa: reusa settings.js real y solo cambia rutas y credenciales de prueba.
const path = require('path');

const DATA = process.env.PREVIEW_DATA_DIR || path.join(__dirname, '.data');
process.env.NODE_RED_USER_DIR = DATA;
const settings = require('../../settings.js');

process.env.MQTT_USERNAME = 'nodered';
process.env.MQTT_PASSWORD = 'preview';
settings.flowFile = path.join(DATA, 'flows.json');
settings.uiPort = Number(process.env.PREVIEW_PORT) || 1880;

const admin = { username: 'admin', permissions: '*' };
settings.adminAuth.authenticate = (u, p) => Promise.resolve(u === 'admin' && p === 'admin' ? admin : null);

module.exports = settings;
