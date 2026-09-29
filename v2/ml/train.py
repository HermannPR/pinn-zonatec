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
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import subprocess
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


def build_model(cfg: cfgmod.ExperimentConfig, num_variants: int):
    if cfg.model.kind == "deeponet":
        return DeepONetPINN(num_variants=num_variants, h_ref=cfg.data.h_ref,
                             num_fourier_bands=cfg.features.num_fourier_bands,
                             fourier_sigma=cfg.features.fourier_sigma,
                             variant_embedding_dim=cfg.features.variant_embedding_dim)
    return PINNMLP(num_variants=num_variants, h_ref=cfg.data.h_ref,
                    num_fourier_bands=cfg.features.num_fourier_bands,
                    fourier_sigma=cfg.features.fourier_sigma,
                    variant_embedding_dim=cfg.features.variant_embedding_dim,
                    hidden_layers=cfg.model.hidden_layers, activation=cfg.model.activation)


def forward_model(model, batch):
    if isinstance(model, DeepONetPINN):
        return model(batch.xyz, batch.sincos, batch.variant_id, batch.sdf_m, batch.height_m,
                     batch.u10_over_uref)
    return model(batch.xyz, batch.sincos, batch.variant_id, batch.sdf_m, batch.height_m)


def train_one_config(cfg: cfgmod.ExperimentConfig, run_dir: Path) -> Dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    device = torch.device(cfg.train.device if torch.cuda.is_available() and cfg.train.device == "cuda" else "cpu")
    if device.type == "cuda":
        check_gpu()
    print(f"[train] device={device} stage={cfg.physics.stage} model={cfg.model.kind}")

    store = CaseStore(cfg.data.manifest)
    sampler = EpochSampler(store, device=device, seed=cfg.data.seed)
    train_ids = store.ids_for_split("train")
    print(f"[train] {len(train_ids)} train cases, {len(store.cases)} total cases, "
          f"{len(store.vocab)} variants")

    model = build_model(cfg, num_variants=len(store.vocab)).to(device)
    weight_cfg = cfg.loss_weights
    base_weights = {"data": weight_cfg.w_data}
    if cfg.physics.stage in ("B", "C"):
        base_weights["continuity"] = weight_cfg.w_continuity
        base_weights["wall_bc"] = weight_cfg.w_wall_bc
    if cfg.physics.stage == "C":
        base_weights["momentum"] = weight_cfg.w_momentum
    weighter = weighting.build_weighting(weight_cfg.mode, base_weights, alpha=weight_cfg.lra_alpha)

    opt = torch.optim.Adam(model.parameters(), lr=cfg.train.lr)

    history: List[Dict[str, float]] = []
    n_per_case_sup = max(1, cfg.data.points_per_epoch // max(1, len(train_ids)))
    n_per_case_col = max(1, cfg.data.collocation_per_epoch // max(1, len(train_ids)))
    n_per_case_wall = max(1, cfg.data.wall_points_per_epoch // max(1, len(train_ids)))

    t0 = time.time()
    for epoch in range(cfg.train.epochs):
        epoch_losses: Dict[str, float] = {}
        for step in range(cfg.train.steps_per_epoch):
            opt.zero_grad()
            loss_terms = {}

            sup = sampler.sample_supervised(train_ids, n_per_case_sup, requires_grad=False)
            pred_sup = forward_model(model, sup)
            l_data, per_field = losses.data_loss(pred_sup, sup.target)
            loss_terms["data"] = l_data

            if cfg.physics.stage in ("B", "C"):
                col = sampler.sample_supervised(train_ids, n_per_case_col, requires_grad=True)
                pred_col = forward_model(model, col)
                loss_terms["continuity"] = losses.continuity_loss(pred_col, col.xyz)
                if cfg.physics.stage == "C":
                    loss_terms["momentum"] = losses.momentum_loss(
                        pred_col, col.xyz, nu=cfg.physics.nu,
                        pressure_includes_two_thirds_k=cfg.physics.pressure_includes_two_thirds_k)

                wall = sampler.sample_wall(train_ids, n_per_case_wall)
                if wall is not None:
                    pred_wall = forward_model(model, wall)
                    loss_terms["wall_bc"] = losses.wall_bc_loss(pred_wall, wall.target)

            if weight_cfg.mode == "lra" and step % max(1, weight_cfg.lra_every) == 0 and len(loss_terms) > 1:
                weights = weighter.update(model, loss_terms)
            else:
                weights = weighter.weights if hasattr(weighter, "weights") else base_weights

            total = sum(weights.get(name, 1.0) * val for name, val in loss_terms.items())
            total.backward()
            if cfg.train.grad_clip:
                torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.train.grad_clip)
            opt.step()

            for name, val in loss_terms.items():
                epoch_losses[name] = epoch_losses.get(name, 0.0) + float(val.item())
            epoch_losses["total"] = epoch_losses.get("total", 0.0) + float(total.item())

        n = cfg.train.steps_per_epoch
        row = {k: v / n for k, v in epoch_losses.items()}
        row["epoch"] = epoch
        row["weights"] = {k: float(v) for k, v in (weighter.weights if hasattr(weighter, "weights") else base_weights).items()}
        history.append(row)
        if epoch % cfg.train.log_every == 0 or epoch == cfg.train.epochs - 1:
            print(f"[train] epoch {epoch:4d} " + " ".join(f"{k}={row[k]:.4e}" for k in row if k not in ("epoch", "weights")))

    # ---- optional L-BFGS refinement phase (P26=A) ----
    if cfg.train.optimizer == "adam+lbfgs" and cfg.train.lbfgs_steps > 0:
        print(f"[train] L-BFGS refinement: {cfg.train.lbfgs_steps} steps")
        fixed_weights = weighter.weights if hasattr(weighter, "weights") else base_weights
        sup = sampler.sample_supervised(train_ids, n_per_case_sup * 2, requires_grad=False)
        col = sampler.sample_supervised(train_ids, n_per_case_col * 2, requires_grad=True) if cfg.physics.stage in ("B", "C") else None
        wall = sampler.sample_wall(train_ids, n_per_case_wall * 2) if cfg.physics.stage in ("B", "C") else None
        lbfgs = torch.optim.LBFGS(model.parameters(), lr=cfg.train.lbfgs_lr, max_iter=cfg.train.lbfgs_steps,
                                   line_search_fn="strong_wolfe")

        def closure():
            lbfgs.zero_grad()
            terms = {}
            pred_sup = forward_model(model, sup)
            l_data, _ = losses.data_loss(pred_sup, sup.target)
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
                terms["continuity"] = losses.continuity_loss(pred_col, col.xyz)
                if cfg.physics.stage == "C":
                    terms["momentum"] = losses.momentum_loss(pred_col, col.xyz, nu=cfg.physics.nu,
                        pressure_includes_two_thirds_k=cfg.physics.pressure_includes_two_thirds_k)
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
        "variant_embedding_dim": cfg.features.variant_embedding_dim,
        "h_ref": cfg.data.h_ref,
        "variants": store.vocab.variants,
    }
    torch.save(ckpt, run_dir / "checkpoint.pt")
    cfgmod.save_config(cfg, str(run_dir / "config.yaml"))
    _plot_loss_curve(history, run_dir / "loss_curve.png", cfg.physics.stage)

    model.eval()
    run_metrics = evaluate_model(model, store, device, model_kind=cfg.model.kind,
                                  tag=f"{cfg.model.kind}_stage{cfg.physics.stage}")

    with open(run_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump({"history": history, "eval": run_metrics, "elapsed_s": elapsed,
                   "peak_vram_mb": peak_vram_mb}, f, indent=2, default=str)

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
            vid = torch.full((end - start,), case.variant_id, dtype=torch.long, device=device)
            sdf_m = torch.tensor(a["sdf"][start:end], dtype=torch.float32, device=device).view(-1, 1)
            h_m = torch.tensor(a["local_height"][start:end], dtype=torch.float32, device=device).view(-1, 1)
            if model_kind == "deeponet":
                u10r = torch.full((end - start, 1), case.u10 / U10_REF, dtype=torch.float32, device=device)
                pred = model(xyz, sincos, vid, sdf_m, h_m, u10r)
            else:
                pred = model(xyz, sincos, vid, sdf_m, h_m)
            for f in OUT_NAMES:
                out[f][start:end] = pred[f].detach().cpu().numpy()
    # de-non-dimensionalise
    phys = {
        "u": out["u"] * uh, "v": out["v"] * uh, "w": out["w"] * uh,
        "p": out["p"] * uh ** 2, "k": out["k"] * uh ** 2, "nut": out["nut"] * uh * href,
    }
    return phys


def evaluate_model(model, store: CaseStore, device, model_kind: str, tag: str,
                    splits=("val", "test-direction", "test-speed", "test-variant")) -> Dict:
    results = {}
    for split in splits:
        ids = store.ids_for_split(split)
        results[split] = {}
        for cid in ids:
            case = store.cases[cid]
            pred = _predict_case_physical(model, model_kind, store, case, device)
            true = {f: case.arrays[f] for f in ["u", "v", "w", "p", "k", "nut"]}
            rel_l2 = metrics.relative_l2_per_component(pred, true)
            mae_k = metrics.mae_speedup_factor(pred["u"], pred["v"], pred["w"],
                                                true["u"], true["v"], true["w"], case.u10)
            hit_u = metrics.vdi_hit_rate(pred["u"], true["u"], u_ref=case.u10)
            hit_v = metrics.vdi_hit_rate(pred["v"], true["v"], u_ref=case.u10)
            hit_w = metrics.vdi_hit_rate(pred["w"], true["w"], u_ref=case.u10)
            zone_err = None
            if case.n_wall > 0:
                zones = metrics.label_zones(case.arrays["x"], case.arrays["y"], case.arrays["z"],
                                             case.arrays["sdf"], case.theta_deg, case.h_ref,
                                             case.wall["x"], case.wall["y"], case.wall["z"],
                                             case.wall["nx"], case.wall["ny"], case.wall["nz"])
                zone_err = metrics.per_zone_relative_l2(pred, true, zones)
            results[split][cid] = {
                "relative_l2": rel_l2, "mae_K": mae_k,
                "vdi_hit_rate": {"u": hit_u, "v": hit_v, "w": hit_w},
                "per_zone_relative_l2": zone_err,
            }
    return {tag: results}


def _run_comparison(cfg: cfgmod.ExperimentConfig, run_dir: Path, self_model, store: CaseStore, device) -> None:
    """Loads sibling checkpoints (e.g. stage A, DeepONet) and evaluates every
    reference model (interpolation, nearest-direction, angular-interp) plus
    all networks on every held-out split, writing comparison_table.{csv,md}.
    """
    print("[compare] building full comparison table")
    loaded = {"self": (self_model, cfg.model.kind)}
    for name, ckpt_path in cfg.compare_checkpoints.items():
        ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
        m = PINNMLP(num_variants=len(ckpt["variants"]), h_ref=ckpt["h_ref"],
                    num_fourier_bands=ckpt["num_fourier_bands"], fourier_sigma=ckpt["fourier_sigma"],
                    variant_embedding_dim=ckpt["variant_embedding_dim"],
                    hidden_layers=ckpt["hidden_layers"], activation=ckpt["activation"]) \
            if ckpt["model_kind"] != "deeponet" else \
            DeepONetPINN(num_variants=len(ckpt["variants"]), h_ref=ckpt["h_ref"],
                         num_fourier_bands=ckpt["num_fourier_bands"], fourier_sigma=ckpt["fourier_sigma"],
                         variant_embedding_dim=ckpt["variant_embedding_dim"])
        m.load_state_dict(ckpt["state_dict"])
        m.to(device).eval()
        loaded[name] = (m, ckpt["model_kind"])

    rows = []
    split_axis = {"val": None, "test-direction": "theta", "test-speed": "u10", "test-variant": None}
    for split, axis in split_axis.items():
        for cid in store.ids_for_split(split):
            case = store.cases[cid]
            true = {f: case.arrays[f] for f in ["u", "v", "w", "p", "k", "nut"]}

            preds = {}
            for name, (m, kind) in loaded.items():
                preds[name] = _predict_case_physical(m, kind, store, case, device)

            if split == "val":
                # val is same-distribution as train; its dedicated reference
                # is spatial linear interpolation *within the field* (leave
                # out a random subset of the case's own points), not the
                # cross-case direction/speed baselines below.
                interp = baselines.spatial_interpolation_within_case(case)
                mask = interp.pop("_mask")
                preds["spatial_interp_within_case"] = {f: v for f, v in interp.items()}
                true_masked = {f: true[f][mask] for f in true}
                for name in ["self"] + [k for k in loaded if k != "self"] + ["spatial_interp_within_case"]:
                    p = preds[name]
                    p_use = {f: p[f][mask] for f in p} if name != "spatial_interp_within_case" else p
                    rows.append(_metrics_row(split, cid, name, p_use, true_masked, case))
                continue

            try:
                preds["nearest_direction"] = baselines.nearest_direction_prediction(
                    store, case, match_axis=axis or "theta")
                if axis == "theta":
                    preds["angular_interp"] = baselines.angular_interpolation_prediction(store, case)
            except RuntimeError as e:
                print(f"[compare] skipping a baseline for {cid}: {e}")

            for name, p in preds.items():
                rows.append(_metrics_row(split, cid, name, p, true, case))

    _write_comparison_table(rows, run_dir)


def _metrics_row(split, cid, model_name, pred, true, case) -> Dict:
    rel = metrics.relative_l2_per_component(pred, true)
    mae_k = metrics.mae_speedup_factor(pred["u"], pred["v"], pred["w"], true["u"], true["v"], true["w"], case.u10)
    hit_u = metrics.vdi_hit_rate(pred["u"], true["u"], u_ref=case.u10)
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
