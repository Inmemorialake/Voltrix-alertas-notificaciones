#!/usr/bin/env bash
# Crea el clúster EKS en Floci y despliega deploy/k8s. Ejecutar desde cualquier carpeta.
# Requisitos: Docker (rootful), AWS CLI v2 y kubectl. Terraform es opcional (si falta, se usa
# la imagen hashicorp/terraform).
#
#   deploy/iac/floci/desplegar.sh            # todo
#   deploy/iac/floci/desplegar.sh destruir   # borra el clúster y los recursos de Floci
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAIZ="$(cd "$DIR/../../.." && pwd)"
CLUSTER="${CLUSTER:-voltrix-alertas}"
IMAGEN="voltrix-alertas:1.0.0"
export KUBECONFIG="${KUBECONFIG_FLOCI:-$DIR/kubeconfig}"

tf() {
  if command -v terraform >/dev/null; then
    terraform -chdir="$DIR" "$@"
  else
    docker run --rm --network host -u "$(id -u):$(id -g)" -v "$DIR":/w -w /w hashicorp/terraform:1.13 "$@"
  fi
}

if [[ "${1:-}" == "destruir" ]]; then
  tf destroy -auto-approve
  exit 0
fi

echo "==> 1. Floci"
docker compose -f "$DIR/docker-compose.yml" up -d
until curl -sf http://localhost:4566/_floci/health >/dev/null; do sleep 2; done

echo "==> 2. Terraform: VPC, rol IAM, clúster EKS y usuario operador"
tf init -input=false >/dev/null
tf apply -auto-approve -input=false

echo "==> 3. kubeconfig con el usuario operador (solo eks:DescribeCluster)"
export AWS_ACCESS_KEY_ID="$(tf output -raw operador_access_key_id)"
export AWS_SECRET_ACCESS_KEY="$(tf output -raw operador_secret_access_key)"
export AWS_REGION=us-east-1 AWS_ENDPOINT_URL=http://localhost:4566
unset AWS_SESSION_TOKEN AWS_PROFILE
aws eks update-kubeconfig --name "$CLUSTER"
kubectl get nodes

echo "==> 4. Imagen de la API importada al nodo k3s"
docker build -t "$IMAGEN" "$RAIZ"
docker save "$IMAGEN" | docker exec -i "floci-aws-eks-$CLUSTER" ctr -n k8s.io images import -

echo "==> 5. Manifiestos"
kubectl apply -k "$RAIZ/deploy/k8s"
kubectl -n voltrix-alertas rollout status deploy/db --timeout=180s
kubectl -n voltrix-alertas rollout status deploy/alertas-api --timeout=180s
kubectl -n voltrix-alertas get pods,svc

# Variables para otra terminal. Archivos ignorados por git: contienen la clave del operador.
umask 077
cat > "$DIR/operador.env" <<EOF
export KUBECONFIG="$KUBECONFIG" AWS_ENDPOINT_URL=http://localhost:4566 AWS_REGION=us-east-1
export AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY"
unset AWS_PROFILE AWS_SESSION_TOKEN
EOF
cat > "$DIR/operador.fish" <<EOF
set -gx KUBECONFIG "$KUBECONFIG"; set -gx AWS_ENDPOINT_URL http://localhost:4566; set -gx AWS_REGION us-east-1
set -gx AWS_ACCESS_KEY_ID "$AWS_ACCESS_KEY_ID"; set -gx AWS_SECRET_ACCESS_KEY "$AWS_SECRET_ACCESS_KEY"
set -e AWS_PROFILE; set -e AWS_SESSION_TOKEN
EOF

cat <<'EOF'

Listo. Para usar kubectl en otra terminal, cargue las variables del operador:
  source deploy/iac/floci/operador.fish    # fish
  source deploy/iac/floci/operador.env     # bash
  kubectl -n voltrix-alertas port-forward svc/alertas-api 18081:8080
EOF
