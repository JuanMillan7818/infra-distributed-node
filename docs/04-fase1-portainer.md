# 04 — Fase 1: Portainer CE (Gestión web)

## 4.1 Objetivo

Panel web para administrar contenedores, imágenes, volúmenes y redes del nodo.

## 4.2 Definición

Archivo: [`services/portainer/compose.yml`](../services/portainer/compose.yml)

| Parámetro | Valor | Nota |
|-----------|-------|------|
| Imagen | `portainer/portainer-ce:${PORTAINER_TAG}` (`lts`) | Rama de soporte extendido |
| Puertos | 9443 (HTTPS), 9000 (HTTP) | 9000 lo exige la guía |
| Volúmenes | `/var/run/docker.sock`, `portainer_data:/data` | Socket = control de Docker; datos persistentes |
| Secreto | `secrets/portainer_admin_password.txt` | Crea el usuario `admin` al arrancar |
| Límites | 0.5 CPU, 256 MB | |
| Red | `red-distribuida` | |

**Por qué el secreto**: sin él, Portainer exige crear el admin vía web en menos de 5 minutos, si no, se bloquea y hay que reiniciarlo. Con `--admin-password-file` queda listo y sin contraseña en texto en el compose.

> ⚠️ Montar `docker.sock` da control total del host a Portainer. Por eso el puerto se restringe a tu IP (y luego solo por VPN).

## 4.3 Despliegue

```bash
cd ~/proyecto_final
sdctl init                    # genera secrets/portainer_admin_password.txt
sdctl up portainer
cat secrets/portainer_admin_password.txt; echo
```

Salida esperada de `sdctl status`:
```
SERVICE     STATE     STATUS         PORTS
portainer   running   Up 10 seconds  0.0.0.0:9000->9000/tcp, 0.0.0.0:9443->9443/tcp
```

## 4.4 Acceso

- `https://<ELASTIC_IP>:9443` (aceptar el certificado autofirmado)
- `http://<ELASTIC_IP>:9000`
- Usuario `admin` · contraseña del secreto.
- Seleccionar el entorno **local** → se ven los contenedores del proyecto `sistema-distribuido`.

## 4.5 Verificación

| Prueba | Comando / acción | Resultado esperado |
|--------|------------------|--------------------|
| Contenedor activo | `sdctl health` | `✔ portainer running` |
| Red correcta | `docker network inspect red-distribuida` | Aparece `portainer` |
| Persistencia | `sdctl down portainer && sdctl up portainer` | Mismo usuario y configuración |
| Backup | `sdctl backup portainer` | Archivo en `backups/` |
| Consumo | `sdctl status` | < 100 MB RAM |

## 4.6 Problemas comunes

| Síntoma | Causa | Solución |
|---------|-------|----------|
| Timeout en navegador | Security Group sin el puerto o IP cambió | Revisar regla con `MI_IP/32` |
| `network red-distribuida declared as external, but could not be found` | Se usó `docker compose` sin `sdctl init` | `sdctl init` o `docker network create red-distribuida` |
| Login rechazado | Contraseña cambiada en el secreto después del primer arranque | El secreto solo aplica al inicializar; borrar volumen (`sdctl down` + `docker volume rm sistema-distribuido_portainer_data`) para reiniciar |
| `permission denied ... docker.sock` | Usuario sin grupo docker | Cerrar y abrir sesión SSH |
