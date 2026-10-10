# 1. Preparar la Raspberry Pi 4 desde la tarjeta en blanco

## Grabar la tarjeta (en el Mac)

Raspberry Pi Imager, versión 1.8 o posterior.

1. Dispositivo: Raspberry Pi 4.
2. Sistema operativo: Raspberry Pi OS (other) > Raspberry Pi OS Lite (64-bit). Sin escritorio, por la memoria.
   Debe ser la versión de 64 bits porque InfluxDB 2 solo publica paquetes para arm64.
3. Almacenamiento: la microSD de 16 GB.
4. En "Editar ajustes" antes de grabar:
   - General: nombre de equipo `borde`; usuario `odukec` y contraseña propia; no configurar Wi-Fi (la Pi va por Ethernet);
     zona horaria `America/Bogota`; teclado `us` o `latam` según el tuyo.
   - Servicios: activar SSH con autenticación por clave pública. Pegar el contenido de `~/.ssh/id_ed25519.pub` del Mac
     (si no existe: `ssh-keygen -t ed25519`).
   - Opciones: desactivar la telemetría del Imager.
5. Grabar y verificar.

## Primer arranque

1. Conectar la Pi por Ethernet al puerto del conmutador asignado a la VLAN de IoT (puerto de acceso, sin etiqueta;
   la Pi no necesita configurar 802.1Q). Alimentarla desde la salida de la UPS con una fuente USB-C de 5 V y 3 A;
   con menos corriente la Pi muestra el aviso de bajo voltaje y se reinicia bajo carga.
2. Esperar dos minutos. Encontrar la IP en el enrutador o con `ping borde.local` desde un equipo en la misma VLAN.
3. Entrar: `ssh odukec@borde.local` (o por IP).
4. Fijar la IP (Raspberry Pi OS Bookworm usa NetworkManager). Ajustar los valores a tu red:

   ```bash
   sudo nmcli con mod "Wired connection 1" ipv4.method manual \
     ipv4.addresses 192.168.50.10/24 ipv4.gateway 192.168.50.1 ipv4.dns 192.168.50.1
   sudo nmcli con up "Wired connection 1"
   ```

   La sesión SSH se cae; volver a entrar con la IP nueva. Esa IP es la que va en los certificados y en `secretos.h` del nodo.
5. Actualizar: `sudo apt update && sudo apt full-upgrade -y && sudo reboot`.

## Instalar el borde

```bash
sudo apt install -y git
git clone https://github.com/<usuario>/iot-cuarto-tecnico.git
cd iot-cuarto-tecnico/borde
nano instalar.sh     # revisar RED_IOT al inicio del archivo
sudo ./instalar.sh
```

Al terminar, `../herramientas/medir_memoria.sh` muestra la memoria disponible con todos los servicios arriba.
Anotar el valor en `docs/bitacora.md`: es el dato que decide si Grafana se queda o se reemplaza por el panel propio de InfluxDB.
Regla de trabajo: con todo arriba y antes del detector, deben quedar más de 400 MB disponibles.
