# Hook de inicialización de Portainer (lo ejecuta "sdctl init" con source).
# Portainer exige contraseña de admin de al menos 12 caracteres.
ensure_secret portainer_admin_password 24
