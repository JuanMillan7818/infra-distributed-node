# Node-RED: tablero de ventas en tiempo real (MQTT)

La web de facturación (Vercel) publica un evento en Mosquitto por cada operación de negocio. Node-RED se suscribe, acumula el día y lo muestra en un tablero que se actualiza solo.

```
[Web facturación · Vercel] --wss (TLS)--> [proxy Codespaces :9001] --ws--> [Mosquitto :9001]
                                                                               |
                                    [Node-RED :1880] <--mqtt :1883 (red-interna)
                                     ├─ /dashboard  tablero (solo lectura)
                                     └─ /           editor de flujos (usuario admin)
```

- **Desacople:** la web no conoce a Node-RED. Solo publica en el broker y cualquier sistema nuevo puede suscribirse sin cambiar la web.
- **Tolerancia a fallos:** si el broker está caído, la venta se guarda igual y solo se pierde el evento. La web tiene un timeout de 4 s y no reintenta.
- **Mínimo privilegio (ACL):** `facturacion` solo **escribe** en `paxia/#`, `nodered` solo **lee** y `admin` puede todo (para depurar).

## Tópicos

| Tópico | Cuándo | Campos principales |
|---|---|---|
| `paxia/<negocio>/ventas/nueva` | venta o cotización | `factura`, `tipo`, `total`, `cliente`, `unidades`, `productos[]` |
| `paxia/<negocio>/inventario/stock-bajo` | un producto vendido quedó en o bajo su mínimo | `producto`, `stock`, `minimo` |
| `paxia/<negocio>/ventas/devolucion` | devolución | `factura`, `monto`, `nota` |
| `paxia/<negocio>/caja/cierre` | cuadre de caja | `esperado`, `contado`, `diferencia` |
| `paxia/<negocio>/creditos/abono` | abono a un crédito | `cliente`, `monto` |

Todos los mensajes son JSON y llevan `evento`, `negocioId` y `ts`.

## Qué muestra el tablero

Es una sola pantalla oscura, tipo centro de operaciones, hecha como un único `ui-template` (Vue) con grilla propia. Se adapta al ancho real: 6 tarjetas por fila en escritorio, 3 en tablet y 2 en celular, sin huecos.

- **Encabezado:** indicador 🟢 EN VIVO / 🔴 SIN CONEXIÓN (estado del broker), tiempo desde el último evento y reloj.
- **Tarjetas animadas:** ventas del día, total vendido (y neto de devoluciones), ticket promedio, devoluciones, abonos y alertas de stock. Los números suben con una animación.
- **Ventas acumuladas:** gráfica de área escalonada con la línea de la meta (`META_DIARIA` en `.env`) y el ritmo de venta por hora.
- **Meta diaria:** anillo de avance que cambia a verde y dorado al superar la meta, más el reparto contado/crédito.
- **Productos más vendidos:** top 5 por monto, con barras.
- **Actividad en vivo:** cada evento entra con una animación, con su ícono y color por tipo.
- **Avisos** (abajo a la derecha, máximo 3): stock bajo, devoluciones, cierres de caja y "meta alcanzada". Llevan cuenta regresiva.

Los acumulados se guardan en el volumen `nodered_data`. Sobreviven a recargas del navegador y a reinicios del contenedor, y vuelven a cero solos al cambiar el día (hora de Bogotá). Para ponerlos en cero a mano, entra al editor y pulsa el botón del nodo **Reiniciar contadores**. Si un apagado brusco daña el archivo del contexto, `settings.js` lo aparta al arrancar: el tablero empieza en cero en vez de quedarse caído.

## 0. Vista previa local (sin Docker)

Levanta un broker de prueba, Node-RED con este `flows.json` y un simulador que publica ventas, devoluciones, stock bajo, abonos y cierres, como lo haría la web. Requiere Node 20 o superior.

```bash
cd services/nodered/tools/preview
npm install
npm start
```

- Tablero: <http://localhost:1880/dashboard>. Editor: <http://localhost:1880> (usuario `admin`, contraseña `admin`).
- Variables opcionales: `PREVIEW_INTERVAL_MS` (por defecto 3000), `META_DIARIA` (por defecto 500000) y `PREVIEW_PORT` / `PREVIEW_MQTT_PORT` (por defecto 1880 / 1883) para correr dos vistas previas a la vez.
- Los acumulados quedan en `tools/preview/.data/`. Bórrala para empezar en cero.

## 1. Levantar en el Codespace

