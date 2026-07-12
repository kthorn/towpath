import type { PlaceSearch, MapView } from './google/contracts';
import type { TripStore } from './stores/trip';

export interface AppDependencies {
  store: TripStore;
  placeSearch: PlaceSearch;
  loadMapView(element: HTMLElement): Promise<MapView>;
}
