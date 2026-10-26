import React, { useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowLeft, ArrowUpRight, Check, ChevronDown, Copy, FileCheck2, FileText, Info, Link2, Loader2, MapPin, X } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { displayDate, fieldLabel, fieldValue, REGISTER_COLORS } from '@/lib/registerUi';
import { realEstateApi } from '@/api/realEstateApi';
import CadastralSummary from '@/components/details/CadastralSummary';
import DevelopmentTimeline from './DevelopmentTimeline';

const REGISTER_GROUPS = ['building_permits', 'projecting_visas', 'exploitation_certificates', 'exploitation_certificates_legacy'];
const SOURCE_ORDER = Object.fromEntries(REGISTER_GROUPS.map((code, index) => [code, index]));
const OVERVIEW_FIELDS = [
  { key: 'address', labels: ['адрес', 'address'] },
  { key: 'district', labels: ['район', 'district'] },
  { key: 'project', labels: ['обект', 'строеж', 'строеж / обект', 'строеж/обект', 'construction / project', 'project', 'object'] },
  { key: 'scope', labels: ['местоположение', 'обхват', 'обхват и идентификатори', 'scope and identifiers', 'scope', 'location'] },
];

function hasValue(value) {
  return value !== null && value !== undefined && String(value).trim() !== '';
}

function normalizeLabel(label) {
  return String(label).toLocaleLowerCase('bg-BG').replace(/\s+/g, ' ').trim();
}

function documentFieldValue(source, label, value, lang) {
  const normalized = normalizeLabel(fieldLabel(source.code, label, 'bg'));
  if (source.code === 'projecting_visas' && ['дата', 'влязъл в сила', 'влязло в сила на'].includes(normalized) && typeof value === 'number' && value > 20000 && value < 70000) {
    return displayDate(new Date(Date.UTC(1899, 11, 30) + value * 86400000).toISOString(), lang);
  }
  return fieldValue(source.code, label, value, lang);
}

function recordTitle(source, document, lang, t) {
  if (source.code === 'projecting_visas' && /^\d{5}$/.test(String(document.record_key || ''))) {
    const dateEntry = Object.entries(document.raw_fields || {}).find(([label, value]) => normalizeLabel(fieldLabel(source.code, label, 'bg')) === 'дата' && String(value) === String(document.record_key));
    if (dateEntry) return documentFieldValue(source, ...dateEntry, lang);
  }
  return document.record_key || t('panel.registerRecord');
}

function sourceLabel(source, lang) {
  return (lang === 'bg' ? source.label_bg : source.label_en) || source.label_bg || source.label_en || source.code;
}

function sourceShortLabel(source, lang, t) {
  const key = `panel.sourceShort.${source.code}`;
  const label = t(key);
  return label === key ? sourceLabel(source, lang) : label;
}

function sourceColor(code) {
  const baseCode = REGISTER_GROUPS.find((group) => code === group || code.startsWith(`${group}_`));
  return REGISTER_COLORS[code] || REGISTER_COLORS[baseCode] || '#64748b';
}

function collectOverview(sources, lang) {
  return OVERVIEW_FIELDS.map((field) => {
    const values = new Map();
    for (const source of sources) {
      for (const document of source.documents || []) {
        for (const [label, value] of Object.entries(document.raw_fields || {})) {
          if (!hasValue(value)) continue;
          const normalized = normalizeLabel(fieldLabel(source.code, label, 'bg'));
          let text = documentFieldValue(source, label, value, lang);
          if (!field.labels.includes(normalized)) {
            if (field.key !== 'address' || !OVERVIEW_FIELDS.find((item) => item.key === 'scope').labels.includes(normalized)) continue;
            const address = String(text).match(/(?:^|[,;\n])\s*(?:Адрес|Address)(?:\s*:\s*|\s+)([^\n]+)/iu);
            if (!address) continue;
            text = address[1].trim();
          }
          if (!values.has(text)) values.set(text, { value: text, sources: new Map() });
          values.get(text).sources.set(source.code, source);
        }
      }
    }
    return { ...field, values: [...values.values()] };
  }).filter((field) => field.values.length);
}

