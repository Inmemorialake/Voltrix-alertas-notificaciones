# Voltrix Energy · Alertas y Notificaciones

Servicio del **Equipo 3** en la plataforma de monitoreo distribuido de Voltrix Energy. Evalúa lecturas de telemetría contra umbrales operativos y registra alertas **sin duplicados ni pérdidas**, con control explícito de concurrencia sobre recursos compartidos.

Proyecto del curso **750023C Infraestructuras Paralelas y Distribuidas**, Universidad del Valle, 2026-2.
Profesor: Manuel Alejandro Pastrana Pardo, PhD.

## Qué hace

- Recibe lotes de lecturas (en el cuerpo de la petición o traídas desde Telemetría de Plantas) y las evalúa en paralelo con N workers.
- Detecta sobrecalentamiento de baterías, caída de generación de paneles y viento fuera de rango en turbinas.
- Protege los recursos compartidos (contadores por activo, registro de alertas y cola de notificaciones) con locks por franja y una cola thread-safe.
- Entre réplicas, evita duplicados con un índice único parcial en PostgreSQL y `INSERT ... ON CONFLICT`.

## Lugar en el sistema

```mermaid
flowchart LR
    TEL["Telemetría de Plantas<br/>(Equipo 2)"] -- "GET /telemetria/{plantaId}" --> ALR["Alertas y Notificaciones<br/>(Equipo 3)"]
    MAN["Mantenimiento Predictivo<br/>(Equipo 6)"] -- "GET /alertas/estado" --> ALR
```

## API

Documentación navegable (Redoc): <https://inmemorialake.github.io/voltrix-alertas-notificaciones/>

Contrato completo: [`openapi.yaml`](openapi.yaml) (OpenAPI 3.0.3, también en [`openapi.json`](openapi.json)). Sigue la plantilla común de Voltrix Energy (Equipo 1) registrada en la hoja Coordinacion_Voltrix.

| Método y ruta | Descripción |
| --- | --- |
| `POST /alertas` | Evalúa un lote de lecturas y registra o actualiza alertas. Admite `?modo=secuencial\|paralelo&workers=N` para el benchmark. |
| `GET /alertas/estado` | Alertas vigentes con totales por severidad y resumen por activo (lo consume el Equipo 6). |
| `GET /health` | Estado del servicio y de su base de datos. |
| `GET /openapi.yaml` | Este contrato. |

## Documentación

- Diseño de la solución: [`docs/diseno.md`](docs/diseno.md).

## Stack

Python 3.12 · FastAPI · Uvicorn · `concurrent.futures` / `threading` · PostgreSQL 16 · Docker y docker-compose (EC2) · Kubernetes sobre Floci EKS.

## Estructura del repositorio

```text
.
├── index.html          # Página Redoc (GitHub Pages)
├── openapi.yaml        # Contrato de la API
├── openapi.json        # Mismo contrato en JSON
├── docs/               # Diseño y evidencia
├── app/                # Código del servicio (FastAPI) y migraciones SQL
├── tests/              # Pruebas que validan las respuestas contra openapi.yaml
├── bench/              # Benchmark secuencial vs paralelo (Avance 2)
├── Dockerfile          # Imagen multi-stage, usuario no root
├── deploy/
│   ├── compose/        # docker-compose para EC2 (api + db)
│   ├── k8s/            # Manifiestos para Floci EKS
│   └── iac/
│       ├── ec2/        # Terraform de la instancia EC2
│       └── floci/      # Floci + Terraform del clúster EKS
└── README.md
```

## Publicar la documentación

En GitHub: *Settings → Pages → Build and deployment → Deploy from a branch*, rama `main`, carpeta `/ (root)`. La página queda en `https://<usuario>.github.io/voltrix-alertas-notificaciones/` y lee `openapi.yaml` del mismo repo.

## Cómo ejecutar en local

Requisitos: Docker con Compose v2. La API escucha en el puerto común `8080`.

```bash
cp .env.example .env            # cambie POSTGRES_PASSWORD
docker compose --env-file .env -f deploy/compose/docker-compose.yml up -d --build --wait
curl http://localhost:8080/health
```

Detener: `docker compose --env-file .env -f deploy/compose/docker-compose.yml down` (agregue `-v` para borrar los datos).

Configuración, solo por variables de entorno (ver [`.env.example`](.env.example)):

