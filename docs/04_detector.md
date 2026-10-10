# 4. Medir el detector en el borde (imágenes fijas)

Objetivo: saber cuánto tiempo y memoria consume el detector SSD-MobileNetV2 en la Pi de 1 GB antes de que llegue la cámara.

## En el Mac: exportar el modelo a ONNX

```bash
cd iot-cuarto-tecnico
bash herramientas/exportar_detector.sh
```

Instala TensorFlow en un entorno aparte (unos 500 MB, solo en el Mac), descarga el modelo del TF Model Zoo y lo convierte.
Al final queda `modelos/ssd_mobilenet_v2_coco.onnx` (unos 20 MB), excluido de git.
Tomar además dos o tres fotos con el celular: una sin personas, una con una persona y una con dos, y copiarlas a `modelos/`.

```bash
ssh odukec@192.168.110.174 mkdir -p iot-cuarto-tecnico/modelos
scp modelos/ssd_mobilenet_v2_coco.onnx modelos/*.jpg odukec@192.168.110.174:iot-cuarto-tecnico/modelos/
```

## En la Pi: medir con todos los servicios arriba

```bash
python3 -m venv ~/venv-detector
~/venv-detector/bin/pip install onnxruntime numpy pillow
cd ~/iot-cuarto-tecnico/herramientas
~/venv-detector/bin/python medir_detector.py --modelo ../modelos/ssd_mobilenet_v2_coco.onnx ../modelos/*.jpg
free -m
```

Anotar en la bitácora: tiempo por imagen, tiempo estimado de la ráfaga, pico de memoria del proceso, memoria disponible
durante la medición y si el conteo de personas coincide con las fotos.
