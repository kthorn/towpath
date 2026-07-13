import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createNavigation, parseRoute, type AppRoute, type NavigationEnvironment } from './navigation';

interface FakeBrowser {
  location: { pathname: string };
  history: {
    pushState: ReturnType<typeof vi.fn>;
    replaceState: ReturnType<typeof vi.fn>;
  };
  addEventListener: ReturnType<typeof vi.fn>;
  removeEventListener: ReturnType<typeof vi.fn>;
  emitPopState: () => void;
}

function fakeBrowser(pathname: string): FakeBrowser {
  const listeners = new Set<() => void>();

  const environment = {
    location: { pathname },
    history: {
      pushState: vi.fn(),
      replaceState: vi.fn(),
    },
    addEventListener: vi.fn((_type: 'popstate', listener: () => void) => {
      listeners.add(listener);
    }),
    removeEventListener: vi.fn((_type: 'popstate', listener: () => void) => {
      listeners.delete(listener);
    }),
  };

  // @ts-expect-error emitPopState is only used in tests
  environment.emitPopState = () => {
    for (const listener of listeners) {
      listener();
    }
  };

  return environment as unknown as FakeBrowser;
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('parseRoute', () => {
  it.each([
    ['/', 'planner'],
    ['/settings', 'settings'],
    ['/settings/', 'settings'],
    ['/not-a-route', 'planner'],
  ])('parses %s as %s', (pathname, expected) => {
    expect(parseRoute(pathname)).toBe(expected);
  });
});

describe('createNavigation', () => {
  it('canonicalizes an initial settings slash and unknown initial paths', () => {
    const settingsBrowser = fakeBrowser('/settings/');
    createNavigation(settingsBrowser);
    expect(settingsBrowser.history.replaceState).toHaveBeenCalledWith(null, '', '/settings');

    const unknownBrowser = fakeBrowser('/missing');
    createNavigation(unknownBrowser);
    expect(unknownBrowser.history.replaceState).toHaveBeenCalledWith(null, '', '/');
  });

  it('pushes only when navigating to a different route', () => {
    const browser = fakeBrowser('/');
    const navigation = createNavigation(browser);

    navigation.navigate('planner');
    expect(browser.history.pushState).not.toHaveBeenCalled();

    navigation.navigate('settings');
    expect(browser.history.pushState).toHaveBeenCalledWith(null, '', '/settings');
  });

  it('publishes popstate changes without pushing another entry', () => {
    const browser = fakeBrowser('/');
    const navigation = createNavigation(browser);
    const values: AppRoute[] = [];
    const unsubscribe = navigation.subscribe((route) => values.push(route));

    browser.location.pathname = '/settings';
    browser.emitPopState();

    expect(values.at(-1)).toBe('settings');
    expect(browser.history.pushState).not.toHaveBeenCalled();
    unsubscribe();
    navigation.destroy();
  });

  it('removes its popstate listener when destroyed', () => {
    const browser = fakeBrowser('/');
    const navigation = createNavigation(browser);
    navigation.destroy();
    expect(browser.removeEventListener).toHaveBeenCalledWith('popstate', expect.any(Function));
  });

  it('returns correct href for each route', () => {
    const browser = fakeBrowser('/');
    const navigation = createNavigation(browser);
    expect(navigation.href('planner')).toBe('/');
    expect(navigation.href('settings')).toBe('/settings');
  });

  it('publishes the initial route to new subscribers', () => {
    const browser = fakeBrowser('/settings');
    const navigation = createNavigation(browser);
    const values: AppRoute[] = [];
    navigation.subscribe((route) => values.push(route));
    expect(values).toEqual(['settings']);
  });

  it('idempotent destroy does not throw or re-register', () => {
    const browser = fakeBrowser('/');
    const navigation = createNavigation(browser);
    navigation.destroy();
    navigation.destroy();
    expect(browser.removeEventListener).toHaveBeenCalledTimes(1);
  });

  it('navigate after destroy does not push or publish', () => {
    const browser = fakeBrowser('/');
    const navigation = createNavigation(browser);
    const values: AppRoute[] = [];
    const unsubscribe = navigation.subscribe((route) => values.push(route));

    navigation.destroy();
    browser.history.pushState.mockClear();

    navigation.navigate('settings');
    expect(browser.history.pushState).not.toHaveBeenCalled();
    expect(values.at(-1)).toBe('planner');
    unsubscribe();
  });
});
