import { mount } from 'svelte';

import App from './App.svelte';
import { createPoundApi } from './lib/api';
import { config } from './lib/config';
import type { PlaceSearch, TransferRouter } from './lib/google/contracts';
import { googleMapsLoader } from './lib/google/loader';
import { createGoogleAdapters } from './lib/google/sdk';
import { createPlaceController } from './lib/places/controller';
import { createTripStore } from './lib/stores/trip';

const target = document.getElementById('app');
if (!target) throw new Error('Missing #app mount target');

const adapters = googleMapsLoader.load(config.googleMapsApiKey)
  .then((modules) => createGoogleAdapters(modules, { mapId: config.googleMapId }));
const placeSearch: PlaceSearch = {
  attach(container, onSelect, onUnavailable) {
    let detach: (() => void) | undefined; let disposed = false;
    adapters.then((loaded) => { if (!disposed) detach = loaded.placeSearch.attach(container, onSelect, onUnavailable); })
      .catch((error) => { if (!disposed) onUnavailable?.(error); });
    return () => { disposed = true; detach?.(); };
  },
};
const transferRouter: TransferRouter = {
  async matrix(...args) { return (await adapters).transferRouter.matrix(...args); },
  async route(...args) { return (await adapters).transferRouter.route(...args); },
};
const store = createTripStore({
  poundApi: createPoundApi(), transferRouter, transferMode: config.transferMode,
});
mount(App, { target, props: { dependencies: {
  store, placeSearch,
  placeDiscovery: createPlaceController({
    transferRouter,
    textSearch: {
      async search(query, bounds) {
        const loaded = await adapters;
        return loaded.placeTextSearch?.search(query, bounds) ?? { status: 'unavailable', places: [] };
      },
    },
  }),
  loadMapView: async (element: HTMLElement) => (await adapters).createMapView(element),
} } });
