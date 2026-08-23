import { fireEvent, render, screen } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createBoatSettingsStore } from '../lib/stores/boat-settings';
import BoatSettings from './BoatSettings.svelte';

const emptySettings = {
  boat_length_m: null,
  boat_beam_m: null,
  boat_draft_m: null,
  boat_height_m: null,
  movable_bridge_delay_min: null,
};

function renderSettings(delay: number | null = null) {
  const store = createBoatSettingsStore(localStorage);
  store.save({ ...emptySettings, movable_bridge_delay_min: delay });
  const onSave = vi.fn();
  render(BoatSettings, { props: { store, onSave, onCancel: vi.fn() } });
  return { onSave, store };
}

describe('movable-bridge delay control', () => {
  beforeEach(() => localStorage.clear());

  it('saves a zero delay entered in the control', async () => {
    const { onSave, store } = renderSettings();

    await fireEvent.input(screen.getByLabelText(/movable-bridge delay/i), {
      target: { value: '0' },
    });
    await fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));

    expect(onSave).toHaveBeenCalledWith('persistent');
    expect(get(store).movable_bridge_delay_min).toBe(0);
  });

  it('saves a cleared delay as the backend-default override', async () => {
    const { onSave, store } = renderSettings(5);
    const delay = screen.getByLabelText(/movable-bridge delay/i);

    expect(delay).toHaveValue(5);
    await fireEvent.input(delay, { target: { value: '' } });
    expect(delay).toHaveValue(null);
    await fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));

    expect(onSave).toHaveBeenCalledWith('persistent');
    expect(get(store).movable_bridge_delay_min).toBeNull();
  });

  it('renders an error without saving an invalid delay', async () => {
    const { onSave, store } = renderSettings();
    const delay = screen.getByLabelText(/movable-bridge delay/i);

    await fireEvent.input(delay, { target: { value: '-0.5' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Movable-bridge delay must be zero or greater.',
    );
    expect(delay).toHaveAttribute('aria-invalid', 'true');
    expect(delay).toHaveAttribute('aria-describedby', 'movable-bridge-delay-error');
    expect(delay).toHaveFocus();
    expect(onSave).not.toHaveBeenCalled();
    expect(get(store).movable_bridge_delay_min).toBeNull();
  });
});
