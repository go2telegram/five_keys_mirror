#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<USAGE
Rollback the production deployment to the previous revision.

Environment variables:
  KUBE_NAMESPACE        Kubernetes namespace (default: default)
  PROD_DEPLOYMENT       Production deployment name (default: five-keys-bot)
  CANARY_DEPLOYMENT     Canary deployment name (default: five-keys-bot-canary)
  CANARY_POST_ROLLBACK_REPLICAS  Replicas to keep for canary after rollback (default: 0)

Options:
  -h, --help            Show this help message
  -r, --revision NUM    Rollback to an explicit rollout revision
USAGE
}

revision=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        -r|--revision)
            if [[ -z "${2:-}" ]]; then
                echo "--revision requires a value" >&2
                exit 1
            fi
            revision=$2
            shift 2
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if ! command -v kubectl >/dev/null 2>&1; then
    echo "kubectl is required but was not found in PATH" >&2
    exit 1
fi

namespace=${KUBE_NAMESPACE:-default}
prod_deployment=${PROD_DEPLOYMENT:-five-keys-bot}
canary_deployment=${CANARY_DEPLOYMENT:-five-keys-bot-canary}
canary_replicas=${CANARY_POST_ROLLBACK_REPLICAS:-0}

cmd=(kubectl rollout undo "deployment/$prod_deployment" --namespace "$namespace")
if [[ -n "$revision" ]]; then
    cmd+=(--to-revision="$revision")
fi

echo "Rolling back deployment $prod_deployment in namespace $namespace..."
"${cmd[@]}"

echo "Waiting for the rollback to finish..."
kubectl rollout status "deployment/$prod_deployment" --namespace "$namespace"

if [[ -n "$canary_deployment" ]]; then
    echo "Scaling canary deployment $canary_deployment to $canary_replicas replicas..."
    kubectl scale deployment "$canary_deployment" \
        --replicas="$canary_replicas" \
        --namespace "$namespace"
fi

echo "Rollback completed."
