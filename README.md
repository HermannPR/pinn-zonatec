# Viento urbano con PINN

Demo local de viento en una ciudad sintética 2D. `sim/lbm.py` genera el campo de referencia con Lattice Boltzmann; `train/pinn.py` entrena la PINN con sensores dispersos y exporta los datos que usa `public/`.

## Estado recibido

- La simulación está guardada en `data/field.npz` y `data/meta.json`.
- El entrenamiento existente está documentado en `train/last_report.json`: 8 000 iteraciones, 250 sensores y 1 107 s. Error relativo L2 de rapidez: PINN 0,317; interpolación 0,396; MLP sin física 0,375. En presión, la PINN fue peor que la interpolación (MAE 10,70 Pa frente a 5,68 Pa).
- `public/model.json` y `public/field.json` son las exportaciones existentes para la interfaz. No se ha verificado aquí que la web funcione en todos los navegadores ni que la validación del entrenamiento sea rigurosa.

## Reproducir

Desde la raíz, con Python y `numpy`, `scipy` y `torch` instalados:

```sh
python sim/lbm.py
python train/pinn.py
```

El entrenamiento completo puede tardar decenas de minutos. Para explorar la web sin repetirlo:

```sh
python -m http.server 8766 --directory public
```

Abrir `http://localhost:8766`. Este repositorio conserva los artefactos iniciales para que el equipo revise la validez científica, mejore la web y prepare el despliegue. La simulación es sintética; no representa mediciones reales de una ciudad.
