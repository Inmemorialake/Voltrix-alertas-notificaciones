# Diseño y contrato: servicio de Alertas y Notificaciones

**Equipo 3 · Voltrix Energy**\
Curso 750023C Infraestructuras Paralelas y Distribuidas, Univalle, 2026-2\
Profesor: Manuel Alejandro Pastrana Pardo, PhD\
Entrega: Diseño y contrato, 19 de noviembre de 2026

| Integrante | Código | Correo | Rol en la célula |
| --- | --- | --- | --- |
| Andrés Gerardo González Rosero | 202416541 | andresgerardogonzales@gmail.com | Por definir |
| Freddy Alexander Melo Buitrago | 202125498 | freddy.melo@correounivalle.edu.co | Por definir |
| Sarahy Gisselle Caicedo Betancourth | 202610315 | sarahy.caicedo@correounivalle.edu.co | Por definir |
| Juan David Guar | 202341909 | juan.guar@correounivalle.edu.co | Por definir |
| Verónica Andreina Granados López | 202123263 | veronica.granados@correounivalle.edu.co | Por definir |

El contrato OpenAPI se entrega aparte, en el archivo `openapi.yaml`.

## 1. Responsabilidad del servicio

Alertas y Notificaciones evalúa las lecturas de telemetría contra umbrales operativos y registra las alertas de condiciones críticas o urgentes, sin duplicarlas ni perderlas. Es un servicio de entidad: su dato principal es la alerta y su estado.

- **Consume:** Telemetría de Plantas (Equipo 2), con `GET /telemetria/{plantaId}`, para traer las lecturas de una planta.
- **Lo consume:** Mantenimiento Predictivo (Equipo 6), que lee `GET /alertas/estado` para generar órdenes de mantenimiento.
- **Condiciones que detecta** (las del caso): sobrecalentamiento de baterías, caída de generación por falla de un panel y viento fuera del rango operativo de las turbinas.
- **Problema que corrige:** el sistema actual produjo notificaciones duplicadas y perdió una alerta crítica por una condición de carrera entre dos procesos que escribían el mismo registro de estado. Este servicio debe demostrar que ese caso ya no ocurre.

Fuera de alcance: el envío real de correos o SMS. La notificación se registra y su despacho se simula con una latencia artificial, porque lo evaluado es el control de concurrencia.

## 2. Arquitectura del servicio

Una petición `POST /alertas` recibe un lote, lo parte entre N workers que evalúan umbrales en paralelo y escriben en un registro compartido protegido por locks. Las alertas nuevas o actualizadas pasan por una cola thread-safe a un despachador, que las persiste en PostgreSQL.

```mermaid
flowchart TB
    TEL["Telemetría de Plantas<br/>(Equipo 2)"]
    MAN["Mantenimiento Predictivo<br/>(Equipo 6)"]
    subgraph SVC["Servicio Alertas y Notificaciones (Equipo 3)"]
        API["API REST<br/>FastAPI"]
        PART["Particionador<br/>del lote"]
        W1["Worker 1"]
        W2["Worker 2"]
        WN["Worker N"]
        REG[("Contadores por activo +<br/>registro de alertas activas<br/>(locks por franja)")]
        COLA[["Cola thread-safe<br/>de notificaciones"]]
        DESP["Despachador"]
    end
    DB[("PostgreSQL<br/>índice único parcial")]

    TEL -- "GET /telemetria/{plantaId}" --> API
    API --> PART
    PART --> W1
    PART --> W2
    PART --> WN
    W1 --> REG
    W2 --> REG
    WN --> REG
    REG -- "alerta nueva o actualizada" --> COLA
    COLA --> DESP
    DESP -- "INSERT ... ON CONFLICT" --> DB
    API -- "consulta" --> DB
    MAN -- "GET /alertas/estado" --> API
```

