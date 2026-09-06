import { beforeEach, describe, expect, it, type Mock, vi } from 'vitest';

import { createNavigation, parseRoute, type AppRoute, type NavigationEnvironment } from './navigation';

interface FakeBrowser extends NavigationEnvironment {
  location: { pathname: string };
  history: {
    pushState: Mock<History['pushState']>;
    replaceState: Mock<History['replaceState']>;
  };
  addEventListener: Mock<NavigationEnvironment['addEventListener']>;
  removeEventListener: Mock<NavigationEnvironment['removeEventListener']>;
  emitPopState: () => void;
}

function fakeBrowser(pathname: string): FakeBrowser {
  const listeners = new Set<() => void>();

  return {
    location: { pathname },
    history: {
      pushState: vi.fn<History['pushState']>(),
      replaceState: vi.fn<History['replaceState']>(),
    },
    addEventListener: vi.fn<NavigationEnvironment['addEventListener']>((_type, listener) => {
      listeners.add(listener);
    }),
    removeEventListener: vi.fn<NavigationEnvironment['removeEventListener']>((_type, listener) => {
      listeners.delete(listener);
    }),
    emitPopState: () => {
      for (const listener of listeners) {
        listener();
      }
    },
  };
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
