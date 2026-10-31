# Hook de inicialización de Node-RED (lo ejecuta "manage init" con source).
ensure_secret nodered_admin_password 24
# Node-RED corre como UID 1000: necesita leer el secreto montado. secrets/ sigue en 700.
chmod 644 "$SECRETS_DIR/nodered_admin_password.txt"
