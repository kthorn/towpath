<script lang="ts">
  import CandidateList from './CandidateList.svelte';
  import PlaceSearch from './PlaceSearch.svelte';
  import type { EndpointSlot, PlaceSearch as Search } from '../lib/google/contracts';
  import type { EndpointState, TripStore } from '../lib/stores/trip';
  let { slot, endpoint, store, search, title: suppliedTitle, optional = false }: { slot: EndpointSlot; endpoint: EndpointState; store: TripStore; search: Search; title?: string; optional?: boolean } = $props();
  const title = $derived(suppliedTitle ?? (slot === 'origin' ? 'Origin' : 'Destination'));
</script>

<section class="endpoint" aria-label={title}>
  <h2>{title}{#if optional} <small>(optional)</small>{/if}</h2>
  {#if optional}<p class="endpoint-help">The boat returns to the origin; this is an outbound waypoint.</p>{/if}
  <PlaceSearch label={`Search ${title.toLowerCase()}`} {search} onselect={(place) => store.setEndpointCoordinate(slot, place)} />
  {#if endpoint.place}<p class="place"><strong>{endpoint.place.name}</strong><span>{endpoint.place.address}</span></p>{/if}
  {#if optional && endpoint.place}<button type="button" class="clear-endpoint" onclick={() => store.clearEndpoint(slot)}>Clear visit on the way</button>{/if}
  <CandidateList {slot} {endpoint} {store} />
  {#if endpoint.transferWarning}<p role="alert" class:prominent={endpoint.requiresManualConfirmation}>{endpoint.transferWarning}</p>{/if}
  {#if endpoint.requiresManualConfirmation && !endpoint.confirmed}<button type="button" onclick={() => store.confirmGeometricFallback(slot)}>Confirm geometric candidate</button>{/if}
</section>
