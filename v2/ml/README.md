# PINN Zona Tec -- ml package

Hybrid physics-informed neural network (+ DeepONet comparator) for 3D mean
urban wind (RANS) around Tecnologico de Monterrey. See
`E:\PINN\v2\docs\DATA_CONTRACT.md` for the binding data contract this
package reads/writes.

**Status: smoke test.** The pipeline below runs end-to-end on a small
*synthetic* dataset (`ml/synthetic.py`) that satisfies the HDF5 contract
exactly but is not a real CFD solution. It proves the plumbing (data
loading, non-dimensionalisation, Fourier-feature MLP + DeepONet, physics
residual losses, adaptive weighting, Adam+L-BFGS, export, metrics,
baselines), not physical accuracy. Swap in real `v2/data/processed/*.h5`
cases (same contract) and point the configs' `data.manifest` at the real
`manifest.csv` to move from smoke test to real training.

## Package layout

```
ml/
  config.py     dataclasses + YAML loading for every stage of the pipeline
  synthetic.py  writes fake contract-compliant HDF5 cases (smoke test only)
  data.py       HDF5 loading, non-dimensionalisation, per-step sampler
  features.py   Fourier features (Tancik 2020), sdf/height scaling
  models.py     PINNMLP (P25=A) and DeepONetPINN comparator
  physics.py    continuity / momentum residuals, wall-normal flux (autograd)
  losses.py     data loss + residual losses -> scalar terms
  weighting.py  fixed weights, and LRA (Wang, Teng & Perdikaris 2021)
  train.py      CLI (`python -m ml.train`), training loop, evaluation,
                comparison-table assembly against the reference models
  metrics.py    relative L2, MAE of K=|U|/U10, VDI 3783-9 hit rate,
                corner/wake/canyon zone labelling + per-zone error
  baselines.py  interpolation (spatial + angular), nearest-direction
  export.py     PINNMLP -> JSON for in-browser JS inference + numpy check
  configs/      YAML configs for the smoke test (stage A/B/C + DeepONet)
  tests/        pytest unit tests (physics, losses, metrics, export)
```

## Quickstart (smoke test)

Run everything from `E:\PINN\v2` with the project venv:

```powershell
$env:TMP='E:\tmp'; $env:TEMP='E:\tmp'; $env:PIP_CACHE_DIR='E:\PINN\cache\pip'
cd E:\PINN\v2

# 1. generate the synthetic contract-compliant dataset
E:\PINN\.venv\Scripts\python.exe -m ml.synthetic

# 2. run the unit tests
E:\PINN\.venv\Scripts\python.exe -m pytest ml/tests -v

# 3. train stage A (data only), stage B (+continuity), the DeepONet
#    comparator, then stage C (+momentum); stage C's config lists the
#    stage-A and DeepONet checkpoints under `compare_checkpoints`, so its
#    run also assembles the full comparison table across every reference
#    model on every held-out split.
E:\PINN\.venv\Scripts\python.exe -m ml.train --config ml/configs/smoke_stageA.yaml
E:\PINN\.venv\Scripts\python.exe -m ml.train --config ml/configs/smoke_stageB.yaml
E:\PINN\.venv\Scripts\python.exe -m ml.train --config ml/configs/smoke_deeponet.yaml
E:\PINN\.venv\Scripts\python.exe -m ml.train --config ml/configs/smoke_stageC.yaml
E:\PINN\.venv\Scripts\python.exe -m ml.train --config ml/configs/smoke_stageC_fixed.yaml
```

Each run writes `<out_dir>/{config.yaml, checkpoint.pt, loss_curve.png,
metrics.json}`; the stage-C runs additionally write
`comparison_table.{csv,md}` combining: stage-A network, stage-C (hybrid
PINN), DeepONet, nearest-simulated-direction, angular interpolation
between the two nearest directions, and (on the validation split) spatial
linear interpolation within the field.

`smoke_stageC.yaml` uses adaptive (LRA) weighting as specified (P26=A) and
is a real, passing run -- but on this tiny smoke dataset the momentum
residual starts ~4 orders of magnitude larger than the data loss (~1e4 vs
~1.7), so LRA's gradient-ratio rule drives its effective weight very high
and the network stops fitting the data at all (relative L2 ~= 1, i.e. no
better than predicting the mean). `smoke_stageC_fixed.yaml` is the same
stage with hand-picked fixed weights (`w_momentum=0.001`) and converges
much more sensibly (data loss 1.76 -> 0.085). This is a real calibration
finding, not a bug in `weighting.py`: LRA as implemented needs a warmup,
gradient clipping on the anchor term, or a cap on `lambda_hat` before it's
usable with residuals this poorly scaled at initialisation -- worth
revisiting before real training.

## Design choices worth re-checking

- **Pressure / 2/3 k convention** (`ml/physics.py` docstring): `p` is taken
  to be exactly OpenFOAM simpleFoam's kinematic pressure, which already
  absorbs 2/3 k into a single modified-pressure scalar; the momentum
  residual therefore has NO separate `+ (2/3) grad(k)` term by default
  (`PhysicsConfig.pressure_includes_two_thirds_k = False`). Flip that flag
  (and it will add the term) if the real dataset instead provides a
  "true" static pressure.
- **VDI 3783-9 hit-rate thresholds** (`ml/metrics.py` docstring): D=0.25,
  W=0.05*U_ref are the commonly-cited defaults found in secondary
  literature; the exact clause of the standard was not available in this
  environment. Both are function parameters -- correct them once you have
  the standard in hand.
- **Zone labelling** (corner/wake/canyon) is a simple, documented
  geometric heuristic built from each case's `wall_faces` group + flow
  direction (see `ml/metrics.label_zones`), not a rigorous flow-feature
  detector.
- The main PINN (`PINNMLP`) does **not** take U10 as an input (only the
  DeepONet branch does, per spec) -- non-dimensionalisation by U_H(U10) is
  what should let it generalise across the held-out-speed split. If that
  assumption turns out too strong on real data, U10 may need to become an
  explicit PINNMLP input too.

## Export format for the web (`ml/export.py`)

Differs from v1 (`E:\PINN\inbox\wind-pinn\public\model.json`): 3D,
multi-direction/geometry/speed; coordinates scaled by `h_ref` (not a
min-max box); outputs are non-dimensional and NOT rescaled inside the
network (a fixed `out_scale` cannot generalise across held-out speeds) --
`nondim` in the JSON carries `h_ref, kappa, cmu, z0, d` so the JS caller
computes `U_H(U10)` client-side with the same log-law formula and rescales
u,v,w,p,k,nut back to physical units; adds a per-variant embedding table;
k and nut pass through softplus. Full details in the `export.py` module
docstring. Round-trip accuracy (torch vs. the pure-NumPy reference
`predict_from_json`) is checked to 1e-5 in `ml/tests/test_export.py`.
