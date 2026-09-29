// map.js -- MapLibre GL JS setup: OSM raster basemap (light usage, proper
// attribution, no bulk prefetch -- a single map instance, no tile
// pre-warming), 3D-extruded building footprints coloured by height, click
// marker, and the heatmap image overlay.

import { enuToLonLat } from "./geo.js";

const OSM_ATTRIBUTION = '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a>';

export function initMap(containerId, sceneData) {
  const maplibregl = window.maplibregl;
  if (!maplibregl) throw new Error("maplibre-gl no cargo (revisa la etiqueta <script> en index.html)");

  const map = new maplibregl.Map({
    container: containerId,
    style: {
      version: 8,
      sources: {
        osm: {
          type: "raster",
          tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
          tileSize: 256,
          maxzoom: 19,
          attribution: OSM_ATTRIBUTION,
        },
      },
      layers: [{ id: "osm", type: "raster", source: "osm" }],
    },
    center: [sceneData.origin_lon, sceneData.origin_lat],
    zoom: 15.5,
    pitch: 45,
    bearing: -10,
    maxPitch: 70,
  });
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
  map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
  return map;
}

export function addBuildingsLayer(map, geojson) {
  map.addSource("buildings", { type: "geojson", data: geojson });
  map.addLayer({
    id: "buildings-3d",
    type: "fill-extrusion",
    source: "buildings",
    paint: {
      "fill-extrusion-height": ["get", "height_m"],
      "fill-extrusion-base": 0,
      "fill-extrusion-opacity": 0.85,
      "fill-extrusion-color": [
        "interpolate", ["linear"], ["get", "height_m"],
        0, "#cde2fb",
        15, "#6da7ec",
        30, "#3987e5",
        50, "#256abf",
        90, "#0d366b",
      ],
    },
  });
}

export function addHeatmapSource(map) {
  // Placeholder 1x1 transparent image; replaced by updateHeatmapImage once
  // the worker returns the first grid. MapLibre requires a valid image/
  // coordinates pair to create an 'image' source.
  const TRANSPARENT_PX = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=";
  map.addSource("heatmap", {
    type: "image",
    url: TRANSPARENT_PX,
    coordinates: [[0, 0], [0, 0], [0, 0], [0, 0]],
  });
  map.addLayer({
    id: "heatmap-layer",
    type: "raster",
    source: "heatmap",
    paint: { "raster-opacity": 0.7, "raster-fade-duration": 0 },
  }, "buildings-3d");
}

/**
 * Replace the heatmap image. `bounds` = {x0,y0,x1,y1} in ZT-ENU metres
 * (x0,y0 = SW corner, x1,y1 = NE corner). `dataUrl` is a canvas.toDataURL()
 * PNG of the rendered grid (row 0 = SOUTH edge, matching the coordinates
 * below).
 */
export function updateHeatmapImage(map, dataUrl, bounds, sceneData) {
  const { x0, y0, x1, y1 } = bounds;
  const nw = enuToLonLat(x0, y1, sceneData.origin_lon, sceneData.origin_lat);
  const ne = enuToLonLat(x1, y1, sceneData.origin_lon, sceneData.origin_lat);
  const se = enuToLonLat(x1, y0, sceneData.origin_lon, sceneData.origin_lat);
  const sw = enuToLonLat(x0, y0, sceneData.origin_lon, sceneData.origin_lat);
  const src = map.getSource("heatmap");
  src.updateImage({ url: dataUrl, coordinates: [nw, ne, se, sw] });
}

export function placeMarker(map, marker, lon, lat) {
  const maplibregl = window.maplibregl;
  if (marker) { marker.setLngLat([lon, lat]); return marker; }
  const el = document.createElement("div");
  el.className = "pin-marker";
  return new maplibregl.Marker({ element: el }).setLngLat([lon, lat]).addTo(map);
}
