"""CLI entry point: `python -m ml.train --config <path>` (run from E:\\PINN\\v2).

Trains one model (PINNMLP at a given physics stage, or the DeepONet
comparator) per invocation, evaluates it on every held-out split with
metrics.py, and writes a run directory:

    <out_dir>/
      config.yaml
      checkpoint.pt
      loss_curve.png
      metrics.json
      comparison_table.csv / .md      (only if `compare_checkpoints` is set)

Wall-BC (P24=B, impermeability u.n=0) is applied whenever stage is B or C
(it is a physics/geometry term, not part of the "data only" stage-A
baseline). Stage A = data loss only. Stage B = A + continuity. Stage C =
B + momentum (using the network's own predicted nut, supervised against
CFD nut by the data loss -- see physics.py docstring for the pressure /
2/3 k convention).

Design-review (M1/M2/M5/M6) additions
----------------------------------------
* **Momentum-weight ramp + optional warm start (M1.4/M2).** Physics-term
  weights (continuity, momentum, wall_bc) are ramped linearly from 0 to
  their configured value over `loss_weights.lra_warmup_steps` (global
  steps), instead of being applied at full strength from an untrained
  network whose momentum residual starts ~1e4x the data loss. `LRAWeighting`
  only starts adjusting weights after that same warmup, and only every
  `lra_every` steps (both were previously effectively immediate/every-step).
  `warm_start_checkpoint` in the config additionally lets a stage load a
  prior stage's converged weights before training.
* **Per-field standardised data loss (M5).** `CaseStore.field_stats` computes
  each field's std on the TRAIN split once; `losses.data_loss` divides each
  field's error by its own std, so low-variance fields aren't starved by a
  plain unweighted MSE sum.
* **Fluid-only, volume-weighted collocation (M6).** Collocation batches are
  sampled from `case.fluid_idx` (excludes `is_wall_adjacent==1`, where a
  wall function -- not the continuum PDE -- sets the near-wall stress) and
  the residual loss is weighted by each point's cell volume.
* **estado.py heartbeat (opt-in only, `train.heartbeat: true`).**
  `E:\\PINN\\estado.json` is a single slot shared with the CFD job queue
  (`E:\\PINN\\cola`); a short smoke/test run must never touch it (default:
  disabled), and a long run dispatched THROUGH the queue as a `kind=python`
  job may opt in, in which case train.py only ever refreshes
  `detalle`/`latido` -- never `corriendo`/`fase`/`caso`/`proceso`, which
  stay whatever the queue itself set. Never raises (see scripts/estado.py).
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch

from . import baselines, config as cfgmod, losses, metrics, weighting
from .data import CaseStore, EpochSampler, U10_REF, nondim_fields
from .models import DeepONetPINN, PINNMLP, OUT_NAMES


def _set_estado(detalle: str, enabled: bool) -> None:
    """Best-effort heartbeat to E:\\PINN\\estado.json; never raises (training
    must never be killed by a status-reporting failure -- see scripts/estado.py).

    Status-reporting rule (updated after the CFD queue started using the
    same single-slot file): estado.json has ONE slot, shared with the CFD
    job queue (E:\\PINN\\cola). A short smoke/test run (this package's
    default) must NOT touch it at all (`enabled=False`, the default via
    `TrainConfig.heartbeat`) -- writing corriendo=True/fase=... here would
    stomp the queue's own in-flight CFD status. A long real run (dispatched
    THROUGH the queue as a kind=python job, see cola/README.md) may opt in
    via `train.heartbeat: true`, and even then this only ever refreshes
    `detalle`/`latido` -- never `corriendo`/`fase`/`caso`/`proceso`, which
    remain whatever the queue itself set for that job.
    """
    if not enabled:
        return
    try:
        sys.path.insert(0, r"E:\PINN\v2")
        from scripts.estado import set_estado
        set_estado(detalle=detalle)
    except Exception as e:  # pragma: no cover - best-effort only
        print(f"[estado] heartbeat skipped ({e})")


def check_gpu(min_free_mb: int = 3500) -> None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total",
                               "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
        used, total = [int(v) for v in out.stdout.strip().split(",")]
        free = total - used
        print(f"[gpu] used={used}MiB total={total}MiB free={free}MiB (shared GPU: ComfyUI/Ollama may be running)")
        if free < min_free_mb:
            print(f"[gpu] WARNING: free VRAM ({free} MiB) is tight for a <4GB job; proceeding anyway.")
    except Exception as e:  # pragma: no cover - environment dependent
        print(f"[gpu] nvidia-smi check failed ({e}); proceeding without a VRAM check.")


def build_model(cfg: cfgmod.ExperimentConfig):
    """No variant_id input (M4, design review) -- see models.py."""
    if cfg.model.kind == "deeponet":
        return DeepONetPINN(h_ref=cfg.data.h_ref, num_fourier_bands=cfg.features.num_fourier_bands,
                             fourier_sigma=cfg.features.fourier_sigma,
                             sdf_wall_scale=cfg.model.sdf_wall_scale,
                             nut_scale=cfg.model.nut_scale, k_scale=cfg.model.k_scale)
    return PINNMLP(h_ref=cfg.data.h_ref, num_fourier_bands=cfg.features.num_fourier_bands,
                    fourier_sigma=cfg.features.fourier_sigma,
                    hidden_layers=cfg.model.hidden_layers, activation=cfg.model.activation,
                    sdf_wall_scale=cfg.model.sdf_wall_scale,
                    nut_scale=cfg.model.nut_scale, k_scale=cfg.model.k_scale)


def forward_model(model, batch):
    if isinstance(model, DeepONetPINN):
        return model(batch.xyz, batch.sincos, batch.sdf_m, batch.height_m)
    return model(batch.xyz, batch.sincos, batch.sdf_m, batch.height_m)


def _nondim_nu(nu_molecular: float, store: CaseStore, train_ids: List[str]) -> float:
    """Non-dimensionalise molecular viscosity (M1, design review: an earlier
    version passed nu in m^2/s -- physical units -- straight into a residual
    computed entirely in non-dim quantities; nu_nd = nu / (U_H * H_ref)).
    Since every non-dim field already divides by a per-case U_H, and nu is
    always negligible next to nut anyway (that's the point of it being
    "molecular"), a single representative nu_nd from the mean U_H/H_ref over
    the training cases is an adequate, documented approximation -- exact
    per-point nu_nd would require carrying a per-case scalar through the
    whole residual pipeline for a term that never matters numerically."""
    h_ref = store.cases[train_ids[0]].h_ref
    u_h_mean = float(np.mean([store.cases[c].u_h for c in train_ids]))
    return nu_molecular / (u_h_mean * h_ref)


def train_one_config(cfg: cfgmod.ExperimentConfig, run_dir: Path) -> Dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    device = torch.device(cfg.train.device if torch.cuda.is_available() and cfg.train.device == "cuda" else "cpu")
    if device.type == "cuda":
        check_gpu()
    print(f"[train] device={device} stage={cfg.physics.stage} model={cfg.model.kind}")
    _set_estado(f"{cfg.name}: starting", enabled=cfg.train.heartbeat)

    store = CaseStore(cfg.data.manifest)
    sampler = EpochSampler(store, device=device, seed=cfg.data.seed)
    train_ids = store.ids_for_split("train")
    print(f"[train] {len(train_ids)} train cases, {len(store.cases)} total cases, "
          f"{len(store.vocab)} variants (variant not fed to the model -- M4)")

    field_std = store.field_stats("train")  # M5
    print(f"[train] per-field train std (M5 standardisation): "
          + ", ".join(f"{k}={v:.4g}" for k, v in field_std.items()))
    nu_nd = _nondim_nu(cfg.physics.nu, store, train_ids)

    model = build_model(cfg).to(device)
    if cfg.warm_start_checkpoint:
        ckpt = torch.load(cfg.warm_start_checkpoint, map_location=device, weights_only=False)
        model.load_state_dict(ckpt["state_dict"])
        print(f"[train] warm-started from {cfg.warm_start_checkpoint}")

    weight_cfg = cfg.loss_weights
    base_weights = {"data": weight_cfg.w_data}
    if cfg.physics.stage in ("B", "C"):
        base_weights["continuity"] = weight_cfg.w_continuity
        base_weights["wall_bc"] = weight_cfg.w_wall_bc
    if cfg.physics.stage == "C":
        base_weights["momentum"] = weight_cfg.w_momentum
    physics_terms = [k for k in base_weights if k != "data"]
    weighter = weighting.build_weighting(weight_cfg.mode, base_weights, alpha=weight_cfg.lra_alpha,
                                          cap_lo=weight_cfg.lra_cap_lo, cap_hi=weight_cfg.lra_cap_hi)

    opt = torch.optim.Adam(model.parameters(), lr=cfg.train.lr)

    history: List[Dict[str, float]] = []
    n_per_case_sup = max(1, cfg.data.points_per_epoch // max(1, len(train_ids)))
    n_per_case_col = max(1, cfg.data.collocation_per_epoch // max(1, len(train_ids)))
    n_per_case_wall = max(1, cfg.data.wall_points_per_epoch // max(1, len(train_ids)))

    total_steps = cfg.train.epochs * cfg.train.steps_per_epoch
    warmup_steps = min(weight_cfg.lra_warmup_steps, max(1, total_steps // 2))

    t0 = time.time()
    global_step = 0
    for epoch in range(cfg.train.epochs):
        epoch_losses: Dict[str, float] = {}
        for step in range(cfg.train.steps_per_epoch):
            opt.zero_grad()
            loss_terms = {}

            sup = sampler.sample_supervised(train_ids, n_per_case_sup, requires_grad=False)
            pred_sup = forward_model(model, sup)
            l_data, per_field = losses.data_loss(pred_sup, sup.target, field_std=field_std)
            loss_terms["data"] = l_data

            if cfg.physics.stage in ("B", "C"):
                # M6: fluid_only=True excludes is_wall_adjacent cells from the residual
                col = sampler.sample_supervised(train_ids, n_per_case_col, requires_grad=True, fluid_only=True)
                pred_col = forward_model(model, col)
                loss_terms["continuity"] = losses.continuity_loss(pred_col, col.xyz, vol_weight=col.vol_weight)
                if cfg.physics.stage == "C":
                    loss_terms["momentum"] = losses.momentum_loss(
                        pred_col, col.xyz, nu=nu_nd,
                        pressure_includes_two_thirds_k=cfg.physics.pressure_includes_two_thirds_k,
                        vol_weight=col.vol_weight)

                wall = sampler.sample_wall(train_ids, n_per_case_wall)
                if wall is not None:
                    pred_wall = forward_model(model, wall)
                    loss_terms["wall_bc"] = losses.wall_bc_loss(pred_wall, wall.target)

            # M2: LRA only engages after warmup, every lra_every steps
            if weight_cfg.mode == "lra" and global_step >= warmup_steps \
                    and global_step % max(1, weight_cfg.lra_every) == 0 and len(loss_terms) > 1:
                weights = dict(weighter.update(model, loss_terms))
            else:
                weights = dict(weighter.weights) if hasattr(weighter, "weights") else dict(base_weights)

            # M1.4/M2: linear ramp of physics-term weights over the warmup window
            ramp = min(1.0, global_step / max(1, warmup_steps))
            for k in physics_terms:
                if k in weights:
                    weights[k] = weights[k] * ramp

            total = sum(weights.get(name, 1.0) * val for name, val in loss_terms.items())
            total.backward()
            if cfg.train.grad_clip:
                torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.train.grad_clip)
            opt.step()

            for name, val in loss_terms.items():
                epoch_losses[name] = epoch_losses.get(name, 0.0) + float(val.item())
            epoch_losses["total"] = epoch_losses.get("total", 0.0) + float(total.item())
            global_step += 1

        n = cfg.train.steps_per_epoch
        row = {k: v / n for k, v in epoch_losses.items()}
        row["epoch"] = epoch
        row["weights"] = {k: float(v) for k, v in (weighter.weights if hasattr(weighter, "weights") else base_weights).items()}
        history.append(row)
        if epoch % cfg.train.log_every == 0 or epoch == cfg.train.epochs - 1:
            print(f"[train] epoch {epoch:4d} " + " ".join(f"{k}={row[k]:.4e}" for k in row if k not in ("epoch", "weights")))
            _set_estado(f"{cfg.name}: epoch {epoch}/{cfg.train.epochs} total={row.get('total', float('nan')):.4e}",
                        enabled=cfg.train.heartbeat)

    # ---- optional L-BFGS refinement phase (P26=A) ----
    if cfg.train.optimizer == "adam+lbfgs" and cfg.train.lbfgs_steps > 0:
        print(f"[train] L-BFGS refinement: {cfg.train.lbfgs_steps} steps")
        _set_estado(f"{cfg.name}: L-BFGS", enabled=cfg.train.heartbeat)
        fixed_weights = dict(weighter.weights) if hasattr(weighter, "weights") else dict(base_weights)
        sup = sampler.sample_supervised(train_ids, n_per_case_sup * 2, requires_grad=False)
        col = sampler.sample_supervised(train_ids, n_per_case_col * 2, requires_grad=True, fluid_only=True) \
            if cfg.physics.stage in ("B", "C") else None
        wall = sampler.sample_wall(train_ids, n_per_case_wall * 2) if cfg.physics.stage in ("B", "C") else None
        lbfgs = torch.optim.LBFGS(model.parameters(), lr=cfg.train.lbfgs_lr, max_iter=cfg.train.lbfgs_steps,
                                   line_search_fn="strong_wolfe")

        def closure():
            lbfgs.zero_grad()
            terms = {}
            pred_sup = forward_model(model, sup)
            l_data, _ = losses.data_loss(pred_sup, sup.target, field_std=field_std)
            terms["data"] = l_data
            if col is not None:
                # L-BFGS's line search calls this closure many times against
                # the SAME fixed `col` batch. col.sdf_m/height_m were built
                # once (by EpochSampler.differentiable_geometry) as tensors
                # with their own graph back to col.xyz; reusing that same
                # graph node as an input to many independent forward+backward
                # passes fails the second time ("backward through the graph a
                # second time") once the first backward() frees it. Recompute
                # them fresh from the (leaf, reusable) col.xyz every closure
                # call -- exactly as the model's own forward pass is already
                # redone fresh every call.
                sdf_m, height_m = sampler.differentiable_geometry(
                    train_ids, n_per_case_col * 2, col.xyz, col.sdf_m, col.height_m)
                col_fresh = dataclasses.replace(col, sdf_m=sdf_m, height_m=height_m)
                pred_col = forward_model(model, col_fresh)
                terms["continuity"] = losses.continuity_loss(pred_col, col.xyz, vol_weight=col.vol_weight)
                if cfg.physics.stage == "C":
                    terms["momentum"] = losses.momentum_loss(pred_col, col.xyz, nu=nu_nd,
                        pressure_includes_two_thirds_k=cfg.physics.pressure_includes_two_thirds_k,
                        vol_weight=col.vol_weight)
            if wall is not None:
                pred_wall = forward_model(model, wall)
                terms["wall_bc"] = losses.wall_bc_loss(pred_wall, wall.target)
            total = sum(fixed_weights.get(k, 1.0) * v for k, v in terms.items())
            total.backward()
            return total

        final_loss = lbfgs.step(closure)
        history.append({"epoch": cfg.train.epochs, "total": float(final_loss.item()), "lbfgs": True})

    elapsed = time.time() - t0
    print(f"[train] done in {elapsed:.1f}s")
    _set_estado(f"{cfg.name}: done in {elapsed:.1f}s", enabled=cfg.train.heartbeat)

    peak_vram_mb = float(torch.cuda.max_memory_allocated(device) / 1e6) if device.type == "cuda" else 0.0

    # ---- save artefacts ----
    ckpt = {
        "state_dict": model.state_dict(),
        "model_kind": cfg.model.kind,
        "stage": cfg.physics.stage,
        "hidden_layers": cfg.model.hidden_layers,
        "activation": cfg.model.activation,
        "num_fourier_bands": cfg.features.num_fourier_bands,
        "fourier_sigma": cfg.features.fourier_sigma,
        "h_ref": cfg.data.h_ref,
        "sdf_wall_scale": cfg.model.sdf_wall_scale,
        "nut_scale": cfg.model.nut_scale,
        "k_scale": cfg.model.k_scale,
    }
    torch.save(ckpt, run_dir / "checkpoint.pt")
    cfgmod.save_config(cfg, str(run_dir / "config.yaml"))
    _plot_loss_curve(history, run_dir / "loss_curve.png", cfg.physics.stage)

    model.eval()
    run_metrics = evaluate_model(model, store, device, model_kind=cfg.model.kind,
                                  tag=f"{cfg.model.kind}_stage{cfg.physics.stage}")

    with open(run_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump({"history": history, "eval": run_metrics, "elapsed_s": elapsed,
                   "peak_vram_mb": peak_vram_mb, "field_std_train": field_std}, f, indent=2, default=str)

    result = {"model": model, "store": store, "history": history, "eval": run_metrics,
              "elapsed_s": elapsed, "peak_vram_mb": peak_vram_mb, "device": device}

    if cfg.compare_checkpoints:
        _run_comparison(cfg, run_dir, model, store, device)

    return result


def _predict_case_physical(model, model_kind: str, store: CaseStore, case, device,
                            chunk: int = 20000) -> Dict[str, np.ndarray]:
    a = case.arrays
    n = case.n_points
    s, c = case.sincos()
    href, uh = case.h_ref, case.u_h
    out = {f: np.empty(n, dtype=np.float32) for f in OUT_NAMES}
    with torch.no_grad():
        for start in range(0, n, chunk):
            end = min(start + chunk, n)
            xyz = torch.tensor(np.stack([a["x"][start:end] / href, a["y"][start:end] / href,
                                          a["z"][start:end] / href], axis=1), dtype=torch.float32, device=device)
            sincos = torch.tensor(np.tile([s, c], (end - start, 1)), dtype=torch.float32, device=device)
            sdf_m = torch.tensor(a["sdf"][start:end], dtype=torch.float32, device=device).view(-1, 1)
            h_m = torch.tensor(a["local_height"][start:end], dtype=torch.float32, device=device).view(-1, 1)
            pred = model(xyz, sincos, sdf_m, h_m)
            for f in OUT_NAMES:
                out[f][start:end] = pred[f].detach().cpu().numpy()
    # de-non-dimensionalise
    phys = {
        "u": out["u"] * uh, "v": out["v"] * uh, "w": out["w"] * uh,
        "p": out["p"] * uh ** 2, "k": out["k"] * uh ** 2, "nut": out["nut"] * uh * href,
    }
    return phys


def evaluate_model(model, store: CaseStore, device, model_kind: str, tag: str,
                    splits=("val", "test-direction", "test-speed", "test-variant"),
                    pedestrian_z: tuple = (1.5, 2.0),
                    eval_half_size_m: Optional[float] = None) -> Dict:
    """`eval_half_size_m` (geometry-pipeline coordination note): the real
    campus evaluation zone is 650x650 m (`eval_half_size_m=325`, from
    `geometry/out/H_best/frame.json`) -- narrower than the full ZOI cases
    are stored over. When set, every metric below is computed only on
    points with |x|<=eval_half_size_m and |y|<=eval_half_size_m (ZT-ENU,
    same frame as x,y in the HDF5). None (default) uses every stored point,
    which is correct for the synthetic smoke domain (already only ~200x200
    m) but WRONG for a real case without passing this."""
    results = {}
    for split in splits:
        ids = store.ids_for_split(split)
        results[split] = {}
        for cid in ids:
            case = store.cases[cid]
            pred_full = _predict_case_physical(model, model_kind, store, case, device)
            true_full = {f: case.arrays[f] for f in ["u", "v", "w", "p", "k", "nut"]}
            vol_full = case.arrays["vol"]
            x_full, y_full, z_full, sdf_full = (case.arrays["x"], case.arrays["y"],
                                                 case.arrays["z"], case.arrays["sdf"])

            if eval_half_size_m is not None:
                box = (np.abs(x_full) <= eval_half_size_m) & (np.abs(y_full) <= eval_half_size_m)
                pred = {k: v[box] for k, v in pred_full.items()}
                true = {k: v[box] for k, v in true_full.items()}
                vol, x, y, z, sdf = vol_full[box], x_full[box], y_full[box], z_full[box], sdf_full[box]
            else:
                pred, true, vol = pred_full, true_full, vol_full
                x, y, z, sdf = x_full, y_full, z_full, sdf_full

            rel_l2 = metrics.relative_l2_per_component(pred, true, weight=vol)
            mae_k = metrics.mae_speedup_factor(pred["u"], pred["v"], pred["w"],
                                                true["u"], true["v"], true["w"], case.u10, weight=vol)
            hit_u = metrics.vdi_hit_rate(pred["u"], true["u"], u_ref=case.u10, weight=vol)
            hit_v = metrics.vdi_hit_rate(pred["v"], true["v"], u_ref=case.u10, weight=vol)
            hit_w = metrics.vdi_hit_rate(pred["w"], true["w"], u_ref=case.u10, weight=vol)

            # M10: headline pedestrian-layer (1.5-2.0 m) K/|U| metric, the
            # metric that actually matters for wind comfort, reported
            # alongside (not instead of) the whole-ZOI numbers above.
            ped_mask = metrics.pedestrian_layer_mask(z, *pedestrian_z)
            if ped_mask.any():
                mae_k_ped = metrics.mae_speedup_factor(
                    pred["u"][ped_mask], pred["v"][ped_mask], pred["w"][ped_mask],
                    true["u"][ped_mask], true["v"][ped_mask], true["w"][ped_mask],
                    case.u10, weight=vol[ped_mask])
                hit_u_ped = metrics.vdi_hit_rate(pred["u"][ped_mask], true["u"][ped_mask],
                                                  u_ref=case.u10, weight=vol[ped_mask])
            else:
                mae_k_ped, hit_u_ped = float("nan"), float("nan")

            zone_err = None
            if case.n_wall > 0:
                zones = metrics.label_zones(x, y, z, sdf, case.theta_deg, case.h_ref,
                                             case.wall["x"], case.wall["y"], case.wall["z"],
                                             case.wall["nx"], case.wall["ny"], case.wall["nz"],
                                             wall_height=case.wall.get("height"), z_range=pedestrian_z)
                zone_err = metrics.per_zone_relative_l2(pred, true, zones, weight=vol)
            results[split][cid] = {
                "relative_l2": rel_l2, "mae_K": mae_k,
                "vdi_hit_rate": {"u": hit_u, "v": hit_v, "w": hit_w},
                "pedestrian_layer": {"mae_K": mae_k_ped, "vdi_hit_rate_u": hit_u_ped,
                                      "z_range": list(pedestrian_z)},
                "per_zone_relative_l2_pedestrian": zone_err,
            }
    return {tag: results}


def _load_checkpoint_model(ckpt_path: str, device):
    ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
    common = dict(h_ref=ckpt["h_ref"], num_fourier_bands=ckpt["num_fourier_bands"],
                  fourier_sigma=ckpt["fourier_sigma"], sdf_wall_scale=ckpt.get("sdf_wall_scale", 10.0),
                  nut_scale=ckpt.get("nut_scale", 0.01), k_scale=ckpt.get("k_scale", 1.0))
    if ckpt["model_kind"] == "deeponet":
        m = DeepONetPINN(**common)
    else:
        m = PINNMLP(hidden_layers=ckpt["hidden_layers"], activation=ckpt["activation"], **common)
    m.load_state_dict(ckpt["state_dict"])
    m.to(device).eval()
    return m, ckpt["model_kind"]


def _run_comparison(cfg: cfgmod.ExperimentConfig, run_dir: Path, self_model, store: CaseStore, device) -> None:
    """Loads sibling checkpoints (e.g. stage A, DeepONet) and evaluates every
    reference model (interpolation, nearest-direction, angular-interp) plus
    all networks on every held-out split, writing comparison_table.{csv,md}.
    """
    print("[compare] building full comparison table")
    loaded = {"self": (self_model, cfg.model.kind)}
    for name, ckpt_path in cfg.compare_checkpoints.items():
        loaded[name] = _load_checkpoint_model(ckpt_path, device)

    rows = []
    split_axis = {"val": None, "test-direction": "theta", "test-speed": "u10", "test-variant": None}
    for split, axis in split_axis.items():
        for cid in store.ids_for_split(split):
            case = store.cases[cid]
            true = {f: case.arrays[f] for f in ["u", "v", "w", "p", "k", "nut"]}
            vol = case.arrays["vol"]

            preds = {}
            for name, (m, kind) in loaded.items():
                preds[name] = _predict_case_physical(m, kind, store, case, device)

            if split == "val":
                # val is same-distribution as train; its dedicated reference
                # is spatial linear interpolation *within the field* (leave
                # out a random subset of the case's own points) -- this is an
                # ORACLE (uses 80% of this case's own ground truth), so it's
                # an upper bound on achievable accuracy, not a fair baseline
                # (M9, design review); labelled accordingly in the table.
                interp = baselines.spatial_interpolation_within_case(case)
                mask = interp.pop("_mask")
                preds["oracle_spatial_interp_within_case"] = {f: v for f, v in interp.items()}
                true_masked = {f: true[f][mask] for f in true}
                vol_masked = vol[mask]
                for name in ["self"] + [k for k in loaded if k != "self"] + ["oracle_spatial_interp_within_case"]:
                    p = preds[name]
                    p_use = {f: p[f][mask] for f in p} if name != "oracle_spatial_interp_within_case" else p
                    rows.append(_metrics_row(split, cid, name, p_use, true_masked, case, vol_masked))
                continue

            try:
                preds["nearest_direction"] = baselines.nearest_direction_prediction(
                    store, case, match_axis=axis or "theta")
                if axis == "theta":
                    preds["angular_interp"] = baselines.angular_interpolation_prediction(store, case)
            except RuntimeError as e:
                print(f"[compare] skipping a baseline for {cid}: {e}")

            for name, p in preds.items():
                rows.append(_metrics_row(split, cid, name, p, true, case, vol))

    _write_comparison_table(rows, run_dir)


def _metrics_row(split, cid, model_name, pred, true, case, vol) -> Dict:
    rel = metrics.relative_l2_per_component(pred, true, weight=vol)
    mae_k = metrics.mae_speedup_factor(pred["u"], pred["v"], pred["w"], true["u"], true["v"], true["w"],
                                        case.u10, weight=vol)
    hit_u = metrics.vdi_hit_rate(pred["u"], true["u"], u_ref=case.u10, weight=vol)
    return {"split": split, "case_id": cid, "model": model_name,
            "rel_l2_u": rel["u"], "rel_l2_v": rel["v"], "rel_l2_w": rel["w"],
            "rel_l2_p": rel["p"], "rel_l2_k": rel["k"], "rel_l2_nut": rel["nut"],
            "mae_K": mae_k, "vdi_hit_rate_u": hit_u}


def _write_comparison_table(rows: List[Dict], run_dir: Path) -> None:
    import csv
    if not rows:
        print("[compare] no rows to write")
        return
    fieldnames = list(rows[0].keys())
    with open(run_dir / "comparison_table.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    with open(run_dir / "comparison_table.md", "w", encoding="utf-8") as f:
        f.write("| " + " | ".join(fieldnames) + " |\n")
        f.write("|" + "|".join(["---"] * len(fieldnames)) + "|\n")
        for r in rows:
            f.write("| " + " | ".join(f"{r[k]:.4f}" if isinstance(r[k], float) else str(r[k]) for k in fieldnames) + " |\n")
    print(f"[compare] wrote {run_dir / 'comparison_table.csv'} ({len(rows)} rows)")


def _plot_loss_curve(history: List[Dict], path: Path, stage: str) -> None:
    keys = set()
    for row in history:
        keys.update(k for k in row if k not in ("epoch", "weights", "lbfgs"))
    fig, ax = plt.subplots(figsize=(6, 4))
    epochs = [row["epoch"] for row in history if "total" in row]
    for k in sorted(keys):
        ys = [row.get(k, np.nan) for row in history if "total" in row]
        ax.plot(epochs, ys, label=k)
    ax.set_yscale("log")
    ax.set_xlabel("epoch")
    ax.set_ylabel("loss")
    ax.set_title(f"loss curve (stage {stage})")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--out-dir", default=None, help="override out_dir from the config")
    args = parser.parse_args()

    cfg = cfgmod.load_config(args.config)
    out_dir = Path(args.out_dir or cfg.out_dir)
    train_one_config(cfg, out_dir)


if __name__ == "__main__":
    main()
