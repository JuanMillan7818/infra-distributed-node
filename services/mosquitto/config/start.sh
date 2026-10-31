#!/bin/sh
# Arranque de mosquitto: genera passwd (hasheado) y acl desde los secretos montados
# en /run/secrets, fuera del repo, y luego reemplaza este shell por el broker.
set -eu

AUTH=/mosquitto/auth
PREFIX="${MQTT_TOPIC_PREFIX:-paxia}"
mkdir -p "$AUTH"
rm -f "$AUTH/passwd"
touch "$AUTH/passwd"

for user in admin facturacion nodered; do
  mosquitto_passwd -b "$AUTH/passwd" "$user" "$(cat "/run/secrets/mqtt_${user}_password")"
done

# ACL: cada sistema solo puede lo que necesita (mínimo privilegio).
cat > "$AUTH/acl" <<ACL
# Administración y depuración (mosquitto_sub / MQTT Explorer): todo.
user admin
topic readwrite #

# Web de facturación: solo publica sus eventos de negocio.
user facturacion
topic write ${PREFIX}/#

# Tablero Node-RED: solo lee.
user nodered
topic read ${PREFIX}/#
ACL

# Mosquitto exige que solo su usuario pueda leer estos archivos.
chown -R mosquitto:mosquitto "$AUTH"
chmod 0700 "$AUTH" && chmod 0600 "$AUTH/passwd" "$AUTH/acl"

exec mosquitto -c /mosquitto/config/mosquitto.conf
