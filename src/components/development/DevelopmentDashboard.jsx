import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowRight, ArrowUpRight, BarChart3, Bookmark, Building2, CalendarDays, Check, ChevronDown, ChevronLeft, ChevronRight, Clipboard, ExternalLink, FileText, Filter, Info, Layers3, Loader2, MapPin, RefreshCw, Search, ShieldCheck, SlidersHorizontal, X } from 'lucide-react';
import { Bar, CartesianGrid, Cell, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useI18n } from '@/lib/i18n';
import { REGISTER_COLORS } from '@/lib/registerUi';
import { developmentApi } from '@/api/developmentApi';
import { marketApi } from '@/api/marketApi';
import { DOCUMENT_TYPE_ICONS as TYPE_ICONS } from '@/components/DocumentTypeIcon';
import TransactionsContext from './TransactionsContext';
import './DevelopmentDashboard.css';

const STATE_KEY = 'sofiapermits-development-view-v1';
const SAVED_KEY = 'sofiapermits-development-saved-v1';
const TYPES = ['building_permits', 'projecting_visas', 'exploitation_certificates', 'exploitation_certificates_legacy'];
const DEFAULT = { type: 'building_permits', year: '', date_from: '', date_to: '', district: '', investor: 'any', q: '', period: 'month' };
const COLORS = { ...REGISTER_COLORS, exploitation_certificates_legacy: '#477564' };
const TYPE_TEXT = {
  building_permits: ['Разрешения за строеж', 'Building permits'],
  projecting_visas: ['Визи за проектиране', 'Design visas'],
  exploitation_certificates: ['Въвеждане в експлоатация', 'Commissioning certificates'],
  exploitation_certificates_legacy: ['Архивни удостоверения', 'Archived certificates'],
};
const TYPE_SHORT = { building_permits: ['Разрешения', 'Permits'], projecting_visas: ['Визи', 'Visas'], exploitation_certificates: ['Удостоверения', 'Certificates'], exploitation_certificates_legacy: ['Архив', 'Archive'] };
function storedState() {
  const query = new URLSearchParams(window.location.search);
  const requestedTab = query.get('view') === 'activity' && ['documents', 'activity', 'market'].includes(query.get('tab')) ? query.get('tab') : null;
  try {
    const saved = JSON.parse(sessionStorage.getItem(STATE_KEY));
    if (saved?.filters && typeof saved.filters === 'object') return { view: requestedTab || (['documents', 'activity', 'market'].includes(saved.view) ? saved.view : 'documents'), filters: { ...DEFAULT, ...Object.fromEntries(Object.entries(saved.filters).filter(([key, value]) => key in DEFAULT && typeof value === 'string')) }, offset: Math.floor(Math.max(0, Math.min(1992, Number(saved.offset) || 0)) / 12) * 12 };
  } catch { /* Session storage may be disabled. */ }
  return { filters: { ...DEFAULT }, offset: 0, view: requestedTab || 'documents' };
}
function storedShortlist() { try { const value = JSON.parse(localStorage.getItem(SAVED_KEY)); return Array.isArray(value) ? [...new Set(value.filter((id) => typeof id === 'string' && /^[a-f0-9]{64}$/.test(id)))].slice(-200) : []; } catch { return []; } }
function number(value, lang, digits = 0) { return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)) ? new Intl.NumberFormat(lang === 'bg' ? 'bg-BG' : 'en-GB', { maximumFractionDigits: digits }).format(Number(value)) : '—'; }
function date(value, lang) { const stamp = value ? Date.parse(value) : NaN; return Number.isFinite(stamp) ? new Intl.DateTimeFormat(lang === 'bg' ? 'bg-BG' : 'en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Europe/Sofia' }).format(stamp) : '—'; }
function safeUrl(value) { try { const url = new URL(value); return !url.username && !url.password && (url.protocol === 'https:' || url.protocol === 'http:') ? url.href : ''; } catch { return ''; } }
function scrollToSection(ref) {
  const target = ref.current;
  if (!target) return;
  target.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
}
function currentSofiaDate() { const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Sofia', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date()).map(({ type, value }) => [type, value])); return `${parts.year}-${parts.month}-${parts.day}`; }
function emptyShortlist(data) {
  return { ...(data || {}), items: [], periods: [], bounds: null, totals: { documents: 0, observations: 0, linked_plots: 0, mapped_plots: 0, dated_documents: 0, unknown_date_documents: 0 }, pagination: { offset: 0, total: 0, has_more: false } };
}
function periodLabel(value, lang, compact = false) {
  if (/^\d{4}$/.test(value || '')) return value;
  if (/^\d{4}-Q[1-4]$/.test(value || '')) return value.replace('-Q', lang === 'bg' ? ' · Т' : ' · Q');
  const stamp = Date.parse(`${value}-01T12:00:00Z`);
  return Number.isFinite(stamp) ? new Intl.DateTimeFormat(lang === 'bg' ? 'bg-BG' : 'en-GB', { month: compact ? 'short' : 'long', year: 'numeric', timeZone: 'Europe/Sofia' }).format(stamp) : value;
}
function periodRange(period) {
  if (/^\d{4}$/.test(period)) return [`${period}-01-01`, `${period}-12-31`];
  if (!/^\d{4}-\d{2}$/.test(period)) return null;
  const [year, month] = period.split('-').map(Number);
  return [`${period}-01`, `${period}-${String(new Date(Date.UTC(year, month, 0)).getUTCDate()).padStart(2, '0')}`];
}
function calendarRows(observations, yearly = false, limit = 36) {
  const existing = new Map(observations.map((row) => [row.period, row]));
  const keys = [...existing.keys()].sort();
  if (!keys.length) return [];
  const rows = [];
  let cursor = keys[keys.length - 1];
  while (cursor >= keys[0] && rows.length < limit) {
    rows.unshift(existing.get(cursor) || { period: cursor, observed: false, partial: false, total: null, document_count: null });
    if (yearly) cursor = String(Number(cursor) - 1);
    else { const [year, month] = cursor.split('-').map(Number); cursor = month === 1 ? `${year - 1}-12` : `${year}-${String(month - 1).padStart(2, '0')}`; }
  }
  return rows;
}
function headlineMarket(summary) {
  const totals = summary?.totals || {};
  if ((totals.headline_priced_count || 0) > 0) return { ...totals, priced_count: totals.headline_priced_count, vat_basis: totals.headline_vat_basis || 'included' };
  return (totals.by_vat_basis || []).find((row) => row.vat_basis === 'unknown' && row.priced_count > 0) || totals;
}
function ChartTooltip({ active, payload, label, lang, pick, price = false }) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload || {};
  return <div className="development-chart-tooltip"><strong>{periodLabel(label, lang)}</strong>{row.partial && <em>{pick('Непълен период', 'Partial period')}</em>}{payload.filter((item) => item.value !== null && item.value !== undefined).map((item) => <span key={item.dataKey}><i style={{ background: item.color }} /><span>{item.name}</span><b>{number(item.value, lang, price && item.dataKey === 'asking' ? 1 : 0)}{item.dataKey === 'asking' ? ' €/m²' : ''}</b></span>)}{row.asking_captured_at && <small>{pick('Офертна снимка:', 'Asking-price snapshot:')} {date(row.asking_captured_at, lang)}</small>}</div>;
}

