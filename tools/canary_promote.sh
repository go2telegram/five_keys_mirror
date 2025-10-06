#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<USAGE
Promote the canary deployment to production.

Environment variables:
  KUBE_NAMESPACE        Kubernetes namespace (default: default)
  PROD_DEPLOYMENT       Production deployment name (default: five-keys-bot)
  CANARY_DEPLOYMENT     Canary deployment name (default: five-keys-bot-canary)
  CONTAINER_NAME        Container name inside the deployments (default: bot)
  SCALE_DOWN_CANARY     Set to 0 to keep the canary running after promotion (default: 1)

Options:
  -h, --help            Show this help message
USAGE
}

for arg in "$@"; do
    case "$arg" in
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg" >&2
            usage >&2
            exit 1
            ;;
    esac
done

namespace=${KUBE_NAMESPACE:-default}
prod_deployment=${PROD_DEPLOYMENT:-five-keys-bot}
canary_deployment=${CANARY_DEPLOYMENT:-five-keys-bot-canary}
container_name=${CONTAINER_NAME:-bot}
scale_down=${SCALE_DOWN_CANARY:-1}

if ! command -v kubectl >/dev/null 2>&1; then
    echo "kubectl is required but was not found in PATH" >&2
    exit 1
fi

echo "Fetching canary image reference..."
canary_image=$(kubectl get deployment "$canary_deployment" \
    --namespace "$namespace" \
    -o jsonpath="{.spec.template.spec.containers[?(@.name=='$container_name')].image}")

if [[ -z "$canary_image" ]]; then
    echo "Failed to discover canary image for container '$container_name' in deployment '$canary_deployment'." >&2
    exit 1
fi

echo "Promoting image $canary_image to deployment $prod_deployment in namespace $namespace..."
kubectl set image "deployment/$prod_deployment" \
    "$container_name=$canary_image" \
    --namespace "$namespace"

echo "Waiting for production rollout to finish..."
kubectl rollout status "deployment/$prod_deployment" --namespace "$namespace"

echo "Synchronising horizontal pod autoscaler (if any)..."
kubectl annotate --overwrite deployment "$prod_deployment" \
    canary.promotedAt="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --namespace "$namespace" >/dev/null || true

if [[ "$scale_down" != "0" ]]; then
    echo "Scaling canary deployment $canary_deployment down to zero replicas..."
    kubectl scale deployment "$canary_deployment" --replicas=0 --namespace "$namespace"
fi

echo "Promotion completed successfully."
