import numpy as np
import torch

from ml.data import VariantVocab
from ml.export import export_pinn_mlp, predict_from_json
from ml.models import PINNMLP
import json


def test_export_round_trip_matches_torch_forward(tmp_path):
    torch.manual_seed(0)
    vocab = VariantVocab(["base", "var1"])
    h_ref = 25.0
    model = PINNMLP(num_variants=len(vocab), h_ref=h_ref, num_fourier_bands=6,
                     fourier_sigma=3.0, variant_embedding_dim=4,
                     hidden_layers=[32, 32], activation="tanh")
    model.eval()

    out_path = tmp_path / "model.json"
    export_pinn_mlp(model, vocab, h_ref=h_ref, z0=0.5, d=0.0, path=str(out_path))

    n = 128
    rng = np.random.default_rng(0)
    xyz_m = rng.uniform(-100, 100, size=(n, 3)).astype(np.float32)
    xyz_m[:, 2] = np.abs(xyz_m[:, 2])
    theta_deg = rng.uniform(0, 360, size=n).astype(np.float32)
    variant_names = rng.choice(vocab.variants, size=n)
    sdf_m = rng.uniform(0, 50, size=n).astype(np.float32)
    height_m = rng.uniform(0, 30, size=n).astype(np.float32)

    with torch.no_grad():
        xyz_t = torch.tensor(xyz_m / h_ref, dtype=torch.float32)
        theta_rad = np.deg2rad(theta_deg)
        sincos_t = torch.tensor(np.stack([np.sin(theta_rad), np.cos(theta_rad)], axis=1), dtype=torch.float32)
        vid_t = torch.tensor([vocab.id_of(v) for v in variant_names], dtype=torch.long)
        sdf_t = torch.tensor(sdf_m, dtype=torch.float32).view(-1, 1)
        h_t = torch.tensor(height_m, dtype=torch.float32).view(-1, 1)
        torch_out = model(xyz_t, sincos_t, vid_t, sdf_t, h_t)

    with open(out_path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    json_out = predict_from_json(obj, xyz_m, theta_deg, list(variant_names), sdf_m, height_m)

    for name in ["u", "v", "w", "p", "k", "nut"]:
        a = torch_out[name].numpy()
        b = json_out[name]
        max_diff = np.max(np.abs(a - b))
        assert max_diff < 1e-5, f"{name}: max diff {max_diff}"
