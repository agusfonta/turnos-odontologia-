# Arquitectura Propuesta

## Patrones aplicados

| Patrón | Dónde se usa | Por qué |
|---|---|---|
| Monolito modular | Backend FastAPI (routers por dominio) | Velocidad v1 sin microservicios |
| Capas domain/application/infrastructure | Backend | Deja abierta la evolución a multi-tenant |
| Jobs async con Redis | Recordatorios WA | El envío nunca bloquea la reserva |
| Token público por turno | Gestión sin login | Reserva sin fricción, mobile-first |
| Auditoría append-only | Movimientos de turnos | Trazabilidad (Ley 25.326) |

## Estructura de directorios

```
turnos-odontologia/
├── backend/
│   └── app/
│       ├── domain/          # entidades, reglas RN-*
│       ├── application/     # casos de uso (reservar, mover, bloquear)
│       ├── infrastructure/  # SQLAlchemy, repos, Redis, WA client
│       ├── api/             # routers FastAPI + schemas
│       └── core/            # config, seguridad JWT, deps
├── frontend/
│   └── src/
│       ├── features/        # reserva, agenda, turnos
│       ├── shared/          # ui, api client
│       └── pages/           # /reservar, /agenda, /turnos/:token
└── docker-compose.yml       # api + web + postgres + redis
```

## Seguridad

- Autenticación: JWT access corto + refresh (odontólogo/secretaria).
- Autorización: RBAC por rol (ver 03); rutas públicas solo con token por turno.
- Validación de input: schemas estrictos (teléfono E.164, zona horaria).
- Secrets management: solo por variables de entorno, nunca en repo.

## Variables de entorno

| Variable | Descripción | Ejemplo | Sensible |
|---|---|---|---|
| DATABASE_URL | Conexión Postgres | postgresql+psycopg://… | Y |
| REDIS_URL | Cola de jobs | redis://redis:6379/0 | Y |
| JWT_SECRET | Firma de tokens | (generado) | Y |
| WA_PROVIDER_API_KEY | Proveedor WhatsApp | (proveedor) | Y |
| CLINIC_TIMEZONE | Zona agenda | America/Argentina/Buenos_Aires | N |
| CANCEL_MIN_HOURS | Anticipación mínima | 24 | N |
