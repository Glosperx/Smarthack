import { useEffect, useState } from 'react';
import { ImageOverlay, Marker, Popup, Tooltip, useMap, useMapEvents } from 'react-leaflet';
import L from 'leaflet';
import {
  HEATMAP_URL,
  formatChange,
  useResourcePoint,
  type ResourceSite,
  type ResourceSummary,
} from './api';

interface WindResourceLayerProps {
  summary: ResourceSummary;
  sites: ResourceSite[];
  focusedRank: number | null;
}

/**
 * Numbered site pin: white disc with dark ink, readable over both the map and the heatmap.
 */
function siteIcon(rank: number, focused: boolean) {
  const size = focused ? 34 : 26;
  return L.divIcon({
    className: '!bg-transparent !border-none',
    html: `<div class="flex items-center justify-center rounded-full bg-white text-slate-900 font-bold border-2 border-slate-900 shadow-[0_2px_10px_rgba(15,23,42,0.55)] ${
      focused ? 'text-sm ring-4 ring-white/60' : 'text-xs'
    } cursor-pointer" style="width:${size}px;height:${size}px">${rank}</div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

/**
 * Flies to the site picked in the side panel.
 */
function FlyToSite({ site }: { site: ResourceSite | null }) {
  const map = useMap();
  useEffect(() => {
    if (!site) return;
    map.flyTo([site.latitude, site.longitude], Math.max(map.getZoom(), 10), { duration: 1.2 });
  }, [site, map]);
  return null;
}

/**
 * Popup content shared by site pins and clicked points.
 */
function WindFigures({
  p50,
  p10,
  p90,
  years,
}: {
  p50: number;
  p10: number;
  p90: number;
  years: number[];
}) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="text-2xl font-bold text-slate-900">{p50.toFixed(1)}</span>
      <span className="text-xs text-slate-600">
        m/s mean wind at 100 m, {years[0]}–{years[1]}
        <br />
        80% band {p10.toFixed(1)}–{p90.toFixed(1)} m/s
      </span>
    </div>
  );
}

/**
 * Popup for an arbitrary clicked point, answered by the backend point query.
 */
function PointPopup({
  point,
  summary,
  onClose,
}: {
  point: { lat: number; lng: number };
  summary: ResourceSummary;
  onClose: () => void;
}) {
  const { data, isLoading, isError } = useResourcePoint(point);
  return (
    <Popup position={[point.lat, point.lng]} eventHandlers={{ remove: onClose }}>
      <div className="font-sans w-64 space-y-2">
        {isLoading && <p className="text-xs text-slate-500">Reading the atlas…</p>}
        {isError && <p className="text-xs text-rose-700">Could not read the atlas here.</p>}
        {data && (
          <>
            {data.inside_country && data.wind_p50 != null && (
              <WindFigures
                p50={data.wind_p50}
                p10={data.wind_p10 ?? data.wind_p50}
                p90={data.wind_p90 ?? data.wind_p50}
                years={summary.target_years}
              />
            )}
            {data.inside_country && (
              <div className="flex flex-wrap gap-1 text-[11px]">
                <span
                  className={`px-1.5 py-0.5 rounded border ${
                    data.buildable
                      ? 'border-slate-900 text-slate-900'
                      : 'border-slate-300 text-slate-500'
                  }`}
                >
                  {data.buildable ? 'Buildable hill' : data.in_band ? 'Too steep' : 'Outside 200–800 m'}
                </span>
                {data.elevation_m != null && (
                  <span className="px-1.5 py-0.5 rounded border border-slate-300 text-slate-600">
                    {data.elevation_m.toFixed(0)} m
                  </span>
                )}
                {data.slope_deg != null && (
                  <span className="px-1.5 py-0.5 rounded border border-slate-300 text-slate-600">
                    slope {data.slope_deg.toFixed(0)}°
                  </span>
                )}
                {data.change_pct != null && (
                  <span className="px-1.5 py-0.5 rounded border border-slate-300 text-slate-600">
                    {formatChange(data.change_pct)} vs {summary.reference_years[0]}–
                    {summary.reference_years[1]}
                  </span>
                )}
              </div>
            )}
            <p className="text-xs leading-snug text-slate-700">{data.explanation}</p>
          </>
        )}
      </div>
    </Popup>
  );
}

/**
 * Hill wind atlas overlay: forecast heatmap, numbered candidate sites and click-to-query.
 * Must be rendered inside a react-leaflet MapContainer.
 */
export function WindResourceLayer({ summary, sites, focusedRank }: WindResourceLayerProps) {
  const [clicked, setClicked] = useState<{ lat: number; lng: number } | null>(null);
  const focused = sites.find((s) => s.rank === focusedRank) ?? null;
  const { south, west, north, east } = summary.bounds;

  useMapEvents({
    click: (e) => {
      const target = e.originalEvent.target as HTMLElement;
      if (target && target.closest('.leaflet-marker-icon')) return;
      setClicked({ lat: e.latlng.lat, lng: e.latlng.lng });
    },
  });

  return (
    <>
      <ImageOverlay
        url={HEATMAP_URL}
        bounds={[
          [south, west],
          [north, east],
        ]}
        opacity={0.85}
        zIndex={250}
      />
      <FlyToSite site={focused} />
      {sites.map((site) => (
        <Marker
          key={site.rank}
          position={[site.latitude, site.longitude]}
          icon={siteIcon(site.rank, site.rank === focusedRank)}
          zIndexOffset={site.rank === focusedRank ? 1000 : 500 - site.rank}
        >
          <Tooltip direction="top" offset={[0, -14]} opacity={0.95}>
            <span className="font-sans text-xs font-semibold text-slate-900">
              #{site.rank} {site.name ?? 'Candidate site'} · {site.wind_p50.toFixed(1)} m/s
            </span>
          </Tooltip>
          <Popup>
            <div className="font-sans w-64 space-y-2">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                Candidate site #{site.rank}
              </p>
              <p className="text-sm font-semibold text-slate-900">
                {site.name ?? `${site.latitude.toFixed(3)}, ${site.longitude.toFixed(3)}`}
              </p>
              <WindFigures
                p50={site.wind_p50}
                p10={site.wind_p10}
                p90={site.wind_p90}
                years={summary.target_years}
              />
              <p className="text-xs leading-snug text-slate-700">{site.explanation}</p>
            </div>
          </Popup>
        </Marker>
      ))}
      {clicked && (
        <PointPopup point={clicked} summary={summary} onClose={() => setClicked(null)} />
      )}
    </>
  );
}
