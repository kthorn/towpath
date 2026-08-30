<script lang="ts">
  let {
    days = $bindable<string | number>(7),
    hours = $bindable<string | number>(6),
    formId,
  }: {
    days?: string | number;
    hours?: string | number;
    formId: string;
  } = $props();
</script>

<fieldset class="schedule-bar">
  <legend>Cruising time</legend>
  <div class="schedule-content">
    <p>
      The map shows canal routes that can return to the same hire base within the selected Days
      and Hours per day, capped at 168 cruising hours.
    </p>
    <div class="constraint-grid">
      <label>Days<input form={formId} type="number" required min="1" max="365" bind:value={days} /></label>
      <label>Hours per day<input form={formId} type="number" required min="0.1" max="24" step="0.5" bind:value={hours} /></label>
    </div>
  </div>
</fieldset>
