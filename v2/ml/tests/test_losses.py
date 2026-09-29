import torch

from ml import losses


def test_wall_bc_loss_zero_for_tangential_field():
    n = 300
    torch.manual_seed(2)
    pred = {
        "u": torch.randn(n),
        "v": torch.randn(n),
        "w": torch.zeros(n),
    }
    normal = {
        "nx": torch.zeros(n),
        "ny": torch.zeros(n),
        "nz": torch.ones(n),
    }
    loss = losses.wall_bc_loss(pred, normal)
    assert loss.item() < 1e-8


def test_wall_bc_loss_nonzero_for_penetrating_field():
    n = 300
    torch.manual_seed(3)
    pred = {
        "u": torch.zeros(n),
        "v": torch.zeros(n),
        "w": torch.ones(n),  # points straight into the wall
    }
    normal = {
        "nx": torch.zeros(n),
        "ny": torch.zeros(n),
        "nz": torch.ones(n),
    }
    loss = losses.wall_bc_loss(pred, normal)
    assert loss.item() > 0.5
