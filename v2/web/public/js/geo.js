// geo.js -- local ENU (ZT-ENU, metres) <-> lon/lat conversion. Tangent-plane
// approximation anchored at scene.origin_lon/origin_lat -- MUST match
// web/build/common.py:meters_per_degree/enu_to_lonlat EXACTLY (same
// constants, same formula) so every precomputed asset (buildings.geojson,
// SDF/height grids) lines up with anything computed here to floating point
// precision, independent of absolute geodetic accuracy (documented
// simplification, see README.md "Marco de coordenadas").

export function metersPerDegree(latDeg) {
  const lat = (latDeg * Math.PI) / 180.0;
  const mPerDegLat = 111132.92 - 559.82 * Math.cos(2 * lat) + 1.175 * Math.cos(4 * lat) - 0.0023 * Math.cos(6 * lat);
  const mPerDegLon = 111412.84 * Math.cos(lat) - 93.5 * Math.cos(3 * lat) + 0.118 * Math.cos(5 * lat);
  return { mPerDegLat, mPerDegLon };
}

export function enuToLonLat(x, y, originLon, originLat) {
  const { mPerDegLat, mPerDegLon } = metersPerDegree(originLat);
  return [originLon + x / mPerDegLon, originLat + y / mPerDegLat];
}

export function lonLatToEnu(lon, lat, originLon, originLat) {
  const { mPerDegLat, mPerDegLon } = metersPerDegree(originLat);
  const x = (lon - originLon) * mPerDegLon;
  const y = (lat - originLat) * mPerDegLat;
  return [x, y];
}

// 16-sector meteorological convention: 0=N,22.5=NNE,...,clockwise.
export const SECTOR_NAMES_ES = [
  "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
  "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO",
];

export function sectorIndex(thetaDeg) {
  return Math.round(((thetaDeg % 360) + 360) % 360 / 22.5) % 16;
}

export function sectorLabel(thetaDeg) {
  return SECTOR_NAMES_ES[sectorIndex(thetaDeg)];
}
