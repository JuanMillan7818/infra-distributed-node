# 01 — Arquitectura y decisiones de diseño

## Requerimiento original (PDF)

| Servicio | Módulo | Puerto | Función |
|----------|--------|--------|---------|
| Gestión web | Portainer CE | 9000 | Administración de contenedores |
| Mensajería | Eclipse Mosquitto | 1883 / 9001 | Broker MQTT |
| Monitoreo | Glances | 61208 | Métricas de hardware |
| VPN | WG-Easy (WireGuard) | 51820/udp, 51821/tcp | Túnel con clientes Windows |
| Almacenamiento | Samba | 139 / 445 | Carpetas compartidas |

Todos en una red bridge `red-distribuida`, orquestados con Docker Compose.

## Destino: AWS EC2

- **1 instancia** `t3.small` (2 vCPU, 2 GiB RAM), Ubuntu 24.04 LTS, 30 GB gp3.
- Todos los contenedores corren en esa instancia, aislados en la red `red-distribuida`.

## Cambios / mejoras respecto a la guía

| # | Guía original | Mejora aplicada | Motivo |
|---|---------------|-----------------|--------|
| 1 | Un solo `docker-compose.yml` monolítico | Un `compose.yml` por servicio + orquestador raíz con `include` | Modularidad: cada fase se activa/desactiva sin tocar las demás |
| 2 | Comandos `docker compose` manuales | Script `sdctl.sh` (init, up, down, health, backup…) | Operación uniforme y repetible |
| 3 | `version: '3.8'` | Eliminado | Campo obsoleto en Compose v2 |
| 4 | Imágenes `:latest` | Tags fijos/versionados por variable en `.env` | Reproducibilidad |
| 5 | Contraseñas en texto plano en el compose (`AdminPassword123`) | Secretos generados aleatoriamente en `secrets/` (fuera de git) | Seguridad |
| 6 | Sin límites de recursos | `deploy.resources.limits` por contenedor | 2 GB RAM compartidos: evitar que un servicio tumbe a los demás |
| 7 | Portainer solo HTTP 9000 | HTTP 9000 + HTTPS 9443 | Cifrado del panel |
| 8 | Sin rotación de logs, sin swap | `daemon.json` con rotación + swap 2 GB | Estabilidad en instancia pequeña |
| 9 | Todos los puertos abiertos | Security Group restringido a la IP del administrador; a futuro todo detrás de la VPN | Superficie de ataque mínima |

### Mejoras propuestas para fases siguientes

- **Mosquitto**: `allow_anonymous false` + usuarios con `mosquitto_passwd`; listener WebSocket 9001.
- **Monitoreo**: Glances exportando a Prometheus + **Grafana** con dashboards (ver abajo).
- **WireGuard**: wg-easy v15 (versión fijada). Samba, Portainer y Grafana accesibles **solo a través de la VPN** → en AWS solo quedan abiertos 22/tcp y 51820/udp.
- **Samba**: reemplazar `dperson/samba` (sin mantenimiento) por una imagen mantenida; usuario con contraseña en vez de acceso invitado. Además el puerto 445 suele estar bloqueado por los ISP → SMB solo por VPN es la única opción realista.
- **Demo MQTT**: pequeño publicador que envíe métricas del nodo a un tópico y un suscriptor (o Grafana) que las muestre → evidencia de "intercambio de eventos entre nodos".

## ¿Grafana reemplaza a Portainer?

**No.** Cumplen funciones distintas:

| | Portainer | Grafana |
|---|-----------|---------|
| Propósito | **Gestionar** contenedores (crear, parar, logs, consola, volúmenes, redes) | **Visualizar** métricas y alertas |
| Actúa sobre Docker | Sí (vía `docker.sock`) | No, solo lee datos de una fuente (Prometheus, InfluxDB…) |
| Necesita fuente de datos | No | Sí |

Grafana sí puede **complementar o reemplazar a Glances** como capa de visualización. Decisión: mantener Portainer (exigido en la demo) y en la fase de monitoreo usar **Glances → Prometheus → Grafana**.

## Presupuesto de memoria (2 GiB + 2 GiB swap)

| Servicio | Límite |
|----------|--------|
| Sistema + Docker | ~350 MB |
| Portainer | 256 MB |
| Mosquitto | 64 MB |
| Glances | 192 MB |
| Prometheus | 256 MB |
| Grafana | 192 MB |
| wg-easy | 128 MB |
| Samba | 128 MB |
| **Total aprox.** | **~1.6 GB** |
