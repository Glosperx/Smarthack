import L from 'leaflet';

/**
 * Standard high-visibility wind park map marker (24px circle with vibrant cyan core and outer glow).
 * Differentiated in color from the green/amber/red status dots used in health charts.
 */
export const dotIcon = L.divIcon({
  className: '!bg-transparent !border-none',
  html: `<div class="relative flex items-center justify-center w-6 h-6 rounded-full bg-gradient-to-tr from-cyan-600 to-sky-400 border-[2.5px] border-white shadow-[0_3px_12px_rgba(6,182,212,0.65)] hover:scale-125 hover:shadow-[0_0_16px_rgba(6,182,212,0.95)] transition-all duration-200 cursor-pointer">
    <div class="w-1.5 h-1.5 rounded-full bg-white shadow-xs"></div>
  </div>`,
  iconSize: [24, 24],
  iconAnchor: [12, 12],
});

/**
 * Selected wind park map marker with active animated pulse ring and highlight halo (34px).
 */
export const selectedIcon = L.divIcon({
  className: '!bg-transparent !border-none',
  html: `<div class="relative flex items-center justify-center w-8 h-8">
    <div class="absolute inset-0 rounded-full bg-cyan-400/40 animate-ping"></div>
    <div class="relative w-8 h-8 rounded-full bg-gradient-to-tr from-cyan-500 to-blue-600 border-[3px] border-white ring-4 ring-cyan-400/60 shadow-[0_0_20px_rgba(6,182,212,0.85)] flex items-center justify-center cursor-pointer">
      <div class="w-2.5 h-2.5 rounded-full bg-white shadow-xs"></div>
    </div>
  </div>`,
  iconSize: [32, 32],
  iconAnchor: [16, 16],
});

/**
 * Marker cluster badge icon displaying child count with matching cyan accents.
 */
export function clusterIcon(cluster: { getChildCount: () => number }) {
  const count = cluster.getChildCount();
  return L.divIcon({
    className: '!bg-transparent !border-none',
    html: `<div class="flex items-center justify-center w-11 h-11 rounded-full bg-slate-900/95 text-cyan-300 border-2 border-cyan-400 font-bold text-sm shadow-[0_4px_16px_rgba(6,182,212,0.45)] hover:scale-110 transition-transform cursor-pointer">${count}</div>`,
    iconSize: [44, 44],
    iconAnchor: [22, 22],
  });
}
