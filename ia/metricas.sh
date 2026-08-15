#!/bin/bash
# Junta las curvas de loss de todas las corridas en un solo CSV, para el tablero de
# Looker Studio.
#
#     ia/metricas.sh
#
# El otro CSV, el de aciertos por campo, lo escribe `comparar-lora.ts` porque necesita la
# base. Este no necesita nada: los `curva_loss.csv` ya están en disco desde que corrió cada
# entrenamiento.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p metricas

{
  echo "corrida,epoch,paso,loss,segundos"
  for f in ia/checkpoints/*/curva_loss.csv; do
    # `sed 1d` saltea el encabezado de cada archivo; el nombre del directorio es la corrida.
    sed 1d "$f" | sed "s|^|$(basename "$(dirname "$f")"),|"
  done
} > metricas/curvas_loss.csv

echo "$(($(wc -l < metricas/curvas_loss.csv) - 1)) filas → metricas/curvas_loss.csv"

# ponytail: la columna `segundos` viene del cronómetro interno de entrenar.py, que para en
# loss.item() y NO cuenta el guardado ni el canario. Sirve para comparar pasos entre sí,
# nunca para estimar cuánto tarda una corrida — para eso, `ps -o etime`.
