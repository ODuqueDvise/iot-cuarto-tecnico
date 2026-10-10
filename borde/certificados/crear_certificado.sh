#!/usr/bin/env bash
# Emite un certificado firmado por la CA del proyecto.
#   ./crear_certificado.sh borde 192.168.110.174   -> certificado de servidor; el SAN incluye la IP, localhost y 127.0.0.1
#                                                     para que los servicios del propio borde no dependan de la IP de la red
#   ./crear_certificado.sh nodo1                 -> certificado de cliente; el CN es el usuario MQTT
set -euo pipefail
NOMBRE="${1:?uso: $0 nombre [ip_del_borde]}"
IP="${2:-}"
DIR="$(dirname "$0")/salida"
[ -f "$DIR/ca.key" ] || { echo "primero ./crear_ca.sh"; exit 1; }
if [ -n "$IP" ]; then
  EXT="basicConstraints=CA:FALSE
keyUsage=digitalSignature
extendedKeyUsage=serverAuth
subjectAltName=DNS:$NOMBRE,DNS:localhost,IP:127.0.0.1,IP:$IP"
else
  EXT="basicConstraints=CA:FALSE
keyUsage=digitalSignature
extendedKeyUsage=clientAuth"
fi
openssl ecparam -name prime256v1 -genkey -noout -out "$DIR/$NOMBRE.key"
openssl req -new -key "$DIR/$NOMBRE.key" -subj "/CN=$NOMBRE" -out "$DIR/$NOMBRE.csr"
openssl x509 -req -in "$DIR/$NOMBRE.csr" -CA "$DIR/ca.crt" -CAkey "$DIR/ca.key" -CAcreateserial \
  -sha256 -days 825 -extfile <(printf '%s\n' "$EXT") -out "$DIR/$NOMBRE.crt"
chmod 600 "$DIR/$NOMBRE.key"
echo "emitido: $DIR/$NOMBRE.crt (la solicitud .csr puede borrarse)"
