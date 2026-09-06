import type { ClimateStore } from './stores/climate';
import type { PlaceSearch, MapView } from './google/contracts';
import type { PlaceController } from './places/controller';
import type { TripStore } from './stores/trip';

export interface AppDependencies {
  store: TripStore;
  placeDiscovery?: PlaceController;

  climateStore?: ClimateStore;
  placeSearch: PlaceSearch;
  loadMapView(element: HTMLElement): Promise<MapView>;
}
