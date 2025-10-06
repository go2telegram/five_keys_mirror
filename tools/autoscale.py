#!/usr/bin/env python3
"""Simple controller to autoscale Compose or Kubernetes workloads based on RPS."""
from __future__ import annotations

import argparse
import json
import logging
import math
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

LOGGER = logging.getLogger("autoscale")
DEFAULT_STATE_PATH = Path(__file__).with_name(".autoscale_state.json")
RPS_FALLBACK_NAMES = (
    "http_requests_per_second",
    "requests_per_second",
    "http_requests_rps",
    "rps",
)


@dataclass
class AutoscaleDecision:
    desired_replicas: int
    reason: str
    scaled: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Autoscale Compose/Kubernetes workloads.")
    parser.add_argument("--provider", choices=("compose", "k8s"), required=True)
    parser.add_argument("--min", dest="min_replicas", type=int, required=True, help="Minimum replicas")
    parser.add_argument("--max", dest="max_replicas", type=int, required=True, help="Maximum replicas")
    parser.add_argument(
        "--rps-target",
        dest="rps_target",
        type=float,
        required=True,
        help="Target requests per second per replica.",
    )
    parser.add_argument(
        "--cooldown",
        dest="cooldown",
        type=int,
        default=120,
        help="Seconds of low traffic before scaling down.",
    )
    parser.add_argument(
        "--metrics-url",
        dest="metrics_url",
        default="http://localhost:8000/metrics",
        help="Prometheus style metrics endpoint.",
    )
    parser.add_argument(
        "--rps-metric",
        dest="rps_metric",
        default="http_requests_per_second",
        help="Metric name that reports current RPS.",
    )
    parser.add_argument(
        "--service",
        dest="service_name",
        default="app",
        help="Compose service name or Kubernetes deployment to scale.",
    )
    parser.add_argument(
        "--compose-file",
        dest="compose_file",
        default="deploy/compose.override.yml",
        help="Path to docker compose override file.",
    )
    parser.add_argument(
        "--project-dir",
        dest="project_dir",
        default=".",
        help="Compose project directory for docker compose commands.",
    )
    parser.add_argument(
        "--state-file",
        dest="state_file",
        default=None,
        help="Where to persist autoscaler state between runs.",
    )
    parser.add_argument(
        "--kubectl",
        dest="kubectl_bin",
        default="kubectl",
        help="kubectl executable to use when provider=k8s.",
    )
    parser.add_argument(
        "--namespace",
        dest="namespace",
        default=None,
        help="Kubernetes namespace for kubectl commands.",
    )
    parser.add_argument(
        "--hpa-file",
        dest="hpa_file",
        default="k8s/hpa.yaml",
        help="Path to write HorizontalPodAutoscaler manifest.",
    )
    parser.add_argument(
        "--cpu-target",
        dest="cpu_target",
        type=int,
        default=75,
        help="Target average CPU utilisation percentage for HPA.",
    )
    return parser.parse_args()


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handler:
            return json.load(handler)
    except json.JSONDecodeError:
        LOGGER.warning("State file %s is corrupted. Starting fresh.", path)
        return {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handler:
        json.dump(state, handler)


def fetch_metrics(url: str) -> str:
    response = httpx.get(url, timeout=5.0)
    response.raise_for_status()
    return response.text


def parse_rps(metrics_text: str, metric_name: str) -> float:
    metric_candidates = (metric_name,) + tuple(name for name in RPS_FALLBACK_NAMES if name != metric_name)
    for name in metric_candidates:
        pattern = re.compile(rf"^{re.escape(name)}(?:{{[^}}]*}})?\s+([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)$", re.MULTILINE)
        match = pattern.search(metrics_text)
        if match:
            return float(match.group(1))
    raise ValueError(f"Unable to find RPS metric '{metric_name}' in metrics payload.")


def read_compose_replicas(path: Path, service: str) -> Optional[int]:
    if not path.exists():
        return None
    replicas = None
    in_services = False
    in_service = False
    in_deploy = False
    with path.open("r", encoding="utf-8") as handler:
        for raw_line in handler:
            line = raw_line.rstrip("\n")
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            if not stripped or stripped.startswith("#"):
                continue
            if indent == 0 and stripped == "services:":
                in_services = True
                in_service = False
                in_deploy = False
                continue
            if not in_services:
                continue
            if indent == 2 and stripped.endswith(":"):
                current_service = stripped[:-1]
                in_service = current_service == service
                in_deploy = False
                continue
            if in_service and indent == 4 and stripped == "deploy:":
                in_deploy = True
                continue
            if in_service and in_deploy and indent == 6 and stripped.startswith("replicas:"):
                try:
                    replicas = int(stripped.split(":", 1)[1].strip())
                except ValueError:
                    LOGGER.warning("Failed to parse replicas value from line '%s'", line)
                return replicas
    return replicas


def update_compose_replicas(path: Path, service: str, replicas: int) -> None:
    if not path.exists():
        LOGGER.info("Compose override file %s is missing. Creating a new one.", path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handler:
            handler.write("version: \"3.9\"\n\n")
            handler.write("services:\n")
            handler.write(f"  {service}:\n")
            handler.write("    deploy:\n")
            handler.write(f"      replicas: {replicas}\n")
        return

    lines = path.read_text(encoding="utf-8").splitlines()
    output_lines = []
    in_services = False
    in_service = False
    in_deploy = False
    replicas_written = False

    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if indent == 0 and stripped == "services:":
            in_services = True
            in_service = False
            in_deploy = False
            output_lines.append(line)
            continue
        if in_services and indent == 2 and stripped.endswith(":"):
            in_service = stripped[:-1] == service
            in_deploy = False
            output_lines.append(line)
            continue
        if in_service and indent == 4 and stripped == "deploy:":
            in_deploy = True
            output_lines.append(line)
            continue
        if in_service and in_deploy and indent == 6 and stripped.startswith("replicas:"):
            output_lines.append("      replicas: {0}".format(replicas))
            replicas_written = True
            continue
        if in_service and in_deploy and indent <= 4:
            if not replicas_written:
                output_lines.append("      replicas: {0}".format(replicas))
                replicas_written = True
            in_deploy = False
        output_lines.append(line)

    if in_service and in_deploy and not replicas_written:
        output_lines.append("      replicas: {0}".format(replicas))
        replicas_written = True

    if not replicas_written:
        if not in_services:
            output_lines.append("services:")
        if not in_service:
            output_lines.append(f"  {service}:")
        output_lines.append("    deploy:")
        output_lines.append("      replicas: {0}".format(replicas))

    path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")


def apply_docker_compose(project_dir: str, compose_file: Path, service: str, replicas: int) -> None:
    docker_bin = shutil.which("docker")
    if docker_bin is None:
        LOGGER.warning("docker binary not found. Skipping docker compose apply.")
        return
    cmd = [docker_bin, "compose", "-f", str(compose_file), "up", "-d", "--scale", f"{service}={replicas}"]
    LOGGER.info("Running command: %s", " ".join(cmd))
    try:
        subprocess.run(cmd, cwd=project_dir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as exc:
        LOGGER.error("docker compose command failed: %s", exc.stderr.decode().strip())


def ensure_hpa_manifest(
    path: Path,
    deployment: str,
    namespace: Optional[str],
    min_replicas: int,
    max_replicas: int,
    rps_target: float,
    cpu_target: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "apiVersion: autoscaling/v2",
        "kind: HorizontalPodAutoscaler",
        "metadata:",
        f"  name: {deployment}-hpa",
    ]
    if namespace:
        lines.append(f"  namespace: {namespace}")
    lines.extend(
        [
            "spec:",
            "  scaleTargetRef:",
            "    apiVersion: apps/v1",
            "    kind: Deployment",
            f"    name: {deployment}",
            f"  minReplicas: {min_replicas}",
            f"  maxReplicas: {max_replicas}",
            "  metrics:",
            "    - type: Pods",
            "      pods:",
            "        metric:",
            "          name: http_requests_per_second",
            "        target:",
            "          type: AverageValue",
            f"          averageValue: \"{rps_target:.2f}\"",
            "    - type: Resource",
            "      resource:",
            "        name: cpu",
            "        target:",
            "          type: Utilization",
            f"          averageUtilization: {cpu_target}",
        ]
    )

    with path.open("w", encoding="utf-8") as handler:
        handler.write("\n".join(lines) + "\n")


def apply_kubectl_manifest(kubectl_bin: str, manifest_path: Path, namespace: Optional[str]) -> None:
    if shutil.which(kubectl_bin) is None:
        LOGGER.warning("kubectl binary '%s' not found. Skipping manifest apply.", kubectl_bin)
        return
    cmd = [kubectl_bin, "apply", "-f", str(manifest_path)]
    if namespace:
        cmd.extend(["-n", namespace])
    LOGGER.info("Running command: %s", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as exc:
        LOGGER.error("kubectl apply failed: %s", exc.stderr.decode().strip())


def scale_k8s_workload(kubectl_bin: str, deployment: str, namespace: Optional[str], replicas: int) -> None:
    if shutil.which(kubectl_bin) is None:
        LOGGER.warning("kubectl binary '%s' not found. Skipping scale command.", kubectl_bin)
        return
    cmd = [kubectl_bin, "scale", "deployment", deployment, f"--replicas={replicas}"]
    if namespace:
        cmd.extend(["-n", namespace])
    LOGGER.info("Running command: %s", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as exc:
        LOGGER.error("kubectl scale failed: %s", exc.stderr.decode().strip())


def get_k8s_replicas(kubectl_bin: str, deployment: str, namespace: Optional[str]) -> Optional[int]:
    if shutil.which(kubectl_bin) is None:
        return None
    cmd = [kubectl_bin, "get", "deployment", deployment, "-o", "jsonpath={.status.replicas}"]
    if namespace:
        cmd.extend(["-n", namespace])
    try:
        result = subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        LOGGER.error("kubectl get deployment failed: %s", exc.stderr.strip())
        return None
    output = result.stdout.strip()
    if not output:
        return None
    try:
        return int(output)
    except ValueError:
        LOGGER.error("Unexpected replica value '%s' from kubectl output", output)
        return None


def calculate_desired_replicas(
    current_replicas: int,
    min_replicas: int,
    max_replicas: int,
    current_rps: float,
    target_rps: float,
    cooldown: int,
    state: dict,
) -> AutoscaleDecision:
    now = time.time()
    idle_since = state.get("idle_since")
    scale_up_threshold = target_rps * 1.2
    scale_down_threshold = target_rps * 0.5
    desired = current_replicas
    scaled = False
    reason = "steady"

    if current_rps > scale_up_threshold and current_replicas < max_replicas:
        desired = min(max_replicas, current_replicas + 1)
        state["idle_since"] = None
        state["last_scale_at"] = now
        scaled = desired != current_replicas
        reason = "scale_up"
    elif current_rps < scale_down_threshold and current_replicas > min_replicas:
        if idle_since is None:
            idle_since = now
            state["idle_since"] = idle_since
            reason = "waiting_cooldown"
        elif now - idle_since >= cooldown:
            desired = max(min_replicas, current_replicas - 1)
            state["idle_since"] = None
            state["last_scale_at"] = now
            scaled = desired != current_replicas
            reason = "scale_down"
        else:
            remaining = cooldown - (now - idle_since)
            reason = f"cooldown_{math.ceil(max(0.0, remaining))}s"
    else:
        state["idle_since"] = None

    return AutoscaleDecision(desired_replicas=desired, reason=reason, scaled=scaled)


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    state_path = Path(args.state_file) if args.state_file else DEFAULT_STATE_PATH
    state = load_state(state_path)

    try:
        metrics_payload = fetch_metrics(args.metrics_url)
        current_rps = parse_rps(metrics_payload, args.rps_metric)
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("Failed to fetch metrics: %s", exc)
        return 1

    if current_rps < 0:
        current_rps = 0

    provider = args.provider
    service = args.service_name
    min_replicas = args.min_replicas
    max_replicas = args.max_replicas

    if min_replicas > max_replicas:
        LOGGER.error("min replicas %s cannot be greater than max replicas %s", min_replicas, max_replicas)
        return 1

    if provider == "compose":
        compose_file = Path(args.compose_file)
        current_replicas = read_compose_replicas(compose_file, service)
        if current_replicas is None:
            current_replicas = min_replicas
        decision = calculate_desired_replicas(
            current_replicas,
            min_replicas,
            max_replicas,
            current_rps,
            args.rps_target,
            args.cooldown,
            state,
        )
        LOGGER.info(
            "compose provider: current=%s desired=%s rps=%.2f reason=%s",
            current_replicas,
            decision.desired_replicas,
            current_rps,
            decision.reason,
        )
        if decision.desired_replicas != current_replicas:
            update_compose_replicas(compose_file, service, decision.desired_replicas)
            apply_docker_compose(args.project_dir, compose_file, service, decision.desired_replicas)
        state["last_replicas"] = decision.desired_replicas
        save_state(state_path, state)
        return 0

    if provider == "k8s":
        current_replicas = get_k8s_replicas(args.kubectl_bin, service, args.namespace)
        if current_replicas is None:
            current_replicas = state.get("last_replicas", min_replicas)
        decision = calculate_desired_replicas(
            current_replicas,
            min_replicas,
            max_replicas,
            current_rps,
            args.rps_target,
            args.cooldown,
            state,
        )
        LOGGER.info(
            "k8s provider: current=%s desired=%s rps=%.2f reason=%s",
            current_replicas,
            decision.desired_replicas,
            current_rps,
            decision.reason,
        )
        ensure_hpa_manifest(
            Path(args.hpa_file),
            service,
            args.namespace,
            min_replicas,
            max_replicas,
            args.rps_target,
            args.cpu_target,
        )
        apply_kubectl_manifest(args.kubectl_bin, Path(args.hpa_file), args.namespace)
        if decision.desired_replicas != current_replicas:
            scale_k8s_workload(args.kubectl_bin, service, args.namespace, decision.desired_replicas)
        state["last_replicas"] = decision.desired_replicas
        save_state(state_path, state)
        return 0

    LOGGER.error("Unsupported provider: %s", provider)
    return 1


if __name__ == "__main__":
    sys.exit(main())
