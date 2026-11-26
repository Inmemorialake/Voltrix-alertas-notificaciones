# Avance 1: esqueleto en EC2 y clúster en Floci EKS

**Equipo 3 · Alertas y Notificaciones · 26 nov 2026**

Entregable del enunciado: *esqueleto desplegado en EC2 con datos de ejemplo según el contrato, y clúster creado en Floci EKS*. Este documento resume qué se entregó, cómo verificarlo y qué queda para el Avance 2. Las instrucciones paso a paso están en el [README](../README.md) y la operación diaria en [operacion.md](operacion.md).

## 1. Qué se entregó

| Punto | Estado | Dónde |
| --- | --- | --- |
| API con los 4 endpoints del contrato (`POST /alertas`, `GET /alertas/estado`, `GET /health`, `GET /openapi.yaml`) | Listo | [`app/`](../app) |
| Errores con el esquema común `Error`; los 422 de FastAPI salen como 400 `SOLICITUD_INVALIDA` | Listo | [`app/errores.py`](../app/errores.py) |
| `X-Request-Id` (uuid) en toda respuesta y logs JSON con `X-Equipo-Consumidor` | Listo | [`app/middleware.py`](../app/middleware.py) |
| 429 `SOBRECARGA` con `Retry-After` por límite de peticiones simultáneas | Listo | `MAX_CONCURRENCIA` |
| `/health` con el esquema `Salud`; 503 si la base de datos no responde | Listo | [`app/main.py`](../app/main.py) |
| PostgreSQL: tablas `umbral` y `alerta`, índice único parcial y datos semilla con IDs del Inventario | Listo | [`app/migraciones/`](../app/migraciones) |
| Pruebas que validan las respuestas contra `openapi.yaml` | 43 pruebas | [`tests/`](../tests) |
| Imagen multi-stage, slim, usuario no root (uid 10001) | Listo | [`Dockerfile`](../Dockerfile) |
| docker-compose: api + db en red propia, solo 8080 publicado, límites de memoria, healthchecks | Listo | [`deploy/compose/`](../deploy/compose) |
| EC2 creada con Terraform (`t3.micro`, swap de 1 GiB, Docker, compose al arrancar) | Desplegada | [`deploy/iac/ec2/`](../deploy/iac/ec2) |
| Clúster EKS en Floci con rol IAM de mínimo privilegio | Creado | [`deploy/iac/floci/`](../deploy/iac/floci) |
| Manifiestos: Deployment de 2 réplicas, sondas, `requests`/`limits`, Service, ConfigMap y Secret | Aplicados en Floci | [`deploy/k8s/`](../deploy/k8s) |

### Despliegue vigente en EC2

| Campo | Valor |
| --- | --- |
| URL base | `http://voltrix-alertas.inmemorialake.dev:8080` |
| `/health` | `http://voltrix-alertas.inmemorialake.dev:8080/health` |
| Contrato | `http://voltrix-alertas.inmemorialake.dev:8080/openapi.yaml` |
| IP | `3.151.244.68` (Elastic IP, fija), registro `A` DNS-only en Cloudflare |
| Instancia | `i-00c45cd7c9644c74b`, `t3.micro` (x86_64, 1 GiB, 2 vCPU), `us-east-2`, Ubuntu 24.04 |
| Cuenta | Plan gratuito nuevo de AWS (créditos), perfil `infraestructuras` |

## 2. Alcance del esqueleto

