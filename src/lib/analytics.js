import { GA_MEASUREMENT_ID } from './analyticsConfig';

// Basic consent mode: the Google tag is requested only after an explicit opt-in.
const measurementId = String(import.meta.env.VITE_GA_MEASUREMENT_ID ?? GA_MEASUREMENT_ID).trim();
const configured = /^G-[A-Z0-9]+$/.test(measurementId);
const CONSENT_KEY = 'sofia.analytics-consent.v1';
const PAGE_CONTEXT = Object.freeze({
  page_location: 'https://sofiapermits.site.je/',
  page_referrer: '',
  page_title: 'Sofia Property Register',
});
const DENIED_CONSENT = Object.freeze({
  analytics_storage: 'denied',
  ad_storage: 'denied',
  ad_user_data: 'denied',
  ad_personalization: 'denied',
});

const listeners = new Set();
let initialized = false;
let tagConfigured = false;
let tagLoaded = false;
let tagPromise = null;
let pageViewSent = false;
let pendingEvents = [];

function browserAvailable() {
  return typeof window !== 'undefined' && typeof document !== 'undefined';
}

function readConsent() {
  if (!browserAvailable()) return 'unknown';
  try {
    const stored = window.localStorage.getItem(CONSENT_KEY);
    return stored === 'granted' || stored === 'denied' ? stored : 'unknown';
  } catch {
    return 'unknown';
  }
}

let consent = readConsent();

function notify() {
  listeners.forEach((listener) => listener());
}

function command() {
  // Keeping commands in the local queue makes no third-party request by itself.
  window.dataLayer.push(arguments);
}

function disableCollection() {
  if (!browserAvailable() || !configured) return;
  // Google checks this flag before writing cookies or sending measurement data.
  window[`ga-disable-${measurementId}`] = true;
  pendingEvents = [];
  if (initialized) command('consent', 'update', DENIED_CONSENT);
  clearAnalyticsCookies();
}

function clearAnalyticsCookies() {
  if (!browserAvailable() || !configured) return;
  const names = ['_ga', `_ga_${measurementId.slice(2)}`];
  const hostParts = window.location.hostname.split('.');
  const domains = [];
  for (let i = 0; i < hostParts.length - 1; i += 1) {
    const domain = hostParts.slice(i).join('.');
    domains.push(domain, `.${domain}`);
  }
  try {
    names.forEach((name) => {
      const expired = `${name}=; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=/; SameSite=Lax`;
      document.cookie = expired;
      domains.forEach((domain) => {
        document.cookie = `${expired}; Domain=${domain}`;
      });
    });
  } catch {
    // A storage restriction must not interfere with the map or consent controls.
  }
}

