import React, { lazy, useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowUpRight, Building2, ChevronDown, Loader2, MapPin, PanelLeft, PanelLeftClose, Search, ShieldCheck, SlidersHorizontal } from 'lucide-react';
import { useToast } from '@/components/ui/use-toast';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { useIsMobile } from '@/hooks/use-mobile';
import { useI18n } from '@/lib/i18n';
import { trackEvent } from '@/lib/analytics';
import { displayCount, displayDate } from '@/lib/registerUi';
import { activeFilterCount, invalidFilterArea, invalidFilterDates, invalidFilterSearch, normalizePropertyFilters, readPropertyFilters, SEARCH_TERM_LIMIT, SEARCH_TERM_LENGTH_LIMIT, writePropertyFilters } from '@/lib/propertyFilters';
import { realEstateApi } from '@/api/realEstateApi';
import { isAddressQuery } from '@/lib/searchIntent';
import AppHeader from '@/components/AppHeader';
import AsyncPanel from '@/components/AsyncPanel';
import MapToolbar from '@/components/map/MapToolbar';
import MapLegend from '@/components/map/MapLegend';
import SearchPanel from '@/components/search/SearchPanel';
import RegisterFilters from '@/components/search/RegisterFilters';
import useViewportParcels from '@/hooks/useViewportParcels';
import useBusinessViewport from '@/hooks/useBusinessViewport';
import CompanyMapPanel, { BusinessMapStatus } from '@/components/map/CompanyMapPanel';
import '@/components/AppShell.css';

const INITIAL_VIEW = { center: [42.684, 23.333], zoom: 13 };
const DevelopmentDashboard = lazy(() => import('@/components/development/DevelopmentDashboard'));
const MarketDashboard = lazy(() => import('@/components/market/MarketDashboard'));
const MapView = lazy(() => import('@/components/map/MapView'));
const DetailsPanel = lazy(() => import('@/components/details/DetailsPanel'));
const BusinessAddressDetails = lazy(() => import('@/components/details/BusinessAddressDetails'));
const AddressSearch = lazy(() => import('@/components/search/AddressSearch'));
function watchingEnabled() {
  try { return JSON.parse(localStorage.getItem('sofiapermits.market.watching.v1') || 'null')?.enabled === true; } catch { return false; }
}
function initialParcelMode() {
  try { return localStorage.getItem('sofiapermits.parcel-display.v1') === 'boundaries' ? 'boundaries' : 'points'; } catch { return 'points'; }
}
const readWorkspace = () => {
  const fragment = window.location.hash.slice(1);
  if (['map', 'offers', 'activity'].includes(fragment)) return fragment;
  const requested = new URLSearchParams(window.location.search).get('view');
  return ['offers', 'activity'].includes(requested) ? requested : 'map';
};

function DatasetSummary({ meta }) {
  const { t, lang } = useI18n();
  const imports = (meta?.imports || []).filter((item, index, rows) => item.source_code !== 'coordinates' && rows.findIndex((row) => row.source_code === item.source_code) === index);
  return (
    <section className="dataset-summary">
      <details className="dataset-summary-disclosure">
        <summary><ShieldCheck size={16} /><span>{t('dataset.sources')}</span><ChevronDown size={14} /></summary>
        <div className="dataset-stats"><div><strong>{meta ? displayCount(meta.counts.plots, lang) : '—'}</strong><span>{t('dataset.points')}</span></div><div><strong>{meta ? displayCount(meta.counts.documents, lang) : '—'}</strong><span>{t('dataset.records')}</span></div></div>
        <div className="dataset-source-list">
          {imports.map((source) => <div key={source.source_code}><a href={source.source_url} target="_blank" rel="noreferrer">{lang === 'bg' ? source.label_bg : source.label_en}<ArrowUpRight size={13} /></a><small>{source.snapshot_date ? t('dataset.snapshot', { date: displayDate(source.snapshot_date, lang) }) : t('dataset.dateUnknown')}</small></div>)}
          {meta?.cadastre && <div><a href={meta.cadastre.source_url} target="_blank" rel="noreferrer">{lang === 'bg' ? meta.cadastre.label_bg : meta.cadastre.label_en}<ArrowUpRight size={13} /></a><small>{t('dataset.cadastreCount', { n: displayCount(meta.cadastre.parcel_count, lang) })}</small>{meta.cadastre.captured_at && <small>{t('dataset.loaded', { date: displayDate(meta.cadastre.captured_at, lang) })}</small>}</div>}
          <p>{t('dataset.snapshotHelp')}</p>
        </div>
      </details>
    </section>
  );
}