| Componente | Tecnología | Función |
| --- | --- | --- |
| API REST | Python 3.12, FastAPI, Uvicorn | Expone los endpoints del contrato, valida entradas y aplica límite de tasa (429) |
| Cliente de Telemetría | httpx, URL inyectada por variable de entorno | Trae las lecturas de una planta cuando la petición trae `plantaId` |
| Evaluador | `concurrent.futures.ThreadPoolExecutor` | Parte el lote en N bloques y evalúa umbrales en paralelo |
| Registro compartido | `dict` en memoria + `threading.Lock` por franja | Contadores de violaciones por activo y alertas activas |
| Cola de notificaciones | `queue.Queue(maxsize)` | Desacopla la detección del despacho; si se llena, la API responde 503 |
| Despachador | Hilos consumidores | Simula el envío y persiste con `INSERT ... ON CONFLICT` |
| Base de datos | PostgreSQL 16 (alpine) | Umbrales y alertas; índice único parcial evita duplicados entre réplicas |

## 3. Modelo de datos y umbrales

El servicio guarda dos tablas: `umbral` (la regla) y `alerta` (el estado vigente de cada condición detectada). La clave de deduplicación de una alerta es `(activo_id, metrica, severidad)` mientras su estado sea `ACTIVA`, y la protege un índice único parcial.

```mermaid
erDiagram
    UMBRAL ||--o{ ALERTA : "se aplica en"
    LECTURA }o--o| ALERTA : "dispara o actualiza"
    UMBRAL {
        string id PK
        string tipoActivo "PANEL, TURBINA, BATERIA"
        string metrica
        string operador "GT, LT, FUERA_RANGO"
        float valorAdvertencia
        float valorCritico
        int lecturasMinimas
    }
    ALERTA {
        string id PK
        string plantaId
        string activoId
        string metrica
        string severidad "ADVERTENCIA, CRITICA"
        string estado "ACTIVA, RESUELTA"
        float valorObservado
        float umbralAplicado
        int ocurrencias
        datetime primeraDeteccion
        datetime ultimaDeteccion
    }
    LECTURA {
        string lecturaId "viene de Telemetría"
        string plantaId
        string activoId
        string tipoActivo
        string metrica
        float valor
        datetime timestamp
    }
```

`Lectura` no se guarda en este servicio: llega en el lote o desde Telemetría, se evalúa y se descarta.

Umbrales iniciales. Son supuestos del equipo: se cargan desde un ConfigMap y se pueden ajustar sin recompilar.

| Tipo de activo | Métrica | Advertencia | Crítica |
| --- | --- | --- | --- |
| Batería | temperatura (°C) | > 40 | > 45 |
| Panel solar | caída de potencia frente a la esperada (%) | > 20 | > 40 |
| Turbina eólica | velocidad del viento (m/s) | > 20 | < 3 o > 25 |

Una alerta se crea cuando un activo acumula `lecturasMinimas` lecturas en violación dentro del lote evaluado (por defecto 3). Esto filtra picos aislados y no depende del orden en que los workers procesen las lecturas. El contador por activo es el recurso compartido que se protege en la sección 5.

## 4. Contrato de la API

El contrato completo está en `openapi.yaml` (OpenAPI 3.0.3, validado con `openapi-spec-validator`). Cubre los dos endpoints mínimos del enunciado más `/health`.

| Método y ruta | Qué hace | Respuestas |
| --- | --- | --- |
| `POST /alertas` | Evalúa un lote de lecturas (en el cuerpo, o traídas de Telemetría con `plantaId`) y registra o actualiza alertas. Parámetros `modo` (secuencial o concurrente) y `workers` para el benchmark. | 200, 400, 429, 502, 503 |
| `GET /alertas/estado` | Alertas vigentes con totales por severidad y por planta. Filtros: `plantaId`, `activoId`, `severidad`, `estado`, `limite`. | 200, 400, 429, 503 |
| `GET /health` | Estado del servicio, de la base de datos y de la conexión con Telemetría. | 200, 503 |

La respuesta de `POST /alertas` incluye `tiempoMs`, `modo`, `workers` y `duplicadasEvitadas`, así que cada llamada deja evidencia del efecto de la técnica. Ante sobrecarga (cola llena) responde 503 con `Retry-After`; ante exceso de tasa, 429.

Ejemplo de petición:

```json
{
  "lecturas": [
    { "lecturaId": "L-000101", "plantaId": "PL-07", "activoId": "BAT-07-02",
      "tipoActivo": "BATERIA", "metrica": "temperatura", "valor": 46.3,
      "unidad": "C", "timestamp": "2026-11-19T13:05:00Z" }
  ]
}
```

