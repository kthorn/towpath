<script lang="ts">
  import './app.css';
  import BoatConstraints from './component/BoatConstraints.svelte';
  import EndpointPanel from './component/EndpointPanel.svelte';
  import MapCanvas from './component/MapCanvas.svelte';
  import TripSummary from './component/TripSummary.svelte';
  import type { AppDependencies } from './lib/app';
  import type { EndpointSlot } from './lib/google/contracts';
  let { dependencies }: { dependencies: AppDependencies } = $props();
  const store = $derived(dependencies.store);
  let active = $state<EndpointSlot>('origin');
</script>

<svelte:head><title>Pound canal journey planner</title></svelte:head>
<header><div><span class="wordmark">Pound</span><p>Canal journey planner</p></div></header>
<main>
  <div class="map-column">
    <fieldset class="map-target"><legend>Map click sets</legend><label><input type="radio" bind:group={active} value="origin" /> Set origin from map</label><label><input type="radio" bind:group={active} value="destination" /> Set destination from map</label></fieldset>
    <MapCanvas load={dependencies.loadMapView} onclick={(coordinate) => dependencies.store.setEndpointCoordinate(active, coordinate)} onready={(view) => dependencies.store.setMapView(view)} />
  </div>
  <div class="planner-column">
    <EndpointPanel slot="origin" endpoint={$store.origin} {store} search={dependencies.placeSearch} />
    <EndpointPanel slot="destination" endpoint={$store.destination} {store} search={dependencies.placeSearch} />
    <BoatConstraints {store} />
    <TripSummary state={$store} />
  </div>
</main>
<footer>Canal routes are planning guidance; verify navigation restrictions and safe access locally. Map data © Google.</footer>
