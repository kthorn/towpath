import { CLIMATE_COLOR_LIMITS } from '../climate';
import { resolveClimateScale, type ClimateColorRange } from '../climate-scale';
import type { ClimateGridSurface } from '../climate-grid';

type Coordinate = { lat: number; lon: number };
type Cell = { coordinate: Coordinate; value: number | null };
type Point = { x: number; y: number };
type Mask = { type: 'Polygon'; coordinates: number[][][] } | { type: 'MultiPolygon'; coordinates: number[][][][] };
type View = 'high_median' | 'high_p90' | 'low_median' | 'low_p10' | 'high_exceedance';
const LAT_KM = 111.195;
const BUCKET_DEGREES = 0.25;
const CUTOFF_KM = 15;

/** Normalized compact inverse-distance interpolation, never a sum of temperatures.
 * A missing nearest cell owns a transparent region, even beside valid samples.
 */
export function createClimateInterpolator(cells: readonly Cell[]): (point: Coordinate) => number | null {
  const buckets = new Map<string, Cell[]>();
  let south = Infinity, north = -Infinity, west = Infinity, east = -Infinity;
  for (const cell of cells) {
    south = Math.min(south, cell.coordinate.lat);
    north = Math.max(north, cell.coordinate.lat);
    west = Math.min(west, cell.coordinate.lon);
    east = Math.max(east, cell.coordinate.lon);
    const key = `${Math.floor(cell.coordinate.lon / BUCKET_DEGREES)}:${Math.floor(cell.coordinate.lat / BUCKET_DEGREES)}`;
    const bucket = buckets.get(key) ?? [];
    bucket.push(cell);
    buckets.set(key, bucket);
  }
  return ({ lat, lon }) => {
    const lonKm = LAT_KM * Math.cos(lat * Math.PI / 180);
    if (lat < south - CUTOFF_KM / LAT_KM || lat > north + CUTOFF_KM / LAT_KM
      || lon < west - CUTOFF_KM / lonKm || lon > east + CUTOFF_KM / lonKm) return null;
    const bx = Math.floor(lon / BUCKET_DEGREES);
    const by = Math.floor(lat / BUCKET_DEGREES);
    const xRadius = Math.ceil(CUTOFF_KM / Math.max(lonKm * BUCKET_DEGREES, 0.1));
    let nearest = Infinity;
    let nearestMissing = false;
    let total = 0;
    let weightSum = 0;
    for (let x = bx - xRadius; x <= bx + xRadius; x++) {
      for (let y = by - 1; y <= by + 1; y++) {
        for (const cell of buckets.get(`${x}:${y}`) ?? []) {
          const dx = (cell.coordinate.lon - lon) * lonKm;
          const dy = (cell.coordinate.lat - lat) * LAT_KM;
          const distance = Math.hypot(dx, dy);
          if (distance >= CUTOFF_KM) continue;
          const missing = cell.value === null || !Number.isFinite(cell.value);
          if (distance < 0.000001) return missing ? null : cell.value;
          if (distance < nearest || (distance === nearest && missing)) {
            nearest = distance;
            nearestMissing = missing;
          }
          if (missing) continue;
          const weight = ((1 - distance / CUTOFF_KM) / distance) ** 2;
          total += cell.value! * weight;
          weightSum += weight;
        }
      }
    }
    return nearestMissing || !weightSum ? null : total / weightSum;
  };
}

/** Fixed metric domains match the named-location legend; optional ranges allow zooming the colour scale. */
export function climateRasterColor(view: View, value: number, range?: ClimateColorRange): [number, number, number] {
  const limits = range ?? (view === 'high_exceedance' ? { min: 0, max: 1 }
    : CLIMATE_COLOR_LIMITS[view.startsWith('low') ? 'low' : 'high']);
  const position = Math.min(1, Math.max(0, (value - limits.min) / (limits.max - limits.min)));
  // Same HSL scale as climateColor, converted directly for ImageData pixels.
  const hue = (220 - 220 * position) / 60;
  const chroma = (1 - Math.abs(2 * 0.75 - 1)) * 0.72;
  const x = chroma * (1 - Math.abs(hue % 2 - 1));
  const offset = 0.75 - chroma / 2;
  const rgb = hue < 1 ? [chroma, x, 0] : hue < 2 ? [x, chroma, 0]
    : hue < 3 ? [0, chroma, x] : [0, x, chroma];
  return rgb.map((channel) => Math.round((channel + offset) * 255)) as [number, number, number];
}

