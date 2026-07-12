<script lang="ts">
  import CandidateList from './CandidateList.svelte';
  import PlaceSearch from './PlaceSearch.svelte';
  import type { EndpointSlot, PlaceSearch as Search } from '../lib/google/contracts';
  import type { EndpointState, TripStore } from '../lib/stores/trip';
  let { slot, endpoint, store, search }: { slot: EndpointSlot; endpoint: EndpointState; store: TripStore; search: Search } = $props();
  const title = $derived(slot === 'origin' ? 'Origin' : 'Destination');
</script>

<section class="endpoint" aria-label={title}>
  <h2>{title}</h2>
  <PlaceSearch label={`Search ${title.toLowerCase()}`} {search} onselect={(place) => store.setEndpointCoordinate(slot, place)} />
  {#if endpoint.place}<p class="place"><strong>{endpoint.place.name}</strong><span>{endpoint.place.address}</span></p>{/if}
  <CandidateList {slot} {endpoint} {store} />
  {#if endpoint.transferWarning}<p role="alert" class:prominent={endpoint.requiresManualConfirmation}>{endpoint.transferWarning}</p>{/if}
  {#if endpoint.requiresManualConfirmation && !endpoint.confirmed}<button type="button" onclick={() => store.confirmGeometricFallback(slot)}>Confirm geometric candidate</button>{/if}
</section>
