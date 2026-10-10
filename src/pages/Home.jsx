import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowUpRight, ChevronDown, MapPin, Search, ShieldCheck, SlidersHorizontal } from 'lucide-react';
import { useToast } from '@/components/ui/use-toast';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { useIsMobile } from '@/hooks/use-mobile';
import { useI18n } from '@/lib/i18n';
import { displayCount, displayDate } from '@/lib/registerUi';
import { activeFilterCount, invalidFilterDates, normalizePropertyFilters, readPropertyFilters, writePropertyFilters } from '@/lib/propertyFilters';
import { realEstateApi } from '@/api/realEstateApi';
import AppHeader from '@/components/AppHeader';
import DataNotice from '@/components/DemoNotice';
import MapView from '@/components/map/MapView';
import MapToolbar from '@/components/map/MapToolbar';
import MapLegend from '@/components/map/MapLegend';
import SearchPanel from '@/components/search/SearchPanel';
import RegisterFilters from '@/components/search/RegisterFilters';
import DetailsPanel from '@/components/details/DetailsPanel';
import useViewportParcels from '@/hooks/useViewportParcels';

const INITIAL_VIEW = { center: [42.684, 23.333], zoom: 13 };

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
          <p>{t('dataset.snapshotHelp')}</p>
        </div>
      </details>
      {latest && <p className="dataset-loaded">{t('dataset.loaded', { date: displayDate(latest, lang) })}</p>}
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
  const [hoveredKey, setHoveredKey] = useState(null);
  const [baseLayer, setBaseLayer] = useState('standard');
  const [query, setQuery] = useState('');
  const [searchedFor, setSearchedFor] = useState('');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [filters, setFilters] = useState(readPropertyFilters);
  const [meta, setMeta] = useState(null);
  const [userLocation, setUserLocation] = useState(null);
  const searchRequest = useRef(0);
  const filterPanel = useRef(null);
  const activeCount = activeFilterCount(filters);
  const { parcels, isLoading, truncated, total, apiError, filterError } = useViewportParcels(bounds, filters);

  useEffect(() => { let active = true; realEstateApi.meta().then((data) => { if (active) setMeta(data); }).catch(() => {}); return () => { active = false; }; }, []);
  useEffect(() => { writePropertyFilters(filters); }, [filters]);
  const handleSelect = useCallback((plot) => { setSelected(plot); setSearchOpen(false); }, []);
  const handleClear = useCallback(() => { searchRequest.current += 1; setQuery(''); setSearchedFor(''); setResults([]); setSearching(false); }, []);
  const handleQueryChange = useCallback((value) => { searchRequest.current += 1; setQuery(value); setSearchedFor(''); setResults([]); setSearching(false); }, []);
  const handleFilterChange = useCallback((value) => {
    searchRequest.current += 1; setFilters(normalizePropertyFilters(value)); setSearchedFor(''); setResults([]); setSearching(false); setSelected(null);
  }, []);
  const clearFilters = useCallback(() => handleFilterChange({}), [handleFilterChange]);
  const editFilters = useCallback(() => {
    if (isMobile) setSearchOpen(true);
    else filterPanel.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [isMobile]);
  const handleSearch = useCallback(async () => {
    const term = query.trim();
    if (!term) return;
    if (invalidFilterDates(filters)) { toast({ title: t('filter.dateRangeError'), variant: 'destructive' }); return; }
    const request = ++searchRequest.current;
    setSearching(true);
    try {
      const response = await realEstateApi.search(term, filters);
      if (request !== searchRequest.current) return;
      setResults((response.items || []).map((item) => ({ ...item, secondary: t('panel.linkedRecords', { n: item.document_count }) })));
      setSearchedFor(term);
    } catch (error) {
      if (request === searchRequest.current) toast({ title: t('error.request'), description: error.message, variant: 'destructive' });
    } finally { if (request === searchRequest.current) setSearching(false); }
  }, [query, filters, t, toast]);
  const handleSelectResult = useCallback((result) => {
    setQuery(result.cadastral_id); setSearchedFor(''); setResults([]); setSearchOpen(false); setSelected(result);
    if (map && result.lat != null && result.lng != null) map.flyTo([Number(result.lat), Number(result.lng)], 18);
  }, [map]);
  const handleLocate = useCallback(() => {
    if (!map || !navigator.geolocation) { toast({ title: t('map.locateError'), variant: 'destructive' }); return; }
    navigator.geolocation.getCurrentPosition((position) => { const point = { lat: position.coords.latitude, lng: position.coords.longitude }; setUserLocation(point); map.flyTo([point.lat, point.lng], 17); }, () => toast({ title: t('map.locateError'), variant: 'destructive' }));
  }, [map, t, toast]);

  const sidebar = <>
    <SearchPanel query={query} onQueryChange={handleQueryChange} onSubmit={handleSearch} onClear={handleClear} loading={searching} results={results} resultQuery={searchedFor} onSelectResult={handleSelectResult} />
    <div ref={filterPanel}><RegisterFilters value={filters} onChange={handleFilterChange} counts={meta?.counts} options={meta?.filter_options} /></div>
    <div className="map-instructions"><span><MapPin size={18} /></span><div><strong>{t('map.howTitle')}</strong><p>{t('map.howHelp')}</p></div></div>
    <DatasetSummary meta={meta} />
  </>;

  return (
    <div className="map-app">
      <AppHeader /><DataNotice />
      <main className={`map-workspace ${selected ? 'has-selected' : ''}`}>
        {!isMobile && <aside className="workspace-sidebar" aria-label={t('search.title')}>{sidebar}</aside>}
        <div className="map-stage">
          <MapView parcels={parcels} selectedParcel={selected} selectedKey={selected?.cadastral_id || null} hoveredKey={hoveredKey} baseLayer={baseLayer} userLocation={userLocation} onSelect={handleSelect} onHover={setHoveredKey} onBoundsChange={setBounds} onMapReady={setMap} onClusterClick={(center, zoom) => map?.flyTo(center, zoom)} />
          {isMobile ? <button className="mobile-search-trigger" onClick={() => setSearchOpen(true)}><Search size={17} />{t('search.mobile')}<SlidersHorizontal size={16} />{activeCount > 0 && <span className="active-filter-dot" aria-label={t('filter.activeCount', { n: activeCount })}>{activeCount}</span>}</button> : <button className="map-context" onClick={editFilters} aria-label={t('filter.edit')}><span className="context-dot" />{t('map.city')}<span className="map-context-divider" /><SlidersHorizontal size={13} />{activeCount ? t('filter.activeCount', { n: activeCount }) : t('filter.all')}</button>}
          <MapToolbar onZoomIn={() => map?.zoomIn()} onZoomOut={() => map?.zoomOut()} onLocate={handleLocate} onReset={() => map?.flyTo(INITIAL_VIEW.center, INITIAL_VIEW.zoom)} baseLayer={baseLayer} onBaseLayerChange={setBaseLayer} />
          <MapLegend count={displayCount(total, lang)} empty={total === 0} loading={isLoading} truncated={truncated} apiError={apiError} filterError={filterError} activeCount={activeCount} onClear={clearFilters} onEdit={editFilters} />
        </div>
        {!isMobile && selected && <aside className="workspace-details" aria-label={t('panel.title')}><DetailsPanel parcel={selected} onClose={() => setSelected(null)} /></aside>}
      </main>
      {isMobile && <>
        <Sheet open={searchOpen} onOpenChange={setSearchOpen}><SheetContent side="bottom" className="mobile-sidebar-sheet overflow-y-auto p-0" aria-describedby={undefined}><SheetTitle className="sr-only">{t('search.mobile')}</SheetTitle>{sidebar}</SheetContent></Sheet>
        <Sheet open={Boolean(selected)} onOpenChange={(open) => !open && setSelected(null)}><SheetContent side="bottom" className="mobile-details-sheet overflow-hidden p-0" aria-describedby={undefined}><SheetTitle className="sr-only">{t('panel.title')}</SheetTitle><DetailsPanel parcel={selected} onClose={() => setSelected(null)} /></SheetContent></Sheet>
      </>}
    </div>
  );
}
