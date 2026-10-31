# wstunnel: probar la VPN desde fuera de un Codespace

**Solo para pruebas en GitHub Codespaces.** En la EC2 no se usa: allí el cliente conecta directo por UDP 51820.

El proxy de Codespaces (`*.app.github.dev`) solo deja pasar HTTPS/WebSocket, no el UDP de WireGuard. wstunnel mete el tráfico de WireGuard dentro de un WebSocket:

```
App WireGuard (tu PC) --UDP--> wstunnel client (127.0.0.1:51820)
    --WSS 443--> proxy de GitHub (<codespace>-8080.app.github.dev)
    --> wstunnel server (Codespace :8080) --UDP--> wg-easy:51820
```

Seguridad: el puerto 8080 queda público, pero el servidor solo acepta conexiones con el **prefijo secreto** (`secrets/wstunnel_path_prefix.txt`) y solo reenvía a `wg-easy:51820`. Además, WireGuard sigue necesitando las claves del cliente.

## 1. En el Codespace

```bash
sudo ./manage.sh init                       # genera secrets/wstunnel_path_prefix.txt
sudo docker compose -p wstunnel -f services/wstunnel/compose.yml up -d
gh codespace ports visibility 8080:public -c "$CODESPACE_NAME"
sudo cat secrets/wstunnel_path_prefix.txt  # lo necesita el cliente
```

- Se usa un proyecto aparte (`-p wstunnel`) a propósito: no está en el orquestador y así `manage up` no lo borra como huérfano.
- `sudo` es necesario porque `secrets/` es de root.

En el panel de wg-easy (pestaña *Ports* → 51821, usuario `admin`, contraseña en `secrets/wg_admin_password.txt`), ve a **Admin Panel** y configura los valores por defecto de los clientes:

| Campo | Valor | Por qué |
|---|---|---|
| Host | `127.0.0.1` | El cliente WireGuard conecta a wstunnel en su propio PC. |
| Puerto | `51820` | |
| MTU | `1280` | Deja espacio para el encapsulado WebSocket/TLS. |
| Persistent Keepalive | `25` | Mantiene vivo el WebSocket. |

Después crea el cliente y descarga su `.conf`. Si el cliente ya existía, revisa que el `.conf` tenga `Endpoint = 127.0.0.1:51820` y `MTU = 1280`, o edítalo a mano.

## 2. En tu PC (Windows)

1. Descarga wstunnel de <https://github.com/erebe/wstunnel/releases> (`wstunnel_*_windows_amd64.tar.gz`) y extrae `wstunnel.exe`.
2. Abre una terminal y déjala abierta mientras uses la VPN:
   ```powershell
   .\wstunnel.exe client -L "udp://127.0.0.1:51820:wg-easy:51820?timeout_sec=0" `
     -P <PREFIJO_SECRETO> wss://<CODESPACE_NAME>-8080.app.github.dev
   ```
   En Linux/macOS es igual, con `\` en vez de `` ` `` para cortar la línea.
3. Importa el `.conf` en la app de WireGuard y activa el túnel.

### Opción: cliente con interfaz gráfica

wstunnel oficial es solo de línea de comandos. Cualquier GUI de terceros sirve si permite configurar los mismos parámetros:

- Descárgala de su repositorio original: va a manejar el tráfico de la VPN.
- Debe usar una versión de wstunnel compatible con la del servidor (`docker logs wstunnel | head -1`; hoy 11.x). Con versiones 9 o anteriores el protocolo puede no coincidir.

| Campo (el nombre puede variar) | Valor |
|---|---|
| Modo | **Client** |
| Servidor / Remote / URL | `wss://<CODESPACE_NAME>-8080.app.github.dev` |
| Tipo de túnel | **Local to remote**, protocolo **UDP** |
| Local (bind) | `127.0.0.1:51820` |
| Remote / destino | `wg-easy:51820` |
| UDP timeout | `0` (sin expiración) |
| HTTP upgrade path prefix (`-P`) | el contenido de `secrets/wstunnel_path_prefix.txt` |
| TLS | Sí (`wss`). No hace falta configurar certificados: el de `*.app.github.dev` es de GitHub. |

Si la GUI acepta los argumentos completos, pega:

```
client -L "udp://127.0.0.1:51820:wg-easy:51820?timeout_sec=0" -P <PREFIJO_SECRETO> wss://<CODESPACE_NAME>-8080.app.github.dev
```

Después: inicia el túnel en la GUI, revisa que el `.conf` tenga `Endpoint = 127.0.0.1:51820` y `MTU = 1280`, y activa el túnel en la app de WireGuard.

## 3. Comprobar

- Desde el PC: `ping 10.8.0.1` responde.
- Desde el PC: `http://10.8.0.1:51821` abre el panel de wg-easy, y los servicios de la red interna (`172.30.0.0/16`) son accesibles.
- En el Codespace: `docker exec wg-easy wg show` muestra el peer con `latest handshake` reciente.
- En el Codespace: `docker logs wstunnel` muestra `Tunnel accepted` con tu IP en `forwarded_for`.

Si no hay handshake: revisa que la terminal de wstunnel siga abierta, que el puerto 8080 sea **Public** y que el prefijo sea el correcto. Si el prefijo está mal o el destino no es `wg-easy:51820`, el log muestra `Rejecting connection`.

## Limitaciones

- Cada cliente necesita wstunnel corriendo. En el celular no es práctico.
- Hay más latencia que con UDP directo (UDP dentro de TCP dentro de TLS).
- Si el Codespace se suspende o cambia de nombre, cambia la URL y hay que reconectar.

## Apagar

```bash
sudo docker compose -p wstunnel -f services/wstunnel/compose.yml down
gh codespace ports visibility 8080:private -c "$CODESPACE_NAME"
```
