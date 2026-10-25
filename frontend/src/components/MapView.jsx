import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import { MapboxOverlay } from "@deck.gl/mapbox";

const STYLE = "https://tiles.openfreemap.org/styles/positron";
const TERRAIN = {
  type: "raster-dem",
  tiles: ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"],
  encoding: "terrarium",
  tileSize: 256,
  maxzoom: 14,
  attribution: "Terrain: Mapzen / AWS Open Data",
};
export const CENTER = [-79.95, 37.24];
// Roanoke service area (extent of the challenge data plus a margin); panning/zooming stays inside it
export const MAX_BOUNDS = [[-80.65, 36.75], [-79.25, 37.75]];

/** MapLibre basemap + deck.gl overlay. Layers update without recreating the map. */
export default function MapView({ layers, getTooltip, terrain = false, pitch = 0, bearing = 0, zoom = 10.2,
  center = CENTER, focus = null, focusZoom = 12, onMap, children }) {
  const el = useRef(null);
  const map = useRef(null);
  const overlay = useRef(null);

  useEffect(() => {
    const m = new maplibregl.Map({
      container: el.current, style: STYLE, center, zoom, pitch, bearing, maxPitch: 75, maxBounds: MAX_BOUNDS,
      attributionControl: { compact: true },
    });
    m.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
    const ov = new MapboxOverlay({ interleaved: false, layers: [], getTooltip });
    m.addControl(ov);
    m.on("load", () => {
      if (terrain) {
        m.addSource("dem", TERRAIN);
        m.setTerrain({ source: "dem", exaggeration: 1.6 });
        m.addLayer({ id: "hills", type: "hillshade", source: "dem", paint: { "hillshade-exaggeration": 0.35 } },
          firstSymbolLayer(m));
      }
      onMap?.(m);
    });
    map.current = m;
    overlay.current = ov;
    return () => m.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    overlay.current?.setProps({ layers: layers.filter(Boolean), getTooltip });
  }, [layers, getTooltip]);

  const fx = focus?.[0];
  const fy = focus?.[1];
  useEffect(() => {
    if (fx != null) map.current?.flyTo({ center: [fx, fy], zoom: focusZoom, duration: 1200 });
  }, [fx, fy]);

  return (
    <div className="map-wrap">
      <div ref={el} style={{ position: "absolute", inset: 0 }} />
      {children}
    </div>
  );
}

function firstSymbolLayer(m) {
  const l = m.getStyle().layers.find((x) => x.type === "symbol");
  return l?.id;
}

export function squarePolygon(lon, lat, half = 0.01) {
  return [[lon - half, lat - half], [lon + half, lat - half], [lon + half, lat + half], [lon - half, lat + half]];
}