function RegisterDocument({ source, document, lang, t }) {
  const entries = Object.entries(document.raw_fields || {});
  return <article className="register-document">
    <div className="document-heading"><FileText size={15} /><strong>{recordTitle(source, document, lang, t)}</strong></div>
    <div className="document-dates">
      {document.issued_at && <span>{t('panel.issueDate', { date: displayDate(document.issued_at, lang) })}</span>}
      <span>{document.snapshot_date ? t('dataset.snapshot', { date: displayDate(document.snapshot_date, lang) }) : t('dataset.dateUnknown')}</span>
    </div>
    {entries.length ? <details className="document-fields-disclosure"><summary>{lang === 'bg' ? 'Всички полета от регистъра' : 'All register fields'} <span>{entries.length}</span><ChevronDown size={14} aria-hidden="true" /></summary><dl>{entries.map(([label, value]) => <div className="register-field" key={label}><dt>{fieldLabel(source.code, label, lang)}</dt><dd className={!hasValue(value) ? 'register-field-empty' : undefined}>{hasValue(value) ? documentFieldValue(source, label, value, lang) : t('panel.fieldEmpty')}</dd></div>)}</dl></details> : <p className="document-fields-empty">{t('panel.noFields')}</p>}
    <a className="document-source-link" href={source.source_url} target="_blank" rel="noreferrer">{t('panel.verifyRecord')}<ArrowUpRight size={13} /></a>
  </article>;
}

function BoundaryDimensions({ parcel, currentKey, lang, t }) {
  if (parcel?.boundary_status !== 'matched' || parcel.cadastral_id !== currentKey) return null;
  const bg = lang === 'bg';
  const source = parcel.source || {};
  let sourceUrl = null;
  try { const url = new URL(source.url); if (url.protocol === 'https:' && !url.username && !url.password) sourceUrl = url.href; } catch { /* Missing source links remain plain text. */ }
  const sourceName = sourceLabel(source, lang) || (bg ? 'АГКК · КАИС, Отворени данни' : 'AGCC · KAIS Open Data');
  const dimension = (value, unit) => typeof value === 'number' && Number.isFinite(value) && value >= 0
    ? `${new Intl.NumberFormat(bg ? 'bg-BG' : 'en-GB', { maximumFractionDigits: 2 }).format(value)} ${unit}` : '—';
  return <section className="property-overview mb-4" aria-label={bg ? 'Размери от избраната кадастрална геометрия' : 'Dimensions from the selected cadastral geometry'}>
    <div className="property-overview-heading"><div><h3>{bg ? 'Размери от избраната граница' : 'Selected boundary dimensions'}</h3><p>{bg ? 'Публикувани геометрични стойности на този слой. Кадастралните атрибути по-долу имат отделна снимка и дата.' : 'Published geometry values from this layer. The cadastral attributes below have their own snapshot and capture date.'}</p></div></div>
    <dl className="mt-3 grid grid-cols-2 gap-3 text-xs"><div><dt className="leading-relaxed text-slate-600">{bg ? 'Публикувана площ' : 'Published area'}</dt><dd className="mt-1 break-words text-sm font-semibold text-emerald-900">{dimension(parcel.area_m2, bg ? 'м²' : 'm²')}</dd></div><div><dt className="leading-relaxed text-slate-600">{bg ? 'Публикуван периметър' : 'Published perimeter'}</dt><dd className="mt-1 break-words text-sm font-semibold text-emerald-900">{dimension(parcel.published_perimeter_m, bg ? 'м' : 'm')}</dd></div></dl>
    <div className="mt-3 text-xs leading-relaxed text-slate-600">{sourceUrl ? <a className="inline-flex min-h-9 items-center gap-1 text-emerald-800 underline underline-offset-2" href={sourceUrl} target="_blank" rel="noreferrer">{sourceName}<ArrowUpRight size={13} aria-hidden="true" /></a> : <span>{sourceName}</span>}<p>{source.captured_at ? `${bg ? 'Извлечено:' : 'Captured:'} ${displayDate(source.captured_at, lang)}` : t('dataset.dateUnknown')}</p></div>
  </section>;
}

