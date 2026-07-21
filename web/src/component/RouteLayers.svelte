<script lang="ts">
  import type { TripStore } from '../lib/stores/trip';

  let { store }: { store: TripStore } = $props();
  const layers = [
    { label: 'Pubs', kinds: ['pub'] },
    { label: 'Water points', kinds: ['water_point'] },
    { label: 'Marinas and moorings', kinds: ['marina', 'mooring'] },
    { label: 'Fuel and sanitary', kinds: ['fuel', 'sanitary_disposal'] },
    {
      label: 'Shops and provisions',
      kinds: ['bakery', 'butcher', 'cafe', 'convenience', 'deli', 'greengrocer', 'restaurant', 'supermarket'],
    },
    { label: 'Transport', kinds: ['bus_stop', 'rail_station', 'taxi_rank'] },
    {
      label: 'Pedestrian access',
      kinds: ['entrance', 'path_connection', 'pedestrian_bridge', 'steps', 'stile', 'gate', 'cycle_barrier', 'kissing_gate'],
    },
  ];

  function toggleLayer(kinds: string[]) {
    const enabled = new Set($store.enabledPoiKinds);
    const allEnabled = kinds.every((kind) => enabled.has(kind));
    for (const kind of kinds) {
      if (allEnabled || !enabled.has(kind)) store.togglePoiKind(kind);
    }
  }
</script>

<section class="route-layers" aria-label="Route layers">
  <h2>Route layers</h2>
  <div class="layer-list">
    {#each layers as layer}
      <label>
        <input
          type="checkbox"
          checked={layer.kinds.every((kind) => $store.enabledPoiKinds.includes(kind))}
          onchange={() => toggleLayer(layer.kinds)}
        />
        {layer.label}
      </label>
    {/each}
  </div>
  {#if $store.routePois?.zoom_in_required}<p class="layer-status" role="status">Zoom in to see route points.</p>{/if}
  {#if $store.poiError}<p class="layer-error" role="alert">Route layer unavailable: {$store.poiError}</p>{/if}
</section>
