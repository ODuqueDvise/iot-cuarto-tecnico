#!/usr/bin/env bash
# Exporta el detector SSD con red troncal MobileNetV2 (COCO, TF2 Model Zoo) a ONNX.
# Ejecutar en el Mac, no en la Pi: la conversión necesita TensorFlow, que no cabe en 1 GB.
# El resultado queda en modelos/ (excluido de git) y se copia a la Pi con scp.
set -euo pipefail
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$RAIZ/modelos"
MODELO=ssd_mobilenet_v2_320x320_coco17_tpu-8
mkdir -p "$DIR"
cd "$DIR"

python3 -m venv .venv-export
# shellcheck disable=SC1091
. .venv-export/bin/activate
pip install --quiet --upgrade pip
# Versiones fijadas para que TensorFlow, tf2onnx, onnx y protobuf sean compatibles entre sí.
pip install --quiet "tensorflow==2.15.1" "tf2onnx==1.16.1" "onnx==1.16.2" "numpy<2"

if [ ! -d "$MODELO" ]; then
  curl -L -o "$MODELO.tar.gz" "http://download.tensorflow.org/models/object_detection/tf2/20200711/$MODELO.tar.gz"
  tar xzf "$MODELO.tar.gz"
fi

python -m tf2onnx.convert --saved-model "$MODELO/saved_model" --output ssd_mobilenet_v2_coco.onnx --opset 13
deactivate
ls -lh ssd_mobilenet_v2_coco.onnx
echo "Copiar a la Pi: scp modelos/ssd_mobilenet_v2_coco.onnx odukec@192.168.110.174:iot-cuarto-tecnico/modelos/"
