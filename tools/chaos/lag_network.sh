#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  cat <<'USAGE'
Introduce artificial latency with tc/netem.

Usage: ./lag_network.sh [delay_ms] [interface]

Arguments:
  delay_ms   Added round-trip latency in milliseconds (default: 150).
  interface  Network interface to shape (default: auto-detected: eth0, ens3 or first non-loopback).

Requires sudo/root privileges because it uses `tc qdisc`.
USAGE
  exit 0
fi

DELAY="${1:-150}"
IFACE="${2:-}"

choose_iface() {
  if [[ -n "${IFACE}" ]]; then
    echo "${IFACE}"
    return
  fi
  for candidate in eth0 ens3 en0; do
    if ip link show "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
      return
    fi
  done
  ip -o link show | awk -F': ' '$2 != "lo" {print $2; exit}'
}

IFACE=$(choose_iface)
if [[ -z "${IFACE}" ]]; then
  echo "[chaos][net] Unable to determine network interface" >&2
  exit 1
fi

echo "[chaos][net] Adding ${DELAY}ms latency on interface ${IFACE}"

if tc qdisc show dev "${IFACE}" | grep -q netem; then
  echo "[chaos][net] netem already configured, replacing..."
  sudo tc qdisc replace dev "${IFACE}" root netem delay "${DELAY}"ms || tc qdisc replace dev "${IFACE}" root netem delay "${DELAY}"ms
else
  sudo tc qdisc add dev "${IFACE}" root netem delay "${DELAY}"ms || tc qdisc add dev "${IFACE}" root netem delay "${DELAY}"ms
fi

tc qdisc show dev "${IFACE}"
