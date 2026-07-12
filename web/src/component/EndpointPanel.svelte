<script lang="ts">
  import CandidateList from './CandidateList.svelte';
  import PlaceSearch from './PlaceSearch.svelte';
  import type { EndpointSlot, PlaceSearch as Search } from '../lib/google/contracts';
  import type { EndpointState, TripStore } from '../lib/stores/trip';
  let { slot, endpoint, store, search }: { slot: EndpointSlot; endpoint: EndpointState; store: TripStore; search: Search } = $props();
  const title = $derived(slot === 'origin' ? 'Origin' : 'Destination');
  let latitude = $state<string | number>(''); let longitude = $state<string | number>(''); let coordinateError = $state('');
  function useCoordinates() {
    const lat = Number(latitude); const lon = Number(longitude);
    if (String(latitude).trim() === '' || !Number.isFinite(lat) || lat < -90 || lat > 90) {
      coordinateError = 'Latitude must be a number from -90 to 90.'; return;
    }
    if (String(longitude).trim() === '' || !Number.isFinite(lon) || lon < -180 || lon > 180) {
      coordinateError = 'Longitude must be a number from -180 to 180.'; return;
    }
    coordinateError = '';
    store.setEndpointCoordinate(slot, { name: 'Selected coordinates', address: `${lat.toFixed(5)}, ${lon.toFixed(5)}`, coordinate: { lat, lon } });
  }
</script>

<section class="endpoint" aria-label={title}>
  <h2>{title}</h2>
  <PlaceSearch label={`Search ${title.toLowerCase()}`} {search} onselect={(place) => store.setEndpointCoordinate(slot, place)} />
  <div class="coordinate-entry">
    <label>{title} latitude<input type="number" min="-90" max="90" step="any" bind:value={latitude} /></label>
    <label>{title} longitude<input type="number" min="-180" max="180" step="any" bind:value={longitude} /></label>
    <button type="button" onclick={useCoordinates}>Use coordinates</button>
  </div>
  {#if coordinateError}<p role="alert">{coordinateError}</p>{/if}
  {#if endpoint.place}<p class="place"><strong>{endpoint.place.name}</strong><span>{endpoint.place.address}</span></p>{/if}
  <CandidateList {slot} {endpoint} {store} />
  {#if endpoint.transferWarning}<p role="alert" class:prominent={endpoint.requiresManualConfirmation}>{endpoint.transferWarning}</p>{/if}
  {#if endpoint.requiresManualConfirmation && !endpoint.confirmed}<button type="button" onclick={() => store.confirmGeometricFallback(slot)}>Confirm geometric candidate</button>{/if}
</section>