function loadTag() {
  if (tagPromise) return tagPromise;
  tagPromise = new Promise((resolve) => {
    const script = document.createElement('script');
    script.id = 'sofia-google-analytics';
    script.async = true;
    script.referrerPolicy = 'no-referrer';
    script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(measurementId)}`;
    script.onload = () => {
      tagLoaded = true;
      resolve(true);
    };
    script.onerror = () => {
      // A blocked analytics request must not break normal website use.
      script.remove();
      tagPromise = null;
      pendingEvents = [];
      resolve(false);
    };
    document.head.appendChild(script);
  });
  return tagPromise;
}

function sendSafeEvent(name, parameters) {
  command('event', name, {
    ...parameters,
    ...PAGE_CONTEXT,
    send_to: measurementId,
  });
}

function activateCollection() {
  if (!configured || consent !== 'granted' || !browserAvailable()) return;
  window[`ga-disable-${measurementId}`] = false;
  command('consent', 'update', { ...DENIED_CONSENT, analytics_storage: 'granted' });
  if (!tagConfigured) {
    command('js', new Date());
    command('config', measurementId, {
      ...PAGE_CONTEXT,
      send_page_view: false,
      allow_google_signals: false,
      allow_ad_personalization_signals: false,
      cookie_domain: 'none',
      cookie_path: '/',
      cookie_flags: 'SameSite=Lax;Secure',
      // Override URL campaign fields so an incoming query cannot enter reports.
      campaign_id: '',
      campaign_source: '',
      campaign_medium: '',
      campaign_name: '',
      campaign_content: '',
      campaign_term: '',
    });
    tagConfigured = true;
  }
  loadTag().then((loaded) => {
    if (!loaded || consent !== 'granted') return;
    if (!pageViewSent) {
      sendSafeEvent('page_view', {});
      pageViewSent = true;
    }
    const events = pendingEvents;
    pendingEvents = [];
    events.forEach(({ name, parameters }) => {
      if (consent === 'granted') sendSafeEvent(name, parameters);
    });
  });
}

export function hasAnalyticsConfiguration() {
  return configured;
}

export function getAnalyticsConsent() {
  return consent;
}

export function subscribeAnalyticsConsent(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function initializeQueue() {
  if (!configured || !browserAvailable() || initialized) return false;
  initialized = true;
  window[`ga-disable-${measurementId}`] = true;
  window.dataLayer = window.dataLayer || [];
  window.gtag = command;
  command('consent', 'default', DENIED_CONSENT);
  command('set', {
    ...PAGE_CONTEXT,
    allow_google_signals: false,
    allow_ad_personalization_signals: false,
    ads_data_redaction: true,
    url_passthrough: false,
  });
  window.addEventListener('storage', (event) => {
    if (event.key !== CONSENT_KEY && event.key !== null) return;
    const next = readConsent();
    if (next === consent) return;
    consent = next;
    if (consent === 'granted') activateCollection();
    else disableCollection();
    notify();
  });
  return true;
}

export function initializeAnalytics() {
  if (!initializeQueue()) return;
  // Another tab may have changed the stored choice since this module loaded.
  const stored = readConsent();
  const changed = stored !== consent;
  consent = stored;
  if (consent === 'granted') activateCollection();
  else clearAnalyticsCookies();
  if (changed) notify();
}

export function setAnalyticsConsent(next) {
  if (next !== 'granted' && next !== 'denied') return;
  // Set up the local queue without activating a previous stored permission.
  initializeQueue();
  consent = next;
  if (browserAvailable()) {
    try {
      window.localStorage.setItem(CONSENT_KEY, next);
    } catch {
      // The choice still applies to this visit if local storage is unavailable.
    }
  }
  if (next === 'granted') activateCollection();
  else disableCollection();
  notify();
}

function safeCount(value, maximum) {
  return typeof value === 'number' && Number.isFinite(value)
    ? Math.max(0, Math.min(maximum, Math.floor(value)))
    : undefined;
}

function clusterBucket(value) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 2) return undefined;
  if (value < 10) return '2-9';
  if (value < 50) return '10-49';
  if (value < 100) return '50-99';
  if (value < 500) return '100-499';
  if (value < 1000) return '500-999';
  if (value < 5000) return '1000-4999';
  return '5000+';
}

// Deliberately allowlist event names and parameters. Never pass a search query,
// cadastral ID, address, district, coordinates, date, URL or document contents.
export function trackEvent(name, parameters = {}) {
  if (!configured || !browserAvailable()) return false;
  initializeAnalytics();
  if (consent !== 'granted') return false;
  const values = parameters && typeof parameters === 'object' ? parameters : {};
  const safe = {};
  if (name === 'search_submit' || name === 'address_locate') {
    // Record the action without the text the visitor entered.
  } else if (name === 'workspace_open') {
    if (!['map', 'offers', 'activity'].includes(values.workspace)) return false;
    safe.workspace = values.workspace;
  } else if (name === 'property_open') {
    if (values.entry_point === 'map' || values.entry_point === 'search') {
      safe.entry_point = values.entry_point;
    }
  } else if (name === 'filter_change') {
    const filterCount = safeCount(values.filter_count, 12);
    const typeCount = safeCount(values.record_type_count, 3);
    if (filterCount !== undefined) safe.filter_count = filterCount;
    if (typeCount !== undefined) safe.record_type_count = typeCount;
  } else if (name === 'cluster_open') {
    const bucket = clusterBucket(values.plot_count);
    if (bucket === undefined) return false;
    safe.size_bucket = bucket;
  } else {
    return false;
  }
  if (tagLoaded) sendSafeEvent(name, safe);
  else if (pendingEvents.length < 50) pendingEvents.push({ name, parameters: safe });
  return true;
}
