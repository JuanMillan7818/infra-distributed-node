# Hook de inicialización de Mosquitto (lo ejecuta "manage init" con source).
# Una contraseña por usuario MQTT; config/start.sh las convierte en passwd + acl al arrancar.
#   admin       -> depuración (mosquitto_sub, MQTT Explorer)
#   facturacion -> la web publica eventos (copiar a MQTT_PASSWORD en Vercel)
#   nodered     -> el tablero lee eventos
ensure_secret mqtt_admin_password 24
ensure_secret mqtt_facturacion_password 24
ensure_secret mqtt_nodered_password 24
# Node-RED corre como UID 1000: necesita leer su secreto montado. secrets/ sigue en 700.
chmod 644 "$SECRETS_DIR/mqtt_nodered_password.txt"