/** Limit interpolation work and memory independently of screen size and DPR. */
export function rasterDimensions(width: number, height: number, dpr = 1): { width: number; height: number } {
  const scale = Math.min(Math.max(1, Math.min(dpr, 2)), 384 / Math.max(width, height, 1));
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

type ClipContext = Pick<CanvasRenderingContext2D, 'beginPath' | 'moveTo' | 'lineTo' | 'closePath' | 'clip'>;
function* landMaskSteps(context: ClipContext, mask: Mask, project: (lon: number, lat: number) => Point | null): Generator<void> {
  context.beginPath();
  const polygons = mask.type === 'Polygon' ? [mask.coordinates] : mask.coordinates;
  for (const polygon of polygons) {
    for (const ring of polygon) {
      const points: Point[] = [];
      let valid = true;
      for (const [lon, lat] of ring) {
        const point = project(lon, lat);
        if (point) points.push(point); else valid = false;
        yield;
      }
      if (!valid || !points.length) continue;
      for (let index = 0; index < points.length; index++) {
        const point = points[index];
        if (index === 0) context.moveTo(point.x, point.y);
        else context.lineTo(point.x, point.y);
        yield;
      }
      context.closePath();
    }
  }
  context.clip('evenodd');
}

export function traceLandMask(context: ClipContext, mask: Mask, project: (lon: number, lat: number) => Point | null): void {
  const steps = landMaskSteps(context, mask, project);
  while (!steps.next().done) { /* Synchronous helper for small masks and tests. */ }
}

interface LatLng { lat(): number; lng(): number }
interface Projection {
  fromLatLngToDivPixel(coordinate: LatLng | { lat: number; lng: number }): Point | null;
  fromDivPixelToLatLng(point: Point): LatLng | null;
}
export interface ClimateRasterMap {
  getDiv(): HTMLElement;
  getCenter(): LatLng | undefined;
}
interface Overlay {
  onAdd(): void;
  onRemove(): void;
  draw(): void;
  setMap(map: ClimateRasterMap | null): void;
  getPanes(): { overlayLayer: HTMLElement } | null;
  getProjection(): Projection;
}
export interface ClimateRasterMapsNamespace { OverlayView: new () => Overlay }
export interface ClimateRaster {
  setSurface(surface: ClimateGridSurface | null, opacity: number, range?: ClimateColorRange | null): void;
  destroy(): void;
}

/** OverlayView owns move/zoom redraws. No map click handlers or interactive pane. */
export function createClimateRaster(map: ClimateRasterMap, maps: ClimateRasterMapsNamespace): ClimateRaster {
  const documentRef = map.getDiv().ownerDocument;
  const windowRef = documentRef.defaultView!;
  const canvas = documentRef.createElement('canvas');
  canvas.className = 'pound-climate-raster';
  canvas.setAttribute('aria-hidden', 'true');
  Object.assign(canvas.style, { position: 'absolute', pointerEvents: 'none' });
  let surface: ClimateGridSurface | null = null;
  let colorRange: ClimateColorRange | undefined;
  let interpolate: ReturnType<typeof createClimateInterpolator> | null = null;
  let destroyed = false;
  let attached = false;
  let pending: number | undefined;
  let settled: number | undefined;
  let bounds: { topLeft: LatLng; bottomRight: LatLng } | null = null;

  // Google moves the overlay pane during gestures; project only the two anchors
  // to scale the already painted image. Never resample temperatures during a draw.
  const position = () => {
    if (!bounds || !attached) return;
    const projection = overlay.getProjection();
    const topLeft = projection?.fromLatLngToDivPixel(bounds.topLeft);
    const bottomRight = projection?.fromLatLngToDivPixel(bounds.bottomRight);
    if (!topLeft || !bottomRight) return;
    Object.assign(canvas.style, { left: `${topLeft.x}px`, top: `${topLeft.y}px`,
      width: `${bottomRight.x - topLeft.x}px`, height: `${bottomRight.y - topLeft.y}px` });
  };

  const paint = () => {
    pending = undefined;
    if (destroyed || !surface || !interpolate || !attached) return;
    const projection = overlay.getProjection();
    const center = map.getCenter();
    if (!projection || !center) return;
    const centerPixel = projection.fromLatLngToDivPixel(center);
    if (!centerPixel) return;
    const element = map.getDiv();
    const width = element.clientWidth;
    const height = element.clientHeight;
    if (!width || !height) return;
    const left = centerPixel.x - width / 2;
    const top = centerPixel.y - height / 2;
    const size = rasterDimensions(width, height, windowRef.devicePixelRatio);
    // Keep the geographic coastline crisp while bounding costly interpolation separately.
    const backingScale = Math.min(Math.max(1, Math.min(windowRef.devicePixelRatio || 1, 2)), 1536 / Math.max(width, height));
    const context = canvas.getContext('2d');
    if (!context) return;
    const image = context.createImageData(size.width, size.height);
    const paintSurface = surface;
    const sample = interpolate;
    const paintRange = colorRange;
    let y = 0;
    const rows = () => {
      pending = undefined;
      if (destroyed || !attached || surface !== paintSurface) return;
      const started = windowRef.performance.now();
      while (y < size.height) {
        for (let x = 0; x < size.width; x++) {
          const coordinate = projection.fromDivPixelToLatLng({
            x: left + (x + 0.5) * width / size.width,
            y: top + (y + 0.5) * height / size.height,
          });
          if (!coordinate) continue;
          const value = sample({ lat: coordinate.lat(), lon: coordinate.lng() });
          if (value === null) continue;
          const offset = (y * size.width + x) * 4;
          const color = climateRasterColor(paintSurface.view, value, paintRange);
          image.data.set([...color, 255], offset);
        }
        y++;
        if (y < size.height && windowRef.performance.now() - started >= 6) {
          pending = windowRef.requestAnimationFrame(rows);
          return;
        }
      }
      // Build the clipped replacement offscreen, retaining the previous image
      // while coastline projection yields across frames just like interpolation.
      const source = documentRef.createElement('canvas');
      source.width = size.width;
      source.height = size.height;
      source.getContext('2d')?.putImageData(image, 0, 0);
      const replacement = documentRef.createElement('canvas');
      replacement.width = Math.max(1, Math.round(width * backingScale));
      replacement.height = Math.max(1, Math.round(height * backingScale));
      const clipped = replacement.getContext('2d');
      if (!clipped) return;
      const steps = landMaskSteps(clipped, paintSurface.mask, (lon, lat) => {
        const pixel = projection.fromLatLngToDivPixel({ lat, lng: lon });
        return pixel ? { x: (pixel.x - left) * replacement.width / width, y: (pixel.y - top) * replacement.height / height } : null;
      });
      const coastline = () => {
        pending = undefined;
        if (destroyed || !attached || surface !== paintSurface) return;
        const started = windowRef.performance.now();
        while (!steps.next().done) {
          if (windowRef.performance.now() - started >= 6) {
            pending = windowRef.requestAnimationFrame(coastline);
            return;
          }
        }
        clipped.drawImage(source, 0, 0, replacement.width, replacement.height);
        canvas.width = replacement.width;
        canvas.height = replacement.height;
        Object.assign(canvas.style, { left: `${left}px`, top: `${top}px`, width: `${width}px`, height: `${height}px` });
        context.drawImage(replacement, 0, 0);
        const topLeft = projection.fromDivPixelToLatLng({ x: left, y: top });
        const bottomRight = projection.fromDivPixelToLatLng({ x: left + width, y: top + height });
        bounds = topLeft && bottomRight ? { topLeft, bottomRight } : null;
      };
      // Start a separate frame so the last temperature rows and first coastline
      // segment do not consume two time budgets in a single callback.
      pending = windowRef.requestAnimationFrame(coastline);
    };
    rows();
  };
  const schedule = () => {
    if (destroyed || pending !== undefined) return;
    pending = windowRef.requestAnimationFrame(paint);
  };
  const cancel = () => {
    if (pending !== undefined) windowRef.cancelAnimationFrame(pending);
    pending = undefined;
    if (settled !== undefined) windowRef.clearTimeout(settled);
    settled = undefined;
  };
  const overlay = new maps.OverlayView();
  overlay.onAdd = () => { overlay.getPanes()?.overlayLayer.append(canvas); schedule(); };
  overlay.draw = () => {
    if (destroyed || !surface || !attached) return;
    position();
    cancel();
    settled = windowRef.setTimeout(() => { settled = undefined; schedule(); }, 150);
  };
  overlay.onRemove = () => { cancel(); bounds = null; canvas.remove(); };
  return {
    setSurface(next, opacity, manualRange) {
      if (destroyed) return;
      const changed = surface !== next;
      const nextRange = next ? resolveClimateScale(next.view, next.cells, manualRange) : undefined;
      const rangeChanged = colorRange?.min !== nextRange?.min || colorRange?.max !== nextRange?.max;
      colorRange = nextRange;
      surface = next;
      if (changed || rangeChanged) {
        cancel();
        bounds = null;
        // Do not display the previous metric/week while the new surface is painted.
        canvas.width = 0;
        if (changed) interpolate = next ? createClimateInterpolator(next.cells) : null;
      }
      canvas.style.opacity = String(Number.isFinite(opacity) ? Math.min(1, Math.max(0, opacity)) : 0);
      if (!next) {
        cancel();
        if (attached) overlay.setMap(null);
        attached = false;
        canvas.remove();
      } else {
        if (!attached) { attached = true; overlay.setMap(map); }
        if (changed || rangeChanged) { cancel(); schedule(); }
      }
    },
    destroy() {
      destroyed = true;
      cancel();
      if (attached) overlay.setMap(null);
      attached = false;
      surface = null;
      interpolate = null;
      canvas.remove();
    },
  };
}
