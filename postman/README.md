# Colección de Postman

16 peticiones del contrato con pruebas automáticas (59 aserciones): estado de `X-Request-Id`, esquemas de respuesta, filtros, paginación, evaluación de lotes y errores del esquema común.

| Carpeta | Peticiones |
| --- | --- |
| 1. Operación | `GET /health`, `GET /openapi.yaml` |
| 2. Estado de alertas | vista del Equipo 6, filtros por planta, severidad y activo, paginación |
| 3. Evaluar lotes | batería crítica (`modo=paralelo`), turbina y panel (`modo=secuencial`), desde Telemetría |
| 4. Errores del contrato | cinco 400 (`lecturas` y `plantaId` juntos, fecha sin zona, JSON malformado, `limit`, `X-Equipo-Consumidor`) y un 404 |

## Importar

En Postman: **Import** y arrastre los cuatro `.json` de esta carpeta. Elija el entorno arriba a la derecha y use **Run collection** para ejecutar todo con sus pruebas.

| Entorno | `baseUrl` | Cuándo |
| --- | --- | --- |
| Voltrix Alertas · EC2 | `http://voltrix-alertas.inmemorialake.dev:8080` | Fuera de la red de la universidad |
| Voltrix Alertas · EC2 por túnel SSH | `http://localhost:18080` | En el campus (el Fortinet bloquea el dominio) |
| Voltrix Alertas · Local | `http://localhost:8080` | Con el compose local levantado |

Túnel para el entorno "EC2 por túnel SSH". Va a la instancia real; solo evita el filtro de la red:

```bash
ssh -i deploy/iac/ec2/voltrix-alertas.pem -f -N -L 18080:localhost:8080 ubuntu@3.151.244.68
# al terminar: pkill -f "[s]sh -i.*-L 18080"
```

## Desde la terminal (Newman)

```bash
docker run --rm --network host -v "$PWD/postman":/etc/newman postman/newman:6-alpine \
  run voltrix-alertas.postman_collection.json -e ec2-tunel.postman_environment.json
```

## Regenerar

Los `.json` salen de [`generar.py`](generar.py): `python3 postman/generar.py postman`.
