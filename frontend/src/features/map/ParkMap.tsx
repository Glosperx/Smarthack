import { useEffect, useRef, type ReactNode } from 'react';
import { MapContainer, TileLayer, Marker, Tooltip, useMap, useMapEvents } from 'react-leaflet';
import L from 'leaflet';
import MarkerClusterGroup from 'react-leaflet-cluster';
import { dotIcon, selectedIcon, clusterIcon } from './mapIcons';
import type { Park } from '../../api/hooks';

interface ParkMapProps {
  parks: Park[];
  selectedId: number | null;
  onSelectPark: (id: number) => void;
  onBackgroundClick: () => void;
  /** Extra map layers (for example the wind resource atlas), rendered inside the map. */
  children?: ReactNode;
}

/**
 * Child helper component to fit bounds automatically once data arrives.
 */
function FitToParks({ parks }: { parks: Park[] }) {
  const map = useMap();
  const fittedRef = useRef(false);

  useEffect(() => {
    if (parks.length === 0 || fittedRef.current) return;

    if (parks.length === 1) {
      map.setView([parks[0].latitude, parks[0].longitude], 12);
    } else {
      const bounds = L.latLngBounds(parks.map((p) => [p.latitude, p.longitude]));
      map.fitBounds(bounds, { padding: [48, 48] });
    }
    fittedRef.current = true;
  }, [parks, map]);

  return null;
}

/**
 * Child helper component to fly to a newly selected park.
 */
function FlyToSelected({ selectedPark }: { selectedPark: Park | null }) {
  const map = useMap();

  useEffect(() => {
    if (!selectedPark) return;
    map.flyTo(
      [selectedPark.latitude, selectedPark.longitude],
      Math.max(map.getZoom(), 11),
      { duration: 1.2 }
    );
  }, [selectedPark, map]);

  return null;
}

/**
 * Child helper component handling background map clicks to close open drawers.
 */
function MapBackgroundEvents({ onBackgroundClick }: { onBackgroundClick: () => void }) {
  useMapEvents({
    click: (e) => {
      // Only fire if the map canvas was clicked directly, not a marker
      const target = e.originalEvent.target as HTMLElement;
      if (target && target.classList.contains('leaflet-container')) {
        onBackgroundClick();
      }
    },
  });

  return null;
}

/**
 * Fullscreen interactive Leaflet map featuring park clusters and pin markers.
 */
export function ParkMap({
  parks,
  selectedId,
  onSelectPark,
  onBackgroundClick,
  children,
}: ParkMapProps) {
  const selectedPark = parks.find((p) => p.id === selectedId) || null;

  // Default initial center (Romania / central Europe) if parks are empty
  const defaultCenter: [number, number] = [45.9432, 24.9668];

  return (
    <div className="relative isolate w-full h-full">
      <MapContainer
        center={defaultCenter}
        zoom={6}
        className="w-full h-full cursor-grab active:cursor-grabbing"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        <FitToParks parks={parks} />
        <FlyToSelected selectedPark={selectedPark} />
        <MapBackgroundEvents onBackgroundClick={onBackgroundClick} />

        <MarkerClusterGroup
          chunkedLoading
          showCoverageOnHover={false}
          maxClusterRadius={50}
          iconCreateFunction={clusterIcon}
        >
          {parks.map((park) => (
            <Marker
              key={park.id}
              position={[park.latitude, park.longitude]}
              icon={park.id === selectedId ? selectedIcon : dotIcon}
              eventHandlers={{
                click: () => onSelectPark(park.id),
              }}
            >
              <Tooltip direction="top" offset={[0, -15]} opacity={0.95}>
                <span className="font-sans font-semibold text-xs text-slate-900">
                  {park.name}
                </span>
              </Tooltip>
            </Marker>
          ))}
        </MarkerClusterGroup>
        {children}
      </MapContainer>
    </div>
  );
}
