# Hook de inicialización de la VPN (lo ejecuta "manage init" con source).
# wg-easy exige contraseña con mayúscula, minúscula, número y símbolo: se agrega un sufijo fijo
# al aleatorio alfanumérico. Se guarda en texto (para consultarla) y como env_file del compose.
if [[ ! -s "$SECRETS_DIR/wg_admin_password.txt" ]]; then
  ensure_secret wg_admin_password 20
  printf '%s' "$(cat "$SECRETS_DIR/wg_admin_password.txt")Aa1-" > "$SECRETS_DIR/wg_admin_password.txt"
fi
printf 'INIT_PASSWORD=%s\n' "$(cat "$SECRETS_DIR/wg_admin_password.txt")" > "$SECRETS_DIR/wg-easy.env"
chmod 600 "$SECRETS_DIR/wg-easy.env"
