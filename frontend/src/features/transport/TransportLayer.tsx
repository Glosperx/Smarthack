import { useEffect, useMemo, useState } from 'react';
import { CircleMarker, Popup, Tooltip, useMap } from 'react-leaflet';
import L from 'leaflet';
import {
  CLASS_LABEL,
  CLASS_WEIGHT,
  VERDICT_STYLE,
  reasonLabels,
  type PackedRoad,
  type TransportNetwork,
  type TransportSummary,
} from './api';

interface TransportLayerProps {
  network: TransportNetwork;
  summary: TransportSummary;
  /** Verdict codes currently shown. */
  visible: Set<number>;
  /** Whether county roads (tertiary) are drawn. */
  showCounty: boolean;
}

interface Picked {
  road: PackedRoad;
  at: L.LatLng;
}

/** Squared distance from a point to a segment, in a plane scaled by cos(latitude). */
function segDist2(px: number, py: number, ax: number, ay: number, bx: number, by: number) {
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2));
  const qx = ax + t * dx - px;
  const qy = ay + t * dy - py;
  return qx * qx + qy * qy;
}

/** The road of a group closest to a clicked point. */
function nearestRoad(roads: PackedRoad[], at: L.LatLng): PackedRoad | null {
  const k = Math.cos((at.lat * Math.PI) / 180);
  let best: PackedRoad | null = null;
  let bestD = Infinity;
  for (const road of roads) {
    const c = road[4];
    for (let i = 0; i + 3 < c.length; i += 2) {
      const d = segDist2(at.lng * k, at.lat, c[i + 1] * k, c[i], c[i + 3] * k, c[i + 2]);
      if (d < bestD) {
        bestD = d;
        best = road;
      }
    }
  }
  return best;
}

/**
 * The judged road network: one canvas multi-polyline per (verdict, class) group, so tens of
 * thousands of roads draw as a handful of layers. A click finds the nearest road of the
 * clicked group and explains its verdict. Must be rendered inside a react-leaflet map.
 */
export function TransportLayer({ network, summary, visible, showCounty }: TransportLayerProps) {
  const map = useMap();
  const [picked, setPicked] = useState<Picked | null>(null);

  // Group once per network: key "verdict:class" -> roads.
  const groups = useMemo(() => {
    const byKey = new Map<string, { verdict: number; cls: number; roads: PackedRoad[] }>();
    for (const road of network.roads) {
      const key = `${road[1]}:${road[0]}`;
      let g = byKey.get(key);
      if (!g) {
        g = { verdict: road[1], cls: road[0], roads: [] };
        byKey.set(key, g);
      }
      g.roads.push(road);
    }
    return [...byKey.values()].sort(
      (a, b) =>
        VERDICT_STYLE[a.verdict].order - VERDICT_STYLE[b.verdict].order || b.cls - a.cls
    );
  }, [network]);

  useEffect(() => {
    const renderer = L.canvas({ padding: 0.5, tolerance: 6 });
    const layers: L.Polyline[] = [];
    for (const g of groups) {
      const cls = network.classes[g.cls];
      if (!visible.has(g.verdict)) continue;
      if (cls === 'tertiary' && !showCounty) continue;
      const lines = g.roads.map((r) => {
        const c = r[4];
        const pts: L.LatLngTuple[] = [];
        for (let i = 0; i + 1 < c.length; i += 2) pts.push([c[i], c[i + 1]]);
        return pts;
      });
      const layer = L.polyline(lines, {
        renderer,
        color: VERDICT_STYLE[g.verdict].color,
        weight: CLASS_WEIGHT[cls] ?? 1.5,
        opacity: 0.9,
        lineCap: 'round',
        lineJoin: 'round',
        bubblingMouseEvents: false,
      });
      layer.on('click', (e: L.LeafletMouseEvent) => {
        const road = nearestRoad(g.roads, e.latlng);
        if (road) setPicked({ road, at: e.latlng });
      });
      layer.addTo(map);
      layers.push(layer);
    }
    return () => {
      for (const layer of layers) layer.remove();
      renderer.remove();
    };
  }, [groups, network, visible, showCounty, map]);

  return (
    <>
      {summary.ports.map((port) => (
        <CircleMarker
          key={port.name}
          center={[port.latitude, port.longitude]}
          radius={7}
          pathOptions={{ color: '#0f172a', weight: 2, fillColor: '#38bdf8', fillOpacity: 1 }}
          bubblingMouseEvents={false}
        >
          <Tooltip direction="top" offset={[0, -6]} opacity={0.95} permanent>
            <span className="font-sans text-[11px] font-semibold text-slate-900">{port.name}</span>
          </Tooltip>
        </CircleMarker>
      ))}
      {picked && (
        <Popup position={picked.at} eventHandlers={{ remove: () => setPicked(null) }}>
          <RoadPopup road={picked.road} network={network} summary={summary} />
        </Popup>
      )}
    </>
  );
}

/** Popup body explaining one road's verdict. */
function RoadPopup({
  road,
  network,
  summary,
}: {
  road: PackedRoad;
  network: TransportNetwork;
  summary: TransportSummary;
}) {
  const [cls, verdict, reasons, refIndex] = road;
  const style = VERDICT_STYLE[verdict];
  const verdictStat = summary.verdicts.find((v) => v.code === verdict);
  const ref = refIndex >= 0 ? network.refs[refIndex] : null;
  const labels = reasonLabels(reasons, summary);
  const className = network.classes[cls];
  return (
    <div className="font-sans w-64 space-y-2">
      <div className="flex items-center gap-2">
        <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: style.color }} />
        <span className="text-sm font-semibold text-slate-900">{style.name}</span>
        <span className="ml-auto text-xs text-slate-500">{ref ?? 'no ref'}</span>
      </div>
      <p className="text-[11px] text-slate-500">{CLASS_LABEL[className] ?? className}</p>
      {verdictStat && <p className="text-xs leading-snug text-slate-700">{verdictStat.label}</p>}
      {labels.length > 0 && (
        <ul className="list-disc pl-4 text-xs text-slate-700">
          {labels.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
