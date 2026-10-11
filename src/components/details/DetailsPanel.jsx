import React, { useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowLeft, ArrowUpRight, Check, Copy, FileCheck2, FileText, Info, Link2, Loader2, MapPin, X } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { displayDate, fieldLabel, fieldValue, REGISTER_COLORS } from '@/lib/registerUi';
import { realEstateApi } from '@/api/realEstateApi';
import CadastralSummary from '@/components/details/CadastralSummary';

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
    {entries.length ? <dl>{entries.map(([label, value]) => <div className="register-field" key={label}><dt>{fieldLabel(source.code, label, lang)}</dt><dd className={!hasValue(value) ? 'register-field-empty' : undefined}>{hasValue(value) ? documentFieldValue(source, label, value, lang) : t('panel.fieldEmpty')}</dd></div>)}</dl> : <p className="document-fields-empty">{t('panel.noFields')}</p>}
    <a className="document-source-link" href={source.source_url} target="_blank" rel="noreferrer">{t('panel.verifyRecord')}<ArrowUpRight size={13} /></a>
  </article>;
}

export default function DetailsPanel({ parcel, onClose, onBackToSearch }) {
  const { t, lang } = useI18n();
  const [state, setState] = useState({ key: null, loading: false, data: null, error: null });
  const [copied, setCopied] = useState(false);
  const sourceSections = useRef({});
  const scrollArea = useRef(null);
  const key = parcel?.cadastral_id || null;
  useEffect(() => {
    if (!key) { setState({ key: null, loading: false, data: null, error: null }); return undefined; }
    let active = true;
    setState({ key, loading: true, data: null, error: null }); setCopied(false);
    scrollArea.current?.scrollTo({ top: 0 });
    realEstateApi.plot(key).then((data) => { if (active) setState({ key, loading: false, data, error: null }); }).catch((error) => { if (active) setState({ key, loading: false, data: null, error: error.message }); });
    return () => { active = false; };
  }, [key]);
  async function copyId() { try { await navigator.clipboard.writeText(key); setCopied(true); window.setTimeout(() => setCopied(false), 1600); } catch { /* Clipboard availability depends on the browser context. */ } }
  function goToSource(code) { sourceSections.current[code]?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
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
  const navigationCodes = [...new Set([...REGISTER_GROUPS, ...sources.map((source) => source.code)])];
  return (
    <div className="details-panel">
      {onBackToSearch && <button className="details-back-search" type="button" onClick={onBackToSearch}><ArrowLeft size={17} aria-hidden="true" /><span>{t('panel.backToSearch')}</span></button>}
      <div className="details-header">
        <div><p className="eyebrow">{t('panel.title')}</p><h2>{plot.cadastral_id}</h2><span className="details-coordinate-type"><MapPin size={12} />{locationAvailable ? t('panel.coordinateMarker') : t('panel.noCoordinate')}</span></div>
        <div className="details-header-actions"><button onClick={copyId} aria-label={t('panel.copyId')} title={copied ? t('panel.copied') : t('panel.copyId')}>{copied ? <Check size={17} className="text-emerald-700" /> : <Copy size={17} />}</button>{onClose && <button onClick={onClose} aria-label={t('panel.close')}><X size={19} /></button>}</div>
      </div>
      <div className="details-scroll" ref={scrollArea}>
        {state.loading || state.key !== key ? <div className="details-loading"><Loader2 size={24} className="animate-spin" /><span>{t('panel.loading')}</span></div> : state.error ? <div className="details-error" role="alert">{t('panel.loadError')}<p>{state.error}</p></div> : <>
          <section className="property-overview">
            <div className="property-overview-heading"><div><h3>{t('panel.overview')}</h3><p>{t('panel.overviewHelp')}</p></div><span className="property-record-total">{t('panel.recordsCount', { n: count })}</span></div>
            <nav className="property-record-navigation" aria-label={t('panel.recordNavigation')}>
              {navigationCodes.map((code) => {
                const source = sources.find((item) => item.code === code);
                const sourceCount = source?.documents?.length || 0;
                return <button key={code} onClick={() => goToSource(code)} disabled={!sourceCount} style={{ '--source-color': sourceColor(code) }}><span>{sourceShortLabel(source || { code }, lang, t)}</span><strong>{sourceCount}</strong>{sourceCount > 0 && <ArrowDown size={12} />}</button>;
              })}
            </nav>
            <div className="property-coordinate"><MapPin size={15} /><div><span>{t('panel.location')}</span>{locationAvailable ? <strong>{Number(plot.lat).toFixed(6)}, {Number(plot.lng).toFixed(6)}</strong> : <p>{t('panel.noCoordinateHelp')}</p>}</div></div>
            {overview.length > 0 && <dl className="property-overview-fields">{overview.map((field) => <div className="property-overview-field" key={field.key}><dt>{t(`panel.overview.${field.key}`)}</dt><dd>{field.values.map((entry) => <div className="property-overview-value" key={entry.value}><p>{entry.value}</p><div className="overview-value-sources">{[...entry.sources.values()].map((source) => <button key={source.code} onClick={() => goToSource(source.code)} title={sourceLabel(source, lang)}>{sourceShortLabel(source, lang, t)}<ArrowDown size={10} /></button>)}</div></div>)}</dd></div>)}</dl>}
          </section>
          <CadastralSummary cadastre={currentData?.cadastre} status={currentData?.cadastre_status} />
          <section className={`certificate-status certificate-status-compact ${hasCertificate ? 'certificate-found' : 'certificate-unknown'}`}>
            <div className="certificate-status-top"><span className="certificate-icon"><FileCheck2 size={18} /></span><div><p>{t('certificate.heading')} · „{t('panel.act16')}“</p><h3>{hasCertificate ? t('certificate.found') : t('certificate.notLinked')}</h3></div>{hasCertificate && <span className="certificate-linked-count">{certificateDocuments.length}</span>}</div>
            <p className="certificate-explanation">{hasCertificate ? t('certificate.foundHelp') : t('certificate.notLinkedHelp')}</p>
            <details className="certificate-term"><summary><Info size={13} />{t('certificate.term')}</summary><p>{t('certificate.termHelp')}</p></details>
          </section>
          <div className="record-summary"><h3>{t('panel.allAvailableRecords')}</h3><span>{t('panel.recordsCount', { n: count })}</span></div>
          {count > 0 && <p className="record-versions-note">{t('panel.recordVersions')}</p>}
          {sources.length === 0 && <div className="no-records"><FileText size={25} /><p>{t('panel.noRecords')}</p><a href="https://nag.sofia.bg/RegisterCertificateForExploitationBuildings" target="_blank" rel="noreferrer">{t('panel.openSource')}<ArrowUpRight size={14} /></a></div>}
          <div className="source-cards">{sources.map((source) => <section className="source-card" key={source.code} ref={(element) => { sourceSections.current[source.code] = element; }} style={{ '--source-color': sourceColor(source.code) }}>
            <div className="source-card-header"><div className="source-card-kind-row"><span className="source-kind">{t(`source.${source.code}`) === `source.${source.code}` ? sourceLabel(source, lang) : t(`source.${source.code}`)}</span><span className="source-record-count">{t('panel.recordsCount', { n: source.documents?.length || 0 })}</span></div><h4>{sourceLabel(source, lang)}</h4><p>{source.snapshot_date ? t('dataset.snapshot', { date: displayDate(source.snapshot_date, lang) }) : t('dataset.dateUnknown')}</p><a href={source.source_url} target="_blank" rel="noreferrer">{t('panel.openSource')}<ArrowUpRight size={15} /></a></div>
            {(source.documents || []).map((document) => <RegisterDocument key={document.id} source={source} document={document} lang={lang} t={t} />)}
          </section>)}</div>
          <details className="evidence-details"><summary><Link2 size={15} />{t('panel.matchMethod')}</summary><p>{t('panel.matchHelp')}</p></details>
          <details className="evidence-details"><summary><MapPin size={15} />{t('panel.coordinateSource')}</summary><p>{locationAvailable ? t('panel.coordinateEvidence') : t('panel.noCoordinateHelp')}</p></details>
          <p className="details-disclaimer">{t('panel.disclaimer')}</p>
        </>}
      </div>
    </div>
  );
}
