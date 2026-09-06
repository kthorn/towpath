<script lang="ts">
  import { onMount, onDestroy, tick } from 'svelte';
  import './app.css';
  import AttractionPanel from './component/AttractionPanel.svelte';

  import ClimateControls from './component/ClimateControls.svelte';
  import ClimateGridControls from './component/ClimateGridControls.svelte';
  import ClimateGridDetail from './component/ClimateGridDetail.svelte';
  import { createClimateGridStore } from './lib/stores/climate-grid';
  import ClimateDetail from './component/ClimateDetail.svelte';
  import { climateColor, CLIMATE_COLOR_LIMITS } from './lib/climate';
  import { createClimateStore } from './lib/stores/climate';
  import BoatConstraints from './component/BoatConstraints.svelte';
  import BoatSettings from './component/BoatSettings.svelte';
  import EndpointPanel from './component/EndpointPanel.svelte';
  import MapCanvas from './component/MapCanvas.svelte';
  import RouteLayers from './component/RouteLayers.svelte';
  import TripSummary from './component/TripSummary.svelte';
  import type { AppDependencies } from './lib/app';
  import type { EndpointSlot, MapView } from './lib/google/contracts';
  import { createNavigation, type AppRoute } from './lib/navigation';
  import { parseSchedule } from './lib/schedule';
  import { createBoatSettingsStore, type SettingsSaveResult } from './lib/stores/boat-settings';

  let { dependencies }: { dependencies: AppDependencies } = $props();
  const store = $derived(dependencies.store);
  const defaultClimateStore = createClimateStore();
  const climateStore = $derived(dependencies.climateStore ?? defaultClimateStore);
  const defaultClimateGridStore = createClimateGridStore();
  const climateGridStore = $derived(dependencies.climateGridStore ?? defaultClimateGridStore);
  let mapView = $state<MapView | undefined>();
  $effect(() => {
    const grid = $climateGridStore;
    mapView?.climateGrid(grid.enabled ? grid.surface : null, grid.opacity);
  });
  let paintedClimateView: MapView | undefined;
  let paintedClimateSignature = "";
  $effect(() => {
    const state = $climateStore;
    const markers = state.enabled ? state.summaries.map((location) => {
      const d = location.distribution;
      const available = d.available && d.median !== null && d.p10 !== null && d.p90 !== null;
      const limits = CLIMATE_COLOR_LIMITS[state.metric];
      const clipped = available && (d.median! < limits.min || d.median! > limits.max);
      return {
        id: location.id, coordinate: location.coordinate,
        value: available ? `${d.median!.toFixed(1)}°${clipped ? '*' : ''}` : '—',
        color: available ? climateColor(state.metric, d.median!) : '#e5e7eb',
        label: `${location.name}: daily ${state.metric}, ${state.weekLabel}, ` +
          `${d.start_year}–${d.end_year}. ` + (available
            ? `Median ${d.median!.toFixed(1)}°C; middle 80% ${d.p10!.toFixed(1)}–${d.p90!.toFixed(1)}°C. ${d.n_days} days across ${d.n_years} summers.${clipped ? ' Colour is at the legend limit.' : ''}`
            : 'Historical range unavailable.'),
      };
    }) : [];
    const signature = JSON.stringify(markers);
    if (mapView !== paintedClimateView || signature !== paintedClimateSignature) {
      mapView?.climate(markers, (id) => { void climateStore.selectLocation(id); });
      paintedClimateView = mapView;
      paintedClimateSignature = signature;
    }
  });
  function setMapView(view: MapView | undefined) {
    mapView = view;
    dependencies.store.setMapView(view);
  }
  const boatSettings = createBoatSettingsStore();
  let active = $state<EndpointSlot | 'temperature'>('origin');
  let temperatureSelectionMessage = $state('');
  $effect(() => {
    if (!$climateGridStore.enabled && active === 'temperature') active = 'origin';
  });
  function handleMapClick(coordinate: { lat: number; lon: number }) {
    if (active !== 'temperature') {
      store.setEndpointCoordinate(active, coordinate);
      return;
    }
    let nearest: string | null = null;
    let distanceKm = 15;
    for (const cell of $climateGridStore.surface?.cells ?? []) {
      const dy = (cell.coordinate.lat - coordinate.lat) * 111.195;
      const dx = (cell.coordinate.lon - coordinate.lon) * 111.195 * Math.cos(coordinate.lat * Math.PI / 180);
      const distance = Math.hypot(dx, dy);
      if (distance < distanceKm) { nearest = cell.id; distanceKm = distance; }
    }
    temperatureSelectionMessage = nearest ? 'Showing the nearest sampled land location.' : 'No temperature sample within 15 km of this point.';
    if (nearest) void climateGridStore.selectCell(nearest);
  }
  let plannerSession = $state({ days: 7 as string | number, hours: 6 as string | number });
  let searchKey = $state(0);
  let hasAttractionPreview = false;
  function clearAttractionPreview() {
    if (!hasAttractionPreview) return;
    hasAttractionPreview = false;
    for (const slot of ['origin', 'destination'] as const) {
      mapView?.clearLand(slot);
      const route = $store[slot].landRoute;
      if (route) mapView?.land(slot, route);
    }
  }
  onDestroy(() => dependencies.placeDiscovery?.destroy());
  let routeError = $state('');
  let submissionGeneration = 0;
  const networkRequest = $derived.by(() => {
    try {
      return { ...parseSchedule(plannerSession.days, plannerSession.hours), ...$boatSettings };
    } catch {
      return null;
    }
  });
  $effect(() => {
    if (networkRequest) store.setNetworkRequest(networkRequest);
  });

  const navigation = createNavigation();
  let saveFeedback = $state<SettingsSaveResult | null>(null);
  let plannerHeading: HTMLHeadingElement | undefined = $state();
  let settingsHeading: HTMLHeadingElement | undefined = $state();

  onMount(() => {
    let firstPublication = true;
    const unsubscribe = navigation.subscribe((route: AppRoute) => {
      if (firstPublication) {
        firstPublication = false;
        return;
      }
      if (route === 'settings') saveFeedback = null;
      void tick().then(() => (route === 'planner' ? plannerHeading : settingsHeading)?.focus());
    });
    return () => { unsubscribe(); navigation.destroy(); };
  });

  function finishSettingsSave(result: SettingsSaveResult) {
    saveFeedback = result;
    navigation.navigate('planner');
  }

  async function planTrip() {
    const generation = ++submissionGeneration;
    routeError = '';
    try {
      await dependencies.store.planCanalRoute({
        ...parseSchedule(plannerSession.days, plannerSession.hours),
        ...$boatSettings,
      });
    } catch (cause) {
      if (generation === submissionGeneration)
        routeError = cause instanceof Error ? cause.message : String(cause);
    }
  }

  function resetTrip() {
    submissionGeneration += 1;
    routeError = '';
    dependencies.store.reset();
    dependencies.placeDiscovery?.cancel();
    plannerSession = { days: 7, hours: 6 };
    searchKey += 1;
  }

  function handleNavClick(event: MouseEvent, route: AppRoute, ordinaryAction: () => void = () => navigation.navigate(route)) {
    if (!(event.currentTarget instanceof HTMLAnchorElement)) return;
    if (event.button !== 0) return;
    if (event.metaKey || event.altKey || event.ctrlKey || event.shiftKey) return;
    if (event.defaultPrevented) return;
    if (event.currentTarget.hasAttribute('download')) return;
    const target = event.currentTarget.target;
    if (target && target !== '_self') return;
    event.preventDefault();
    ordinaryAction();
  }