export default function Home() {
  const { t, lang } = useI18n();
  const { toast } = useToast();
  const isMobile = useIsMobile();
  const [bounds, setBounds] = useState(null);
  const [map, setMap] = useState(null);
  const [selected, setSelected] = useState(null);
  const [canReturnToSearch, setCanReturnToSearch] = useState(false);
  const [hoveredKey, setHoveredKey] = useState(null);
  const [baseLayer, setBaseLayer] = useState('standard');
  const [parcelMode, setParcelMode] = useState(initialParcelMode);
  const [mapDataset, setMapDataset] = useState(() => new URL(window.location.href).searchParams.get('layer') === 'companies' ? 'companies' : 'properties');
  const mapDatasetRef = useRef(mapDataset);
  mapDatasetRef.current = mapDataset;
  const [businessMapDraft, setBusinessMapDraft] = useState('');
  const [businessMapQuery, setBusinessMapQuery] = useState('');
  const [businessMapLevel, setBusinessMapLevel] = useState('all');
  const [businessFitRequest, setBusinessFitRequest] = useState(() => new URL(window.location.href).searchParams.get('layer') === 'companies' ? { query: '', level: 'all', generation: 0 } : null);
  const [boundaryStatus, setBoundaryStatus] = useState(null);
  const [boundaryRevision, setBoundaryRevision] = useState(0);
  const [query, setQuery] = useState('');
  const [searchResponse, setSearchResponse] = useState(null);
  const [businessSearchState, setBusinessSearchState] = useState({});
  const [searchError, setSearchError] = useState(false);
  const [searching, setSearching] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [filters, setFilters] = useState(readPropertyFilters);
  const [meta, setMeta] = useState(null);
  const [userLocation, setUserLocation] = useState(null);
  const [addressLocation, setAddressLocation] = useState(null);
  const [addressRequest, setAddressRequest] = useState(null);
  const [addressProvider, setAddressProvider] = useState(null);
  const [searchTab, setSearchTab] = useState('records');
  const [workspace, setWorkspace] = useState(readWorkspace);
  const workspaceRef = useRef(workspace);
  workspaceRef.current = workspace;
  const [mapVisited, setMapVisited] = useState(() => readWorkspace() === 'map');
  const [marketVisited, setMarketVisited] = useState(() => readWorkspace() === 'offers' || watchingEnabled());
  const [addressVisited, setAddressVisited] = useState(false);
  const [developmentVisited, setDevelopmentVisited] = useState(() => readWorkspace() === 'activity');
  const [returnToDevelopment, setReturnToDevelopment] = useState(false);
  const pendingMapNavigation = useRef(null);
  const [marketAlertCount, setMarketAlertCount] = useState(0);
  const searchRequest = useRef(0);
  const addressRequestSequence = useRef(0);
  const navigationGeneration = useRef(0);
  const pendingAddressNavigation = useRef(null);
  const fitSearchResults = useRef(filters.searchTerms.length > 0);
  const mapRef = useRef(null);
  mapRef.current = map;
  const filterPanel = useRef(null);
  const companyPanel = useRef(null);
  const searchPanel = useRef(null);
  const sidebarScroll = useRef(null);
  const sidebarOpener = useRef(null);
  const focusSidebar = useRef(false);
  const searchReturn = useRef(null);
  const pendingSearchReturn = useRef(null);
  const returningToSearch = useRef(false);
  const activeCount = activeFilterCount(filters);
  const { parcels, isLoading, truncated, total, apiError, filterError, refetch: refetchViewport } = useViewportParcels(bounds, filters, workspace === 'map' && mapDataset === 'properties');
  const businessViewport = useBusinessViewport(bounds, businessMapQuery, workspace === 'map' && mapDataset === 'companies', businessMapLevel);
  const changeMapDataset = useCallback((next) => {
    if (!['companies', 'properties'].includes(next)) return;
    const generation = ++navigationGeneration.current;
    pendingAddressNavigation.current = null;
    setSelected(null); setMapDataset(next);
    searchReturn.current = null; pendingSearchReturn.current = null; setCanReturnToSearch(false);
    setBusinessFitRequest(next === 'companies' ? { query: businessMapQuery, level: businessMapLevel, generation } : null);
    const url = new URL(window.location.href);
    if (next === 'companies') url.searchParams.set('layer', 'companies');
    else url.searchParams.delete('layer');
    window.history.replaceState(window.history.state, '', url.pathname + url.search + url.hash);
  }, [businessMapQuery, businessMapLevel]);
  const applyBusinessMapQuery = useCallback((value, level = businessMapLevel) => {
    const next = value.trim().replace(/\s+/gu, ' ');
    const generation = ++navigationGeneration.current;
    pendingAddressNavigation.current = null;
    setBusinessMapDraft(next); setBusinessMapQuery(next); setSelected(null); setBusinessMapLevel(level);
    setBusinessFitRequest({ query: next, level, generation });
  }, [businessMapLevel]);
  const changeBusinessMapLevel = useCallback((level) => {
    if (!['all', 'parcel', 'address'].includes(level)) return;
    const generation = ++navigationGeneration.current;
    setBusinessMapLevel(level); setSelected(null);
    setBusinessFitRequest({ query: businessMapQuery, level, generation });
  }, [businessMapQuery]);
  useEffect(() => {
    const data = businessViewport.data;
    if (!businessFitRequest || workspace !== 'map' || mapDataset !== 'companies' || !map || !data || data.query !== businessFitRequest.query || data.level !== businessFitRequest.level || businessFitRequest.generation !== navigationGeneration.current) return;
    const extent = data.bounds;
    if (extent && ['south', 'north', 'west', 'east'].every((key) => Number.isFinite(Number(extent[key])))) map.fitBounds([[extent.south, extent.west], [extent.north, extent.east]], { padding: [42, 42], maxZoom: 17 });
    setBusinessFitRequest(null);
  }, [businessViewport.data, businessFitRequest, workspace, mapDataset, map]);
  const changeParcelMode = useCallback((next) => {
    if (!['points', 'boundaries'].includes(next)) return;
    setParcelMode(next); setBoundaryStatus(null);
    try { localStorage.setItem('sofiapermits.parcel-display.v1', next); } catch { /* This view still works without storage. */ }
  }, []);
  const retryMapData = useCallback(() => { setBoundaryRevision((value) => value + 1); refetchViewport(); }, [refetchViewport]);

  useEffect(() => { if (!mapVisited) return undefined; let active = true; realEstateApi.meta().then((data) => { if (active) setMeta(data); }).catch(() => {}); return () => { active = false; }; }, [mapVisited]);
  useEffect(() => {
    const updateWatching = () => { if (watchingEnabled()) setMarketVisited(true); };
    window.addEventListener('storage', updateWatching);
    return () => window.removeEventListener('storage', updateWatching);
  }, []);
  useEffect(() => { if (searchTab === 'address' || addressRequest) setAddressVisited(true); }, [searchTab, addressRequest]);
  useEffect(() => { writePropertyFilters(filters); }, [filters]);
  useEffect(() => {
    const update = () => {
      const next = readWorkspace();
      if (workspaceRef.current !== next) {
        navigationGeneration.current += 1;
        pendingAddressNavigation.current = null;
        setAddressRequest(null);
        workspaceRef.current = next;
      }
      if (next === 'activity') setDevelopmentVisited(true);
      if (next === 'map') setMapVisited(true);
      if (next === 'offers') setMarketVisited(true);
      setWorkspace(next);
    };
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  const changeWorkspace = useCallback((next) => {
    if (!['map', 'offers', 'activity'].includes(next)) return;
    if (next === 'activity') setDevelopmentVisited(true);
    if (next === 'map') setMapVisited(true);
    if (next === 'offers') setMarketVisited(true);
    navigationGeneration.current += 1; pendingAddressNavigation.current = null; setAddressRequest(null);
    trackEvent('workspace_open', { workspace: next });
    setSearchOpen(false);
    workspaceRef.current = next;
    setWorkspace(next);
    window.location.hash = next;
    const nextUrl = new URL(window.location.href);
    nextUrl.searchParams.set('view', next);
    window.history.replaceState(window.history.state, '', nextUrl.pathname + nextUrl.search + nextUrl.hash);
  }, []);
  useEffect(() => {
    if (workspace !== 'map' || !map) return undefined;
    const frame = window.requestAnimationFrame(() => {
      map.invalidateSize({ pan: false });
      const pending = pendingMapNavigation.current;
      pendingMapNavigation.current = null;
      if (!pending || pending.generation !== navigationGeneration.current) return;
      map.stop();
      if (pending.kind === 'bounds') {
        map.fitBounds([[pending.bounds.south, pending.bounds.west], [pending.bounds.north, pending.bounds.east]], { padding: [48, 48], maxZoom: 17, animate: false });
      } else if (pending.lat != null && pending.lng != null && Number.isFinite(Number(pending.lat)) && Number.isFinite(Number(pending.lng))) {
        map.setView([Number(pending.lat), Number(pending.lng)], pending.zoom || 17, { animate: false });
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, [workspace, map]);
  const openDevelopmentPlot = useCallback((plot) => {
    if (!plot?.cadastral_id) return;
    changeMapDataset('properties');
    searchReturn.current = null; pendingSearchReturn.current = null; setCanReturnToSearch(false);
    setSelected(plot); setReturnToDevelopment(true); changeWorkspace('map');
    pendingMapNavigation.current = { kind: 'point', ...plot, zoom: 17, generation: navigationGeneration.current };
  }, [changeWorkspace, changeMapDataset]);
  const backToDevelopment = useCallback(() => {
    setSelected(null); setReturnToDevelopment(false); changeWorkspace('activity');
  }, [changeWorkspace]);
  const handleAddressSelect = useCallback((location, lookupGeneration) => {
    if (lookupGeneration != null && lookupGeneration !== navigationGeneration.current) return;
    navigationGeneration.current += 1;
    pendingAddressNavigation.current = location;
    setAddressLocation(location); setSelected(null); setSearchOpen(false);
    searchReturn.current = null; pendingSearchReturn.current = null; returningToSearch.current = false; setCanReturnToSearch(false);
    trackEvent('address_locate');
  }, []);
  useEffect(() => {
    const location = pendingAddressNavigation.current;
    if (!map || !location) return;
    pendingAddressNavigation.current = null;
    map.stop();
    map.invalidateSize({ pan: false });
    const extent = location.bounds;
    if (extent && ['south', 'north', 'west', 'east'].every((key) => Number.isFinite(extent[key]))) {
      map.fitBounds([[extent.south, extent.west], [extent.north, extent.east]], { padding: [48, 48], maxZoom: location.precision === 'address' ? 18 : 16 });
    } else map.flyTo([location.lat, location.lng], location.precision === 'address' ? 18 : 16);
  }, [map, addressLocation]);
  const clearAddress = useCallback(() => { navigationGeneration.current += 1; pendingAddressNavigation.current = null; setAddressLocation(null); }, []);
  const addressLookupStarted = useCallback(() => { navigationGeneration.current += 1; pendingAddressNavigation.current = null; fitSearchResults.current = false; return navigationGeneration.current; }, []);
  const addressRequestHandled = useCallback((id) => setAddressRequest((current) => current?.id === id ? null : current), []);
  const addressRequestCurrent = useCallback((request) => request.generation === navigationGeneration.current, []);
  const rememberSearchView = useCallback((plot, force = false) => {
    pendingSearchReturn.current = null;
    returningToSearch.current = false;
    if (!force && !filters.searchTerms.length) return;
    const list = searchPanel.current?.querySelector(force ? '.business-address-search-results ul' : '.search-results ul');
    if (searchReturn.current) {
      searchReturn.current.resultId = plot.cadastral_id || plot.address_id;
      if (sidebarScroll.current) searchReturn.current.scrollTop = sidebarScroll.current.scrollTop;
      if (list) searchReturn.current.listScrollTop = list.scrollTop;
      return;
    }
    const currentMap = mapRef.current;
    currentMap?.stop();
    const center = currentMap?.getCenter();
    searchReturn.current = {
      center: center ? [center.lat, center.lng] : null,
      zoom: currentMap?.getZoom(),
      bounds: searchResponse?.bounds,
      scrollTop: sidebarScroll.current?.scrollTop || 0,
      listScrollTop: list?.scrollTop || 0,
      resultId: plot.cadastral_id || plot.address_id,
      business: force,
    };
    setCanReturnToSearch(true);
  }, [filters.searchTerms, searchResponse]);
  const handleReturnToSearch = useCallback(() => {
    const saved = searchReturn.current;
    if (!saved) return;
    searchReturn.current = null;
    pendingSearchReturn.current = saved;
    returningToSearch.current = true;
    setCanReturnToSearch(false); setSelected(null); setHoveredKey(null);
    if (isMobile) setSearchOpen(true);
    else setSidebarCollapsed(false);
  }, [isMobile]);
  const handleCloseDetails = useCallback(() => {
    if (searchReturn.current) handleReturnToSearch();
    else setSelected(null);
  }, [handleReturnToSearch]);
  useEffect(() => {
    const saved = pendingSearchReturn.current;
    if (!saved || selected || (isMobile && !searchOpen)) return;
    const frame = window.requestAnimationFrame(() => {
      if (pendingSearchReturn.current !== saved) return;
      pendingSearchReturn.current = null;
      const currentMap = mapRef.current;
      if (currentMap && saved.center && Number.isFinite(saved.zoom)) {
        currentMap.stop();
        currentMap.invalidateSize({ pan: false });
        currentMap.setView(saved.center, saved.zoom, { animate: false });
      } else if (saved.bounds && ['south', 'north', 'west', 'east'].every((edge) => Number.isFinite(Number(saved.bounds[edge])))) {
        if (currentMap) currentMap.fitBounds([[saved.bounds.south, saved.bounds.west], [saved.bounds.north, saved.bounds.east]], { padding: [48, 48], maxZoom: 17, animate: false });
        else pendingMapNavigation.current = { kind: 'bounds', bounds: saved.bounds, generation: navigationGeneration.current };
      }
      sidebarScroll.current?.scrollTo({ top: saved.scrollTop, behavior: 'instant' });
      const list = searchPanel.current?.querySelector(saved.business ? '.business-address-search-results ul' : '.search-results ul');
      list?.scrollTo({ top: saved.listScrollTop, behavior: 'instant' });
      const resultButton = Array.from(list?.querySelectorAll(saved.business ? '[data-business-result-id]' : '[data-search-result-id]') || [])
        .find((button) => (saved.business ? button.dataset.businessResultId : button.dataset.searchResultId) === saved.resultId);
      (resultButton || searchPanel.current?.querySelector('input'))?.focus({ preventScroll: true });
      if (!isMobile) returningToSearch.current = false;
    });
    return () => { window.cancelAnimationFrame(frame); };
  }, [selected, isMobile, searchOpen, map]);
  const handleSelect = useCallback((plot) => { navigationGeneration.current += 1; pendingAddressNavigation.current = null; trackEvent('property_open', { entry_point: 'map' }); if (mapDataset === 'properties') rememberSearchView(plot); setSelected(plot); setSearchOpen(false); }, [rememberSearchView, mapDataset]);
  const handleClear = useCallback(() => { setQuery(''); }, []);
  const handleQueryChange = useCallback((value) => { setQuery(value); }, []);
  const handleFilterChange = useCallback((value) => {
    navigationGeneration.current += 1; pendingAddressNavigation.current = null;
    const next = normalizePropertyFilters(value);
    trackEvent('filter_change', { filter_count: activeFilterCount(next), record_type_count: next.recordTypes.length });
    searchReturn.current = null; pendingSearchReturn.current = null; returningToSearch.current = false; setCanReturnToSearch(false);
    searchRequest.current += 1; setFilters(next); setSearchResponse(null); setSearchError(false); setSelected(null);
  }, []);
  const clearFilters = useCallback(() => handleFilterChange({}), [handleFilterChange]);
  const openDevelopmentMap = useCallback((value) => {
    changeMapDataset('properties');
    const mapTypes = ['building_permits', 'projecting_visas', 'exploitation_certificates'];
    const selectedTypes = value.type === 'all' ? mapTypes : String(value.type || '').split(',').filter((type) => mapTypes.includes(type));
    const year = /^\d{4}$/.test(String(value.year || '')) ? String(value.year) : '';
    const phrases = value.q ? [value.q] : [];
    handleFilterChange({ recordTypes: selectedTypes, match: 'any', dateFrom: value.date_from || (year ? `${year}-01-01` : ''), dateTo: value.date_to || (year ? `${year}-12-31` : ''), district: value.district || '', searchTerms: phrases });
    fitSearchResults.current = phrases.length > 0;
    setReturnToDevelopment(true); changeWorkspace('map');
    mapRef.current?.setView(INITIAL_VIEW.center, 11, { animate: false });
  }, [changeWorkspace, handleFilterChange, changeMapDataset]);
  const editFilters = useCallback(() => {
    if (isMobile) setSearchOpen(true);
    else {
      setSidebarCollapsed(false);
      window.requestAnimationFrame(() => {
        const container = sidebarScroll.current;
        const target = mapDataset === 'companies' ? companyPanel.current : filterPanel.current;
        const inset = container?.querySelector('.map-sidebar-toolbar')?.offsetHeight || 0;
        if (container && target) container.scrollTo({ top: Math.max(0, container.scrollTop + target.getBoundingClientRect().top - container.getBoundingClientRect().top - inset), behavior: 'smooth' });
      });
    }
  }, [isMobile, mapDataset]);
  const openMapPanel = useCallback(() => {
    focusSidebar.current = true;
    setSidebarCollapsed(false);
  }, []);
  useEffect(() => {
    if (isMobile) return undefined;
    const frame = window.requestAnimationFrame(() => {
      if (sidebarCollapsed) sidebarOpener.current?.focus({ preventScroll: true });
      else if (focusSidebar.current) {
        focusSidebar.current = false;
        sidebarScroll.current?.querySelector('.map-sidebar-collapse')?.focus({ preventScroll: true });
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, [sidebarCollapsed, isMobile]);
  const handleSearchTabKeys = (event) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 'records' : event.key === 'End' ? 'address' : searchTab === 'records' ? 'address' : 'records';
    if (next === 'records') {
      navigationGeneration.current += 1; pendingAddressNavigation.current = null; setAddressRequest(null);
    }
    setSearchTab(next);
    event.currentTarget.querySelector(`#${next}-search-tab`)?.focus();
  };
  const handleRecordSearch = useCallback(() => {
    const term = query.trim();
    if (!term) return;
    navigationGeneration.current += 1; pendingAddressNavigation.current = null;
    if (invalidFilterDates(filters)) { toast({ title: t('filter.dateRangeError'), variant: 'destructive' }); return; }
    if (invalidFilterArea(filters)) { toast({ title: t('filter.areaRangeError'), variant: 'destructive' }); return; }
    if (Array.from(term).length > SEARCH_TERM_LENGTH_LIMIT || filters.searchTerms.length >= SEARCH_TERM_LIMIT) {
      toast({ title: t('search.limitError'), variant: 'destructive' }); return;
    }
    if (filters.searchTerms.some((value) => value.toLocaleLowerCase('bg') === term.toLocaleLowerCase('bg'))) {
      setQuery(''); return;
    }
    trackEvent('search_submit');
    fitSearchResults.current = true;
    handleFilterChange({ ...filters, searchTerms: [...filters.searchTerms, term] });
    setQuery('');
  }, [query, filters, handleFilterChange, t, toast]);
  const handleFindAddress = useCallback(() => {
    const value = query.trim();
    if (Array.from(value).length < 3 || Array.from(value).length > 160) return;
    // Recover an identical address phrase saved by the previous record-only input.
    const remainingTerms = filters.searchTerms.filter((term) => term.trim().toLocaleLowerCase('bg') !== value.toLocaleLowerCase('bg'));
    if (remainingTerms.length !== filters.searchTerms.length) handleFilterChange({ ...filters, searchTerms: remainingTerms });
    const generation = addressLookupStarted();
    setSearchTab('address');
    setAddressRequest({ id: ++addressRequestSequence.current, query: value, generation });
  }, [query, filters, handleFilterChange, addressLookupStarted]);
  const handleSearch = useCallback(() => {
    if (isAddressQuery(query)) handleFindAddress();
    else handleRecordSearch();
  }, [query, handleFindAddress, handleRecordSearch]);
  const handleRemoveTerm = useCallback((term) => {
    fitSearchResults.current = true;
    handleFilterChange({ ...filters, searchTerms: filters.searchTerms.filter((value) => value !== term) });
  }, [filters, handleFilterChange]);
  const handleClearTerms = useCallback(() => {
    fitSearchResults.current = false;
    handleFilterChange({ ...filters, searchTerms: [], searchMatch: 'all' });
  }, [filters, handleFilterChange]);
  const handleSearchMatchChange = useCallback((searchMatch) => {
    fitSearchResults.current = true;
    handleFilterChange({ ...filters, searchMatch });
  }, [filters, handleFilterChange]);
  useEffect(() => {
    const request = ++searchRequest.current;
    if (!filters.searchTerms.length) {
      setSearchResponse(null); setSearching(false); setSearchError(false); fitSearchResults.current = false;
      return;
    }
    if (invalidFilterDates(filters) || invalidFilterArea(filters) || invalidFilterSearch(filters)) {
      setSearchResponse(null); setSearching(false); setSearchError(true); fitSearchResults.current = false;
      return;
    }
    const controller = new AbortController();
    const shouldFit = fitSearchResults.current;
    const generation = navigationGeneration.current;
    fitSearchResults.current = false;
    setSearching(true); setSearchResponse(null); setSearchError(false);
    realEstateApi.search('', filters, controller.signal).then((response) => {
      if (request !== searchRequest.current) return;
      setSearchResponse(response);
      const extent = response.bounds;
      const coordinates = ['south', 'north', 'west', 'east'].map((key) => Number(extent?.[key]));
      if (shouldFit && mapDatasetRef.current === 'properties' && workspaceRef.current === 'map' && generation === navigationGeneration.current && extent && coordinates.every(Number.isFinite) && coordinates[0] <= coordinates[1] && coordinates[2] <= coordinates[3]) {
        if (mapRef.current) mapRef.current.fitBounds([[coordinates[0], coordinates[2]], [coordinates[1], coordinates[3]]], { padding: [48, 48], maxZoom: 17 });
        else pendingMapNavigation.current = { kind: 'bounds', bounds: extent, generation };
      }
    }).catch((error) => {
      if (request === searchRequest.current && error.name !== 'AbortError') setSearchError(true);
    }).finally(() => { if (request === searchRequest.current) setSearching(false); });
    return () => { controller.abort(); };
  }, [filters]);
  const handleSelectResult = useCallback((result) => {
    navigationGeneration.current += 1; pendingAddressNavigation.current = null;
    trackEvent('property_open', { entry_point: 'search' });
    rememberSearchView(result);
    setSearchOpen(false); setSelected(result);
    if (map && result.lat != null && result.lng != null) map.flyTo([Number(result.lat), Number(result.lng)], 18);
    else if (result.lat != null && result.lng != null) pendingMapNavigation.current = { kind: 'point', ...result, zoom: 18, generation: navigationGeneration.current };
  }, [map, rememberSearchView]);
  const handleSelectBusiness = useCallback(async (cadastralId) => {
    const generation = ++navigationGeneration.current;
    pendingAddressNavigation.current = null;
    try {
      const addressOnly = /^address-[a-f0-9]{24}$/.test(cadastralId || '');
      let response;
      if (addressOnly) {
        const url = new URL('./business-data.php', window.location.href);
        url.searchParams.set('action', 'address'); url.searchParams.set('id', cadastralId);
        const fetched = await fetch(url, { headers: { Accept: 'application/json' } });
        response = await fetched.json();
        if (!fetched.ok || response.error) throw new Error('Address unavailable');
      } else response = await realEstateApi.plot(cadastralId);
      if (generation !== navigationGeneration.current) return;
      const plot = addressOnly ? response.address : response.plot;
      if (!plot || (plot.cadastral_id || plot.address_id) !== cadastralId) throw new Error('Missing location');
      rememberSearchView(plot, true);
      if (searchReturn.current) searchReturn.current.business = true;
      setSelected(plot); setSearchOpen(false);
      if (map && plot.lat != null && plot.lng != null) map.flyTo([Number(plot.lat), Number(plot.lng)], 18);
      else if (plot.lat != null && plot.lng != null) pendingMapNavigation.current = { kind: 'point', ...plot, zoom: 18, generation };
    } catch {
      if (generation === navigationGeneration.current) toast({ title: lang === 'bg' ? 'Имотът не може да бъде отворен. Опитайте отново.' : 'The plot could not be opened. Please try again.', variant: 'destructive' });
    }
  }, [map, rememberSearchView, lang, toast]);
  const handleLocate = useCallback(() => {
    if (!map || !navigator.geolocation) { toast({ title: t('map.locateError'), variant: 'destructive' }); return; }
    navigator.geolocation.getCurrentPosition((position) => { const point = { lat: position.coords.latitude, lng: position.coords.longitude }; setUserLocation(point); map.flyTo([point.lat, point.lng], 17); }, () => toast({ title: t('map.locateError'), variant: 'destructive' }));
  }, [map, t, toast]);
  const handleClusterClick = useCallback((center, zoom, clusterBounds, plotCount) => {
    if (!map) return;
    trackEvent('cluster_open', { plot_count: plotCount });
    map.stop();
    const limits = ['south', 'north', 'west', 'east'].map((key) => Number(clusterBounds?.[key]));
    if (clusterBounds && limits.every(Number.isFinite) && limits[0] <= limits[1] && limits[2] <= limits[3]) {
      map.fitBounds([[limits[0], limits[2]], [limits[1], limits[3]]], { padding: [48, 48], maxZoom: zoom, animate: true });
    } else map.flyTo(center, zoom);
  }, [map]);

  const sidebar = <>
    <div className="map-sidebar-toolbar">
    <div className="map-dataset-switch" role="group" aria-label={lang === 'bg' ? 'Слой на картата' : 'Map layer'}>
      <button type="button" aria-pressed={mapDataset === 'properties'} onClick={() => changeMapDataset('properties')}><MapPin size={16} aria-hidden="true" />{lang === 'bg' ? 'Имоти' : 'Properties'}</button>
      <button type="button" aria-pressed={mapDataset === 'companies'} onClick={() => changeMapDataset('companies')}><Building2 size={16} aria-hidden="true" />{lang === 'bg' ? 'Фирми' : 'Companies'}</button>
    </div>
    {!isMobile && <button type="button" className="map-sidebar-collapse" onClick={() => setSidebarCollapsed(true)} title={lang === 'bg' ? 'Скрий панела за по-голяма карта' : 'Hide the panel for a larger map'} aria-label={lang === 'bg' ? 'Скрий страничния панел' : 'Hide the side panel'} aria-controls="map-sidebar"><PanelLeftClose size={19} aria-hidden="true" /></button>}
    </div>
    <div hidden={mapDataset !== 'companies'}><CompanyMapPanel panelRef={companyPanel} draft={businessMapDraft} onDraftChange={setBusinessMapDraft} query={businessMapQuery} level={businessMapLevel} onLevelChange={changeBusinessMapLevel} onApply={applyBusinessMapQuery} onShowAll={() => applyBusinessMapQuery('', 'all')} data={businessViewport.data} loading={businessViewport.isLoading} error={businessViewport.apiError} onRetry={businessViewport.refetch} /></div>
    <div hidden={mapDataset !== 'properties'}>
    <div className="search-mode-tabs" role="tablist" onKeyDown={handleSearchTabKeys} aria-label={lang === 'bg' ? 'Начин на търсене' : 'Search method'}>
      <button type="button" id="records-search-tab" role="tab" tabIndex={searchTab === 'records' ? 0 : -1} aria-selected={searchTab === 'records'} aria-controls="records-search-panel" onClick={() => { navigationGeneration.current += 1; pendingAddressNavigation.current = null; setAddressRequest(null); setSearchTab('records'); }}>{lang === 'bg' ? 'Търсене' : 'Search'}</button>
      <button type="button" id="address-search-tab" role="tab" tabIndex={searchTab === 'address' ? 0 : -1} aria-selected={searchTab === 'address'} aria-controls="address-search-panel" onClick={() => setSearchTab('address')}><MapPin size={14} aria-hidden="true" />{lang === 'bg' ? 'Адрес' : 'Address'}</button>
    </div>
    <div id="records-search-panel" role="tabpanel" aria-labelledby="records-search-tab" hidden={searchTab !== 'records'}>
    <SearchPanel panelRef={searchPanel} query={query} onQueryChange={handleQueryChange} onSubmit={handleSearch} onClear={handleClear} loading={searching}
      businessSearchState={businessSearchState} onBusinessSearchStateChange={setBusinessSearchState} onSelectBusiness={handleSelectBusiness}
      addressIntent={isAddressQuery(query)} onFindAddress={handleFindAddress} onSubmitAsRecords={handleRecordSearch} addressProviderLabel={addressProvider?.label}
      searchTerms={filters.searchTerms} searchMatch={filters.searchMatch} onRemoveTerm={handleRemoveTerm} onClearTerms={handleClearTerms} onSearchMatchChange={handleSearchMatchChange}
      results={(searchResponse?.items || []).map((item) => ({ ...item, secondary: t('panel.linkedRecords', { n: item.document_count }) }))}
      resultQuery={filters.searchTerms.join(' · ')} resultTotal={searchResponse?.total} resultMappedTotal={searchResponse?.mapped_total} resultUnmappedTotal={searchResponse?.unmapped_total}
      resultsTruncated={searchResponse?.truncated} searchError={searchError} onSelectResult={handleSelectResult} />
    </div>
    <div id="address-search-panel" className="address-panel-wrap" role="tabpanel" aria-labelledby="address-search-tab" hidden={searchTab !== 'address'}>
      {activeCount > 0 && <div className="address-filter-notice"><p>{lang === 'bg' ? `Картата остава ограничена от ${activeCount} активни условия за имоти.` : `The map still uses ${activeCount} active property conditions.`}</p><button onClick={clearFilters}>{lang === 'bg' ? 'Покажи всички имоти' : 'Show all properties'}</button></div>}
      {addressVisited && <AsyncPanel fallback={<div className="workspace-loading" role="status"><Loader2 size={20} className="animate-spin" />{lang === 'bg' ? 'Зареждане на търсенето по адрес…' : 'Loading address search…'}</div>}><AddressSearch onSelectLocation={handleAddressSelect} selectedLocation={addressLocation} onClearLocation={clearAddress}
        externalRequest={addressRequest} isRequestCurrent={addressRequestCurrent} onRequestHandled={addressRequestHandled} onLookupStart={addressLookupStarted} onProviderChange={setAddressProvider} /></AsyncPanel>}
    </div>
    <div ref={filterPanel}><RegisterFilters value={filters} onChange={handleFilterChange} counts={meta?.counts} options={meta?.filter_options} /></div>
    <DatasetSummary meta={meta} />
    </div>
    <nav className="sidebar-footer" aria-label={lang === 'bg' ? 'Информация за сайта' : 'Site information'}><a href="/about.html">{lang === 'bg' ? 'За данните' : 'About the data'}</a><a href="/privacy.html">{lang === 'bg' ? 'Поверителност' : 'Privacy'}</a></nav>
  </>;

  return (
    <div className="map-app">
      <AppHeader activeWorkspace={workspace} onWorkspaceChange={changeWorkspace} alertCount={marketAlertCount} />
      {marketVisited && <div className="offers-workspace-host" hidden={workspace !== 'offers'}><AsyncPanel fallback={<div className="workspace-loading" role="status"><Loader2 size={24} className="animate-spin" />{lang === 'bg' ? 'Зареждане на обявите…' : 'Loading offers…'}</div>}><MarketDashboard active={workspace === 'offers'} onBackToMap={() => changeWorkspace('map')} onAlertCountChange={setMarketAlertCount} /></AsyncPanel></div>}
      {developmentVisited && <div className="development-workspace-host" hidden={workspace !== 'activity'}><AsyncPanel fallback={<div className="workspace-loading" role="status"><Loader2 size={24} className="animate-spin" />{lang === 'bg' ? 'Зареждане на строителната активност…' : 'Loading construction activity…'}</div>}><DevelopmentDashboard onOpenPlot={openDevelopmentPlot} onOpenMap={openDevelopmentMap} onOpenOffers={() => changeWorkspace('offers')} /></AsyncPanel></div>}
      {workspace === 'map' && returnToDevelopment && <div className="development-return-bar"><button type="button" onClick={backToDevelopment}><ArrowLeft size={16} />{lang === 'bg' ? 'Обратно към строителната активност' : 'Back to construction activity'}</button><span>{lang === 'bg' ? 'Избраният период и списъкът са запазени.' : 'Your selected period and list are preserved.'}</span></div>}
      {mapVisited && <main hidden={workspace !== 'map'} className={`map-workspace ${selected ? 'has-selected' : ''}`}>
        {!isMobile && <aside id="map-sidebar" ref={sidebarScroll} className="workspace-sidebar" hidden={sidebarCollapsed} aria-label={t('search.title')}>{sidebar}</aside>}
        <div className="map-stage">
          <AsyncPanel fallback={<div className="workspace-loading" role="status"><Loader2 size={24} className="animate-spin" />{lang === 'bg' ? 'Зареждане на картата…' : 'Loading map…'}</div>}><MapView parcels={mapDataset === 'companies' ? businessViewport.parcels : parcels} dataMode={mapDataset} selectedParcel={selected} selectedKey={selected?.cadastral_id || selected?.address_id || null} hoveredKey={hoveredKey} baseLayer={baseLayer} parcelMode={mapDataset === 'companies' ? 'points' : parcelMode} bounds={bounds} filters={filters} active={workspace === 'map' && mapDataset === 'properties'} boundaryRevision={boundaryRevision} onBoundaryStatusChange={setBoundaryStatus} userLocation={userLocation} addressLocation={addressLocation} onSelect={handleSelect} onHover={setHoveredKey} onBoundsChange={setBounds} onMapReady={setMap} onClusterClick={handleClusterClick} /></AsyncPanel>
          {isMobile ? <button className="mobile-search-trigger" onClick={() => setSearchOpen(true)}><Search size={17} />{mapDataset === 'companies' ? (lang === 'bg' ? 'Фирми' : 'Companies') : t('search.mobile')}<SlidersHorizontal size={16} />{mapDataset === 'properties' && activeCount > 0 && <span className="active-filter-dot" aria-label={t('filter.activeCount', { n: activeCount })}>{activeCount}</span>}</button> : sidebarCollapsed && <button ref={sidebarOpener} type="button" className="map-context map-panel-opener" onClick={openMapPanel} aria-expanded={false} aria-controls="map-sidebar"><PanelLeft size={17} aria-hidden="true" /><span>{mapDataset === 'companies' ? (lang === 'bg' ? 'Търсене на фирми' : 'Find companies') : (lang === 'bg' ? 'Търсене и филтри' : 'Search and filters')}</span>{(mapDataset === 'companies' ? Number(Boolean(businessMapQuery)) + Number(businessMapLevel !== 'all') : activeCount) > 0 && <span className="map-panel-filter-count">{mapDataset === 'companies' ? Number(Boolean(businessMapQuery)) + Number(businessMapLevel !== 'all') : activeCount}</span>}</button>}
          <MapToolbar active={workspace === 'map'} onZoomIn={() => map?.zoomIn()} onZoomOut={() => map?.zoomOut()} onLocate={handleLocate} onReset={() => mapDataset === 'companies' ? applyBusinessMapQuery(businessMapQuery) : map?.flyTo(INITIAL_VIEW.center, INITIAL_VIEW.zoom)} baseLayer={baseLayer} onBaseLayerChange={setBaseLayer} parcelMode={parcelMode} onParcelModeChange={mapDataset === 'properties' ? changeParcelMode : undefined} />
          {mapDataset === 'companies' ? <BusinessMapStatus total={businessViewport.total} loading={!map || businessViewport.isLoading} error={businessViewport.apiError} onEdit={editFilters} onRetry={businessViewport.refetch} /> : <MapLegend count={displayCount(total, lang)} empty={total === 0} loading={!map || isLoading} truncated={truncated} apiError={apiError} filterError={filterError} parcelMode={parcelMode} boundaryStatus={boundaryStatus} onZoomIn={() => map?.zoomIn()} activeCount={activeCount} onClear={clearFilters} onEdit={editFilters} onRetry={retryMapData} />}
        </div>
        {!isMobile && selected && <aside className="workspace-details" aria-label={t('panel.title')}><AsyncPanel fallback={<div className="workspace-loading" role="status"><Loader2 size={20} className="animate-spin" />{t('panel.loading')}</div>}>{selected?.address_id ? <BusinessAddressDetails address={selected} onClose={handleCloseDetails} onBackToSearch={canReturnToSearch ? handleReturnToSearch : undefined} /> : <DetailsPanel closeOnEscape parcel={selected} onClose={handleCloseDetails} onBackToSearch={canReturnToSearch ? handleReturnToSearch : undefined} onBackToActivity={returnToDevelopment ? backToDevelopment : undefined} />}</AsyncPanel></aside>}
      </main>}
      {isMobile && workspace === 'map' && <>
        <Sheet open={searchOpen} onOpenChange={setSearchOpen}><SheetContent ref={sidebarScroll} side="bottom" className="mobile-sidebar-sheet overflow-y-auto p-0" aria-describedby={undefined}
          onOpenAutoFocus={(event) => { if (pendingSearchReturn.current) event.preventDefault(); }}
          onCloseAutoFocus={(event) => { if (searchReturn.current || returningToSearch.current) event.preventDefault(); }}><SheetTitle className="sr-only">{t('search.mobile')}</SheetTitle>{sidebar}</SheetContent></Sheet>
        <Sheet open={Boolean(selected)} onOpenChange={(open) => { if (!open) handleCloseDetails(); }}><SheetContent side="bottom" className="mobile-details-sheet overflow-hidden p-0" aria-describedby={undefined}
          onCloseAutoFocus={(event) => { if (returningToSearch.current) { event.preventDefault(); returningToSearch.current = false; } }}><SheetTitle className="sr-only">{t('panel.title')}</SheetTitle><AsyncPanel fallback={<div className="workspace-loading" role="status"><Loader2 size={20} className="animate-spin" />{t('panel.loading')}</div>}>{selected?.address_id ? <BusinessAddressDetails address={selected} onClose={handleCloseDetails} onBackToSearch={canReturnToSearch ? handleReturnToSearch : undefined} /> : <DetailsPanel parcel={selected} onClose={handleCloseDetails} onBackToSearch={canReturnToSearch ? handleReturnToSearch : undefined} onBackToActivity={returnToDevelopment ? backToDevelopment : undefined} />}</AsyncPanel></SheetContent></Sheet>
      </>}
    </div>
  );
}