- `POST /alertas` evalúa contra los umbrales del [diseño](diseno.md#3-modelo-de-datos-y-umbrales). Una alerta se crea con 3 lecturas en violación del mismo activo y severidad. El tipo de activo se deduce del ID si falta y la caída de potencia se calcula contra la mediana del panel en el lote. Todavía no persiste, por eso `alertasActualizadas` y `duplicadasEvitadas` valen 0.
- `modo=paralelo` y `workers` ya están en el contrato y en la respuesta (`MetricasProcesamiento`), pero la evaluación aún es secuencial. La interfaz del núcleo concurrente está en [`app/concurrencia.py`](../app/concurrencia.py).
- Con `plantaId`, `desde` y `hasta`, el servicio llama a Telemetría si `TELEMETRIA_URL` está definida. Si no, genera lecturas de ejemplo deterministas.
- `GET /alertas/estado` lee de PostgreSQL 6 alertas semilla (4 activas y 2 resueltas) de `PL-001-PS-07`, `PL-002-BB-01` y `PL-041-TB-03`.

## 3. Evidencia medida

### Local (docker compose), 26 nov 2026

| Verificación | Resultado |
| --- | --- |
| `docker compose ps` | `api` y `db` *healthy*; puertos: `0.0.0.0:8080->8080/tcp` en api, ninguno en db |
| `docker stats` | api 58 MiB / 384 MiB; db 15 MiB / 256 MiB |
| `docker exec … id` | `uid=10001(alertas) gid=10001(alertas)` |
| `GET /health` | 200 `{"estado":"disponible","baseDatos":"ok",…}` |
| `GET /health` con `db` detenida | 503 `{"estado":"no_disponible","baseDatos":"error",…}` en unos 3 s; vuelve a 200 al arrancar `db` |
| `GET /alertas/estado` con `db` detenida | 503 `NO_DISPONIBLE` con `requestId` |
| `GET /openapi.yaml` | 200, `content-type: application/yaml`, idéntico byte a byte al archivo del repo |
| `POST /alertas` (3 lecturas de 45,9–47,1 °C) | 1 alerta `critica` con `ocurrencias: 3` y `umbralAplicado: 45` |
| `POST /alertas` con `lecturas` y `plantaId` | 400 `SOLICITUD_INVALIDA`, `detalles: [{campo: lecturas, …}]` |
| `GET /alertas/estado?limit=500` | 400, `limit: debe ser menor o igual que 200` |
| `pytest` en proceso | 43 aprobadas |
| `VOLTRIX_BASE_URL=http://localhost:8080 pytest` | 38 aprobadas; 3 omitidas porque simulan la base de datos caída y la sobrecarga |

Ejemplo de log, una línea JSON por petición:

```json
{"ts": "2026-11-26T18:30:40.408+00:00", "nivel": "INFO", "logger": "alertas.http", "mensaje": "solicitud",
 "requestId": "fc507f0d-ce1b-42ae-bb1a-b4136a112121", "equipoConsumidor": "equipo-6", "metodo": "GET",
 "ruta": "/alertas/estado", "query": null, "status": 200, "duracionMs": 6.8}
```

### EC2

| Verificación | Resultado |
| --- | --- |
| `terraform plan` | 8 recursos; SSH limitado a un rango, 8080 abierto; precondición de capa gratuita aprobada |
| `terraform apply` | Instancia creada en 14 s |
| Salida de consola (cloud-init) | Compose *healthy* y `/health` → `disponible` a los 100 s del arranque |
| `pytest` contra el dominio público (túnel SOCKS) | 40 aprobadas, 3 omitidas (solo en proceso) |
| DNS `voltrix-alertas.inmemorialake.dev` | Resuelve a `3.151.244.68`; desde internet `/health` → 200 con `X-Request-Id` y `/openapi.yaml` → `application/yaml` |
| Elastic IP y `ssh_cidr` del campus | 1 recurso nuevo y 1 cambio, sin reemplazar la instancia; SSH funciona desde el campus |
| En la instancia | `free -m`: 909 MiB de RAM + 1023 MiB de swap; `docker stats`: api 51 MiB / 384 MiB, db 37 MiB / 256 MiB |

### Floci EKS (Floci 2.5.0)

| Verificación | Resultado |
| --- | --- |
| `terraform apply` desde cero | VPC, 2 subredes, rol del clúster, clúster 1.33 `ACTIVE`, usuario operador |
| `kubectl get nodes` | 1 nodo `Ready`, `v1.33.1+k3s1` |
| `kubectl -n voltrix-alertas get pods` | 2 réplicas de `alertas-api` y `db` en `Running`, 0 reinicios |
| `curl /health` vía `port-forward svc/alertas-api` | 200 `disponible`; `/alertas/estado` → 4 activas |
| Migraciones con 2 réplicas | Una réplica aplicó `001` y `002`; la otra no aplicó ninguna (advisory lock) |
| Operador: `aws iam list-roles` | `AccessDenied` |
| Operador: `aws eks delete-cluster` | `AccessDeniedException` |

## 4. Capturas para la entrega

Tomarlas fuera de la red de la universidad, o desde el campus a través del túnel SOCKS por la instancia, porque el Fortinet bloquea la IP y el dominio, que aún no tiene categoría (ver [operacion.md](operacion.md#red-de-la-universidad)).

- [ ] Navegador o `curl -i` a `http://voltrix-alertas.inmemorialake.dev:8080/health` mostrando `X-Request-Id`
- [ ] `curl` a `/alertas/estado` y a `POST /alertas` contra EC2
- [ ] Un 400 contra EC2
- [ ] En la instancia: `docker compose ps`, `docker stats --no-stream`, `free -m`
- [ ] En la instancia: 503 de `/health` con `db` detenida y recuperación
- [ ] `VOLTRIX_BASE_URL=http://voltrix-alertas.inmemorialake.dev:8080 pytest` en verde
- [ ] Floci: `kubectl get nodes` y `kubectl -n voltrix-alertas get deploy,pods,svc`
- [ ] Fila actualizada en la hoja Coordinacion_Voltrix

## 5. Pendientes

| Pendiente | Para | Nota |
| --- | --- | --- |
| Núcleo concurrente: workers, locks por franja, cola y despachador con `INSERT … ON CONFLICT` | Avance 2 | Interfaz en `app/concurrencia.py` |
| Benchmark secuencial frente a paralelo (`bench/`) | Avance 2 | [Plan en el diseño](diseno.md#6-plan-de-benchmark) |
| Consumo real de Telemetría (Equipo 2) | Avance 2 | Basta con definir `TELEMETRIA_URL` |
| Recategorizar el dominio en Fortinet | Por hacer | Enlace "volver a evaluar" en la página de bloqueo de OITEL |
| HTTPS con Caddy (80/443) | Por decidir | Sale de la convención común; acordarlo con el Equipo 1 |
