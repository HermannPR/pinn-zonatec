# Circular domain recommendation (H_max=54.0 m)
radius = ring_half*sqrt(2) + 15*H_max = 545*1.4142 + 15*54.0 = 1581 m
height = 6*H_max = 324 m
worst-case blockage (frontal_area_max / (2R*height)) = 18852 / 1024324 = 1.84%  (<3% target: OK)

Margin compromise: the outlet (15H) requirement is applied on EVERY side (not just downwind), since a circle has no preferred direction; this over-satisfies the 5H inlet/lateral requirement everywhere. Extra upstream distance costs little (coarse background mesh only). A 16-gon could trim ~21% of background volume vs. this circle at the same reach; not adopted here for simplicity.

## Mesh cell-count estimate, AS REQUESTED (bg 16 m / ring 4 m to 40 m height / ZOI core 2 m to 20 m height):
- background (outside ring band): 609,351 cells
- ring band (4 m): 516,781 cells
- ZOI core (2 m): 1,806,250 cells
- TOTAL (excl. near-wall boundary layers, +~10-20% typical): 2,932,383 cells

**This exceeds the 2-2.5M target** (and is above even the original 3-5M PC budget only if H_max grows further). To reach ~2-2.5M, background must coarsen to ~28 m and ring to ~6 m (ZOI core at 2 m over the full 850x850x20 m box is an essentially irreducible ~1,806,250 cells on its own):
- background (28 m): 113,698 cells
- ring band (6 m): 153,120 cells
- ZOI core (2 m, unchanged): 1,806,250 cells
- TOTAL: 2,073,069 cells

**What gives**: hitting 2-2.5M means coarsening background/ring beyond the requested 16 m/4 m (28 m/6 m as shown), OR shrinking the 2 m-refined ZOI footprint/height below 850x850x20 m, OR accepting ~4-4.5M cells (background 16 m, ring 4 m only up to 40 m height) which still fits the ORIGINAL 3-5M PC budget from the task brief. Recommendation: keep ZOI near-field resolution (pedestrian-level answer quality depends on it most) and accept ~4-4.5M, OR relax to the 28 m/6 m plan if 2-2.5M is a hard ceiling.