| Variable | Defecto | Uso |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql://voltrix:voltrix@localhost:5432/alertas` | PostgreSQL. En compose se arma con `POSTGRES_*`. |
| `TELEMETRIA_URL` | vacía | URL base de Telemetría (Equipo 2). Vacía: `POST /alertas` con `plantaId` usa lecturas de ejemplo. |
| `WORKERS` | `4` | Workers por defecto en `modo=paralelo`. |
| `MAX_CONCURRENCIA` | `16` | Peticiones simultáneas antes de responder `429 SOBRECARGA` (no cuenta `/health` ni `/openapi.yaml`). |

Al arrancar, la API aplica las migraciones de [`app/migraciones/`](app/migraciones) (tablas `umbral` y `alerta`, índice único parcial y datos semilla). Usa un advisory lock, así que varias réplicas pueden arrancar a la vez.

### Pruebas

```bash
uv venv -p 3.12 .venv && uv pip install -p .venv/bin/python -r requirements-dev.txt
.venv/bin/pytest                                          # en proceso, con repositorio en memoria
VOLTRIX_BASE_URL=http://localhost:8080 .venv/bin/pytest   # contra el servicio levantado (local o EC2)
```

Las pruebas validan cada respuesta contra [`openapi.yaml`](openapi.yaml) con `openapi-core`: códigos, esquemas y encabezados. Cubren las respuestas 200, 400, 429 y 503.

### Alcance del Avance 1

