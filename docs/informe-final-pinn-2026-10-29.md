# PINN Zona Tec: informe final (29 oct 2026)

## Resultado

El entregable es un **interpolador lineal en theta sobre CFD densa**: 32 direcciones a 11.25 grados, caso base, malla m1. Se eligio la opcion A (Hermann, 21 oct). La red PINN no entra al entregable.

| medida | valor |
|---|---|
| LOO sobre las 32 direcciones (cada una se predice con sus vecinas a +-11.25, hueco de 22.5) | **L2 medio 0.187**, max 0.227; error peatonal medio 0.046 u_h |
| control test-direction-fino dentro del LOO | 0.179 (antes, con 12 direcciones: 0.193) |
| error estimado en uso real (hueco de 11.25, punto medio, peor caso) | ~0.12, extrapolado de la curva de abajo |
| escala con U10 (consulta a 10 m/s contra el CFD real a 10 m/s, theta 112.5) | L2 0.004 |

Error contra el hueco angular entre vecinas (LOO32, `train/hueco.py <V2> <carpeta train>`):

| hueco | L2 medio | max |
|---|---|---|
| 22.5 | 0.187 | 0.227 |
| 45 | 0.290 | 0.346 |
| 90 | 0.473 | 0.508 |

El error baja como hueco^0.66, asi que el factor decisivo fue tener mas CFD. Con 12 direcciones, la red a2 (0.28-0.33) y los metodos clasicos (spline y GP) quedaron peor que la interpolacion lineal (`docs/estado-pinn-2026-10-22.md`). Las direcciones con meseta (11.25, 191.25, 202.5, 213.75, 225) no son atipicas en el LOO.

## Uso

```
cd train
.venv/bin/python -I interp_denso.py consulta ../f3/paquete/pinn/v2 <theta_deg> <U10> salida.h5
.venv/bin/python -I interp_denso.py evaluar  ../f3/paquete/pinn/v2 [N_puntos] [salida.json]
```

La salida tiene la misma malla que los HDF5 de processed (x, y, z, cell_id, vol, is_wall_adjacent). Trae u, v, w en m/s y p cinematica. En los atributos van theta, U10, u_h y las vecinas con sus pesos.

Como funciona:
- Interpola los campos adimensionales (velocidad entre u_h, presion entre u_h^2) y u_h entre las dos direcciones vecinas.
- Despues escala con U10/5, y la presion con su cuadrado. La similitud de Reynolds esta validada en `rescale_check.json` y en la prueba de 10 m/s.
- Solo carga 2 casos.

## Red residual: no se hizo

El plan la dejaba como opcional y solo si bajaba el LOO. No se entreno, por tres razones:
1. Para probar que baja el LOO hay que entrenar una red por cada caso que se deja fuera: 32 entrenamientos de horas cada uno.
2. a2, con fisica y armonicos, no le gano a la interpolacion ni siquiera con 12 direcciones.
3. El error que queda viene sobre todo de estelas que se desplazan entre direcciones vecinas. Una red suave en theta no las corrige.

Si mas adelante hiciera falta bajar del ~0.12, conviene mas CFD (5.625 grados en las zonas peores, 135-225) o un metodo de transporte o alineacion de estelas (sPOD o Grassmann). Una red pura no es la via.

## Datos y archivos

- Datos: `f3/paquete/pinn/v2/data/processed/manifest.csv` (57 casos). F4b, de cln, se recibio el 23 oct con SHA verificado y esta en `f3/recibido-20261023F4b/`.
- Codigo: `train/interp_denso.py` (entregable), `train/clasicos.py` (comparacion), `train/f4.py` (red, historico).
- Metricas: `docs/resultados-2026-10-29/interp_denso.json` y `docs/resultados-2026-10-22/`.
- Alcance: solo el caso base. var1 y var2 tienen 8 direcciones a 45 grados. El mismo script sirve cambiando `variant` en `malla()`, pero con un error esperado de ~0.29 o mas (hueco de 45).
