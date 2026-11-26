# Operación del servicio

Guía para el equipo: cómo actualizar, revisar y apagar los despliegues. La instalación inicial está en el [README](../README.md).

## Credenciales y archivos locales

La cuenta AWS del curso usa el perfil `infraestructuras`, región `us-east-2`.

```bash
aws login --profile infraestructuras
export AWS_PROFILE=infraestructuras
```

Estos archivos no están en git y solo los tiene quien hizo el `apply`. Guárdelos en un lugar seguro:

| Archivo | Para qué | Si se pierde |
| --- | --- | --- |
| `deploy/iac/ec2/terraform.tfstate` | Terraform sabe qué recursos administra | No se puede modificar ni destruir la instancia con Terraform. Hay que importarlos o borrarlos desde la consola |
| `deploy/iac/ec2/voltrix-alertas.pem` | SSH a la instancia | Sin acceso SSH. Otro `apply` crea una clave nueva y reemplaza la instancia |
| `.env` (en la instancia, `/opt/voltrix-alertas/.env`) | Clave de PostgreSQL generada al arrancar | Se puede regenerar, pero los datos usan la clave original |

## EC2

### Entrar a la instancia

```bash
cd deploy/iac/ec2
ssh -i voltrix-alertas.pem ubuntu@$(terraform output -raw ip_publica)
cd /opt/voltrix-alertas
C="sudo docker compose --env-file .env -f deploy/compose/docker-compose.yml"
```

Si SSH da *timeout*, la IP desde la que se conecta no está en `ssh_cidr` (ver [red de la universidad](#red-de-la-universidad)).

### Desplegar una versión nueva de `main`

En la instancia:

```bash
sudo git pull --ff-only
$C up -d --build --wait
curl -s localhost:8080/health
```

Si no hay acceso SSH, `terraform apply -replace=aws_instance.api` crea una instancia nueva que clona `main`. La Elastic IP se reasocia, así que la URL no cambia.

### Revisar estado y logs

```bash
$C ps
$C logs -f api                       # una línea JSON por petición
$C logs api | grep equipo-6          # consumo de un equipo concreto
sudo docker stats --no-stream
free -m
sudo tail -50 /var/log/voltrix-user-data.log
```

Sin SSH, la salida del arranque se ve con:

```bash
ID=$(aws ec2 describe-instances --filters Name=tag:Name,Values=voltrix-alertas Name=instance-state-name,Values=running \
      --query "Reservations[].Instances[].InstanceId" --output text)
aws ec2 get-console-output --instance-id "$ID" --latest --output text
```

### Detener, encender o destruir

| Acción | Comando | Efecto en costo e IP |
| --- | --- | --- |
| Detener | `aws ec2 stop-instances --instance-ids <id>` | Deja de cobrar la instancia; siguen cobrando el disco (~0,6 USD/mes) y la Elastic IP (~3,6 USD/mes). La IP no cambia |
| Encender | `aws ec2 start-instances --instance-ids <id>` | El compose arranca solo (`restart: unless-stopped`) |
| Destruir | `terraform destroy` | Borra todo. La base de datos solo tiene datos de ejemplo |

Costo con la instancia encendida 24/7: ~11–12 USD/mes del crédito del plan gratuito (vence el 10 may 2027). Créditos restantes:

```bash
aws freetier get-account-plan-state --region us-east-1 --query accountPlanRemainingCredits
```

## Floci EKS

```bash
deploy/iac/floci/desplegar.sh                 # crear o actualizar (idempotente)
deploy/iac/floci/desplegar.sh destruir        # borrar el clúster
docker compose -f deploy/iac/floci/docker-compose.yml down   # apagar Floci
```

Para usar kubectl en otra terminal, el script imprime las variables necesarias (kubeconfig y credenciales del usuario operador).

Problemas conocidos:

- **`No free port available in range 6500-6599`**: algo ocupa esos puertos en el host. Floci publica ahí el API server de cada k3s; no los mapee en su `docker-compose.yml`.
- **`ResourceInUseException: Cluster already exists` justo después de borrar**: Floci tarda unos segundos en liberar el nombre. Espere y vuelva a aplicar.
- **Docker no crea redes (`veth … operation not supported`)**: el kernel se actualizó y no se ha reiniciado. Reinicie el equipo.
- **Pods en `ErrImageNeverPull` o `ImagePullBackOff` de `voltrix-alertas`**: falta importar la imagen al nodo. El paso 4 del script lo hace.

## Red de la universidad

- **HTTP a la IP o al dominio da `403` con una página de Fortinet/OITEL.** El filtro bloquea las URLs sin categoría ("Unrated"): la IP y también `voltrix-alertas.inmemorialake.dev`, que es nuevo. No es un fallo del servicio. Pruebe desde otra red, como los datos del celular o la casa. Para desbloquear el dominio en el campus, use el enlace "por favor siga este enlace" de la página de bloqueo (re-evaluación de Fortinet) y pida una categoría como *Information Technology*.
- **Probar desde el campus: túnel SOCKS por la instancia.** SSH sí sale del campus, así que el tráfico puede salir a internet desde AWS:

  ```bash
  ssh -i deploy/iac/ec2/voltrix-alertas.pem -f -N -D 1080 ubuntu@3.151.244.68
  curl -i --socks5-hostname localhost:1080 http://voltrix-alertas.inmemorialake.dev:8080/health
  ALL_PROXY=socks5h://localhost:1080 VOLTRIX_BASE_URL=http://voltrix-alertas.inmemorialake.dev:8080 .venv/bin/pytest
  google-chrome-stable --proxy-server="socks5://localhost:1080" --user-data-dir=/tmp/chrome-voltrix   # navegador por el túnel
  ```

  En Firefox: *Ajustes → Configuración de red → Proxy manual → SOCKS v5 `localhost` puerto `1080`*, y marque "DNS por proxy". Para cerrar el túnel: `pkill -f "ssh.*-D 1080"`.
- **SSH da *timeout*.** La IP de salida del campus cambia dentro de `45.5.164.0/22` (se vieron `45.5.165.19` y `45.5.167.167`). `terraform.tfvars` (copiado de `example.tfvars`) ya usa ese rango. Para entrar desde la casa, agregue su IP con `/32`.
- **Equipos que consumen desde el campus** se encontrarán el mismo bloqueo. Avíseles en la hoja o en la pestaña "Integraciones".

## Hoja Coordinacion_Voltrix

Fila del Equipo 3. El dominio apunta a la Elastic IP `3.151.244.68` con un registro `A` DNS-only en Cloudflare, que se gestiona a mano. Si se destruye la Elastic IP, actualice ese registro:

| Columna | Valor |
| --- | --- |
| URL base | `http://voltrix-alertas.inmemorialake.dev:8080` |
| URL de `/health` | `http://voltrix-alertas.inmemorialake.dev:8080/health` |
| URL del contrato | Página Redoc del repo o `terraform output -raw url_openapi` |
| Servicios que consume | Equipo 2, Telemetría de Plantas |
| Fecha de actualización y contacto | Andrés Gerardo González Rosero |
