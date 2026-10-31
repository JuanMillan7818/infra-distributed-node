# Hook de inicialización de wstunnel (lo ejecuta "manage init" con source).
# El prefijo de ruta actúa como clave: el puerto es público y sin él cualquiera podría usar el túnel.
ensure_secret wstunnel_path_prefix 32
printf 'WSTUNNEL_PATH_PREFIX=%s\n' "$(cat "$SECRETS_DIR/wstunnel_path_prefix.txt")" > "$SECRETS_DIR/wstunnel.env"
chmod 600 "$SECRETS_DIR/wstunnel.env"