```bash
sudo iptables-legacy -P FORWARD ACCEPT        # en cada arranque del Codespace (ver docs/10-guia-local.md §10.9)
sudo ./manage.sh init                         # genera los secretos mqtt_* y nodered_admin_password
sudo ./manage.sh up mosquitto nodered
gh codespace ports visibility 9001:public -c "$CODESPACE_NAME"
sudo cat secrets/mqtt_facturacion_password.txt   # -> MQTT_PASSWORD en Vercel
```

- **9001 (MQTT WebSocket):** tiene que ser **Public**, porque Vercel no puede iniciar sesión en GitHub. El puerto está protegido con usuario y contraseña, y la cuenta `facturacion` solo puede publicar.
- **1880 (Node-RED):** puede quedar **Private**. Lo abres tú desde el navegador con tu sesión de GitHub.
  - Tablero: `https://<CODESPACE_NAME>-1880.app.github.dev/dashboard`
  - Editor: `https://<CODESPACE_NAME>-1880.app.github.dev/` (usuario `admin`, contraseña en `sudo cat secrets/nodered_admin_password.txt`)

La visibilidad Public de un puerto puede volver a Private al reiniciar el Codespace. Revísala antes de cada demo.

## 2. Configurar la web en Vercel

En *Project → Settings → Environment Variables*:

| Variable | Valor |
|---|---|
| `MQTT_ENABLED` | `true` (con `false` la web no se conecta a nada) |
| `MQTT_URL` | `wss://<CODESPACE_NAME>-9001.app.github.dev` |
| `MQTT_USERNAME` | `facturacion` |
| `MQTT_PASSWORD` | contenido de `secrets/mqtt_facturacion_password.txt` |
| `MQTT_TOPIC_PREFIX` | `paxia` (igual al del `.env` de este repo) |

Después de cambiar variables hay que hacer **Redeploy**: Vercel solo las lee al desplegar. Si creas un Codespace nuevo, cambia su nombre, y con él `MQTT_URL`.

En la EC2 se usa `MQTT_URL=ws://<IP-elástica>:9001`. Hay que abrir 9001/TCP en el Security Group, y conviene un proxy con TLS, porque sin TLS la contraseña MQTT viaja en claro.

## 3. Guion de demo

1. Pon en pantalla la web de facturación a la izquierda y el tablero a la derecha.
2. Haz una venta de contado: en ~1 s sube el contador, se mueve la línea y el medidor, y aparece una fila nueva en la tabla.
3. Vende las últimas unidades de un producto: aparece el aviso **Stock bajo**.
4. Haz una devolución o un cierre de caja: aparece un aviso.
5. Abre el editor (`/`): los nodos muestran el último evento recibido y la barra lateral de *debug* tiene el JSON completo.
6. Para mostrar tolerancia a fallos, ejecuta `sudo ./manage.sh stop mosquitto`. El tablero pasa a 🔴, y aun así la venta en la web **se guarda normal**. Luego `sudo ./manage.sh start mosquitto` y el tablero vuelve a 🟢.

Para ver los mensajes crudos del broker:

```bash
sudo ./manage.sh exec mosquitto sh -c 'mosquitto_sub -u admin -P "$(cat /run/secrets/mqtt_admin_password)" -t "paxia/#" -v'
```

También puedes usar [MQTT Explorer](https://mqtt-explorer.com/) con el usuario `admin`, por WebSocket (`wss://<CODESPACE_NAME>-9001.app.github.dev`, puerto 443).

## Cambiar el flujo

`flows.json` se genera con `tools/gen_flows.py`, igual que el dashboard de Grafana. Los cambios hechos en el editor **se pierden al recrear el contenedor**. Para conservarlos, pásalos al generador y vuelve a desplegar:

```bash
python services/nodered/tools/gen_flows.py services/nodered/flows.json
sudo ./manage.sh up nodered      # pull_policy: build -> reconstruye la imagen con el flujo nuevo
```

## Problemas comunes

| Síntoma | Causa probable |
|---|---|
| Tablero en 🔴 y `docker logs nodered` dice `Connection failed` | `FORWARD DROP` del Codespace (`sudo iptables-legacy -P FORWARD ACCEPT`), o mosquitto caído |
| La web vende pero no llega nada | `MQTT_ENABLED` no es `true`, faltó el Redeploy, el puerto 9001 no está Public o `MQTT_URL` apunta a un Codespace viejo. Revisa los logs de la función en Vercel (`[mqtt] No se publicó …`) |
| `not authorised` en el log de mosquitto | Contraseña de Vercel distinta a `secrets/mqtt_facturacion_password.txt`, o `MQTT_TOPIC_PREFIX` distinto entre la web y este repo |
