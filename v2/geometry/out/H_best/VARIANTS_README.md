# Zona Tec geometry variants

## var1 -- projected tower
A hypothetical 28x28 m tower, height capped at this scenario's H_max=87.8 m, is added at ZT-ENU (-45, 25) (largest open gap, >=8 m clearance, found by grid search). Capped at H_max so base/var1/var2/var3 share one COST-732 domain; a taller tower would need its own domain/mesh.

## var2 -- empty lot
Building osm_id=1539829822 (footprint 1019 m2, height 6.5 m, source=google_25d) at ZT-ENU (332,47) removed (demolition/vacant-lot scenario).

## var3 -- infill (optional)
A hypothetical 18x18 m, 15 m infill building at ZT-ENU (43, -47), a second open gap. Milder densification than var1.
