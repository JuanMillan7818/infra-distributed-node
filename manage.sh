#!/usr/bin/env bash
# manage.sh - Controlador del Sistema Distribuido.
# Envuelve docker compose sobre el orquestador raíz (docker-compose.yml) y añade
# tareas propias: red compartida, secretos, salud, backups por servicio.
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
NETWORK="red-interna"
# Subred fija: la VPN (wg-easy) la anuncia a los clientes en "Allowed IPs".
NETWORK_SUBNET="172.30.0.0/16"
SECRETS_DIR="$ROOT/secrets"
BACKUP_DIR="$ROOT/backups"

c_ok=$'\e[32m'; c_warn=$'\e[33m'; c_err=$'\e[31m'; c_dim=$'\e[2m'; c_off=$'\e[0m'
info() { echo "${c_ok}[manage]${c_off} $*"; }
warn() { echo "${c_warn}[manage]${c_off} $*" >&2; }
die()  { echo "${c_err}[manage]${c_off} $*" >&2; exit 1; }

compose() {
  docker compose --project-directory "$ROOT" -f "$ROOT/docker-compose.yml" "$@"
}

# Servicios habilitados = los que el orquestador incluye.
enabled_services() { compose config --services 2>/dev/null; }

# Servicios disponibles = carpetas con compose.yml, estén o no incluidas.
available_services() {
  for f in "$ROOT"/services/*/compose.yml; do
    [[ -e "$f" ]] && basename "$(dirname "$f")"
  done
}

require_docker() {
  command -v docker >/dev/null || die "Docker no está instalado."
  docker compose version >/dev/null 2>&1 || die "Falta el plugin docker compose."
  docker info >/dev/null 2>&1 || die "Sin acceso al daemon (¿usuario en grupo docker? ¿sesión reiniciada?)."
}

ensure_network() {
  if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
    docker network create --driver bridge --subnet "$NETWORK_SUBNET" "$NETWORK" >/dev/null
    info "Red '$NETWORK' creada ($NETWORK_SUBNET)."
    return
  fi
  local subnet
  subnet=$(docker network inspect -f '{{range .IPAM.Config}}{{.Subnet}}{{end}}' "$NETWORK")
  if [[ "$subnet" != "$NETWORK_SUBNET" ]]; then
    warn "Red '$NETWORK' usa $subnet (se espera $NETWORK_SUBNET). Para recrearla:"
    warn "  manage down && docker network rm $NETWORK && manage up"
  fi
}

# Genera un secreto aleatorio si no existe. Uso: ensure_secret <nombre> [longitud]
ensure_secret() {
  local file="$SECRETS_DIR/$1.txt" len="${2:-24}"
  mkdir -p "$SECRETS_DIR"; chmod 700 "$SECRETS_DIR"
  if [[ ! -s "$file" ]]; then
    printf '%s' "$(openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | head -c "$len")" > "$file"
    chmod 600 "$file"
    info "Secreto '$1' generado en secrets/$1.txt"
  fi
}

cmd_init() {
  require_docker
  [[ -f "$ROOT/.env" ]] || { cp "$ROOT/.env.example" "$ROOT/.env"; warn "Creado .env desde .env.example: revisa sus valores."; }
  ensure_network
  # restart: unless-stopped solo sobrevive a reinicios del servidor si Docker arranca con el sistema.
  if command -v systemctl >/dev/null && ! systemctl is-enabled --quiet docker 2>/dev/null; then
    warn "Docker no arranca con el sistema. Ejecuta: sudo systemctl enable docker containerd"
  fi
  # Cada servicio puede aportar su propio init (secretos, configs) en services/<svc>/init.sh
  for svc in $(available_services); do
    local hook="$ROOT/services/$svc/init.sh"
    if [[ -f "$hook" ]]; then
      info "init: $svc"
      # shellcheck source=/dev/null
      source "$hook"
    fi
  done
  info "Inicialización lista."
}

cmd_up()      { require_docker; ensure_network; compose up -d --remove-orphans "$@"; cmd_status; }
cmd_down() {
  if (( $# )); then compose rm -sf "$@"; else compose down; fi
}
# Falla con mensaje claro si algún servicio no está incluido en el orquestador.
check_services() {
  local enabled
  enabled="$(enabled_services)" || die "docker-compose.yml inválido. Revisa con: manage config"
  for s in "$@"; do
    grep -qx -- "$s" <<<"$enabled" || die "Servicio '$s' no incluido. Disponibles: $(tr '\n' ' ' <<<"$enabled")"
  done
}

# -f/--force puede ir en cualquier posición: restart -f samba | restart samba -f
cmd_restart() {
  local force=0 args=()
  for a in "$@"; do
    case "$a" in -f|--force) force=1 ;; *) args+=("$a") ;; esac
  done
  if (( force )); then cmd_rebuild "${args[@]}"; return; fi
  require_docker; check_services "${args[@]}"
  compose restart "${args[@]}"
  cmd_status
}

# Reinicio forzado: elimina contenedores, descarga imágenes nuevas, reconstruye sin caché
# y recrea en segundo plano (-d). Conserva los volúmenes con nombre (datos).
cmd_rebuild() {
  require_docker; check_services "$@"; ensure_network
  info "Reinicio forzado sin caché: ${*:-todos los servicios}"
  cmd_down "$@"
  compose build --no-cache --pull "$@"
  compose up -d --pull always --force-recreate --renew-anon-volumes --remove-orphans "$@"
  cmd_status
}
cmd_stop()    { compose stop "$@"; }
cmd_start()   { compose start "$@"; }
cmd_logs()    { compose logs --tail=100 "$@"; }
cmd_pull()    { compose pull "$@"; }
cmd_update()  { compose pull "$@" && cmd_up "$@" && docker image prune -f >/dev/null; }
cmd_exec()    { [[ $# -ge 2 ]] || die "Uso: manage exec <servicio> <comando...>"; compose exec "$@"; }
cmd_config()  { compose config "$@"; }

cmd_status() {
  compose ps --format 'table {{.Service}}\t{{.State}}\t{{.Status}}\t{{.Ports}}'
  local ids; ids=$(compose ps -q)
  [[ -n "$ids" ]] || return 0
  echo
  echo "${c_dim}Recursos:${c_off}"
  # shellcheck disable=SC2086
  docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}' $ids
}

cmd_list() {
  local enabled; enabled="$(enabled_services || true)"
  printf '%-14s %s\n' "SERVICIO" "ESTADO EN ORQUESTADOR"
  for svc in $(available_services); do
    if grep -qx "$svc" <<<"$enabled"; then printf '%-14s %s\n' "$svc" "${c_ok}incluido${c_off}"
    else printf '%-14s %s\n' "$svc" "${c_dim}no incluido${c_off}"; fi
  done
}

cmd_health() {
  local fail=0
  for id in $(compose ps -aq); do
    local name state health
    name=$(docker inspect -f '{{.Name}}' "$id" | tr -d /)
    state=$(docker inspect -f '{{.State.Status}}' "$id")
    health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}sin-healthcheck{{end}}' "$id")
    if [[ "$state" == "running" && "$health" != "unhealthy" ]]; then
      printf '%s %-14s %s (%s)\n' "${c_ok}✔${c_off}" "$name" "$state" "$health"
    else
      printf '%s %-14s %s (%s)\n' "${c_err}✘${c_off}" "$name" "$state" "$health"; fail=1
    fi
  done
  return $fail
}

# Respalda los volúmenes con nombre de un servicio en backups/<svc>-<fecha>.tar.gz
cmd_backup() {
  [[ $# -eq 1 ]] || die "Uso: manage backup <servicio>"
  local svc="$1" ts; ts=$(date +%Y%m%d-%H%M%S)
  mkdir -p "$BACKUP_DIR"
  local vols
  vols=$(docker inspect -f '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}} {{end}}{{end}}' \
    "$(compose ps -q "$svc")") || die "Servicio '$svc' no está corriendo."
  [[ -n "$vols" ]] || die "'$svc' no tiene volúmenes con nombre."
  for v in $vols; do
    docker run --rm -v "$v":/data:ro -v "$BACKUP_DIR":/backup alpine \
      tar czf "/backup/${svc}-${v}-${ts}.tar.gz" -C /data .
    info "Backup: backups/${svc}-${v}-${ts}.tar.gz"
  done
}

cmd_install() {
  sudo ln -sf "$ROOT/manage.sh" /usr/local/bin/manage
  info "Instalado: ahora puedes usar 'manage' desde cualquier ruta."
}

cmd_help() {
  (( $# )) && { cmd_help_topic "$1"; return; }
  cat <<EOF
manage - Controlador del Sistema Distribuido

Uso: manage <comando> [servicio...]
     manage help <comando>     Ayuda detallada de un comando
     manage <comando> --help   Igual que la anterior

Configuración
  init                 Crea .env, red '$NETWORK' y secretos de cada servicio
  install              Crea el enlace /usr/local/bin/manage
  config               Muestra el compose final resuelto

Ciclo de vida
  up      [svc...]     Levanta todo o los servicios indicados
  down    [svc...]     Baja todo (sin args) o elimina los servicios indicados
  start   [svc...]     Inicia contenedores detenidos
  stop    [svc...]     Detiene sin eliminar
  restart [svc...]     Reinicia (rápido, mismo contenedor)
  restart -f [svc...]  Reinicio forzado sin caché (= rebuild)
  rebuild [svc...]     Elimina, descarga imágenes, build --no-cache y up -d

Observación
  status | ps          Estado + consumo CPU/RAM de los contenedores
  health               Chequeo de salud (exit 1 si alguno falla)
  logs    [-f] [svc]   Últimos 100 logs (-f para seguir)
  list                 Servicios disponibles e incluidos en el orquestador

Mantenimiento
  pull    [svc...]     Descarga imágenes
  update  [svc...]     pull + up + limpia imágenes viejas
  exec    <svc> <cmd>  Ejecuta un comando dentro del contenedor
  backup  <svc>        Respalda volúmenes del servicio en backups/

Servicios disponibles: $(available_services | tr '\n' ' ')

Ejemplos
  manage init && manage up           Primer despliegue completo
  manage up portainer                Solo Portainer
  manage logs -f portainer           Seguir logs en vivo
  manage exec <svc> sh               Shell dentro del contenedor (si la imagen trae sh)
  manage help backup                 Ayuda detallada de un comando
EOF
}

cmd_help_topic() {
  case "$1" in
    init) cat <<EOF
manage init
  1. Copia .env.example -> .env si no existe.
  2. Crea la red bridge '$NETWORK' si no existe.
  3. Ejecuta services/<svc>/init.sh de cada servicio (genera secretos en secrets/).
  Es idempotente: no sobrescribe .env ni secretos existentes.
EOF
    ;;
    up) cat <<EOF
manage up [svc...]
  Crea la red si falta y ejecuta 'docker compose up -d --remove-orphans'.
  Sin argumentos levanta todos los servicios incluidos en docker-compose.yml.
  Ejemplo: manage up portainer
EOF
    ;;
    down) cat <<EOF
manage down [svc...]
  Sin argumentos: 'docker compose down' (elimina contenedores; conserva volúmenes y red).
  Con servicios: detiene y elimina solo esos contenedores.
  Ejemplo: manage down portainer
EOF
    ;;
    start|stop) cat <<EOF
manage $1 [svc...]
  Ejecuta 'docker compose $1' sobre todos o los servicios indicados.
EOF
    ;;
    restart|rebuild) cat <<EOF
manage restart [svc...]
  Reinicio rápido: 'docker compose restart'. Mismo contenedor y misma imagen.

manage restart -f|--force [svc...]   (equivalente: manage rebuild [svc...])
  Reinicio forzado sin caché, siempre en segundo plano (-d):
    1. Elimina los contenedores (los volúmenes con nombre se conservan).
    2. build --no-cache --pull (servicios con 'build:').
    3. up -d --pull always --force-recreate --renew-anon-volumes
  Ejemplos: manage restart -f portainer   |   manage rebuild
EOF
    ;;
    status|ps) cat <<EOF
manage status   (alias: ps)
  Tabla servicio/estado/puertos + consumo de CPU y RAM (docker stats).
EOF
    ;;
    health) cat <<EOF
manage health
  Revisa cada contenedor: debe estar 'running' y no 'unhealthy'.
  Devuelve exit 1 si alguno falla (útil en scripts/cron).
EOF
    ;;
    logs) cat <<EOF
manage logs [-f] [svc...]
  Últimas 100 líneas. -f sigue en vivo (Ctrl+C para salir).
  Ejemplo: manage logs -f portainer
EOF
    ;;
    pull|update) cat <<EOF
manage pull [svc...]     Descarga las imágenes más recientes del tag configurado.
manage update [svc...]   pull + recrea contenedores + 'docker image prune -f'.
EOF
    ;;
    exec) cat <<EOF
manage exec <svc> <comando...>
  Ejecuta un comando dentro del contenedor en ejecución.
  Ejemplo: manage exec mosquitto mosquitto_sub -t '#' -v
EOF
    ;;
    backup) cat <<EOF
manage backup <svc>
  Empaqueta cada volumen con nombre del servicio en
  backups/<svc>-<volumen>-<fecha>.tar.gz (usa un contenedor alpine temporal).
EOF
    ;;
    list) echo "manage list  -> Servicios en services/ y si están incluidos en docker-compose.yml." ;;
    config) echo "manage config  -> 'docker compose config': compose final con variables resueltas." ;;
    install) echo "manage install  -> Enlace simbólico /usr/local/bin/manage (requiere sudo)." ;;
    *) die "Sin ayuda para '$1'. Usa: manage help" ;;
  esac
}

main() {
  local cmd="${1:-help}"; shift || true
  # Ayuda por comando: manage <comando> -h|--help
  if [[ "$cmd" != "help" && ( "${1:-}" == "-h" || "${1:-}" == "--help" ) ]]; then
    cmd_help_topic "$cmd"; return
  fi
  case "$cmd" in
    init|up|down|restart|rebuild|stop|start|logs|pull|update|exec|config|status|list|health|backup|install|help)
      "cmd_$cmd" "$@" ;;
    ps) cmd_status ;;
    -h|--help) cmd_help ;;
    *) cmd_help; die "Comando desconocido: $cmd" ;;
  esac
}

main "$@"
