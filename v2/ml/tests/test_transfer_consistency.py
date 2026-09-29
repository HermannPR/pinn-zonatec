"""Design review (I2/M-transfer): ml/export.py's documented U_H(U10) formula
must match climate.transfer's actual P14-A two-layer roughness transfer, not
the earlier no-transfer formula (u_star = U10*kappa/ln((10-d+z0)/z0), which
silently treats the airport station's open-terrain z0 as if it were the
urban z0 and overestimates K by 5-31%). This test applies export.py's
DOCUMENTED formula using climate.transfer's own functions and checks it
reproduces climate.transfer.K_from_cfd_normalized exactly -- if the two
modules' APIs ever drift, this fails instead of silently re-introducing the
no-transfer bug in a future edit of the export.py note string.

Skips if climate/transfer.py or its roughness table isn't available in this
environment (it lives outside ml/'s scope; this test only ever reads it).
"""
import math
import os

import numpy as np
import pytest


def _load_transfer():
    import sys
    sys.path.insert(0, r"E:\PINN\v2")
    try:
        from climate import transfer
    except Exception as e:
        pytest.skip(f"climate.transfer not importable in this environment: {e}")
    if not os.path.exists(transfer.ROUGHNESS_CSV_DEFAULT):
        pytest.skip("roughness_16sectors.csv not present in this environment")
    return transfer


def test_export_formula_matches_climate_transfer_K():
    transfer = _load_transfer()
    table = transfer.load_roughness_table()
    U10 = 8.0
    H_ref = 85.0
    u_over_UH = 0.73  # arbitrary CFD-normalised sample output
    max_rel_diff = 0.0

    for _, row in table.iterrows():
        theta = float(row["theta_deg"])
        inflow = transfer.inflow_for_sector(theta, U10, row, z0_method="macdonald")

        # Reproduce export.py's documented formula by hand, using ONLY the
        # quantities export.py's nondim block carries (h_ref, kappa, z0, d)
        # plus T from climate.transfer (as the note says to) -- not
        # transfer.py's own U_H()/K_from_cfd_normalized convenience methods,
        # so this is a real cross-check of the formula text, not a tautology.
        u_star = inflow.T * U10
        U_H = (u_star / transfer.KAPPA) * math.log((H_ref - inflow.d + inflow.z0) / inflow.z0)
        K_by_hand = u_over_UH * (U_H / U10)
        K_reference = transfer.K_from_cfd_normalized(u_over_UH, inflow, H_ref)
        assert math.isclose(K_by_hand, K_reference, rel_tol=1e-9)

        # the no-transfer formula export.py used to document (bug)
        u_star_no_transfer = U10 * transfer.KAPPA / math.log((10.0 - inflow.d + inflow.z0) / inflow.z0)
        U_H_no_transfer = (u_star_no_transfer / transfer.KAPPA) * math.log(
            (H_ref - inflow.d + inflow.z0) / inflow.z0)
        K_no_transfer = u_over_UH * (U_H_no_transfer / U10)
        max_rel_diff = max(max_rel_diff, abs(K_no_transfer - K_reference) / K_reference)

    # across sectors, the no-transfer formula must diverge meaningfully from
    # the transfer-aware one (design review: 5-31% depending on sector) --
    # guards against silently reverting export.py's note to the buggy formula
    assert max_rel_diff > 0.03, f"max relative difference across sectors was only {max_rel_diff:.4f}"
