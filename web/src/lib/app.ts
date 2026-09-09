import type { ClimateGridStore } from './stores/climate-grid';
import type { ClimateStore } from './stores/climate';
import type { PlaceSearch, MapView } from './google/contracts';
import type { PlaceController } from './places/controller';
import type { TripStore } from './stores/trip';

export interface AppDependencies {
  store: TripStore;
  placeDiscovery?: PlaceController;

  climateStore?: ClimateStore;
  climateGridStore?: ClimateGridStore;
  placeSearch: PlaceSearch;
  loadMapView(element: HTMLElement): Promise<MapView>;
}
