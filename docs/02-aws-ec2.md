# 02 — Infraestructura AWS (EC2)

## 2.1 Capa gratuita: qué aplica

| Tipo de cuenta | Instancias gratuitas | ¿`t3.small` (2 vCPU / 2 GiB) gratis? |
|----------------|----------------------|--------------------------------------|
| Creada **desde el 15-jul-2025** (Free Plan con créditos, 6 meses) | t3.micro, **t3.small**, t4g.micro, t4g.small, c7i-flex.large, m7i-flex.large | Sí, consume créditos (hasta USD 200) |
| Creada **antes** (Free Tier legado, 12 meses) | 750 h/mes de t2.micro / t3.micro (1 GiB) | No: ~USD 0.0208/h ≈ USD 15/mes (us-east-1) |

> Verificar en la consola: al lanzar la instancia, el tipo elegible muestra la etiqueta **"Free tier eligible"**.
> También se cobran las IPv4 públicas (USD 0.005/h) fuera de lo que cubra el plan.

Se elige **`t3.small` (x86_64)** sobre `t4g.small` (ARM) para evitar incompatibilidades de imágenes Docker.

## 2.2 Alerta de costos (hacer primero)

1. Consola → **Billing and Cost Management → Budgets → Create budget**.
2. Plantilla **Zero spend budget** (o *Monthly cost budget* de USD 5).
3. Correo de notificación → Crear.

## 2.3 Par de llaves (SSH)

EC2 → **Key Pairs → Create key pair**
- Nombre: `sd-key` · Tipo: ED25519 · Formato: `.pem`
- Guardar `sd-key.pem` fuera del repositorio (está en `.gitignore`).

En Windows (PowerShell) restringir permisos:
```powershell
icacls .\sd-key.pem /inheritance:r /grant:r "$($env:USERNAME):(R)"
```

## 2.4 Security Group `sd-sg`

Fase actual (sin VPN). `MI_IP` = tu IP pública (`curl ifconfig.me`).

| Tipo | Puerto | Origen | Uso |
|------|--------|--------|-----|
| SSH | 22/tcp | MI_IP/32 | Administración |
| Custom TCP | 9443/tcp | MI_IP/32 | Portainer HTTPS |
| Custom TCP | 9000/tcp | MI_IP/32 | Portainer HTTP |

Se agregarán reglas por fase. Objetivo final (con VPN): **solo 22/tcp (MI_IP) y 51820/udp (0.0.0.0/0)**.

## 2.5 Lanzar la instancia

EC2 → **Launch instance**:

| Campo | Valor |
|-------|-------|
| Nombre | `sd-nodo-01` |
| AMI | Ubuntu Server 24.04 LTS (x86_64) |
| Tipo | `t3.small` |
| Key pair | `sd-key` |
| Red | VPC por defecto, subred pública, *Auto-assign public IP* = Enable |
| Security group | `sd-sg` |
| Almacenamiento | 30 GiB **gp3** (máximo gratuito) |
| Advanced → *Credit specification* | **Standard** (evita cargos por modo Unlimited de t3) |
| Advanced → *User data* | contenido de [`infra/aws/user-data.sh`](../infra/aws/user-data.sh) |

El *user data* instala Docker + Compose, agrega `ubuntu` al grupo `docker`, configura rotación de logs, swap de 2 GB y zona horaria.

## 2.6 Elastic IP (IP fija)

EC2 → **Elastic IPs → Allocate** → **Associate** a `sd-nodo-01`.
Evita que la IP cambie al detener/iniciar (necesario para WireGuard en la fase 4).

## 2.7 Conexión y verificación

```powershell
ssh -i .\sd-key.pem ubuntu@<ELASTIC_IP>
```
```bash
cloud-init status --wait          # espera a que termine el user-data
docker version && docker compose version   # Compose >= 2.20
free -h                           # debe mostrar Swap: 2.0Gi
```

## 2.8 Subir el proyecto

Opción A — Git (recomendada):
```bash
git clone <URL_REPO> ~/proyecto_final
```
Opción B — copia directa desde Windows:
```powershell
scp -i .\sd-key.pem -r .\proyecto_final ubuntu@<ELASTIC_IP>:~/
```

## 2.9 Ahorro

- Detener la instancia cuando no se use (`Instance state → Stop`). El disco y la Elastic IP asociada se conservan.
- No crear snapshots/AMIs innecesarios (consumen almacenamiento).
