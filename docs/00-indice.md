# Sistema Operativo Distribuido sobre Docker en AWS

Proyecto final — Sistemas Distribuidos (UNINTEP). Base: `Guia_Instalacion_Sistema_Distribuido.pdf`.

## Índice

| # | Documento | Estado |
|---|-----------|--------|
| 01 | [Arquitectura y decisiones de diseño](01-arquitectura-y-decisiones.md) | ✅ |
| 02 | [Infraestructura AWS (EC2)](02-aws-ec2.md) | ✅ |
| 03 | [Orquestador: docker-compose + sdctl](03-orquestador-sdctl.md) | ✅ |
| 04 | [Fase 1 — Portainer CE](04-fase1-portainer.md) | ✅ |
| 05 | Fase 2 — Mosquitto (MQTT) | ⏳ |
| 06 | Fase 3 — Monitoreo (Glances + Grafana) | ⏳ |
| 07 | Fase 4 — VPN WireGuard (wg-easy) | ⏳ |
| 08 | Fase 5 — Samba | ⏳ |
| 09 | Pruebas, demo y sustentación | ⏳ |

## Estructura del repositorio

```
proyecto_final/
├── docker-compose.yml        # Orquestador raíz (include de cada servicio)
├── sdctl.sh                  # Comando personalizado de operación
├── .env.example              # Variables (copiar a .env)
├── infra/aws/user-data.sh    # Bootstrap de la instancia EC2
├── services/
│   └── portainer/
│       ├── compose.yml       # Definición del servicio
│       └── init.sh           # Hook de inicialización (secretos)
├── secrets/                  # Generado por sdctl init (NO versionar)
└── docs/                     # Esta documentación
```
