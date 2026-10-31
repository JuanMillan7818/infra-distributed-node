# Hook de inicialización de la VPN (lo ejecuta "manage init" con source).
# wg-easy exige contraseña con mayúscula, minúscula, número y símbolo: se agrega un sufijo fijo
# al aleatorio alfanumérico. Se guarda en texto (para consultarla) y como env_file del compose.
if [[ ! -s "$SECRETS_DIR/wg_admin_password.txt" ]]; then
  ensure_secret wg_admin_password 20
  printf '%s' "$(cat "$SECRETS_DIR/wg_admin_password.txt")Aa1-" > "$SECRETS_DIR/wg_admin_password.txt"
fi
printf 'INIT_PASSWORD=%s\n' "$(cat "$SECRETS_DIR/wg_admin_password.txt")" > "$SECRETS_DIR/wg-easy.env"
chmod 600 "$SECRETS_DIR/wg-easy.env"

# El endpoint de los clientes sale de SERVER_PUBLIC_IP y wg-easy solo lo lee en su primer arranque:
# con un valor inválido los clientes reciben un Endpoint inalcanzable. Solo avisa.
# En Codespaces no entra UDP: la VPN se prueba por wstunnel (ver services/wstunnel/README.md).
# Se detecta por el directorio porque "sudo" no siempre conserva la variable CODESPACES.
if [[ -n "${CODESPACES:-}" || -d /workspaces/.codespaces ]]; then
  info "Codespaces: el UDP de WireGuard no es accesible desde fuera. Para probar la VPN usa wstunnel"
  info "  (services/wstunnel/README.md); en ese modo el host de wg-easy debe ser 127.0.0.1."
else
  wg_host=$(sed -n 's/^SERVER_PUBLIC_IP=//p' "$ROOT/.env" 2>/dev/null | tail -n1 | tr -d "\"' \r")
  case "$wg_host" in
    ""|0.0.0.0|127.*|localhost)
      warn "SERVER_PUBLIC_IP='${wg_host}' en .env: los clientes VPN no podrán conectar."
      warn "  Ponle la IP pública de la EC2 (o la IP LAN del PC) antes de levantar wg-easy por primera vez."
      warn "  Si wg-easy ya se inicializó, cambia el host en su panel (Admin Panel) o recrea el volumen wg_data."
      ;;
  esac
  unset wg_host
fi
