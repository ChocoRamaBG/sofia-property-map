import React, { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowUpRight, ChevronDown, HardHat, Loader2, MapPin, Search, ShieldCheck, SlidersHorizontal } from 'lucide-react';
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
import DataNotice from '@/components/DemoNotice';
import MapView from '@/components/map/MapView';
import MapToolbar from '@/components/map/MapToolbar';
import MapLegend from '@/components/map/MapLegend';
import SearchPanel from '@/components/search/SearchPanel';
import AddressSearch from '@/components/search/AddressSearch';
import MarketDashboard, { MarketTeaser } from '@/components/market/MarketDashboard';
import RegisterFilters from '@/components/search/RegisterFilters';
import DetailsPanel from '@/components/details/DetailsPanel';
import useViewportParcels from '@/hooks/useViewportParcels';

const INITIAL_VIEW = { center: [42.684, 23.333], zoom: 13 };
const DevelopmentDashboard = lazy(() => import('@/components/development/DevelopmentDashboard'));
const readWorkspace = () => {
  const fragment = window.location.hash.slice(1);
  if (['map', 'offers', 'activity'].includes(fragment)) return fragment;
  const requested = new URLSearchParams(window.location.search).get('view');
  return ['offers', 'activity'].includes(requested) ? requested : 'map';
};