## 5. Estrategia de concurrencia

La técnica exigida para este servicio es el **control explícito de concurrencia sobre un recurso compartido**. Los workers comparten tres recursos, y cada uno tiene su mecanismo.

| Recurso compartido | Condición de carrera sin control | Mecanismo |
| --- | --- | --- |
| Contador de violaciones por activo | Dos workers leen el mismo valor y ambos escriben valor + 1: se pierde un incremento, el activo no llega al mínimo y **se pierde una alerta crítica** | `threading.Lock` por franja: 64 locks, el activo usa el de índice `hash(activoId) % 64` |
| Registro de alertas activas | Dos workers comprueban "no existe alerta" a la vez y ambos la crean: **notificación duplicada** | El mismo lock de franja vuelve atómico el par comprobar y crear |
| Cola de notificaciones | Productores y consumidores modificando una lista común sin sincronizar | `queue.Queue` (thread-safe) con tamaño máximo; si se llena, la API responde 503 |

Las dos carreras de la tabla son exactamente las dos fallas que describe el caso. Por eso la evidencia mostrará una versión sin locks que las reproduce y una versión con locks que no. El diagrama muestra la notificación duplicada y cómo el lock la evita.

```mermaid
sequenceDiagram
    participant W1 as Worker 1
    participant W2 as Worker 2
    participant R as Registro de alertas
    Note over W1,R: Sin control: carrera de comprobar y crear
    W1->>R: ¿existe alerta BAT-07-02 / CRITICA?
    W2->>R: ¿existe alerta BAT-07-02 / CRITICA?
    R-->>W1: no
    R-->>W2: no
    W1->>R: crear alerta y notificar
    W2->>R: crear alerta y notificar
    Note over R: Resultado: 2 notificaciones de la misma condición
    Note over W1,R: Con lock de franja: comprobar y crear es atómico
    W1->>R: adquirir lock(franja de BAT-07-02)
    W2->>R: adquirir lock(misma franja)
    Note over W2: espera
    W1->>R: no existe, crear alerta y encolar notificación
    W1->>R: liberar lock
    R-->>W2: lock concedido
    W2->>R: ya existe, ocurrencias + 1
    W2->>R: liberar lock
    Note over R: Resultado: 1 alerta con ocurrencias = 2
```

**Por qué locks por franja y no un lock global.** Un solo lock serializaría a todos los workers y anularía la ganancia. Con 64 franjas, dos workers solo esperan cuando tocan activos de la misma franja.

**Entre réplicas.** En Floci EKS corren 2 réplicas, y un lock de Python no cruza procesos. La base de datos cierra ese hueco: el índice único parcial sobre `(activo_id, metrica, severidad) WHERE estado = 'ACTIVA'` y la escritura `INSERT ... ON CONFLICT DO UPDATE SET ocurrencias = alerta.ocurrencias + EXCLUDED.ocurrencias` hacen que dos réplicas que detectan la misma condición terminen en una sola alerta.

**Sobre el GIL.** La comparación contra un umbral es una operación corta de CPU, y en CPython los hilos no la aceleran. La ganancia de tiempo viene de solapar la espera de E/S (escrituras en la base de datos y despacho simulado de notificaciones). Si el benchmark muestra que la evaluación pura domina, se prueba `ProcessPoolExecutor` para esa fase, con un único agregador que mantiene el registro.

## 6. Plan de benchmark

El benchmark compara tres versiones del mismo procesamiento sobre los mismos lotes, se ejecuta en local (no en EC2) y declara núcleos, RAM y sistema operativo del equipo.

| Versión | Qué es | Para qué sirve |
| --- | --- | --- |
| A. Secuencial | Un hilo, lectura por lectura | Línea base de tiempo y oráculo de resultados correctos |
| B. Concurrente sin locks | N workers, sin sincronización | Evidenciar la condición de carrera (duplicadas y perdidas) |
| C. Concurrente con control | N workers, locks por franja y cola thread-safe | Versión entregable: misma salida que A, en menos tiempo |

