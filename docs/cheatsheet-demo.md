# Cheatsheet de la demo · Avance 1

Sigue el orden del guion (partes 7 y 8). Se usan **tres terminales** en fish, abiertas en la raíz del repo. En el campus el Fortinet bloquea el dominio, así que la API se alcanza por **túneles SSH a la instancia**. La IP y el dominio siguen siendo los reales; el túnel solo evita el filtro de la red.

| Puerto local | Túnel | Lo usa |
| --- | --- | --- |
| `1080` | SOCKS (`-D`) | `curl` con el dominio real (terminal 1) |
| `18080` | Reenvío directo a la API de EC2 (`-L`) | Postman, entorno "EC2 por túnel SSH" |
| `18081` | `kubectl port-forward` | Floci (terminal 3) |

## 0. Antes de entrar (unos 10 minutos)

```fish
cd ~/Materias\ 2026-II/Infraestrucuturas\ Paralelas\ y\ Distribuidas/Proyecto/voltrix-alertas-notificaciones

# Túneles a la instancia (si ya están abiertos, el comando falla sin daño)
ssh -i deploy/iac/ec2/voltrix-alertas.pem -f -N -D 1080 ubuntu@3.151.244.68
ssh -i deploy/iac/ec2/voltrix-alertas.pem -f -N -L 18080:localhost:8080 ubuntu@3.151.244.68

# kubectl, si no está instalado
sudo pacman -S --needed kubectl

# Floci: levanta el clúster y deja impresas las variables para kubectl (tarda unos 2 minutos)
deploy/iac/floci/desplegar.sh
```

- [ ] GitHub Pages activado y página Redoc abierta.
- [ ] Postman: colección importada y entorno **"Voltrix Alertas · EC2 por túnel SSH"** elegido; `GET /health` en verde.
- [ ] Terminales 1, 2 y 3 preparadas (abajo).
- [ ] `docs/avance-1.md` abierto por si falla la red.

## Terminal 1 · API en EC2 (parte 7)

```fish
set -gx ALL_PROXY socks5h://localhost:1080      # curl sale por la instancia
set -gx NO_PROXY localhost,127.0.0.1
set URL http://voltrix-alertas.inmemorialake.dev:8080
```

**Salud.** Mostrar `200`, `X-Request-Id` y `disponible`:

```fish
curl -i $URL/health
```

**Lo que ve el Equipo 6:**

```fish
curl -s -H 'X-Equipo-Consumidor: equipo-6' "$URL/alertas/estado?plantaId=PL-002" | jq
curl -s -H 'X-Equipo-Consumidor: equipo-6' "$URL/alertas/estado" | jq '{totalActivas, porSeveridad, resumenPorActivo}'
```

**Evaluar un lote.** 3 lecturas sobre 45 °C dan 1 alerta crítica con `ocurrencias: 3`:

```fish
curl -s -X POST "$URL/alertas?modo=paralelo&workers=4" -H 'Content-Type: application/json' -H 'X-Equipo-Consumidor: equipo-3' -d '{"lecturas":[
 {"plantaId":"PL-002","activoId":"PL-002-BB-01","fechaHora":"2026-11-26T19:00:00Z","metrica":"temperatura","valor":45.9,"unidad":"C"},
 {"plantaId":"PL-002","activoId":"PL-002-BB-01","fechaHora":"2026-11-26T19:00:10Z","metrica":"temperatura","valor":46.4,"unidad":"C"},
 {"plantaId":"PL-002","activoId":"PL-002-BB-01","fechaHora":"2026-11-26T19:00:20Z","metrica":"temperatura","valor":47.1,"unidad":"C"}]}' | jq
```

Destacar: el tipo se dedujo de `BB`, el umbral es 45 y `metricas` muestra el modo, los workers y la duración.

**Errores del contrato** con el esquema común `Error`:

```fish
curl -s "$URL/alertas/estado?limit=500" | jq
curl -s -X POST $URL/alertas -H 'Content-Type: application/json' -d '{"plantaId":"PL-002","lecturas":[{"plantaId":"PL-002","activoId":"PL-002-BB-01","fechaHora":"2026-11-26T19:00:00Z","metrica":"temperatura","valor":46,"unidad":"C"}]}' | jq
```

**Contrato servido tal cual:**

```fish
curl -sI $URL/openapi.yaml
```

**Opcional: las pruebas de contrato contra EC2**, unos 5 s (40 pasan y 3 se omiten porque solo aplican en proceso):

```fish
env VOLTRIX_BASE_URL=$URL .venv/bin/pytest -q
```

## Terminal 2 · Dentro de la instancia (parte 7)

SSH no necesita túnel: sale directo desde el campus. Dentro de la instancia la shell es **bash**.

```fish
ssh -i deploy/iac/ec2/voltrix-alertas.pem ubuntu@3.151.244.68
```

```bash
cd /opt/voltrix-alertas
C="sudo docker compose --env-file .env -f deploy/compose/docker-compose.yml"

$C ps                          # api y db healthy; solo api publica 8080
sudo docker stats --no-stream  # límites de 384 y 256 MiB
free -m                        # 1 GiB de RAM + 1 GiB de swap

# Caída de la base de datos: 503 en unos 3 s y recuperación
$C stop db; curl -s -w '  [%{http_code}]\n' localhost:8080/health
$C start db; sleep 5; curl -s -w '  [%{http_code}]\n' localhost:8080/health

# Logs JSON con el equipo consumidor y el X-Request-Id
$C logs api | grep equipo-6 | tail -3
$C logs api | grep equipo-3 | tail -1 | jq   # la petición del lote recién hecha
```

Si `jq` no está en la instancia, quite el `| jq`.

## Terminal 3 · Floci (parte 8)

En esta terminal **no** defina `ALL_PROXY`. Cargue las variables del operador, que `desplegar.sh` deja en un archivo ignorado por git:

```fish
source deploy/iac/floci/operador.fish
```

```fish
kubectl get nodes
kubectl -n voltrix-alertas get deploy,pods,svc
kubectl -n voltrix-alertas port-forward svc/alertas-api 18081:8080 &
curl -s localhost:18081/health | jq

aws eks describe-cluster --name voltrix-alertas --query 'cluster.[status,version,roleArn]'
aws iam list-roles                                  # AccessDenied: mínimo privilegio
aws eks delete-cluster --name voltrix-alertas       # AccessDeniedException

# Migraciones: una réplica aplicó 001 y 002, la otra ninguna (advisory lock)
for p in (kubectl -n voltrix-alertas get pods -l app.kubernetes.io/name=alertas-api -o name); kubectl -n voltrix-alertas logs $p | grep migraciones; end
```

Para terminar el `port-forward`: `kill %1`.

## Si algo falla

| Síntoma | Solución |
| --- | --- |
| `curl` responde `403` con HTML de Fortinet | Falta `ALL_PROXY` en esa terminal o el túnel 1080 está caído; vuelva a abrirlo |
| `curl: (97)` o `Connection refused` en el 1080 | `ssh -i deploy/iac/ec2/voltrix-alertas.pem -f -N -D 1080 ubuntu@3.151.244.68` |
| Postman: `ECONNREFUSED localhost:18080` | Abra el túnel `-L 18080` (paso 0) |
| Postman: la URL empieza por `{{baseUrl}}` | Falta elegir el entorno, arriba a la derecha |
| `kubectl`: `connection refused` en el 6500 | Floci no está arriba: `deploy/iac/floci/desplegar.sh` |
| `port-forward`: `address already in use` | Use otro puerto, por ejemplo `18082:8080` |
| Se cae todo | Muestre las tablas de evidencia de `docs/avance-1.md` |

## Al terminar

```fish
pkill -f "[s]sh -i.*-D 1080"; pkill -f "[s]sh -i.*-L 18080"
docker compose -f deploy/iac/floci/docker-compose.yml down
docker stop floci-aws-eks-voltrix-alertas floci-aws-ecr-registry
```