export default function DetailsPanel({ parcel, onClose, onBackToSearch, onBackToActivity, closeOnEscape = false }) {
  const { t, lang } = useI18n();
  const [state, setState] = useState({ key: null, loading: false, data: null, error: null });
  const [copied, setCopied] = useState(false);
  const sourceSections = useRef({});
  const scrollArea = useRef(null);
  const heading = useRef(null);
  const key = parcel?.cadastral_id || null;
  useEffect(() => {
    if (!key) { setState({ key: null, loading: false, data: null, error: null }); return undefined; }
    let active = true;
    setState({ key, loading: true, data: null, error: null }); setCopied(false);
    scrollArea.current?.scrollTo({ top: 0 });
    heading.current?.focus({ preventScroll: true });
    realEstateApi.plot(key).then((data) => { if (active) setState({ key, loading: false, data, error: null }); }).catch((error) => { if (active) setState({ key, loading: false, data: null, error: error.message }); });
    return () => { active = false; };
  }, [key]);
  async function copyId() { try { await navigator.clipboard.writeText(key); setCopied(true); window.setTimeout(() => setCopied(false), 1600); } catch { /* Clipboard availability depends on the browser context. */ } }
  function goToSource(code) {
    const section = sourceSections.current[code];
    if (!section) return;
    section.open = true;
    section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    section.querySelector('summary')?.focus({ preventScroll: true });
  }
  if (!parcel) return null;
  const currentData = state.key === key ? state.data : null;
  const plot = currentData?.plot || parcel;
  const sources = [...(currentData?.sources || [])].map((source) => ({
    ...source,
    documents: [...(source.documents || [])].sort((a, b) =>
      String(b.issued_at || '').localeCompare(String(a.issued_at || ''))
      || String(b.snapshot_date || '').localeCompare(String(a.snapshot_date || ''))
      || String(a.record_key || '').localeCompare(String(b.record_key || ''), lang)),
  })).sort((a, b) => (SOURCE_ORDER[a.code] ?? 9) - (SOURCE_ORDER[b.code] ?? 9));
  const count = sources.reduce((total, source) => total + (source.documents?.length || 0), 0);
  const certificateDocuments = sources.filter((source) => source.code.startsWith('exploitation_certificates')).flatMap((source) => source.documents || []);
  const hasCertificate = Boolean(certificateDocuments.length);
  const locationAvailable = plot.lat != null && plot.lng != null;
  const overview = collectOverview(sources, lang);
  return (
    <div className="details-panel" onKeyDown={(event) => { if (closeOnEscape && event.key === 'Escape' && !event.defaultPrevented) { event.stopPropagation(); onClose?.(); } }}>
      {onBackToActivity && <button className="details-back-search" type="button" onClick={onBackToActivity}><ArrowLeft size={17} aria-hidden="true" /><span>{lang === 'bg' ? 'Обратно към списъка с документи' : 'Back to the document list'}</span></button>}
      {onBackToSearch && <button className="details-back-search" type="button" onClick={onBackToSearch}><ArrowLeft size={17} aria-hidden="true" /><span>{t('panel.backToSearch')}</span></button>}
      <div className="details-header">
        <div><p className="eyebrow">{t('panel.title')}</p><h2 ref={heading} tabIndex={-1}>{plot.cadastral_id}</h2><span className="details-coordinate-type"><MapPin size={12} />{locationAvailable ? t('panel.coordinateMarker') : t('panel.noCoordinate')}</span></div>
        <div className="details-header-actions"><button onClick={copyId} aria-label={t('panel.copyId')} title={copied ? t('panel.copied') : t('panel.copyId')}>{copied ? <Check size={17} className="text-emerald-700" /> : <Copy size={17} />}</button>{onClose && <button onClick={onClose} aria-label={t('panel.close')}><X size={19} /></button>}</div>
      </div>
      <div className="details-scroll" ref={scrollArea}>
        <BoundaryDimensions parcel={parcel} currentKey={key} lang={lang} t={t} />
        {state.loading || state.key !== key ? <div className="details-loading"><Loader2 size={24} className="animate-spin" /><span>{t('panel.loading')}</span></div> : state.error ? <div className="details-error" role="alert">{t('panel.loadError')}<p>{state.error}</p></div> : <>
          <section className="property-overview">
            <div className="property-overview-heading"><div><h3>{t('panel.overview')}</h3><p>{t('panel.overviewHelp')}</p></div><span className="property-record-total">{t('panel.recordsCount', { n: count })}</span></div>
            <details className="property-coordinate-details"><summary><MapPin size={14} />{lang === 'bg' ? 'Координати на точката' : 'Point coordinates'}<ChevronDown size={14} /></summary><div className="property-coordinate"><MapPin size={15} /><div><span>{t('panel.location')}</span>{locationAvailable ? <strong>{Number(plot.lat).toFixed(6)}, {Number(plot.lng).toFixed(6)}</strong> : <p>{t('panel.noCoordinateHelp')}</p>}</div></div></details>
            {overview.length > 0 && <dl className="property-overview-fields">{overview.map((field) => <div className="property-overview-field" key={field.key}><dt>{t(`panel.overview.${field.key}`)}</dt><dd>{field.values.map((entry) => <div className="property-overview-value" key={entry.value}><p>{entry.value}</p><div className="overview-value-sources">{[...entry.sources.values()].map((source) => <button key={source.code} onClick={() => goToSource(source.code)} title={sourceLabel(source, lang)}>{sourceShortLabel(source, lang, t)}<ArrowDown size={10} /></button>)}</div></div>)}</dd></div>)}</dl>}
          </section>
          <CadastralSummary cadastre={currentData?.cadastre} status={currentData?.cadastre_status} />
          <DevelopmentTimeline sources={sources} lang={lang} onOpenSource={goToSource} />
          <section className={`certificate-status certificate-status-compact ${hasCertificate ? 'certificate-found' : 'certificate-unknown'}`}>
            <div className="certificate-status-top"><span className="certificate-icon"><FileCheck2 size={18} /></span><div><p>{t('certificate.heading')} · „{t('panel.act16')}“</p><h3>{hasCertificate ? t('certificate.found') : t('certificate.notLinked')}</h3></div>{hasCertificate && <span className="certificate-linked-count">{certificateDocuments.length}</span>}</div>
            <p className="certificate-explanation">{hasCertificate ? t('certificate.foundHelp') : t('certificate.notLinkedHelp')}</p>
            <details className="certificate-term"><summary><Info size={13} />{t('certificate.term')}</summary><p>{t('certificate.termHelp')}</p></details>
          </section>
          <div className="record-summary"><h3>{t('panel.allAvailableRecords')}</h3><span>{t('panel.recordsCount', { n: count })}</span></div>
          {count > 0 && <p className="record-versions-note">{t('panel.recordVersions')}</p>}
          {sources.length === 0 && <div className="no-records"><FileText size={25} /><p>{t('panel.noRecords')}</p><a href="https://nag.sofia.bg/RegisterCertificateForExploitationBuildings" target="_blank" rel="noreferrer">{t('panel.openSource')}<ArrowUpRight size={14} /></a></div>}
          <div className="source-cards">{sources.map((source) => <details className="source-card source-card-disclosure" key={source.code} ref={(element) => { sourceSections.current[source.code] = element; }} style={{ '--source-color': sourceColor(source.code) }}>
            <summary className="source-disclosure-heading"><span><strong>{sourceShortLabel(source, lang, t)}</strong><small>{t('panel.recordsCount', { n: source.documents?.length || 0 })}</small></span><ChevronDown size={17} aria-hidden="true" /></summary>
            <div className="source-card-header"><div className="source-card-kind-row"><span className="source-kind">{t(`source.${source.code}`) === `source.${source.code}` ? sourceLabel(source, lang) : t(`source.${source.code}`)}</span><span className="source-record-count">{t('panel.recordsCount', { n: source.documents?.length || 0 })}</span></div><h4>{sourceLabel(source, lang)}</h4><p>{source.snapshot_date ? t('dataset.snapshot', { date: displayDate(source.snapshot_date, lang) }) : t('dataset.dateUnknown')}</p><a href={source.source_url} target="_blank" rel="noreferrer">{t('panel.openSource')}<ArrowUpRight size={15} /></a></div>
            {(source.documents || []).map((document) => <RegisterDocument key={document.id} source={source} document={document} lang={lang} t={t} />)}
          </details>)}</div>
          <details className="evidence-details"><summary><Link2 size={15} />{t('panel.matchMethod')}</summary><p>{t('panel.matchHelp')}</p></details>
          <details className="evidence-details"><summary><MapPin size={15} />{t('panel.coordinateSource')}</summary><p>{locationAvailable ? t('panel.coordinateEvidence') : t('panel.noCoordinateHelp')}</p></details>
          <p className="details-disclaimer">{t('panel.disclaimer')}</p>
        </>}
      </div>
    </div>
  );
}