function ActivityChart({ data, filters, lang, pick, onPeriod }) {
  const [table, setTable] = useState(false);
  const [chartWindow, setChartWindow] = useState('36');
  const selected = filters.type === 'all' ? TYPES : filters.type.split(',').filter((type) => TYPES.includes(type));
  const yearly = filters.period === 'year';
  const allRows = calendarRows(data.periods || [], yearly, 1200);
  const rows = chartWindow === 'all' ? allRows : allRows.slice(-Number(chartWindow));
  return <section className="development-panel development-activity-chart" aria-labelledby="development-series-title">
    <div className="development-section-heading"><div><p className="development-eyebrow">{pick('По дата на издаване', 'By issue date')}</p><h2 id="development-series-title">{pick('Как се движи строителната активност', 'How construction activity changes')}</h2><p>{pick('Изберете колона, за да отворите документите за периода. Датата на издаване е различна от датата на обновяване на набора.', 'Select a bar to open that period’s documents. Issue date differs from the dataset update date.')}</p></div><div className="development-chart-controls"><label><span>{pick('Обхват на графиката', 'Chart window')}</span><select value={chartWindow} onChange={(event) => setChartWindow(event.target.value)}><option value="12">{pick('Последните 12 периода', 'Last 12 periods')}</option><option value="36">{pick('Последните 36 периода', 'Last 36 periods')}</option><option value="120">{pick('Последните 120 периода', 'Last 120 periods')}</option><option value="all">{pick('Цялата налична история', 'All available history')}</option></select></label><button type="button" className="development-button is-quiet" aria-expanded={table} onClick={() => setTable(!table)}><Layers3 size={15} />{pick(table ? 'Скрий таблицата' : 'Данните в таблица', table ? 'Hide table' : 'Data table')}</button></div></div>
    {rows.length ? <><div className="development-chart" role="img" aria-label={pick('Брой документи по период; таблицата и изборът на период са достъпни под графиката.', 'Documents by period; an accessible table and period selector are available below.')}><ResponsiveContainer width="100%" height="100%"><ComposedChart data={rows} margin={{ top: 12, right: 10, left: -16, bottom: 12 }}><CartesianGrid strokeDasharray="3 5" vertical={false} stroke="#e4eae5" /><XAxis dataKey="period" tickFormatter={(value) => periodLabel(value, lang, true)} tick={{ fill: '#6c8079', fontSize: 10 }} axisLine={false} tickLine={false} minTickGap={25} /><YAxis allowDecimals={false} tick={{ fill: '#6c8079', fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip cursor={{ fill: '#eef4ef' }} content={<ChartTooltip lang={lang} pick={pick} />} />{selected.map((type) => <Bar key={type} dataKey={type} name={TYPE_SHORT[type][lang === 'bg' ? 0 : 1]} stackId="documents" fill={COLORS[type]} maxBarSize={43} onClick={(entry) => entry.observed !== false && onPeriod(entry.period, type)} cursor="pointer">{rows.map((row) => <Cell key={row.period} fillOpacity={row.partial ? 0.45 : 1} />)}</Bar>)}</ComposedChart></ResponsiveContainer></div><div className="development-chart-bottom"><div className="development-chart-legend">{selected.map((type) => <span key={type}><i style={{ background: COLORS[type] }} />{TYPE_SHORT[type][lang === 'bg' ? 0 : 1]}</span>)}</div><label className="development-period-picker"><span>{pick('Отвори период', 'Open period')}</span><select value="" onChange={(event) => event.target.value && onPeriod(event.target.value)}><option value="">{pick('Изберете…', 'Select…')}</option>{[...rows].reverse().filter((row) => row.observed !== false).map((row) => <option key={row.period} value={row.period}>{periodLabel(row.period, lang)}{row.partial ? pick(' · непълен', ' · partial') : ''}</option>)}</select></label></div>{table && <div className="development-table-scroll"><table className="development-period-table"><thead><tr><th scope="col">{pick('Период', 'Period')}</th>{selected.map((type) => <th scope="col" key={type}>{TYPE_SHORT[type][lang === 'bg' ? 0 : 1]}</th>)}<th scope="col">{pick('Общо', 'Total')}</th></tr></thead><tbody>{[...rows].reverse().map((row) => <tr key={row.period}><th scope="row"><button type="button" disabled={row.observed === false} onClick={() => onPeriod(row.period)}>{periodLabel(row.period, lang)}{row.partial && <small>{pick('Непълен период', 'Partial period')}</small>}{row.observed === false && <small>{pick('Няма налично наблюдение', 'No available observation')}</small>}</button></th>{selected.map((type) => <td key={type}>{number(row[type], lang)}</td>)}<td>{number(row.total, lang)}</td></tr>)}</tbody></table></div>}</> : <div className="development-empty"><BarChart3 size={24} /><p>{pick('Няма документи с разпознаваема дата за тези условия.', 'No documents with a recognizable issue date match these conditions.')}</p></div>}
    {rows.length < allRows.length && <p className="development-footnote">{pick('Показани периоди:', 'Periods shown:')} {rows.length} / {allRows.length}. {pick('За по-ранни години променете обхвата на графиката или филтъра за година.', 'For earlier years change the chart window or the year filter.')}</p>}<p className="development-footnote"><Info size={14} />{pick('Светлите колони обозначават непълен период. Показани са налични регистрови наблюдения, а не доказателство за пълен обем строителство. Липсващ месец не означава нулева активност. Непълните периоди не участват в сравнението.', 'Lighter bars indicate a partial period. Available register observations do not establish the full volume of construction. A missing month does not mean zero activity. Partial periods are excluded from comparisons.')}</p>
  </section>;
}

function ConstructionContext({ construction, lang, pick }) {
  const series = Array.isArray(construction?.series) ? construction.series.filter((row) => /^\d{4}-Q[1-4]$/.test(row.period || '')).sort((a, b) => a.period.localeCompare(b.period)) : [];
  const latest = series[series.length - 1];
  if (!latest || construction?.status !== 'available') return null;
  const previous = series.find((row) => row.period === `${Number(latest.period.slice(0, 4)) - 1}${latest.period.slice(4)}`);
  const groups = [{ key: 'permitted', bg: 'Разрешено жилищно строителство', en: 'Permitted residential construction' }, { key: 'started', bg: 'Започнато жилищно строителство', en: 'Residential construction started' }];
  const metrics = [{ key: 'buildings', bg: 'Сгради', en: 'Buildings' }, { key: 'dwellings', bg: 'Жилища', en: 'Dwellings' }, { key: 'floor_area_m2', bg: 'РЗП', en: 'Floor area', unit: ' m²' }];
  function yoy(group, metric) {
    const now = latest[group]?.[metric];
    const before = previous?.[group]?.[metric];
    return typeof now === 'number' && Number.isFinite(now) && typeof before === 'number' && Number.isFinite(before) && before > 0 ? (now / before - 1) * 100 : null;
  }
  const divergences = groups.flatMap((group) => {
    const buildings = yoy(group.key, 'buildings');
    const dwellings = yoy(group.key, 'dwellings');
    const area = yoy(group.key, 'floor_area_m2');
    if (buildings === null) return [];
    if (buildings < 0 && ((dwellings !== null && dwellings > 0) || (area !== null && area > 0))) return [{ group, down: true }];
    if (buildings > 0 && ((dwellings !== null && dwellings < 0) || (area !== null && area < 0))) return [{ group, down: false }];
    return [];
  });
  return <section className="development-construction" aria-labelledby="development-construction-title">
    <div className="development-construction-heading"><div><p className="development-eyebrow">{pick('НСИ · ОБЛАСТ СОФИЯ (СТОЛИЦА)', 'NSI · SOFIA CAPITAL PROVINCE')}</p><h3 id="development-construction-title">{pick('Колко жилища стоят зад броя сгради?', 'How many dwellings sit behind the building count?')}</h3><p>{pick('Официални тримесечни обеми на новото жилищно строителство. Отделна статистика за цялата област София (столица); филтрите за документи по-горе не я ограничават.', 'Official quarterly volumes of new residential construction for the entire Sofia-city district. This separate series is not narrowed by the document filters above.')}</p></div><span>{periodLabel(latest.period, lang)}</span></div>
    <div className="development-construction-grid">{groups.map((group) => <article key={group.key}><h4>{pick(group.bg, group.en)}</h4><dl>{metrics.map((metric) => { const change = yoy(group.key, metric.key); return <div key={metric.key}><dt>{pick(metric.bg, metric.en)}</dt><dd><strong>{number(latest[group.key]?.[metric.key], lang)}{metric.unit && <small>{metric.unit}</small>}</strong><span>{change === null ? pick('Няма съпоставима годишна база', 'No comparable year-earlier base') : `${change > 0 ? '+' : ''}${number(change, lang, 1)}% ${pick('на годишна база', 'year on year')}`}</span></dd></div>; })}</dl></article>)}</div>
    {divergences.length > 0 && <div className="development-volume-insight"><strong><Layers3 size={15} />{pick('Какво показва сравнението с година по-рано', 'What the year-on-year comparison shows')}</strong>{divergences.map(({ group, down }) => <p key={group.key}><b>{pick(group.bg, group.en)}: </b>{down ? pick('По-малко сгради, но повече жилища или РЗП. Спадът в броя на сградите не означава спад в целия строителен обем.', 'Fewer buildings, but more dwellings or floor area. A fall in building count does not mean every measure of construction volume has fallen.') : pick('Повече сгради, но спад при жилищата или РЗП. Ръстът в броя на сградите не означава ръст във всички мерки на предлагането.', 'More buildings, but fewer dwellings or less floor area. A rise in building count does not mean every measure of supply has risen.')}</p>)}</div>}
    <p className="development-footnote"><Info size={14} />{pick('Сравнявайте и жилищата, и РЗП: по-малко сгради могат да съдържат повече жилища. Разрешеното строителство е потенциален обем; започнатото е отделен наблюдаван етап. Нито един показател сам не определя бъдещата цена.', 'Compare dwellings and floor area as well: fewer buildings can contain more homes. Permitted construction is potential volume; starts are a separately observed stage. No single measure determines future prices.')}</p>
    <details className="development-construction-history"><summary>{pick('Тримесечна история и официални източници', 'Quarterly history and official sources')}<ChevronDown size={15} /></summary><div className="development-table-scroll"><table className="development-period-table"><caption>{pick('Ново жилищно строителство · София (столица)', 'New residential construction · Sofia city')}</caption><thead><tr><th scope="col" rowSpan={2}>{pick('Период', 'Period')}</th>{groups.map((group) => <th scope="colgroup" colSpan={3} key={group.key}>{pick(group.bg, group.en)}</th>)}</tr><tr>{groups.flatMap((group) => metrics.map((metric) => <th scope="col" key={`${group.key}-${metric.key}`}>{pick(metric.bg, metric.en)}{metric.unit || ''}</th>))}</tr></thead><tbody>{[...series].reverse().map((row) => <tr key={row.period}><th scope="row">{periodLabel(row.period, lang)}</th>{groups.flatMap((group) => metrics.map((metric) => <td key={`${group.key}-${metric.key}`}>{number(row[group.key]?.[metric.key], lang)}</td>))}</tr>)}</tbody></table></div><div className="development-construction-sources">{(construction.sources || []).filter((source) => safeUrl(source.page_url || source.url)).map((source, index) => <a key={`${source.kind || index}-${source.url}`} className="development-source-link" href={safeUrl(source.page_url || source.url)} target="_blank" rel="noreferrer">{source.name || pick('НСИ · Официална таблица', 'NSI · Official table')}<ExternalLink size={13} /></a>)}</div>{lang === 'bg' && (construction.notes || []).map((note, index) => <p className="development-footnote" key={index}>{note}</p>)}<p className="development-footnote">{pick('Публикувано:', 'Published:')} {date(construction.published_at, lang)} · {pick('Извлечено:', 'Retrieved:')} {date(construction.retrieved_at, lang)}</p></details>
  </section>;
}

function MarketContext({ market, housing, activity, lang, pick, onOpenOffers }) {
  function openSalesStatistics(event) {
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const target = document.getElementById('sales-statistics');
    if (!target) return;
    event.preventDefault();
    const url = new URL(window.location.href);
    url.searchParams.set('view', 'activity'); url.searchParams.set('tab', 'market'); url.searchParams.set('section', 'transactions');
    window.history.replaceState(window.history.state, '', url.pathname + url.search + url.hash);
    target.scrollIntoView({ block: 'start', behavior: 'auto' }); target.focus({ preventScroll: true });
  }
  const metric = headlineMarket(market.data);
  const captures = Array.isArray(market.data?.history?.series) ? market.data.history.series : [];
  const marketPeriods = useMemo(() => {
    const grouped = new Map();
    for (const point of captures) {
      const month = point.captured_at?.slice(0, 7);
      if (!/^\d{4}-\d{2}$/.test(month || '') || point.median_eur_per_sqm === null || !Number.isFinite(Number(point.median_eur_per_sqm))) continue;
      const old = grouped.get(month);
      if (!old || point.captured_at > old.asking_captured_at) grouped.set(month, { period: month, asking: Number(point.median_eur_per_sqm), asking_captured_at: point.captured_at });
    }
    return grouped;
  }, [captures]);
  const combined = useMemo(() => {
    const periods = new Map((activity.periods || []).map((row) => [row.period, { ...row, document_count: row.total }]));
    if (activity.filters?.period !== 'year') for (const [key, value] of marketPeriods) periods.set(key, { ...(periods.get(key) || { period: key, document_count: null }), ...value });
    return calendarRows([...periods.values()], activity.filters?.period === 'year', 36);
  }, [activity, marketPeriods]);
  const hasPriceHistory = marketPeriods.size >= 2 && activity.filters?.period !== 'year';
  const housingData = housing.data;
  const housingSeries = Array.isArray(housingData?.series) ? housingData.series : [];
  const latestHousing = housingSeries[housingSeries.length - 1];
  const historySpan = captures.length > 1 ? (Date.parse(captures[captures.length - 1].captured_at) - Date.parse(captures[0].captured_at)) / 86400000 : 0;
  return <section className="development-panel development-market-context" aria-labelledby="development-market-title">
    <p className="development-inline-note"><a className="development-button is-quiet" href="/?view=activity&tab=market&section=transactions" onClick={openSalesStatistics}><BarChart3 size={16} aria-hidden="true" />{pick('Вписани продажби и ипотеки', 'Registered sales and mortgages')}<ArrowRight size={14} aria-hidden="true" /></a></p>
    <div className="development-section-heading"><div><p className="development-eyebrow">{pick('Предлагане + пазар', 'Supply + market')}</p><h2 id="development-market-title">{pick('Строителство и цени', 'Construction and prices')}</h2><p>{pick('Разрешенията описват потенциален бъдещ обем. Офертите описват заявени цени днес. Те измерват различни неща.', 'Permits describe potential future supply. Listings describe asking prices today. They measure different things.')}</p></div>{onOpenOffers && <button type="button" className="development-button" onClick={onOpenOffers}>{pick('Към пазарните данни', 'Open market data')}<ArrowRight size={15} /></button>}</div>
    <p className="development-footnote development-market-scope">{pick('Офертният контекст обхваща апартаментите в София и населените места от каталога на източника; не се ограничава от филтрите за строителни документи. Това са офертни цени, а не цени по сделки.', 'The asking-price context covers apartments in Sofia and settlements in the source catalogue; construction-document filters do not constrain it. These are asking prices, not transaction prices.')}</p><div className="development-market-grid"><article className="development-market-stat"><span>{pick('Текуща офертна медиана', 'Current asking-price median')}</span>{market.loading ? <Loader2 className="animate-spin" size={19} /> : market.error ? <p>{pick('Пазарният набор временно не е достъпен.', 'Market data is temporarily unavailable.')}</p> : <><strong>{number(metric.median_eur_per_sqm, lang)}<small> €/m²</small></strong><p>{number(metric.priced_count, lang)} {pick('обяви с цена', 'priced listings')} · {metric.vat_basis === 'unknown' ? pick('ДДС не е посочен', 'VAT not stated') : pick('ДДС включен / не се начислява', 'VAT included / not charged')}</p><small>{pick('Снимка:', 'Captured:')} {date(market.data?.captured_at, lang)}</small></>}</article><article className="development-market-stat"><span>{pick('История на офертните снимки', 'Asking-price snapshot history')}</span><strong>{number(captures.length, lang)}<small> {pick('наблюдения', 'observations')}</small></strong><p>{captures.length > 1 ? `${date(captures[0].captured_at, lang)} – ${date(captures[captures.length - 1].captured_at, lang)}` : pick('Начална отправна база', 'Initial baseline')}</p><small>{pick('Промяната на извадката също променя медианата.', 'Changes in the sample also change the median.')}</small></article></div>
    {hasPriceHistory ? <div className="development-comparison-chart"><div className="development-axis-labels"><span>{pick('Лява ос: брой избрани документи', 'Left axis: selected documents')}</span><span>{pick('Дясна ос: офертна медиана €/m²', 'Right axis: asking median €/m²')}</span></div><div className="development-chart"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={combined} margin={{ top: 15, right: 12, left: -12, bottom: 10 }}><CartesianGrid strokeDasharray="3 5" vertical={false} stroke="#e4eae5" /><XAxis dataKey="period" tickFormatter={(value) => periodLabel(value, lang, true)} tick={{ fill: '#6c8079', fontSize: 10 }} tickLine={false} axisLine={false} minTickGap={30} /><YAxis yAxisId="documents" allowDecimals={false} tick={{ fill: '#287d68', fontSize: 10 }} tickLine={false} axisLine={false} /><YAxis yAxisId="price" orientation="right" tick={{ fill: '#b48534', fontSize: 10 }} tickLine={false} axisLine={false} /><Tooltip content={<ChartTooltip lang={lang} pick={pick} price />} /><Bar yAxisId="documents" dataKey="document_count" name={pick('Документи', 'Documents')} fill="#bad3c7" maxBarSize={36} /><Line yAxisId="price" dataKey="asking" name={pick('Офертна медиана', 'Asking median')} stroke="#b48534" strokeWidth={2} connectNulls={false} dot={{ r: 4, fill: '#b48534' }} /></ComposedChart></ResponsiveContainer></div><p className="development-footnote">{pick('Във всеки месец е показана само последната налична завършена офертна снимка. Цени не се попълват за липсващи месеци. Съпоставянето не установява причинност.', 'Each month shows only its last available completed asking-price snapshot. Missing months are not filled. The comparison does not establish causality.')}</p></div> : <p className="development-inline-note"><Info size={16} />{activity.filters?.period === 'year' ? pick('Изберете групиране по месеци за съпоставка с кратката офертна история. Не обобщаваме няколко дни обяви като годишна цена.', 'Select monthly grouping to compare with the short asking-price history. A few days of listings are not aggregated into an annual price.') : pick('Все още няма поне два различни месеца с офертни наблюдения за времева съпоставка. Текущата медиана не се пренася назад в миналото.', 'At least two distinct months of asking-price observations are needed for a time comparison. Today’s median is not carried back into the past.')}</p>}
    {housingSeries.length > 0 && <details className="development-housing"><summary><BarChart3 size={17} /><span>{pick('Официални жилищни цени · НСИ · София', 'Official housing prices · NSI · Sofia')}</span>{latestHousing && <strong>{latestHousing.period}{typeof latestHousing.yoy_pct === 'number' && <> · {latestHousing.yoy_pct > 0 ? '+' : ''}{number(latestHousing.yoy_pct, lang, 1)}% {pick('год.', 'YoY')}</>}</strong>}<ChevronDown size={16} /></summary><p>{pick('Тримесечен индекс по реални сделки; отделен от офертните €/м². Не попълваме стойности между тримесечията.', 'Quarterly index of completed transactions, separate from asking €/m². We do not fill values between quarters.')} {housingData.base_label || housingData.base || ''}</p>{latestHousing && <div className="development-housing-latest"><span>{pick('Последно тримесечие', 'Latest quarter')} <strong>{latestHousing.period}{latestHousing.provisional ? '*' : ''}</strong></span><span>{pick('Индекс', 'Index')} <strong>{number(latestHousing.index, lang, 2)}</strong></span><span>{pick('Спрямо предходното тримесечие', 'Quarter on quarter')} <strong>{latestHousing.qoq_pct > 0 ? '+' : ''}{number(latestHousing.qoq_pct, lang, 1)}%</strong></span><span>{pick('Спрямо година по-рано', 'Year on year')} <strong>{latestHousing.yoy_pct > 0 ? '+' : ''}{number(latestHousing.yoy_pct, lang, 1)}%</strong></span></div>}<div className="development-chart is-small"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={housingSeries.slice(-32)} margin={{ top: 10, right: 10, left: -12, bottom: 5 }}><CartesianGrid vertical={false} strokeDasharray="3 5" stroke="#e4eae5" /><XAxis dataKey="period" tick={{ fill: '#6c8079', fontSize: 10 }} minTickGap={26} tickLine={false} axisLine={false} /><YAxis domain={['auto', 'auto']} tick={{ fill: '#6c8079', fontSize: 10 }} tickLine={false} axisLine={false} /><Tooltip formatter={(value) => [number(value, lang, 2), pick('Индекс', 'Index')]} /><Line type="linear" dataKey="index" stroke="#578ead" strokeWidth={2} dot={false} connectNulls={false} /></ComposedChart></ResponsiveContainer></div>{safeUrl(housingData.source?.url || housingData.source_url) && <a className="development-source-link" href={safeUrl(housingData.source?.url || housingData.source_url)} target="_blank" rel="noreferrer">{housingData.source?.name || pick('НСИ · Официален източник', 'NSI · Official source')}<ExternalLink size={13} /></a>}<small>{pick('Извлечено:', 'Retrieved:')} {date(housingData.retrieved_at || housingData.captured_at, lang)}</small>{latestHousing?.provisional && <p className="development-footnote">{pick('* Предварителни данни за последното тримесечие.', '* Provisional data for the latest quarter.')}</p>}<details className="development-housing-table"><summary>{pick('Всички тримесечия и методология', 'All quarters and methodology')}<ChevronDown size={14} /></summary><div className="development-table-scroll"><table className="development-period-table"><thead><tr><th scope="col">{pick('Тримесечие', 'Quarter')}</th><th scope="col">{pick('Индекс', 'Index')}</th><th scope="col">QoQ %</th><th scope="col">YoY %</th></tr></thead><tbody>{[...housingSeries].reverse().map((row) => <tr key={row.period}><th scope="row">{row.period}{row.provisional ? '*' : ''}</th><td>{number(row.index, lang, 2)}</td><td>{number(row.qoq_pct, lang, 1)}</td><td>{number(row.yoy_pct, lang, 1)}</td></tr>)}</tbody></table></div>{lang === 'bg' && (housingData.notes || []).map((note, index) => <p className="development-footnote" key={index}>{note}</p>)}{lang !== 'bg' && <p className="development-footnote">NSI publishes this series for Sofia city, all new and existing dwellings, without seasonal adjustment. The source notes methodological changes in 2022 and 2024; consult the original methodology before comparing long periods.</p>}</details></details>}
    <ConstructionContext construction={housingData?.construction} lang={lang} pick={pick} />
    <TransactionsContext />
    <details className="development-analyst"><summary><ShieldCheck size={18} /><span>{pick('Как да тълкуваме сигналите за бъдещите цени', 'How to interpret signals about future prices')}</span><ChevronDown size={15} /></summary><div className="development-analyst-body"><p className="development-analysis-availability">{pick('Все още няма модел за следващите 12 месеца, проверен върху по-късни периоди извън обучението.', 'There is not yet a 12-month forecast model evaluated on later periods excluded from training.')}{historySpan > 0 && <> {pick('Офертна история:', 'Asking-price history:')} {number(historySpan, lang)} {pick('дни.', 'days.')}</>}</p><h3>{pick('По-малко разрешения не определят посоката на цените', 'Fewer permits do not determine price direction')}</h3><p>{pick('Не може да се направи такъв извод само от броя. По-малко разрешения може да означава по-малко бъдещо предлагане и натиск за поскъпване, но може да е и реакция на слабо търсене или скъп кредит. Един документ може да обхваща съвсем различен мащаб от друг.', 'Counts alone cannot support that conclusion. Fewer permits may mean less future supply and upward price pressure, or a response to weaker demand or expensive credit. Individual documents can cover very different project sizes.')}</p><div className="development-analysis-factors"><span>{pick('Сравним обхват и сезонност', 'Comparable coverage and seasonality')}</span><span>{pick('РЗП и жилища, когато са публикувани', 'Floor area and dwellings, when published')}</span><span>{pick('Започнато строителство и завършвания', 'Construction starts and completions')}</span><span>{pick('Търсене, доходи и кредит', 'Demand, income and credit')}</span><span>{pick('Реални сделки и времеви лаг', 'Actual transactions and time lag')}</span></div><p className="development-analysis-conclusion">{pick('За по-уверен извод следете няколко показателя за сравними периоди и проверявайте официалните документи за конкретния проект.', 'For a stronger conclusion, follow several indicators across comparable periods and check the official documents for the specific project.')}</p></div></details>
  </section>;
}

function DocumentCard({ item, lang, pick, onOpenPlot, saved, onSave }) {
  const [copyState, setCopyState] = useState('idle');
  const [expanded, setExpanded] = useState(false);
  const [allPlots, setAllPlots] = useState(false);
  const copyTimer = useRef(null);
  useEffect(() => () => window.clearTimeout(copyTimer.current), []);
  const type = TYPES.includes(item.source_code) ? item.source_code : 'building_permits';
  const Icon = TYPE_ICONS[type];
  const investors = (item.investors || []).filter((value) => value?.value);
  const source = safeUrl(item.source_url);
  const ids = item.cadastral_ids || [];
  const plots = (item.plots || []).filter((plot) => plot.lat !== null && plot.lng !== null && Number.isFinite(Number(plot.lat)) && Number.isFinite(Number(plot.lng)));
  async function copyBrief() {
    const text = [TYPE_TEXT[type][lang === 'bg' ? 0 : 1], `${pick('№', 'No.')} ${item.record_key || '—'} · ${date(item.issued_at, lang)}`, item.description, item.address, item.district, ...investors.map((entry) => `${entry.label || entry.role}: ${entry.value}`), ids.join(', '), source].filter(Boolean).join('\n');
    try { await navigator.clipboard.writeText(text); setCopyState('copied'); } catch { setCopyState('error'); }
    window.clearTimeout(copyTimer.current);
    copyTimer.current = window.setTimeout(() => setCopyState('idle'), 3500);
  }
  return <article className="development-document-card">
    <div className="development-document-type"><span style={{ '--type-color': COLORS[type] }}><Icon size={14} />{TYPE_TEXT[type][lang === 'bg' ? 0 : 1]}</span><button type="button" className={`development-save${saved ? ' is-saved' : ''}`} onClick={() => onSave(item.id)} aria-pressed={saved} aria-label={pick(saved ? 'Премахни от запазените' : 'Запази за проверка', saved ? 'Remove saved record' : 'Save for research')}><Bookmark size={17} fill={saved ? 'currentColor' : 'none'} /></button></div>
    <div className="development-document-heading"><h3>{item.record_key || pick('Номерът не е посочен', 'Number not stated')}</h3><span><CalendarDays size={13} />{pick('Издадено:', 'Issued:')} <strong>{date(item.issued_at, lang)}</strong></span></div>
    <p id={`development-description-${item.id}`} className={`development-document-description${!expanded && item.description?.length > 140 ? ' is-collapsed' : ''}`}>{item.description || pick('В наличния запис няма описание на строежа.', 'The available record has no project description.')}</p>{item.description?.length > 140 && <button type="button" className="development-description-toggle" aria-expanded={expanded} aria-controls={`development-description-${item.id}`} onClick={() => setExpanded(!expanded)}>{pick(expanded ? 'Свий описанието' : 'Цялото описание', expanded ? 'Collapse description' : 'Full description')}<ChevronDown size={13} /></button>}
    {(item.address || item.district) && <p className="development-document-place"><MapPin size={14} /><span>{[item.district, item.address].filter(Boolean).join(' · ')}</span></p>}
    <div className={`development-investor${investors.length ? '' : ' is-unknown'}`}><Building2 size={16} /><div><span>{pick('Публикуван възложител / инвеститор', 'Published assignor / investor')}</span>{investors.length ? investors.map((entry, index) => <p key={`${entry.role}-${index}`}><strong>{entry.value}</strong><small>{entry.label || entry.role}</small></p>) : <p>{pick('Не е посочено юридическо лице.', 'No legal entity is stated.')}</p>}</div></div>
    <div className="development-parcels"><span>{pick('Точни кадастрални идентификатори', 'Exact cadastral identifiers')}</span>{ids.length ? <div id={`development-plots-${item.id}`}>{(allPlots ? ids : ids.slice(0, 3)).map((id) => { const plot = plots.find((entry) => entry.cadastral_id === id); return plot && onOpenPlot ? <button type="button" key={id} onClick={() => onOpenPlot(plot)} title={pick('Отвори имота на картата; филтрите се запазват', 'Open plot on the map; filters are preserved')}><MapPin size={12} />{id}<ArrowUpRight size={12} /></button> : <span className="is-unmapped" key={id}>{id}</span>; })}</div> : <p>{pick('Няма точен идентификатор; адресът не се използва за свързване с парцел.', 'No exact identifier; addresses are not used to link a parcel.')}</p>}{ids.length > 3 && <button type="button" className="development-more-plots" aria-expanded={allPlots} aria-controls={`development-plots-${item.id}`} onClick={() => setAllPlots(!allPlots)}>{allPlots ? pick('Покажи по-малко', 'Show fewer') : `${pick('Още', 'Show')} ${number(ids.length - 3, lang)} ${pick('имота', 'more plots')}`}<ChevronDown size={12} /></button>}{item.cadastral_ids_truncated && <small>{pick('Показани са първите 100 идентификатора от ', 'Showing the first 100 identifiers of ')}{number(item.cadastral_id_count, lang)}.</small>}{ids.length > plots.length && <small>{pick('Част от идентификаторите нямат налична координатна точка.', 'Some identifiers have no available coordinate point.')}</small>}</div>
    <details className="development-document-evidence"><summary><Info size={13} />{pick('Проследимост на записа', 'Record provenance')}<ChevronDown size={14} /></summary><dl><div><dt>{pick('Официален регистър', 'Official register')}</dt><dd>{item.source_name}</dd></div><div><dt>{pick('Дата на снимката', 'Snapshot date')}</dt><dd>{date(item.snapshot_date, lang)}</dd></div><div><dt>{pick('Запазени наблюдения', 'Retained observations')}</dt><dd>{number(item.observation_count || 1, lang)}</dd></div><div><dt>{pick('Първа поява', 'First observed')}</dt><dd>{item.first_observed_at ? date(item.first_observed_at, lang) : pick('Не е установена; нов запис не означава нов статут.', 'Not established; a new record does not imply a new status.')}</dd></div></dl><p>{pick('Името е публикувано в ролята от регистъра. То не доказва текуща собственост. Непублични лица и контакти не се показват.', 'The name is shown in its stated register role. It does not establish current ownership. Non-public individuals and contacts are not shown.')}</p></details>
    <div className="development-document-actions">{source && <a className="development-button is-primary" href={source} target="_blank" rel="noreferrer">{pick('Официален източник', 'Official source')}<ExternalLink size={14} /></a>}<button type="button" className="development-button is-quiet" onClick={copyBrief}><Clipboard size={14} />{pick(copyState === 'copied' ? 'Копирано' : 'Копирай за проверка', copyState === 'copied' ? 'Copied' : 'Copy research brief')}</button></div>{copyState === 'error' && <p className="development-copy-error" role="status">{pick('Браузърът не разреши копирането. Използвайте официалния източник или маркирайте текста.', 'Your browser did not allow copying. Open the official source or select the text manually.')}</p>}
  </article>;
}

export default function DevelopmentDashboard({ onOpenPlot, onOpenMap, onOpenOffers }) {
  const { lang, pick } = useI18n();
  const initial = useRef(null);
  if (!initial.current) initial.current = storedState();
  const [filters, setFilters] = useState(initial.current.filters);
  const [view, setView] = useState(initial.current.view);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [marketVisited, setMarketVisited] = useState(initial.current.view === 'market');
  const workspaceRef = useRef(null);
  const tablistRef = useRef(null);
  const [draft, setDraft] = useState(initial.current.filters);
  const [offset, setOffset] = useState(initial.current.offset);
  const [state, setState] = useState({ data: null, loading: true, error: false });
  const [market, setMarket] = useState({ data: null, loading: true, error: false });
  const [housing, setHousing] = useState({ data: null, loading: true });
  const [revision, setRevision] = useState(0);
  const [saved, setSaved] = useState(storedShortlist);
  const [savedOnly, setSavedOnly] = useState(false);
  const [filterError, setFilterError] = useState('');
  const feedRef = useRef(null);
  const filterRef = useRef(null);
  const savedIds = savedOnly ? saved.join(',') : '';
  const query = JSON.stringify({ ...filters, offset, revision, savedOnly, savedIds });
  useEffect(() => { try { sessionStorage.setItem(STATE_KEY, JSON.stringify({ filters, offset, view })); } catch { /* In-memory state remains available. */ } }, [filters, offset, view]);
  useEffect(() => {
    const controller = new AbortController();
    if (savedOnly && !saved.length) { setState((old) => ({ data: emptyShortlist(old.data), loading: false, error: false })); return () => controller.abort(); }
    setState((old) => ({ ...old, loading: true, error: false }));
    developmentApi.activity({ ...filters, offset, limit: 12, saved_ids: savedIds }, controller.signal).then((data) => { if (!controller.signal.aborted) setState({ data, loading: false, error: false }); }).catch((error) => { if (!controller.signal.aborted && error.name !== 'AbortError') setState((old) => ({ ...old, loading: false, error: true })); });
    return () => controller.abort();
  }, [query]);
  useEffect(() => {
    if (!marketVisited) return;
    const controller = new AbortController();
    setMarket((old) => ({ ...old, loading: true, error: false }));
    setHousing((old) => ({ ...old, loading: true }));
    marketApi.summary(controller.signal).then((data) => { if (!controller.signal.aborted) setMarket({ data, loading: false, error: false }); }).catch((error) => { if (!controller.signal.aborted && error.name !== 'AbortError') setMarket({ data: null, loading: false, error: true }); });
    developmentApi.housingContext(controller.signal).then((data) => { if (!controller.signal.aborted) setHousing({ data, loading: false }); }).catch((error) => { if (!controller.signal.aborted && error.name !== 'AbortError') setHousing({ data: null, loading: false }); });
    return () => controller.abort();
  }, [revision, marketVisited]);
  function selectView(next) {
    if (!['documents', 'activity', 'market'].includes(next)) return;
    setView(next);
    if (next === 'market') setMarketVisited(true);
    const url = new URL(window.location.href);
    url.searchParams.set('tab', next); url.searchParams.delete('section');
    window.history.replaceState(window.history.state, '', url.pathname + url.search + url.hash);
    workspaceRef.current?.scrollTo({ top: 0, behavior: 'auto' });
  }
  function onViewKeys(event) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const views = ['documents', 'activity', 'market'];
    const index = views.indexOf(view);
    const next = event.key === 'Home' ? views[0] : event.key === 'End' ? views[2] : views[(index + (event.key === 'ArrowRight' ? 1 : 2)) % views.length];
    selectView(next);
    tablistRef.current?.querySelector(`#development-tab-${next}`)?.focus();
  }
  function apply(next = draft) {
    if (next.date_from && next.date_to && next.date_from > next.date_to) { setFilterError(pick('Началната дата трябва да е преди крайната.', 'The start date must be before the end date.')); return; }
    if (!next.type) { setFilterError(pick('Изберете поне един вид документ.', 'Select at least one document type.')); return; }
    setFilterError(''); setFilters({ ...next, q: next.q.trim() }); setDraft({ ...next, q: next.q.trim() }); setOffset(0); setFiltersOpen(false);
  }
  function toggleType(type) {
    const current = draft.type === 'all' ? [...TYPES] : draft.type.split(',').filter(Boolean);
    const next = current.includes(type) ? current.filter((entry) => entry !== type) : [...current, type];
    setDraft({ ...draft, type: TYPES.filter((entry) => next.includes(entry)).join(',') });
  }
  function openPeriod(period, type) {
    const range = periodRange(period); if (!range) return;
    const next = { ...filters, ...(type ? { type } : {}), year: '', date_from: range[0], date_to: range[1] };
    apply(next); setSavedOnly(false); selectView('documents'); window.setTimeout(() => scrollToSection(feedRef), 30);
  }
  function toggleSaved(id) {
    if (savedOnly) setOffset(0);
    setSaved((current) => { const next = current.includes(id) ? current.filter((value) => value !== id) : [...current, id].slice(-200); try { localStorage.setItem(SAVED_KEY, JSON.stringify(next)); } catch { /* Save remains available during this visit. */ } return next; });
  }
  function quickPeriod(kind) {
    const next = { ...draft, year: '', date_from: '', date_to: '' };
    if (kind === 'latest') {
      const range = periodRange(latestSelectedDate?.slice(0, 7));
      if (!range) return;
      [next.date_from, next.date_to] = range;
    } else if (kind === '30' || kind === '90') {
      const today = currentSofiaDate();
      const from = new Date(`${today}T12:00:00Z`);
      from.setUTCDate(from.getUTCDate() - Number(kind) + 1);
      next.date_from = from.toISOString().slice(0, 10); next.date_to = today;
    }
    apply(next);
  }
  function selectMonth(value) {
    const range = periodRange(value);
    setDraft({ ...draft, year: '', date_from: range?.[0] || '', date_to: range?.[1] || '' });
  }
  function removeFilter(key) { const next = { ...filters, [key]: DEFAULT[key] }; apply(next); }
  function clear() { apply({ ...DEFAULT, type: 'all' }); setSavedOnly(false); }
  const data = state.data;
  const totals = data?.totals || {};
  const facets = data?.facets || {};
  const types = filters.type === 'all' ? TYPES : filters.type.split(',');
  const feed = data?.items || [];
  const pendingChanges = Object.keys(DEFAULT).some((key) => draft[key] !== filters[key]);
  const draftTypes = draft.type === 'all' ? TYPES : draft.type.split(',');
  const latestSelectedDate = (data?.coverage?.per_source || []).filter((source) => draftTypes.includes(source.source_code)).map((source) => source.date_max).filter((value) => /^\d{4}-\d{2}-\d{2}$/.test(value || '')).sort().at(-1);
  const draftMonth = draft.date_from && draft.date_to && draft.date_from.slice(0, 7) === draft.date_to.slice(0, 7) && periodRange(draft.date_from.slice(0, 7))?.every((value, index) => value === (index === 0 ? draft.date_from : draft.date_to)) ? draft.date_from.slice(0, 7) : '';
  const coverage = data?.coverage || {};
  const activeCount = ['year', 'date_from', 'date_to', 'district', 'q'].filter((key) => filters[key]).length + (filters.investor === 'known' ? 1 : 0);
  const splitCertificates = types.includes('exploitation_certificates') !== types.includes('exploitation_certificates_legacy');
  const canOpenMap = onOpenMap && filters.investor !== 'known' && !splitCertificates && !savedOnly;
  return <main ref={workspaceRef} className="development-workspace development-task-workspace"><div className="development-shell">
    <header className="development-hero">
      <div><h1>{pick('Строителни документи', 'Construction documents')}</h1><p>{pick('Намерете документ, отворете имота и проверете официалния източник.', 'Find a document, open its plot and check the official source.')}</p></div>
      <div className="development-header-meta"><span><CalendarDays size={14} />{pick('Снимка:', 'Snapshot:')} {date(coverage.latest_snapshot_date, lang)}</span><button type="button" className="development-button is-quiet" disabled={state.loading} onClick={() => setRevision((value) => value + 1)} aria-label={pick('Обнови наличните данни в изгледа', 'Refresh the available data in this view')}><RefreshCw size={15} className={state.loading ? 'animate-spin' : ''} /><span>{pick('Обнови', 'Refresh')}</span></button></div>
    </header>
    <div ref={tablistRef} className="development-view-tabs" role="tablist" aria-label={pick('Изглед на строителните данни', 'Construction data view')} onKeyDown={onViewKeys}>
      {[{ key: 'documents', Icon: FileText, bg: 'Документи', en: 'Documents' }, { key: 'activity', Icon: BarChart3, bg: 'Активност', en: 'Activity' }, { key: 'market', Icon: Layers3, bg: 'Цени и пазар', en: 'Prices & market' }].map(({ key, Icon, bg, en }) => <button key={key} id={`development-tab-${key}`} type="button" role="tab" aria-selected={view === key} aria-controls={`development-panel-${key}`} tabIndex={view === key ? 0 : -1} onClick={() => selectView(key)}><Icon size={17} /><span>{pick(bg, en)}</span></button>)}
    </div>
    {view !== 'market' && <>
      <form ref={filterRef} className="development-panel development-filters" onSubmit={(event) => { event.preventDefault(); apply(); }} aria-label={pick('Филтри за строителните документи', 'Construction document filters')}>
        <fieldset className="development-type-fieldset"><legend>{pick('Вид документ · може повече от един', 'Document type · select more than one')}</legend><div className="development-type-options">{TYPES.map((type) => { const selected = draft.type === 'all' || draft.type.split(',').includes(type); const Icon = TYPE_ICONS[type]; return <label key={type} className={selected ? 'is-selected' : ''} style={{ '--type-color': COLORS[type] }}><input type="checkbox" checked={selected} onChange={() => toggleType(type)} /><Icon size={15} /><span>{TYPE_SHORT[type][lang === 'bg' ? 0 : 1]}</span><span className="development-custom-check">{selected && <Check size={11} />}</span></label>; })}</div></fieldset>
        <div className="development-primary-filters">
          <label className="development-primary-search"><span>{pick('Търси в документите', 'Search documents')}</span><div><Search size={16} /><input type="search" maxLength={120} value={draft.q} onChange={(event) => setDraft({ ...draft, q: event.target.value })} placeholder={pick('Фирма, номер, адрес или описание…', 'Company, number, address or description…')} /></div></label>
          <label><span>{pick('Година', 'Year')}</span><select value={draft.year} onChange={(event) => setDraft({ ...draft, year: event.target.value, date_from: '', date_to: '' })}><option value="">{pick('Всички години', 'All years')}</option>{(facets.years || []).map((entry) => <option key={entry.year} value={entry.year}>{entry.year} · {number(entry.count, lang)}</option>)}</select></label>
          <button type="button" className="development-button development-more-filters" aria-expanded={filtersOpen} aria-controls="development-advanced-filters" onClick={() => setFiltersOpen(!filtersOpen)}><SlidersHorizontal size={15} />{pick('Още филтри', 'More filters')}{activeCount > 0 && <b>{activeCount}</b>}<ChevronDown size={13} /></button>
          <button type="submit" className="development-button is-primary" disabled={state.loading}>{state.loading ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}{pick('Покажи', 'Show')}</button>
        </div>
        <div id="development-advanced-filters" className="development-advanced-filters" hidden={!filtersOpen}>
          <div className="development-quick-periods" role="group" aria-label={pick('Бърз избор на период', 'Quick date range')}><span><CalendarDays size={14} />{pick('Период', 'Date range')}</span><button type="button" onClick={() => quickPeriod('latest')} disabled={!latestSelectedDate} title={pick('Най-новият месец за избраните видове документи; останалите условия се запазват.', 'Latest month for the selected document types; other conditions are preserved.')}>{pick('Последен наличен месец', 'Latest available month')}</button><button type="button" onClick={() => quickPeriod('30')}>{pick('30 дни', '30 days')}</button><button type="button" onClick={() => quickPeriod('90')}>{pick('90 дни', '90 days')}</button><button type="button" onClick={() => quickPeriod('all')}>{pick('Всички периоди', 'All dates')}</button></div>
          <div className="development-filter-grid"><label><span>{pick('Конкретен месец', 'Specific month')}</span><input type="month" value={draftMonth} onChange={(event) => selectMonth(event.target.value)} /></label><label><span>{pick('Издадено от', 'Issued from')}</span><input type="date" value={draft.date_from} onChange={(event) => setDraft({ ...draft, date_from: event.target.value, year: '' })} /></label><label><span>{pick('Издадено до', 'Issued to')}</span><input type="date" value={draft.date_to} onChange={(event) => setDraft({ ...draft, date_to: event.target.value, year: '' })} /></label><label><span>{pick('Район в документа', 'District in document')}</span><select value={draft.district} onChange={(event) => setDraft({ ...draft, district: event.target.value })}><option value="">{pick('Всички райони', 'All districts')}</option>{(facets.districts || []).map((entry) => <option key={entry.key} value={entry.key}>{entry.label} · {number(entry.count, lang)}</option>)}</select></label><label><span>{pick('Публикуван възложител', 'Published assignor')}</span><select value={draft.investor} onChange={(event) => setDraft({ ...draft, investor: event.target.value })}><option value="any">{pick('Всички записи', 'All records')}</option><option value="known">{pick('С посочено юридическо лице', 'With a stated legal entity')}</option></select></label></div>
          <div className="development-advanced-actions"><button type="button" className="development-text-button" onClick={clear}>{pick('Изчисти всички условия', 'Clear all conditions')}</button><button type="submit" className="development-button is-primary" disabled={state.loading}><Filter size={14} />{pick('Приложи филтрите', 'Apply filters')}</button></div>
        </div>
        {view === 'activity' && <div className="development-grouping-row"><span>{pick('Групиране на графиката', 'Chart grouping')}</span><div className="development-period-toggle" role="group" aria-label={pick('Групиране на графиката', 'Chart grouping')}><button type="button" aria-pressed={draft.period === 'month'} onClick={() => setDraft({ ...draft, period: 'month' })}>{pick('По месеци', 'Monthly')}</button><button type="button" aria-pressed={draft.period === 'year'} onClick={() => setDraft({ ...draft, period: 'year' })}>{pick('По години', 'Yearly')}</button></div></div>}
        {pendingChanges && <p className="development-pending-note" role="status"><Info size={14} />{pick('Промените още не са приложени. Натиснете „Покажи“.', 'Changes are not applied yet. Select “Show”.')}</p>}{filterError && <p className="development-form-error" role="alert">{filterError}</p>}
      </form>
      {(activeCount > 0 || savedOnly) && <div className="development-active-filters" aria-label={pick('Приложени условия', 'Applied conditions')}>{savedOnly && <button type="button" onClick={() => { setSavedOnly(false); setOffset(0); }}><Bookmark size={12} />{pick('Само запазени', 'Saved only')}<X size={12} /></button>}{['year', 'date_from', 'date_to', 'district', 'q'].filter((key) => filters[key]).map((key) => <button key={key} type="button" onClick={() => removeFilter(key)} aria-label={`${pick('Премахни', 'Remove')} ${key}: ${filters[key]}`}>{key === 'date_from' ? pick('От: ', 'From: ') : key === 'date_to' ? pick('До: ', 'To: ') : ''}{key === 'district' ? facets.districts?.find((entry) => entry.key === filters[key])?.label || filters[key] : filters[key]}<X size={12} /></button>)}{filters.investor === 'known' && <button type="button" onClick={() => removeFilter('investor')}>{pick('Посочено юридическо лице', 'Stated legal entity')}<X size={12} /></button>}<button type="button" className="development-clear-chip" onClick={clear}>{pick('Изчисти', 'Clear')}</button></div>}
    </>}
    {view === 'market' ? <section id="development-panel-market" className="development-view" role="tabpanel" aria-labelledby="development-tab-market" tabIndex={0}><p className="development-market-selection">{pick('Пазарните и НСИ данни са за целия им обхват. Само съпоставените регистрови документи следват избраните условия.', 'Market and NSI data cover their full stated scope. Only the compared register documents follow the selected filters.')}<button type="button" onClick={() => selectView('activity')}>{pick('Промени избора на документи', 'Change document selection')}<ArrowRight size={13} /></button></p><MarketContext market={market} housing={housing} activity={data || {}} lang={lang} pick={pick} onOpenOffers={onOpenOffers} /></section> : state.error ? <div className="development-panel development-empty is-error" role="alert"><Info size={25} /><h2>{pick('Документите не се заредиха.', 'Documents could not load.')}</h2><p>{pick('Опитайте отново след малко.', 'Please try again shortly.')}</p><button type="button" className="development-button is-primary" onClick={() => setRevision((value) => value + 1)}><RefreshCw size={15} />{pick('Опитай отново', 'Try again')}</button></div> : !data ? <div className="development-loading" role="status"><Loader2 size={27} className="animate-spin" /><span>{pick('Зареждане на документите…', 'Loading documents…')}</span></div> : <section id={`development-panel-${view}`} className={state.loading ? 'development-view development-results is-updating' : 'development-view development-results'} role="tabpanel" aria-labelledby={`development-tab-${view}`} tabIndex={0} aria-busy={state.loading}>
      {state.loading && <div className="development-update-indicator" role="status"><Loader2 size={14} className="animate-spin" />{pick('Прилагаме избраните условия…', 'Applying selected conditions…')}</div>}
      {view === 'documents' ? <section ref={feedRef} tabIndex={-1} className="development-feed" aria-labelledby="development-feed-title">
        <div className="development-section-heading development-feed-heading"><div><h2 id="development-feed-title">{savedOnly ? pick('Запазени документи', 'Saved documents') : pick('Документи', 'Documents')}<span className="development-result-count">{number(totals.documents, lang)}</span></h2><p>{pick('Най-новата дата на издаване е първа.', 'Newest issue date first.')}</p></div><div className="development-feed-actions"><button type="button" className={`development-button${savedOnly ? ' is-primary' : ''}`} aria-pressed={savedOnly} onClick={() => { setSavedOnly(!savedOnly); setOffset(0); }}><Bookmark size={14} />{pick('Запазени', 'Saved')}<b>{saved.length}</b></button>{canOpenMap && <button type="button" className="development-button" onClick={() => onOpenMap(filters)}><MapPin size={14} />{pick('На картата', 'Show on map')}</button>}</div></div>
        <p className="development-inline-scope"><Info size={14} />{pick('Налични свързани записи, не пълен регистър за София. Документът не доказва покупка или старт на строеж.', 'Available linked records, not a complete Sofia register. A document does not establish a purchase or construction start.')}</p>
        {(!canOpenMap || savedOnly) && <details className="development-map-help"><summary>{pick('За картата и запазените записи', 'About map access and saved records')}<ChevronDown size={13} /></summary>{splitCertificates && <p>{pick('За общ изглед на картата изберете текущите и архивните удостоверения заедно. Отделен имот се отваря от неговия точен идентификатор.', 'Select current and archived certificates together for the combined map. Open individual plots through their exact identifier.')}</p>}{filters.investor === 'known' && <p>{pick('Филтърът за юридическо лице работи в списъка. За карта отворете отделен кадастрален идентификатор.', 'The legal-entity filter applies to the list. Open an individual cadastral identifier for the map.')}</p>}{savedOnly && <p>{pick('Отметките остават в този браузър и важат за всички страници. Активните условия продължават да ги филтрират. За карта отворете отделен идентификатор.', 'Bookmarks stay in this browser across all pages and remain constrained by the active filters. Open an individual identifier for the map.')}</p>}</details>}
    {feed.length ? <div className="development-document-grid">{feed.map((item) => <DocumentCard key={item.id} item={item} lang={lang} pick={pick} onOpenPlot={onOpenPlot} saved={saved.includes(item.id)} onSave={toggleSaved} />)}</div> : <div className="development-panel development-empty"><Search size={25} /><h3>{pick(savedOnly ? 'Няма запазени записи с тези условия.' : 'Няма документи с тези условия.', savedOnly ? 'No saved records match these conditions.' : 'No documents match these conditions.')}</h3><p>{pick('Променете периода, района или видовете документи.', 'Change the period, district or document types.')}</p><button type="button" className="development-button" onClick={clear}>{pick('Покажи всички документи', 'Show all documents')}</button></div>}
    <div className="development-pagination"><span>{data.pagination?.total ? `${number(offset + 1, lang)}–${number(Math.min(offset + (data.items?.length || 0), data.pagination.total), lang)} ${pick('от', 'of')} ${number(data.pagination.total, lang)}` : pick('0 резултата', '0 results')}</span><div><button type="button" className="development-button" disabled={offset === 0 || state.loading} onClick={() => { setOffset(Math.max(0, offset - 12)); scrollToSection(feedRef); }} aria-label={pick('Предишна страница', 'Previous page')}><ChevronLeft size={17} /></button><button type="button" className="development-button" disabled={!data.pagination?.has_more || offset + 12 > (data.pagination?.max_offset ?? 2000) || state.loading} onClick={() => { setOffset(offset + 12); scrollToSection(feedRef); }} aria-label={pick('Следваща страница', 'Next page')}><ChevronRight size={17} /></button></div></div>{data.pagination?.has_more && offset + 12 > (data.pagination?.max_offset ?? 2000) && <p className="development-inline-note"><Info size={15} />{pick('За по-стари документи ограничете годината или периода. Достъпът по страници е ограничен до 2000 записа.', 'Narrow the year or date range to reach older documents. Pagination is limited to 2,000 records.')}</p>}</section>
      : <><div className="development-activity-summary"><span><FileText size={16} /><strong>{number(totals.documents, lang)}</strong>{pick('документа', 'documents')}</span><span><MapPin size={16} /><strong>{number(totals.linked_plots, lang)}</strong>{pick('свързани имота', 'linked plots')}</span><span><CalendarDays size={16} /><strong>{number(totals.unknown_date_documents, lang)}</strong>{pick('без дата · извън графиката', 'undated · outside chart')}</span></div><p className="development-inline-scope"><ShieldCheck size={14} />{pick('Наличният свързан набор не е пълният брой документи за София. Липсващ период не означава нула.', 'The available linked subset is not the complete count of Sofia documents. Missing periods do not mean zero.')}</p><ActivityChart data={data} filters={filters} lang={lang} pick={pick} onPeriod={openPeriod} /></>}
    </section>}
    {data && <details id="development-methodology" className="development-panel development-methodology"><summary><ShieldCheck size={16} /><span>{pick('Източници, обхват и как да четете данните', 'Sources, coverage and how to read the data')}</span><ChevronDown size={15} /></summary><div className="development-methodology-body"><p className="development-method-summary">{pick('Показваме налични документи с точен кадастрален идентификатор; това не е пълна справка за цяла София.', 'We show available documents with exact cadastral identifiers; this is not a complete Sofia-wide register.')} {number(coverage.unlinked_observations, lang)} {pick('наблюдения без точна връзка са извън анализа.', 'observations without an exact link are outside the analysis.')}{totals.identity_fallback_documents > 0 && <> {number(totals.identity_fallback_documents, lang)} {pick('от филтрираните записи нямат надежден номер/издател и се пазят отделно; може да съдържат повторения.', 'of the filtered records lack reliable number/issuer identity and stay separate; duplicates may remain.')}</>}</p><div className="development-method-grid"><article><FileText size={21} /><h3>{pick('Виза → разрешение → въвеждане', 'Visa → permit → commissioning')}</h3><p>{pick('Различни административни етапи. Визата не е разрешение за строеж. Разрешението не доказва реален старт. Удостоверението се отнася до описания строеж и неговия обхват.', 'Different administrative stages. A visa is not a building permit. A permit does not prove construction has started. A certificate relates to the project and scope it describes.')}</p></article><article><Layers3 size={21} /><h3>{pick('Документ, версия и имот', 'Document, version and plot')}</h3><p>{pick('Един документ може да се отнася до няколко имота. Версиите се пазят за проследимост. Броят на документите не е брой нови жилища, сделки или започнати строежи.', 'One document can relate to several plots. Versions are retained for traceability. Document counts are not counts of new homes, transactions or construction starts.')}</p></article><article><CalendarDays size={21} /><h3>{pick('Датите имат различен смисъл', 'Dates have different meanings')}</h3><p>{pick('Сортираме по издаване. Датата на снимката показва кога е получен регистровият набор. Първа поява или промяна на статут не се предполага от последното обновяване.', 'Sorting uses issue date. Snapshot date shows when the register dataset was captured. First appearance or status change is not inferred from the last update.')}</p></article></div><div className="development-source-coverage"><h3>{pick('Обхват на наличната регистрова снимка', 'Coverage of the available register snapshot')}</h3><p>{pick('Документни дати:', 'Issue dates:')} {date(coverage.date_min, lang)} – {date(coverage.date_max, lang)} · {number(totals.observations, lang)} {pick('запазени наблюдения', 'retained observations')}</p>{(coverage.per_source || []).length > 0 && <div className="development-coverage-grid">{coverage.per_source.map((source) => <div key={source.source_code || source.key}><strong>{TYPE_TEXT[source.source_code]?.[lang === 'bg' ? 0 : 1] || source.source_name || source.key}</strong><span>{number(source.documents, lang)} {pick('документа', 'documents')}</span><small>{pick('Снимка:', 'Snapshot:')} {date(source.snapshot_date, lang)}</small></div>)}</div>}<p className="development-footnote">{pick('Липсващ запис или точна връзка не доказва липса на документ. Месечните и годишните стойности описват наличния набор, чиито източници и обхват могат да се различават във времето.', 'A missing record or exact link does not prove a document is absent. Monthly and yearly values describe the available dataset; sources and coverage may differ over time.')}</p></div></div></details>}
  </div></main>;
}
