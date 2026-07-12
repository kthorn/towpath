<script lang="ts">
  import './app.css';
  import BoatConstraints from './component/BoatConstraints.svelte';
  import BoatSettings from './component/BoatSettings.svelte';
  import EndpointPanel from './component/EndpointPanel.svelte';
  import MapCanvas from './component/MapCanvas.svelte';
  import TripSummary from './component/TripSummary.svelte';
  import type { AppDependencies } from './lib/app';
  import type { EndpointSlot } from './lib/google/contracts';
  import { createBoatSettingsStore } from './lib/stores/boat-settings';
  let { dependencies }: { dependencies: AppDependencies } = $props();
  const store = $derived(dependencies.store);
  const boatSettings = createBoatSettingsStore();
  let active = $state<EndpointSlot>('origin');
  let view = $state<'planner' | 'settings'>('planner');
</script>

<svelte:head><title>Pound canal journey planner</title></svelte:head>
<header><div><span class="wordmark">Pound</span><p>Canal journey planner</p><nav aria-label="Primary"><button type="button" class:active={view === 'planner'} aria-current={view === 'planner' ? 'page' : undefined} onclick={() => view = 'planner'}>Plan trip</button><button type="button" class:active={view === 'settings'} aria-current={view === 'settings' ? 'page' : undefined} onclick={() => view = 'settings'}>Settings</button></nav></div></header>
<main class="planner-page" hidden={view !== 'planner'}>
  <div class="map-column">
    <fieldset class="map-target"><legend>Map click sets</legend><label><input type="radio" bind:group={active} value="origin" /> Set origin from map</label><label><input type="radio" bind:group={active} value="destination" /> Set destination from map</label></fieldset>
    <MapCanvas load={dependencies.loadMapView} onclick={(coordinate) => dependencies.store.setEndpointCoordinate(active, coordinate)} onready={(view) => dependencies.store.setMapView(view)} />
  </div>
  <div class="planner-column">
    <EndpointPanel slot="origin" endpoint={$store.origin} {store} search={dependencies.placeSearch} />
    <EndpointPanel slot="destination" endpoint={$store.destination} {store} search={dependencies.placeSearch} />
    <BoatConstraints {store} settings={boatSettings} />
    <TripSummary state={$store} />
  </div>
</main>
<main class="settings-page" hidden={view !== 'settings'}><BoatSettings store={boatSettings} /></main>
<footer>
  Canal routes are planning guidance; verify navigation restrictions and safe access locally.
  Map data © Google and
  <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">© OpenStreetMap contributors</a>.
</footer>
