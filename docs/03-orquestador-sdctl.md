# 03 — Orquestador: docker-compose + sdctl

## 3.1 Diseño

```
docker-compose.yml  (name: sistema-distribuido)
   └── include:
        ├── services/portainer/compose.yml
        ├── services/mosquitto/compose.yml   (fase 2)
        └── ...
red externa: red-distribuida (bridge) ← creada por sdctl
```

- **Un archivo por servicio**: cada `services/<svc>/compose.yml` es autocontenido (imagen, puertos, volúmenes, secretos, límites).
- **Orquestador raíz**: un solo proyecto Compose (`sistema-distribuido`) que agrupa los servicios con `include` (Compose ≥ 2.20).
- **Red externa `red-distribuida`**: la crea `sdctl`, así todos los servicios comparten red aunque se levanten por separado.
- **Hooks `init.sh`**: cada servicio puede declarar su inicialización (secretos, archivos de config). `sdctl init` los ejecuta.

Activar un servicio nuevo = crear `services/<svc>/` + descomentar su línea en `include`.

## 3.2 Instalación en la instancia

```bash
cd ~/proyecto_final
chmod +x sdctl.sh
./sdctl.sh install      # enlace /usr/local/bin/sdctl
sdctl init              # .env, red, secretos
```

## 3.3 Referencia de comandos

| Comando | Acción |
|---------|--------|
| `sdctl init` | Crea `.env`, la red y los secretos de todos los servicios |
| `sdctl up [svc…]` | Levanta todo o solo los indicados y muestra estado |
| `sdctl down [svc…]` | Sin args: baja todo. Con args: elimina solo esos contenedores |
| `sdctl start/stop/restart [svc…]` | Control de ciclo de vida |
| `sdctl status` (o `ps`) | Estado, puertos y consumo CPU/RAM |
| `sdctl health` | Verifica que todo esté `running`/`healthy` (exit 1 si falla) |
| `sdctl logs [-f] [svc]` | Últimas 100 líneas de log |
| `sdctl pull / update [svc…]` | Descargar imágenes / actualizar y recrear |
| `sdctl exec <svc> <cmd>` | Comando dentro del contenedor |
| `sdctl backup <svc>` | `.tar.gz` de los volúmenes del servicio en `backups/` |
| `sdctl list` | Servicios disponibles vs. incluidos en el orquestador |
| `sdctl config` | Compose final resuelto (útil para depurar) |

## 3.4 Equivalencias sin sdctl

```bash
docker network create red-distribuida
docker compose up -d                 # desde la raíz del proyecto
docker compose ps
```
