<script lang="ts">
  import type { PlacesQueryPolicy } from '../lib/types';
  import type { TripStore } from '../lib/stores/trip';

  let { store }: { store: TripStore } = $props();
  const layers: Array<{ label: string; kinds: string[]; policy: PlacesQueryPolicy }> = [
    {
      label: 'Attractions',
      kinds: ['museum', 'gallery', 'historic_site', 'garden', 'wildlife_attraction', 'landmark'],
      policy: { basis: 'waterway', radius_m: 2_000 },
    },
    { label: 'Hospitality', kinds: ['pub', 'cafe', 'restaurant'], policy: { basis: 'route', radius_m: 2_000 } },
    {
      label: 'Shops and provisions',
      kinds: ['supermarket', 'convenience', 'bakery', 'greengrocer', 'butcher', 'deli', 'general'],
      policy: { basis: 'route', radius_m: 2_000 },
    },
    {
      label: 'Canal utilities',
      kinds: ['marina', 'mooring', 'fuel', 'water_point', 'sanitary_disposal'],
      policy: { basis: 'waterway', radius_m: 500 },
    },
  ];

  function toggleLayer(layer: typeof layers[number]) {
    store.togglePlaceKinds(layer.kinds, layer.policy);
  }
</script>

<section class="route-layers" aria-label="Route layers">
  <h2>Route layers</h2>
  <div class="layer-list">
    {#each layers as layer}
      <label>
        <input
          type="checkbox"
          disabled={$store.placesStatus === 'unavailable'}
          checked={layer.kinds.every((kind) => $store.places.enabledKinds.includes(kind))}
          onchange={() => toggleLayer(layer)}
        />
        {layer.label}
      </label>
    {/each}
  </div>
  {#if $store.placesStatus === 'unavailable'}
    <p class="layer-status" role="status">Places unavailable. Route planning remains available.</p>
  {:else if $store.places.loading}
    <p class="layer-status" role="status">Loading places…</p>
  {:else if $store.placesResultLimitExceeded}
    <p class="layer-status" role="status">Zoom in to see more places.</p>
  {:else if $store.places.enabledKinds.length && !$store.places.places.length && !$store.places.error}
    <p class="layer-status" role="status">No places found in this view.</p>
  {/if}
  {#if $store.places.error}<p class="layer-error" role="alert">Places layer unavailable: {$store.places.error}</p>{/if}
  {#if $store.routePois?.zoom_in_required}<p class="layer-status" role="status">Zoom in to see route points.</p>{/if}
  {#if $store.poiError}<p class="layer-error" role="alert">Route layer unavailable: {$store.poiError}</p>{/if}
</section>