</script>

<svelte:head><title>{$navigation === 'planner' ? 'Pound canal journey planner' : 'Boat settings — Pound'}</title></svelte:head>
<header><div><span class="wordmark">Pound</span><p>Canal journey planner</p><nav aria-label="Primary"><a href="/" aria-current={$navigation === 'planner' ? 'page' : undefined} onclick={(event) => handleNavClick(event, 'planner')}>Plan trip</a><a href="/settings" aria-current={$navigation === 'settings' ? 'page' : undefined} onclick={(event) => handleNavClick(event, 'settings')}>Settings</a></nav></div></header>
{#if $navigation === 'planner'}
  <main class="planner-page">
    <h1 bind:this={plannerHeading} tabindex="-1">Plan your canal journey</h1>
    {#if saveFeedback}
      <p class="save-status" role="status">
        {saveFeedback === 'persistent'
          ? 'Boat settings saved.'
          : 'Boat settings saved for this session; browser storage is unavailable.'}
      </p>
    {/if}
    <BoatConstraints formId="route-actions" bind:days={plannerSession.days} bind:hours={plannerSession.hours} />
    <div class="map-column">
      <fieldset class="map-target"><legend>Map click action</legend><label><input type="radio" bind:group={active} value="origin" /> Set origin from map</label><label><input type="radio" bind:group={active} value="destination" /> Set destination from map</label>{#if $climateGridStore.enabled}<label><input type="radio" bind:group={active} value="temperature" /> Inspect temperature from map</label>{/if}</fieldset>
      {#if active === 'temperature' && temperatureSelectionMessage}<p role="status">{temperatureSelectionMessage}</p>{/if}
    <MapCanvas
        load={dependencies.loadMapView}
        onclick={handleMapClick}
        onhirebaseselect={store.selectHireBase}
        onhirebaseendpointselect={(slot, base) => store.setEndpointCoordinate(slot, {
          name: base.name,
          address: base.operator,
          coordinate: base.coordinate,
        })}
        onready={setMapView}
      />
    {#if $store.networkLoading && !$store.hasNetworkOverlay}
      <p class="network-status" role="status">Loading canal network overlay…</p>
    {/if}
    {#if $store.networkError}
      <p class="network-status" role="status">
        {$store.hasNetworkOverlay
          ? `Canal network overlay could not be updated: ${$store.networkError}`
          : `Canal network overlay is unavailable: ${$store.networkError}`}
      </p>
    {/if}
	</div>
    <div class="planner-column">
      {#if dependencies.placeDiscovery}
        <AttractionPanel controller={dependencies.placeDiscovery}
          onPreview={(routes) => { hasAttractionPreview = true; mapView?.land('origin', routes.outward); mapView?.land('destination', routes.return); }}
          onClearPreview={clearAttractionPreview} />
      {/if}

      <ClimateGridControls store={climateGridStore} />
      <ClimateGridDetail store={climateGridStore} />
      <details open={$climateStore.enabled}>
        <summary>City temperature references</summary>
        <ClimateControls store={climateStore} />
        <ClimateDetail store={climateStore} />
      </details>
		{#key searchKey}
			<EndpointPanel slot="origin" endpoint={$store.origin} {store} search={dependencies.placeSearch} />
			<EndpointPanel slot="destination" endpoint={$store.destination} {store} search={dependencies.placeSearch} />
		{/key}
      <form id="route-actions" class="route-actions" novalidate onsubmit={(event) => { event.preventDefault(); planTrip(); }}>
        <div class="constraint-actions">
          <button type="submit">Plan canal route</button>
          <button type="button" onclick={resetTrip}>Reset trip</button>
        </div>
        {#if routeError}<p role="alert">{routeError}</p>{/if}
      </form>
      <TripSummary state={$store} onDaySelect={store.selectDay} />
      <RouteLayers {store} />
    </div>
  </main>
{:else}
  <main class="settings-page">
    <h1 bind:this={settingsHeading} tabindex="-1">Boat settings</h1>
    <BoatSettings store={boatSettings} onSave={finishSettingsSave} onCancel={() => navigation.navigate('planner')} />
  </main>
{/if}
<footer>
  Canal routes are planning guidance; verify navigation restrictions and safe access locally.
  Map data © Google and
  <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">© OpenStreetMap contributors</a>.
</footer>
