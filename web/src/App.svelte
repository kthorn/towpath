<script lang="ts">
  import { onMount, tick } from 'svelte';
  import './app.css';
  import BoatConstraints from './component/BoatConstraints.svelte';
  import BoatSettings from './component/BoatSettings.svelte';
  import EndpointPanel from './component/EndpointPanel.svelte';
  import MapCanvas from './component/MapCanvas.svelte';
  import RouteLayers from './component/RouteLayers.svelte';
  import TripSummary from './component/TripSummary.svelte';
  import type { AppDependencies } from './lib/app';
  import type { EndpointSlot } from './lib/google/contracts';
  import type { JourneyMode } from './lib/types';
  import { createNavigation, type AppRoute } from './lib/navigation';
  import { parseSchedule } from './lib/schedule';
  import { createBoatSettingsStore, type SettingsSaveResult } from './lib/stores/boat-settings';

  let { dependencies }: { dependencies: AppDependencies } = $props();
  const store = $derived(dependencies.store);
  const journeyMode = $derived($store.journeyMode ?? 'point_to_point');
  const boatSettings = createBoatSettingsStore();
  let active = $state<EndpointSlot>('origin');
  let plannerSession = $state({ days: 7 as string | number, hours: 6 as string | number });
  let searchKey = $state(0);
  const networkRequest = $derived.by(() => {
    try {
      return { ...parseSchedule(plannerSession.days, plannerSession.hours), ...$boatSettings };
    } catch {
      return null;
    }
  });
  $effect(() => {
    store.setNetworkRequest(networkRequest);
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

  function resetTrip() {
    dependencies.store.reset();
    plannerSession = { days: 7, hours: 6 };
    searchKey += 1;
  }

  function changeJourneyMode(event: Event) {
    if (!(event.currentTarget instanceof HTMLInputElement)) return;
    store.setJourneyMode(event.currentTarget.value as JourneyMode);
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
    <div class="map-column">
		<fieldset class="map-target"><legend>Map click sets</legend><label><input type="radio" bind:group={active} value="origin" /> Set origin from map</label><label><input type="radio" bind:group={active} value="destination" /> Set {journeyMode === 'out_and_back' ? 'visit on the way' : 'destination'} from map</label></fieldset>
		<MapCanvas load={dependencies.loadMapView} onclick={(coordinate) => dependencies.store.setEndpointCoordinate(active, coordinate)} onready={(view) => dependencies.store.setMapView(view)} />
    {#if $store.networkError}
      <p class="network-status" role="status">
        {$store.hasNetworkOverlay
          ? `Canal network overlay could not be updated: ${$store.networkError}`
          : `Canal network overlay is unavailable: ${$store.networkError}`}
      </p>
    {/if}
	</div>
    <div class="planner-column">
		<fieldset class="journey-mode" aria-label="Journey mode">
			<legend>Journey mode</legend>
			<label><input type="radio" name="journey-mode" value="point_to_point" checked={journeyMode === 'point_to_point'} onchange={changeJourneyMode} /> Point to point</label>
			<label><input type="radio" name="journey-mode" value="out_and_back" checked={journeyMode === 'out_and_back'} onchange={changeJourneyMode} /> Out-and-back</label>
		</fieldset>
		{#key searchKey}
			<EndpointPanel slot="origin" endpoint={$store.origin} {store} search={dependencies.placeSearch} />
			<EndpointPanel slot="destination" endpoint={$store.destination} {store} search={dependencies.placeSearch} title={journeyMode === 'out_and_back' ? 'Visit on the way' : 'Destination'} optional={journeyMode === 'out_and_back'} />
		{/key}
      <BoatConstraints {store} settings={boatSettings} onReset={resetTrip} mode={journeyMode} bind:days={plannerSession.days} bind:hours={plannerSession.hours} />
      <TripSummary state={$store} {store} onDaySelect={store.selectDay} />
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