function DatasetSummary({ meta }) {
  const { t, lang } = useI18n();
  const imports = (meta?.imports || []).filter((item, index, rows) => item.source_code !== 'coordinates' && rows.findIndex((row) => row.source_code === item.source_code) === index);
  const latest = meta?.imports?.[0]?.imported_at;
  return (
    <section className="dataset-summary">
      <div className="dataset-stats"><div><strong>{meta ? displayCount(meta.counts.plots, lang) : '—'}</strong><span>{t('dataset.points')}</span></div><div><strong>{meta ? displayCount(meta.counts.documents, lang) : '—'}</strong><span>{t('dataset.records')}</span></div></div>
      <details>
        <summary><ShieldCheck size={16} /><span>{t('dataset.sources')}</span><ChevronDown size={14} /></summary>
        <div className="dataset-source-list">
          {imports.map((source) => <div key={source.source_code}><a href={source.source_url} target="_blank" rel="noreferrer">{lang === 'bg' ? source.label_bg : source.label_en}<ArrowUpRight size={13} /></a><small>{source.snapshot_date ? t('dataset.snapshot', { date: displayDate(source.snapshot_date, lang) }) : t('dataset.dateUnknown')}</small></div>)}
          {meta?.cadastre && <div><a href={meta.cadastre.source_url} target="_blank" rel="noreferrer">{lang === 'bg' ? meta.cadastre.label_bg : meta.cadastre.label_en}<ArrowUpRight size={13} /></a><small>{t('dataset.cadastreCount', { n: displayCount(meta.cadastre.parcel_count, lang) })}</small>{meta.cadastre.captured_at && <small>{t('dataset.loaded', { date: displayDate(meta.cadastre.captured_at, lang) })}</small>}</div>}
          <p>{t('dataset.snapshotHelp')}</p>
        </div>
      </details>
      {latest && <p className="dataset-loaded">{t('dataset.loaded', { date: displayDate(latest, lang) })}</p>}
      <nav className="dataset-page-links" aria-label={lang === 'bg' ? 'Информация за сайта' : 'Site information'}><a href="/about.html">{lang === 'bg' ? 'За данните и проверката' : 'About the data'}</a><a href="/privacy.html">{lang === 'bg' ? 'Поверителност' : 'Privacy'}</a></nav>
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
  const [query, setQuery] = useState('');
  const [searchResponse, setSearchResponse] = useState(null);
  const [searchError, setSearchError] = useState(false);
  const [searching, setSearching] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [filters, setFilters] = useState(readPropertyFilters);
  const [meta, setMeta] = useState(null);
  const [userLocation, setUserLocation] = useState(null);
  const [addressLocation, setAddressLocation] = useState(null);
  const [addressRequest, setAddressRequest] = useState(null);
  const [addressProvider, setAddressProvider] = useState(null);
  const [searchTab, setSearchTab] = useState('records');
  const [workspace, setWorkspace] = useState(readWorkspace);
  const [developmentVisited, setDevelopmentVisited] = useState(() => readWorkspace() === 'activity');
  const [returnToDevelopment, setReturnToDevelopment] = useState(false);
  const pendingDevelopmentPlot = useRef(null);
  const [marketAlertCount, setMarketAlertCount] = useState(0);
  const searchRequest = useRef(0);
  const addressRequestSequence = useRef(0);
  const navigationGeneration = useRef(0);
  const pendingAddressNavigation = useRef(null);
  const fitSearchResults = useRef(filters.searchTerms.length > 0);
  const mapRef = useRef(null);
  mapRef.current = map;
  const filterPanel = useRef(null);
  const searchPanel = useRef(null);
  const sidebarScroll = useRef(null);
  const searchReturn = useRef(null);
  const pendingSearchReturn = useRef(null);
  const returningToSearch = useRef(false);
  const activeCount = activeFilterCount(filters);
  const { parcels, isLoading, truncated, total, apiError, filterError, refetch: refetchViewport } = useViewportParcels(bounds, filters);

  useEffect(() => { let active = true; realEstateApi.meta().then((data) => { if (active) setMeta(data); }).catch(() => {}); return () => { active = false; }; }, []);
  useEffect(() => { writePropertyFilters(filters); }, [filters]);
  useEffect(() => {
    const update = () => {
      const next = readWorkspace();
      if (next === 'activity') setDevelopmentVisited(true);
      setWorkspace(next);
    };
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  const changeWorkspace = useCallback((next) => {
    if (!['map', 'offers', 'activity'].includes(next)) return;
    if (next === 'activity') setDevelopmentVisited(true);
    navigationGeneration.current += 1; pendingAddressNavigation.current = null; setAddressRequest(null);
    trackEvent('workspace_open', { workspace: next });
    setSearchOpen(false);
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
      const plot = pendingDevelopmentPlot.current;
      pendingDevelopmentPlot.current = null;
      if (plot?.lat != null && plot?.lng != null && Number.isFinite(Number(plot.lat)) && Number.isFinite(Number(plot.lng))) {
        map.stop(); map.setView([Number(plot.lat), Number(plot.lng)], 17, { animate: false });
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, [workspace, map]);
  const openDevelopmentPlot = useCallback((plot) => {
    if (!plot?.cadastral_id) return;
    searchReturn.current = null; pendingSearchReturn.current = null; setCanReturnToSearch(false);
    pendingDevelopmentPlot.current = plot;
    setSelected(plot); setReturnToDevelopment(true); changeWorkspace('map');
  }, [changeWorkspace]);
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
  const rememberSearchView = useCallback((plot) => {
    pendingSearchReturn.current = null;
    returningToSearch.current = false;
    if (!filters.searchTerms.length) return;
    const list = searchPanel.current?.querySelector('.search-results ul');
    if (searchReturn.current) {
      searchReturn.current.resultId = plot.cadastral_id;
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
      scrollTop: sidebarScroll.current?.scrollTop || 0,
      listScrollTop: list?.scrollTop || 0,
      resultId: plot.cadastral_id,
    };
    setCanReturnToSearch(true);
  }, [filters.searchTerms]);
  const handleReturnToSearch = useCallback(() => {
    const saved = searchReturn.current;
    if (!saved) return;
    searchReturn.current = null;
    pendingSearchReturn.current = saved;
    returningToSearch.current = true;
    setCanReturnToSearch(false); setSelected(null); setHoveredKey(null);
    if (isMobile) setSearchOpen(true);
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
      }
      sidebarScroll.current?.scrollTo({ top: saved.scrollTop, behavior: 'instant' });
      const list = searchPanel.current?.querySelector('.search-results ul');
      list?.scrollTo({ top: saved.listScrollTop, behavior: 'instant' });
      const resultButton = Array.from(list?.querySelectorAll('[data-search-result-id]') || [])
        .find((button) => button.dataset.searchResultId === saved.resultId);
      (resultButton || searchPanel.current?.querySelector('input'))?.focus({ preventScroll: true });
      if (!isMobile) returningToSearch.current = false;
    });
    return () => { window.cancelAnimationFrame(frame); };
  }, [selected, isMobile, searchOpen, map]);
  const handleSelect = useCallback((plot) => { navigationGeneration.current += 1; pendingAddressNavigation.current = null; trackEvent('property_open', { entry_point: 'map' }); rememberSearchView(plot); setSelected(plot); setSearchOpen(false); }, [rememberSearchView]);
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
    const mapTypes = ['building_permits', 'projecting_visas', 'exploitation_certificates'];
    const selectedTypes = value.type === 'all' ? mapTypes : String(value.type || '').split(',').filter((type) => mapTypes.includes(type));
    const year = /^\d{4}$/.test(String(value.year || '')) ? String(value.year) : '';
    const phrases = value.q ? [value.q] : [];
    handleFilterChange({ recordTypes: selectedTypes, match: 'any', dateFrom: value.date_from || (year ? `${year}-01-01` : ''), dateTo: value.date_to || (year ? `${year}-12-31` : ''), district: value.district || '', searchTerms: phrases });
    fitSearchResults.current = phrases.length > 0;
    setReturnToDevelopment(true); changeWorkspace('map');
    mapRef.current?.setView(INITIAL_VIEW.center, 11, { animate: false });
  }, [changeWorkspace, handleFilterChange]);
  const editFilters = useCallback(() => {
    if (isMobile) setSearchOpen(true);
    else filterPanel.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [isMobile]);
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
      if (shouldFit && generation === navigationGeneration.current && extent && coordinates.every(Number.isFinite) && coordinates[0] <= coordinates[1] && coordinates[2] <= coordinates[3]) {
        mapRef.current?.fitBounds([[coordinates[0], coordinates[2]], [coordinates[1], coordinates[3]]], { padding: [48, 48], maxZoom: 17 });
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
  }, [map, rememberSearchView]);
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
    <div className="search-mode-tabs" role="tablist" onKeyDown={handleSearchTabKeys} aria-label={lang === 'bg' ? 'Начин на търсене' : 'Search method'}>
      <button type="button" id="records-search-tab" role="tab" tabIndex={searchTab === 'records' ? 0 : -1} aria-selected={searchTab === 'records'} aria-controls="records-search-panel" onClick={() => { navigationGeneration.current += 1; pendingAddressNavigation.current = null; setAddressRequest(null); setSearchTab('records'); }}>{lang === 'bg' ? 'Търсене' : 'Search'}</button>
      <button type="button" id="address-search-tab" role="tab" tabIndex={searchTab === 'address' ? 0 : -1} aria-selected={searchTab === 'address'} aria-controls="address-search-panel" onClick={() => setSearchTab('address')}><MapPin size={14} aria-hidden="true" />{lang === 'bg' ? 'Адрес' : 'Address'}</button>
    </div>
    <div id="records-search-panel" role="tabpanel" aria-labelledby="records-search-tab" hidden={searchTab !== 'records'}>
    <SearchPanel panelRef={searchPanel} query={query} onQueryChange={handleQueryChange} onSubmit={handleSearch} onClear={handleClear} loading={searching}
      addressIntent={isAddressQuery(query)} onFindAddress={handleFindAddress} onSubmitAsRecords={handleRecordSearch} addressProviderLabel={addressProvider?.label}
      searchTerms={filters.searchTerms} searchMatch={filters.searchMatch} onRemoveTerm={handleRemoveTerm} onClearTerms={handleClearTerms} onSearchMatchChange={handleSearchMatchChange}
      results={(searchResponse?.items || []).map((item) => ({ ...item, secondary: t('panel.linkedRecords', { n: item.document_count }) }))}
      resultQuery={filters.searchTerms.join(' · ')} resultTotal={searchResponse?.total} resultMappedTotal={searchResponse?.mapped_total} resultUnmappedTotal={searchResponse?.unmapped_total}
      resultsTruncated={searchResponse?.truncated} searchError={searchError} onSelectResult={handleSelectResult} />
    </div>
    <div id="address-search-panel" className="address-panel-wrap" role="tabpanel" aria-labelledby="address-search-tab" hidden={searchTab !== 'address'}>
      {activeCount > 0 && <div className="address-filter-notice"><p>{lang === 'bg' ? `Картата остава ограничена от ${activeCount} активни условия за имоти.` : `The map still uses ${activeCount} active property conditions.`}</p><button onClick={clearFilters}>{lang === 'bg' ? 'Покажи всички имоти' : 'Show all properties'}</button></div>}
      <AddressSearch onSelectLocation={handleAddressSelect} selectedLocation={addressLocation} onClearLocation={clearAddress}
        externalRequest={addressRequest} isRequestCurrent={addressRequestCurrent} onRequestHandled={addressRequestHandled} onLookupStart={addressLookupStarted} onProviderChange={setAddressProvider} />
    </div>
    <button type="button" className="development-map-teaser" onClick={() => changeWorkspace('activity')}><span className="development-teaser-icon"><HardHat size={21} /></span><span><strong>{lang === 'bg' ? 'Нови разрешения и проекти' : 'New permits & projects'}</strong><small>{lang === 'bg' ? 'Документи, възложители и активност по период' : 'Documents, contracting parties & activity by period'}</small></span><ArrowUpRight size={17} /></button>
    <div ref={filterPanel}><RegisterFilters value={filters} onChange={handleFilterChange} counts={meta?.counts} options={meta?.filter_options} /></div>
    <div className="map-market-discovery"><MarketTeaser onOpen={() => changeWorkspace('offers')} alertCount={marketAlertCount} /></div>
    <div className="map-instructions"><span><MapPin size={18} /></span><div><strong>{t('map.howTitle')}</strong><p>{t('map.howHelp')}</p></div></div>
    <DatasetSummary meta={meta} />
  </>;

  return (
    <div className="map-app">
      <AppHeader activeWorkspace={workspace} onWorkspaceChange={changeWorkspace} alertCount={marketAlertCount} />
      {workspace === 'map' && <DataNotice />}
      <div className="offers-workspace-host" hidden={workspace !== 'offers'}><MarketDashboard onBackToMap={() => changeWorkspace('map')} onAlertCountChange={setMarketAlertCount} /></div>
      {developmentVisited && <div className="development-workspace-host" hidden={workspace !== 'activity'}><Suspense fallback={<div className="workspace-loading" role="status"><Loader2 size={24} className="animate-spin" />{lang === 'bg' ? 'Зареждане на строителната активност…' : 'Loading construction activity…'}</div>}><DevelopmentDashboard onOpenPlot={openDevelopmentPlot} onOpenMap={openDevelopmentMap} onOpenOffers={() => changeWorkspace('offers')} /></Suspense></div>}
      {workspace === 'map' && returnToDevelopment && <div className="development-return-bar"><button type="button" onClick={backToDevelopment}><ArrowLeft size={16} />{lang === 'bg' ? 'Обратно към строителната активност' : 'Back to construction activity'}</button><span>{lang === 'bg' ? 'Избраният период и списъкът са запазени.' : 'Your selected period and list are preserved.'}</span></div>}
      <main hidden={workspace !== 'map'} className={`map-workspace ${selected ? 'has-selected' : ''}`}>
        {!isMobile && <aside ref={sidebarScroll} className="workspace-sidebar" aria-label={t('search.title')}>{sidebar}</aside>}
        <div className="map-stage">
          <MapView parcels={parcels} selectedParcel={selected} selectedKey={selected?.cadastral_id || null} hoveredKey={hoveredKey} baseLayer={baseLayer} userLocation={userLocation} addressLocation={addressLocation} onSelect={handleSelect} onHover={setHoveredKey} onBoundsChange={setBounds} onMapReady={setMap} onClusterClick={handleClusterClick} />
          {isMobile ? <button className="mobile-search-trigger" onClick={() => setSearchOpen(true)}><Search size={17} />{t('search.mobile')}<SlidersHorizontal size={16} />{activeCount > 0 && <span className="active-filter-dot" aria-label={t('filter.activeCount', { n: activeCount })}>{activeCount}</span>}</button> : <button className="map-context" onClick={editFilters} aria-label={t('filter.edit')}><span className="context-dot" />{t('map.city')}<span className="map-context-divider" /><SlidersHorizontal size={13} />{activeCount ? t('filter.activeCount', { n: activeCount }) : t('filter.all')}</button>}
          <MapToolbar onZoomIn={() => map?.zoomIn()} onZoomOut={() => map?.zoomOut()} onLocate={handleLocate} onReset={() => map?.flyTo(INITIAL_VIEW.center, INITIAL_VIEW.zoom)} baseLayer={baseLayer} onBaseLayerChange={setBaseLayer} />
          <MapLegend count={displayCount(total, lang)} empty={total === 0} loading={isLoading} truncated={truncated} apiError={apiError} filterError={filterError} activeCount={activeCount} onClear={clearFilters} onEdit={editFilters} onRetry={() => refetchViewport()} />
        </div>
        {!isMobile && selected && <aside className="workspace-details" aria-label={t('panel.title')}><DetailsPanel parcel={selected} onClose={handleCloseDetails} onBackToSearch={canReturnToSearch ? handleReturnToSearch : undefined} onBackToActivity={returnToDevelopment ? backToDevelopment : undefined} /></aside>}
      </main>
      {isMobile && workspace === 'map' && <>
        <Sheet open={searchOpen} onOpenChange={setSearchOpen}><SheetContent ref={sidebarScroll} side="bottom" className="mobile-sidebar-sheet overflow-y-auto p-0" aria-describedby={undefined}
          onOpenAutoFocus={(event) => { if (pendingSearchReturn.current) event.preventDefault(); }}
          onCloseAutoFocus={(event) => { if (searchReturn.current || returningToSearch.current) event.preventDefault(); }}><SheetTitle className="sr-only">{t('search.mobile')}</SheetTitle>{sidebar}</SheetContent></Sheet>
        <Sheet open={Boolean(selected)} onOpenChange={(open) => { if (!open) handleCloseDetails(); }}><SheetContent side="bottom" className="mobile-details-sheet overflow-hidden p-0" aria-describedby={undefined}
          onCloseAutoFocus={(event) => { if (returningToSearch.current) { event.preventDefault(); returningToSearch.current = false; } }}><SheetTitle className="sr-only">{t('panel.title')}</SheetTitle><DetailsPanel parcel={selected} onClose={handleCloseDetails} onBackToSearch={canReturnToSearch ? handleReturnToSearch : undefined} onBackToActivity={returnToDevelopment ? backToDevelopment : undefined} /></SheetContent></Sheet>
      </>}
    </div>
  );
}