- **Datos:** generador sintético con semilla fija; lotes de 1 000, 10 000 y 50 000 lecturas para 40 y 80 plantas; cerca de 5 % de lecturas en violación, concentradas en pocos activos para forzar contención.
- **Parámetros:** workers = 1, 2, 4 y 8; una corrida de calentamiento y 5 repeticiones por combinación; se reporta la mediana.
- **Métricas:** tiempo total; speedup = tiempo de A / tiempo de C; eficiencia = speedup / workers; alertas duplicadas y perdidas frente al oráculo A.
- **Criterio de aceptación:** C produce el mismo conjunto de alertas que A en todas las corridas, y B muestra al menos una discrepancia. Si la carrera no aparece de forma natural, se ensancha la ventana entre leer y escribir con una pausa corta, y se declara en el informe.
- **Reproducibilidad:** un script `bench/benchmark.py` con parámetros por línea de comandos que genera un CSV y la gráfica, ejecutable por el docente con un solo comando.

## 7. Despliegue

### Componente B: EC2 con docker-compose

- Dos contenedores en una red de compose: `api` y `db` (postgres:16-alpine). Solo se publica el puerto de la API (propuesto: 8003); `db` no publica puertos.
- Límites de memoria para la instancia de 1 GiB: `api` 384 MiB y `db` 256 MiB, ambos con `restart: unless-stopped`. PostgreSQL configurado liviano (`shared_buffers=32MB`, `max_connections=20`, `work_mem=2MB`) y swap de 1 GiB en la instancia.
- `/health` para verificación; 429 por límite de tasa y 503 con cola llena o base de datos caída.
- La URL de Telemetría se inyecta por variable de entorno, nunca en el código.
- Instancia creada como código (Terraform o script de user-data) para que un tercero la reproduzca sin pasos manuales. Antes se verifica la fecha de creación y el plan de la cuenta AWS para elegir un tipo de instancia elegible.
- Evidencia de memoria con `docker stats` y `free -m` durante la prueba de consumo.

### Componente A: Floci EKS

- Clúster EKS emulado con Floci, creado como código, con un rol IAM de mínimo privilegio.
- Manifiestos: Deployment con 2 réplicas (sondas de liveness y readiness sobre `/health`, `requests` y `limits` de memoria), Service, ConfigMap (umbrales, número de workers, URL de Telemetría) y Secret (credenciales de la base de datos).
- Demostración con `kubectl get pods,svc` y peticiones contra el Service.

### Operación y directorio compartido

- Logs estructurados en JSON con `modo`, `workers`, `tiempoMs` y `duplicadasEvitadas` por lote, para verificar el efecto de la técnica en producción simulada.
- El equipo registra y mantiene su fila en el directorio compartido de servicios que crea el Equipo 1: URL base en EC2, URL del contrato OpenAPI, URL de `/health`, servicios que consume, fecha de actualización y contacto.

## 8. Supuestos, pendientes y plan de trabajo

**Supuestos por confirmar con otros equipos**

- El formato de `Lectura` y el endpoint `GET /telemetria/{plantaId}` (con filtros `desde` y `hasta`) deben coincidir con el contrato del Equipo 2.
- Los campos que necesita el Equipo 6 de `GET /alertas/estado`.
- Los valores de los umbrales, que son supuestos del equipo y no vienen en el enunciado.

**Reparto propuesto para 5 integrantes**

| Frente | Responsable |
| --- | --- |
| API, contrato y cliente de Telemetría | Por asignar |
| Núcleo concurrente (workers, locks, cola) | Por asignar |
| Benchmark y evidencia de la carrera | Por asignar |
| docker-compose, EC2 e IaC | Por asignar |
| Floci EKS y manifiestos (requiere Docker en modo root) | Por asignar |

**Cronograma**

| Fecha | Entrega | Qué lleva este servicio |
| --- | --- | --- |
| 19 nov 2026 | Diseño y contrato | Este documento y `openapi.yaml` |
| 26 nov 2026 | Avance 1 | Esqueleto en EC2 con datos de ejemplo del contrato y clúster creado en Floci EKS |
| 3 dic 2026 | Avance 2 | Versiones secuencial y concurrente, benchmark preliminar, 2 réplicas y consumo real de Telemetría |
| 10 dic 2026 | Entrega final | Todo completo, IaC, consumo contra versiones finales y sustentación individual |
