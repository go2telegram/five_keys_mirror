#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  cat <<'USAGE'
Remove network latency introduced by lag_network.sh.

Usage: ./restore_network.sh [interface]

Arguments:
  interface  Network interface to reset (default: auto-detected: eth0, ens3 or first non-loopback).

Requires sudo/root privileges because it uses `tc qdisc`.
USAGE
  exit 0
fi

IFACE="${1:-}"

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

echo "[chaos][net] Restoring network on interface ${IFACE}"
if tc qdisc show dev "${IFACE}" | grep -q netem; then
  sudo tc qdisc del dev "${IFACE}" root netem || tc qdisc del dev "${IFACE}" root
else
  echo "[chaos][net] No netem qdisc configured on ${IFACE}" >&2
fi

tc qdisc show dev "${IFACE}"
