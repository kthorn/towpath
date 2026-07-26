<script lang="ts">
  import type { CatalogQueryPolicy } from '../lib/types';
  import type { TripStore } from '../lib/stores/trip';

  let { store }: { store: TripStore } = $props();
  const layers: Array<{ label: string; kinds: string[]; policy: CatalogQueryPolicy }> = [
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
    store.toggleCatalogKinds(layer.kinds, layer.policy);
  }
</script>

<section class="route-layers" aria-label="Route layers">
  <h2>Route layers</h2>
  <div class="layer-list">
    {#each layers as layer}
      <label>
        <input
          type="checkbox"
          disabled={$store.catalogStatus === 'unavailable'}
          checked={layer.kinds.every((kind) => $store.catalog.enabledKinds.includes(kind))}
          onchange={() => toggleLayer(layer)}
        />
        {layer.label}
      </label>
    {/each}
  </div>
  {#if $store.catalogStatus === 'unavailable'}
    <p class="layer-status" role="status">Catalog unavailable. Route planning remains available.</p>
  {:else if $store.catalog.loading}
    <p class="layer-status" role="status">Loading catalog places…</p>
  {:else if $store.catalogOverCap}
    <p class="layer-status" role="status">Zoom in to see more catalog places.</p>
  {:else if $store.catalog.enabledKinds.length && !$store.catalog.places.length && !$store.catalog.error}
    <p class="layer-status" role="status">No catalog places found in this view.</p>
  {/if}
  {#if $store.catalog.error}<p class="layer-error" role="alert">Catalog layer unavailable: {$store.catalog.error}</p>{/if}
  {#if $store.routePois?.zoom_in_required}<p class="layer-status" role="status">Zoom in to see route points.</p>{/if}
  {#if $store.poiError}<p class="layer-error" role="alert">Route layer unavailable: {$store.poiError}</p>{/if}
</section>
