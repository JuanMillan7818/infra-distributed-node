#!/usr/bin/env bash
# sdctl - Controlador del Sistema Distribuido.
# Envuelve docker compose sobre el orquestador raíz (docker-compose.yml) y añade
# tareas propias: red compartida, secretos, salud, backups por servicio.
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
NETWORK="red-distribuida"
SECRETS_DIR="$ROOT/secrets"
BACKUP_DIR="$ROOT/backups"

c_ok=$'\e[32m'; c_warn=$'\e[33m'; c_err=$'\e[31m'; c_dim=$'\e[2m'; c_off=$'\e[0m'
info() { echo "${c_ok}[sdctl]${c_off} $*"; }
warn() { echo "${c_warn}[sdctl]${c_off} $*" >&2; }
die()  { echo "${c_err}[sdctl]${c_off} $*" >&2; exit 1; }

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
    docker network create --driver bridge "$NETWORK" >/dev/null
    info "Red '$NETWORK' creada."
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
cmd_restart() { compose restart "$@"; }
cmd_stop()    { compose stop "$@"; }
cmd_start()   { compose start "$@"; }
cmd_logs()    { compose logs --tail=100 "$@"; }
cmd_pull()    { compose pull "$@"; }
cmd_update()  { compose pull "$@" && cmd_up "$@" && docker image prune -f >/dev/null; }
cmd_exec()    { [[ $# -ge 2 ]] || die "Uso: sdctl exec <servicio> <comando...>"; compose exec "$@"; }
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
  [[ $# -eq 1 ]] || die "Uso: sdctl backup <servicio>"
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
  sudo ln -sf "$ROOT/sdctl.sh" /usr/local/bin/sdctl
  info "Instalado: ahora puedes usar 'sdctl' desde cualquier ruta."
}

cmd_help() {
  cat <<EOF
sdctl - Controlador del Sistema Distribuido

Uso: sdctl <comando> [servicio...]

  init                 Crea .env, red '$NETWORK' y secretos de cada servicio
  up      [svc...]     Levanta todo o los servicios indicados
  down    [svc...]     Baja todo (sin args) o elimina los servicios indicados
  start|stop|restart   [svc...]
  status               Estado + consumo CPU/RAM de los contenedores
  health               Chequeo de salud (exit 1 si alguno falla)
  logs    [-f] [svc]   Últimos 100 logs (-f para seguir)
  pull    [svc...]     Descarga imágenes
  update  [svc...]     pull + up + limpia imágenes viejas
  exec    <svc> <cmd>  Ejecuta un comando dentro del contenedor
  backup  <svc>        Respalda volúmenes del servicio en backups/
  list                 Servicios disponibles e incluidos en el orquestador
  config               Muestra el compose final resuelto
  install              Crea el enlace /usr/local/bin/sdctl
EOF
}

main() {
  local cmd="${1:-help}"; shift || true
  case "$cmd" in
    init|up|down|restart|stop|start|logs|pull|update|exec|config|status|list|health|backup|install|help)
      "cmd_$cmd" "$@" ;;
    ps) cmd_status ;;
    -h|--help) cmd_help ;;
    *) cmd_help; die "Comando desconocido: $cmd" ;;
  esac
}

main "$@"