- `POST /alertas` evalúa de verdad contra los umbrales de [docs/diseno.md](docs/diseno.md#3-modelo-de-datos-y-umbrales): 3 lecturas en violación crean la alerta, el tipo se deduce del ID y la caída de potencia se calcula contra la mediana del panel. Todavía no persiste, por eso `alertasActualizadas` y `duplicadasEvitadas` valen 0.
- `modo=paralelo` ya existe en el contrato, pero delega en la evaluación secuencial. Los workers, los locks por franja y la cola son del Avance 2, y su interfaz está en [`app/concurrencia.py`](app/concurrencia.py).
- `GET /alertas/estado` lee de PostgreSQL las alertas semilla (`PL-001-PS-07`, `PL-002-BB-01`, `PL-041-TB-03`).

## Desplegar en EC2 (Componente B)

Requisitos: Terraform ≥ 1.6 y credenciales de AWS. La cuenta del equipo usa el perfil `infraestructuras` (`aws login --profile infraestructuras`, región `us-east-2`). La instancia clona este repositorio público, así que despliega lo que esté en `main`.

```bash
cd deploy/iac/ec2
export AWS_PROFILE=infraestructuras
terraform init
terraform plan -var ssh_cidr=45.5.164.0/22 -out=tfplan   # revise el plan antes de aplicar
terraform apply tfplan
terraform output                     # IP, url_base, url_health, url_openapi, ssh
```

Terraform crea:
- un par de claves SSH (la privada se guarda en `deploy/iac/ec2/voltrix-alertas.pem`, ignorado por git);
- un security group que solo abre los puertos 22 y 8080;
- una instancia Ubuntu 24.04 con IMDSv2 y disco gp3 cifrado de 8 GiB.

El plan falla antes de crear nada si el tipo de instancia no es elegible para la capa gratuita de la cuenta.

El [user-data](deploy/iac/ec2/user-data.sh.tftpl) hace todo lo demás:
- crea 1 GiB de swap;
- instala Docker y Compose;
- clona el repo y genera `.env` con una clave aleatoria de PostgreSQL;
- levanta el compose y espera a `/health`.

Tarda unos 2 minutos; el registro queda en `/var/log/voltrix-user-data.log` y en la salida de consola (`aws ec2 get-console-output --instance-id <id> --latest`). Para eliminar todo: `terraform destroy`.

Notas de operación:

- **Costo.** La cuenta tiene el plan gratuito nuevo de AWS (créditos, vence el 10 may 2027). Una `t3.micro` encendida 24/7 consume unos 11–12 USD/mes del crédito: instancia ~7,6, IPv4 pública ~3,6 y EBS ~0,6.
- **La IP no es fija.** Se conserva al reiniciar, pero cambia si la instancia se detiene y arranca. Si cambia, actualice la hoja Coordinacion_Voltrix con el nuevo `terraform output url_base`.
- **El estado de Terraform es local** (`terraform.tfstate`, ignorado por git) y está en el equipo de quien hizo el `apply`. Sin ese archivo, otro integrante no puede modificar ni destruir la instancia con Terraform.
- **Red de la universidad.** El filtro Fortinet de OITEL responde `403` a las URLs sin categoría ("Unrated"), como `http://<ip>:8080`. Pruebe desde otra red, por ejemplo los datos del celular. La IP de salida del campus cambia dentro de `45.5.164.0/22`, por eso `ssh_cidr` usa ese rango y no una sola IP.

### Despliegue vigente

| Campo | Valor |
| --- | --- |
| Instancia | `i-00c45cd7c9644c74b`, `t3.micro` (x86_64, 1 GiB), `us-east-2` |
| URL base | <http://18.222.99.242:8080> |
| `/health` | <http://18.222.99.242:8080/health> |
| Contrato | <http://18.222.99.242:8080/openapi.yaml> |
| Desplegado | 26 nov 2026; `/health` respondió `disponible` a los 100 s del arranque |

### Pendientes del despliegue

- **Elastic IP**, para que la URL de la hoja no cambie. Cuesta lo mismo que la IP actual mientras esté asociada.
- **Subdominio en Cloudflare** (`alertas.<dominio>`, registro DNS-only), creado con Terraform y opcional por variable. También podría evitar el bloqueo "Unrated" del Fortinet, aunque no está garantizado.

## Crear el clúster en Floci EKS (Componente A)

Requisitos: Docker **rootful** (Floci arranca un contenedor `rancher/k3s` por clúster a través del socket), AWS CLI v2 y kubectl. Terraform es opcional: si falta, el script usa la imagen `hashicorp/terraform`.

```bash
deploy/iac/floci/desplegar.sh            # Floci + Terraform + kubeconfig + imagen + manifiestos
deploy/iac/floci/desplegar.sh destruir   # borra el clúster
```

Qué hace el script:

1. Levanta Floci 2.5.0 ([`docker-compose.yml`](deploy/iac/floci/docker-compose.yml)) con `FLOCI_SERVICES_IAM_ENFORCEMENT_ENABLED=true`, para que Floci evalúe las políticas IAM.
2. Aplica [Terraform](deploy/iac/floci/main.tf) contra `http://localhost:4566`. Crea:
   - una VPC con 2 subredes;
   - el rol del clúster, que solo puede asumir `eks.amazonaws.com` de la misma cuenta (condición `aws:SourceAccount`) y lleva únicamente `AmazonEKSClusterPolicy`;
   - el clúster EKS 1.33;
   - un usuario operador que solo puede hacer `eks:DescribeCluster` sobre ese clúster.
3. Genera el kubeconfig con `aws eks update-kubeconfig` usando el operador.
4. Construye la imagen y la importa al nodo k3s (`ctr images import`), porque la imagen no está en un registro.
5. Aplica [`deploy/k8s/`](deploy/k8s) con Kustomize:
   - el Deployment de la API: 2 réplicas, sondas sobre `/health`, `requests` y `limits`, usuario no root y sistema de archivos de solo lectura;
   - el Service, el ConfigMap y un Secret de ejemplo;
   - un PostgreSQL de demostración.

Supuestos sobre Floci, verificados al probar:
- No acepta `test/test` en `aws eks get-token`, por eso existe el usuario operador.
- El rango de puertos 6500–6599 debe quedar libre en el host para el API server de k3s.
- El nodegroup sería solo metadatos (k3s tiene un único nodo), así que no se crea.

## Evidencia del Avance 1

Comandos que demuestran cada punto. `B` es la URL base: `http://localhost:8080` en local o el output `url_base` de Terraform en EC2.

```bash
B=http://18.222.99.242:8080

# Salud y contrato (X-Request-Id en toda respuesta)
curl -i $B/health
curl -sI $B/openapi.yaml                       # content-type: application/yaml

# Estado de alertas (lo consume el Equipo 6) con filtros y paginación
curl -s -H 'X-Equipo-Consumidor: equipo-6' "$B/alertas/estado" | jq '{totalActivas, porSeveridad, resumenPorActivo}'
curl -s "$B/alertas/estado?plantaId=PL-041&estado=todas&limit=1&offset=1" | jq '{total, datos: [.datos[].id]}'

# Evaluar un lote: crea 1 alerta crítica y devuelve MetricasProcesamiento
curl -s -X POST "$B/alertas?modo=paralelo&workers=4" -H 'Content-Type: application/json' \
  -H 'X-Equipo-Consumidor: equipo-6' -d '{"lecturas": [
  {"plantaId":"PL-002","activoId":"PL-002-BB-01","tipoActivo":"banco_baterias","fechaHora":"2026-11-25T13:05:00Z","metrica":"temperatura","valor":46.3,"unidad":"C"},
  {"plantaId":"PL-002","activoId":"PL-002-BB-01","tipoActivo":"banco_baterias","fechaHora":"2026-11-25T13:05:10Z","metrica":"temperatura","valor":47.1,"unidad":"C"},
  {"plantaId":"PL-002","activoId":"PL-002-BB-01","tipoActivo":"banco_baterias","fechaHora":"2026-11-25T13:05:20Z","metrica":"temperatura","valor":45.9,"unidad":"C"}]}' | jq

# 400 SOLICITUD_INVALIDA con el esquema común Error
curl -si -X POST $B/alertas -H 'Content-Type: application/json' \
  -d '{"lecturas":[{"plantaId":"PL-002","activoId":"PL-002-BB-01","fechaHora":"2026-11-25T13:05:00Z","metrica":"temperatura","valor":46,"unidad":"C"}],"plantaId":"PL-002"}'

# Las respuestas del servicio desplegado cumplen el contrato
VOLTRIX_BASE_URL=$B .venv/bin/pytest
```

En la instancia (`ssh -i deploy/iac/ec2/voltrix-alertas.pem ubuntu@<ip-ec2>`, luego `cd /opt/voltrix-alertas`):

```bash
C="sudo docker compose --env-file .env -f deploy/compose/docker-compose.yml"
$C ps                                   # api y db healthy; solo 8080 publicado
sudo docker stats --no-stream           # api ≤ 384 MiB, db ≤ 256 MiB
free -m                                 # 1 GiB de RAM + 1 GiB de swap
$C logs api | grep equipo-6             # logs JSON con requestId y X-Equipo-Consumidor

# 503 en /health con la base de datos detenida, y recuperación
$C stop db && curl -i localhost:8080/health
$C start db && sleep 5 && curl -i localhost:8080/health
```

Floci EKS:

```bash
kubectl get nodes
kubectl -n voltrix-alertas get deploy,pods,svc            # 2/2 réplicas de alertas-api
kubectl -n voltrix-alertas port-forward svc/alertas-api 18080:8080 &
curl -s localhost:18080/health
aws eks describe-cluster --name voltrix-alertas --query 'cluster.[status,version,roleArn]'
aws iam list-roles   # con el operador: AccessDenied (mínimo privilegio)
```

Resultados de la verificación local del 26 nov 2026:
- `docker stats`: api 58 MiB / 384 MiB y db 15 MiB / 256 MiB.
- `/health` responde 503 en unos 3 s con la base de datos detenida y vuelve a 200 al arrancarla.
- Las pruebas pasan en proceso y contra el compose.
- En Floci, el nodo `v1.33.1+k3s1` queda `Ready` y las 2 réplicas `Running`. El operador recibe `AccessDenied` en `iam:ListRoles` y `eks:DeleteCluster`.

## Cronograma

| Fecha | Entrega | Estado |
| --- | --- | --- |
| 19 nov 2026 | Diseño y contrato OpenAPI | Entregado |
| 26 nov 2026 | Avance 1: esqueleto en EC2 y clúster en Floci EKS | Desplegado |
| 3 dic 2026 | Avance 2: versiones secuencial y paralela, benchmark, 2 réplicas, consumo real | Pendiente |
| 10 dic 2026 | Entrega final y sustentación | Pendiente |

## Equipo 3

| Integrante | Código | Correo | GitHub |
| --- | --- | --- | --- |
| Andrés Gerardo González Rosero | 202416541 | andres.gerardo.gonzalez@correounivalle.edu.co | [@Inmemorialake](https://github.com/Inmemorialake) |
| Juan David Guar | 202341909 | juan.guar@correounivalle.edu.co | [@juan-guar](https://github.com/juan-guar) |
| Sarahy Gisselle Caicedo Betancourth | 202610315 | sarahy.caicedo@correounivalle.edu.co | [@Gimmsy](https://github.com/Gimmsy) |
| Verónica Andreina Granados López | 202123263 | veronica.granados@correounivalle.edu.co | [@DarkXPrincess](https://github.com/DarkXPrincess) |
| Freddy Alexander Melo Buitrago | 202125498 | freddy.melo@correounivalle.edu.co | [@FoxArtMotion](https://github.com/FoxArtMotion) |
