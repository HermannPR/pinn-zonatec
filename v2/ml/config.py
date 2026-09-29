"""Configuration objects and YAML loading for the PINN Zona Tec package.

All physical non-dimensionalisation constants live here so every module
(sythetic data generation, training, metrics) agrees on the same reference
scales, per docs/DATA_CONTRACT.md ("Non-dimensionalisation (ML)" section):

    lengths  / H_ref
    velocities / U_H      (inflow speed at z = H_ref)
    p, k     / U_H^2
    nut      / (U_H * H_ref)

For the synthetic smoke-test data (no real geometry/frame.json exists yet)
H_ref is fixed to the height of the tallest "base"-variant building, and is
stored as an attribute on every synthetic case file so it never has to be
guessed downstream.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

KAPPA = 0.41
CMU = 0.09


@dataclasses.dataclass
class DataConfig:
    data_dir: str = "data/synthetic"
    manifest: str = "data/synthetic/manifest.csv"
    h_ref: float = 25.0  # m, reference building height (non-dim length scale)
    points_per_epoch: int = 4096  # supervised points sampled per case per step
    collocation_per_epoch: int = 4096  # physics collocation points per case per step
    wall_points_per_epoch: int = 512
    num_workers: int = 0
    seed: int = 0


@dataclasses.dataclass
class FeatureConfig:
    num_fourier_bands: int = 8
    fourier_sigma: float = 4.0
    variant_embedding_dim: int = 4
    include_sdf: bool = True
    include_local_height: bool = True


@dataclasses.dataclass
class ModelConfig:
    kind: str = "mlp"  # "mlp" | "deeponet"
    hidden_layers: List[int] = dataclasses.field(default_factory=lambda: [128, 128, 128, 128])
    activation: str = "tanh"
    output_kind_positive: str = "softplus"  # for k, nut >= 0


@dataclasses.dataclass
class PhysicsConfig:
    stage: str = "A"  # "A" (data only) | "B" (+continuity) | "C" (+momentum)
    nu: float = 1.5e-5  # m^2/s, kinematic molecular viscosity of air
    n_collocation: int = 4096
    n_wall: int = 512
    pressure_includes_two_thirds_k: bool = False  # see physics.py docstring


@dataclasses.dataclass
class LossWeightConfig:
    mode: str = "fixed"  # "fixed" | "lra" (learning-rate annealing, Wang et al. 2021)
    lra_alpha: float = 0.9
    lra_every: int = 20
    w_data: float = 1.0
    w_continuity: float = 1.0
    w_momentum: float = 1.0
    w_wall_bc: float = 1.0


@dataclasses.dataclass
class TrainConfig:
    epochs: int = 200
    steps_per_epoch: int = 20
    optimizer: str = "adam"  # "adam" | "adam+lbfgs"
    lr: float = 1e-3
    lbfgs_steps: int = 50
    lbfgs_lr: float = 1.0
    batch_size: int = 4096
    device: str = "cuda"
    amp: bool = False  # must stay False for residual (autograd) terms per P26
    grad_clip: Optional[float] = 1.0
    log_every: int = 5


@dataclasses.dataclass
class ExperimentConfig:
    name: str = "smoke"
    out_dir: str = "ml/runs/smoke"
    data: DataConfig = dataclasses.field(default_factory=DataConfig)
    features: FeatureConfig = dataclasses.field(default_factory=FeatureConfig)
    model: ModelConfig = dataclasses.field(default_factory=ModelConfig)
    physics: PhysicsConfig = dataclasses.field(default_factory=PhysicsConfig)
    loss_weights: LossWeightConfig = dataclasses.field(default_factory=LossWeightConfig)
    train: TrainConfig = dataclasses.field(default_factory=TrainConfig)
    # optional: {name: checkpoint_path} of sibling runs (e.g. stage A, DeepONet)
    # to fold into this run's comparison_table.{csv,md} after training finishes.
    compare_checkpoints: Optional[Dict[str, str]] = None


def _merge(dc_cls, d: Optional[Dict[str, Any]]):
    if d is None:
        return dc_cls()
    return dc_cls(**d)


def load_config(path: str) -> ExperimentConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    cfg = ExperimentConfig(
        name=raw.get("name", "smoke"),
        out_dir=raw.get("out_dir", "ml/runs/smoke"),
        data=_merge(DataConfig, raw.get("data")),
        features=_merge(FeatureConfig, raw.get("features")),
        model=_merge(ModelConfig, raw.get("model")),
        physics=_merge(PhysicsConfig, raw.get("physics")),
        loss_weights=_merge(LossWeightConfig, raw.get("loss_weights")),
        train=_merge(TrainConfig, raw.get("train")),
        compare_checkpoints=raw.get("compare_checkpoints"),
    )
    return cfg


def config_to_dict(cfg: ExperimentConfig) -> Dict[str, Any]:
    return dataclasses.asdict(cfg)


def save_config(cfg: ExperimentConfig, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config_to_dict(cfg), f, sort_keys=False)
