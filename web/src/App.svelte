<script lang="ts">
  import { onMount, onDestroy, tick } from 'svelte';
  import './app.css';
  import AttractionPanel from './component/AttractionPanel.svelte';
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
  const boatSettings = createBoatSettingsStore();
  let active = $state<EndpointSlot>('origin');
  let plannerSession = $state({ days: 7 as string | number, hours: 6 as string | number });
  let searchKey = $state(0);
  let mapView: MapView | undefined;
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
      <fieldset class="map-target"><legend>Map click sets</legend><label><input type="radio" bind:group={active} value="origin" /> Set origin from map</label><label><input type="radio" bind:group={active} value="destination" /> Set destination from map</label></fieldset>
		<MapCanvas
        load={dependencies.loadMapView}
        onclick={(coordinate) => store.setEndpointCoordinate(active, coordinate)}
        onhirebaseselect={store.selectHireBase}
        onhirebaseendpointselect={(slot, base) => store.setEndpointCoordinate(slot, {
          name: base.name,
          address: base.operator,
          coordinate: base.coordinate,
        })}
        onready={(view) => { mapView = view; store.setMapView(view); }}
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
