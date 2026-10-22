# PINN Zona Tec: estado y plan (22 oct 2026)

Para claude-cln y quien retome. Lo escribe @pinn (M5).

## Decision de Hermann (21 oct 23:58): opcion A

El entregable es la **interpolacion lineal en theta sobre CFD densa** (malla de 32 direcciones a 11.25 grados). La red PINN queda solo como **correccion residual opcional** sobre la interpolacion. No se hace a3 de PINN pura.

Por que: con 12 direcciones de train, a2 y los metodos clasicos pierden contra la interpolacion lineal. El error crece con la distancia angular a la direccion de train mas cercana: 0.28 a 22.5 grados y 0.19 a 11.25 grados. La palanca es tener mas CFD.

## Resultados (L2 relativo medio de velocidad, base m1 U050)

| metodo | test-direction | test-direction-fino | LOO |
|---|---|---|---|
| lineal, marco fijo | 0.284 | 0.193 | 0.339 |
| lineal, marco del viento | 0.290 | 0.198 | 0.337 |
| spline periodico, fijo | 0.311 | 0.199 | 0.366 |
| GP periodico, fijo | 0.394 | 0.223 | 0.473 |
| a2 (M5, ws 0.05, theta-harm 3) | 0.28-0.33 | 0.23-0.30 | - |
| a2 cln, ws 0.01 | 0.26-0.31 | - | - |

Los JSON estan en `docs/resultados-2026-10-22/`: a1, a2, clasicos y el barrido CUDA de cln. Los scripts son `train/f4.py` (red; `--solo-eval` reevalua) y `train/clasicos.py` (lineal, spline y GP).

## Datos

- `f3/paquete/pinn/v2/data/processed/manifest.csv` tiene 45 filas:
  - 12 train;
  - 4 test-direction (22.5, 157.5, 247.5, 337.5);
  - 4 test-direction-fino (33.75, 123.75, 213.75, 303.75);
  - gci, test-speed, var1 y var2.
- **F4b (cln, en curso):** 12 CFD base m1 U050 a 11.25, 56.25, 78.75, 101.25, 146.25, 168.75, 191.25, 236.25, 258.75, 281.25, 326.25 y 348.75 grados. Se mandan a la M5 por Taildrop con manifest y SHA256SUMS.

## Plan cuando llegue F4b

1. Verificar los SHA, instalar en `processed` y agregar al manifest.
2. Malla de 32 direcciones: las 12 base, las 12 de F4b, las 4 test-direction pasadas a train y las 4 finas. Protocolo: LOO sobre las 32 y test-direction-fino como control.
3. Entregable: interpolador lineal sobre las 32 direcciones, con un script de consulta (theta, U10) -> campo.
4. Opcional: red residual (f4.py entrenando sobre campo menos interpolacion). Solo se queda si baja el LOO.

## Reglas

- Las decisiones tecnicas de PINN las toma la sesion con su recomendacion y solo avisa el hito.
- Push, gasto y borrar resultados piden OK a Hermann.
- Casos fallidos o atorados se relanzan sin pedir OK y se avisa una vez.
- PINN nunca va al canal Fabrica.
