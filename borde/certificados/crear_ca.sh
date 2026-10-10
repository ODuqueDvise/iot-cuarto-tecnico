#!/usr/bin/env bash
# Autoridad certificadora propia del proyecto (curva P-256, diez años).
set -euo pipefail
DIR="$(dirname "$0")/salida"
mkdir -p "$DIR"
[ -f "$DIR/ca.key" ] && { echo "ya existe $DIR/ca.key; no se sobreescribe"; exit 1; }
openssl ecparam -name prime256v1 -genkey -noout -out "$DIR/ca.key"
openssl req -x509 -new -key "$DIR/ca.key" -sha256 -days 3650 -subj "/CN=CA cuarto tecnico" -out "$DIR/ca.crt"
chmod 600 "$DIR/ca.key"
echo "creada: $DIR/ca.crt"
