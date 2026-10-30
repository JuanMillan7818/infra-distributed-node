# Hook de inicialización de Monitoreo (lo ejecuta "manage init" con source).
ensure_secret grafana_admin_password 24
# Grafana corre como UID 472: necesita leer el secreto montado. secrets/ sigue en 700,
# así que otros usuarios del host no pueden llegar al archivo.
chmod 644 "$SECRETS_DIR/grafana_admin_password.txt"
