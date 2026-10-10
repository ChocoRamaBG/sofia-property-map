import React, { useEffect, useState } from 'react';
import { ArrowUpRight, Check, Copy, FileCheck2, FileText, Info, Link2, Loader2, MapPin, X } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { displayDate, fieldLabel, fieldValue, REGISTER_COLORS } from '@/lib/registerUi';
import { realEstateApi } from '@/api/realEstateApi';

const SOURCE_ORDER = { exploitation_certificates: 0, building_permits: 1, projecting_visas: 2 };

function RegisterDocument({ source, document, lang, t }) {
  const entries = Object.entries(document.raw_fields || {}).filter(([, value]) => value !== null && value !== undefined && String(value).trim());
  return <article className="register-document">
    <div className="document-heading"><FileText size={15} /><strong>{document.record_key || t('panel.registerRecord')}</strong></div>
    {document.snapshot_date && <p className="document-capture">{t('dataset.snapshot', { date: displayDate(document.snapshot_date, lang) })}</p>}
    <dl>{entries.map(([label, value]) => <div className="register-field" key={label}><dt>{fieldLabel(source.code, label, lang)}</dt><dd>{fieldValue(source.code, label, value, lang)}</dd></div>)}</dl>
  </article>;
}

export default function DetailsPanel({ parcel, onClose }) {
  const { t, lang } = useI18n();
  const [state, setState] = useState({ loading: false, data: null, error: null });
  const [copied, setCopied] = useState(false);
  const key = parcel?.cadastral_id || null;
  useEffect(() => {
    if (!key) { setState({ loading: false, data: null, error: null }); return undefined; }
    let active = true;
    setState({ loading: true, data: null, error: null }); setCopied(false);
    realEstateApi.plot(key).then((data) => { if (active) setState({ loading: false, data, error: null }); }).catch((error) => { if (active) setState({ loading: false, data: null, error: error.message }); });
    return () => { active = false; };
  }, [key]);
  async function copyId() { try { await navigator.clipboard.writeText(key); setCopied(true); window.setTimeout(() => setCopied(false), 1600); } catch { /* Clipboard availability depends on the browser context. */ } }
  if (!parcel) return null;
  const plot = state.data?.plot || parcel;
  const sources = [...(state.data?.sources || [])].sort((a, b) => (a.code.startsWith('exploitation_certificates') ? 0 : SOURCE_ORDER[a.code] ?? 9) - (b.code.startsWith('exploitation_certificates') ? 0 : SOURCE_ORDER[b.code] ?? 9));
  const count = sources.reduce((total, source) => total + (source.documents?.length || 0), 0);
  const certificateDocuments = sources.filter((source) => source.code.startsWith('exploitation_certificates')).flatMap((source) => source.documents || []);
  const hasCertificate = Boolean(certificateDocuments.length);
  const locationAvailable = plot.lat != null && plot.lng != null;
  return (
    <div className="details-panel">
      <div className="details-header">
        <div><p className="eyebrow">{t('panel.title')}</p><h2>{plot.cadastral_id}</h2><span className="details-coordinate-type"><MapPin size={12} />{locationAvailable ? t('panel.coordinateMarker') : t('panel.noCoordinate')}</span></div>
        <div className="details-header-actions"><button onClick={copyId} aria-label={t('panel.copyId')} title={copied ? t('panel.copied') : t('panel.copyId')}>{copied ? <Check size={17} className="text-emerald-700" /> : <Copy size={17} />}</button>{onClose && <button onClick={onClose} aria-label={t('panel.close')}><X size={19} /></button>}</div>
      </div>
      <div className="details-scroll">
        {state.loading ? <div className="details-loading"><Loader2 size={24} className="animate-spin" /><span>{t('panel.loading')}</span></div> : state.error ? <div className="details-error" role="alert">{t('panel.loadError')}<p>{state.error}</p></div> : <>
          <section className={`certificate-status ${hasCertificate ? 'certificate-found' : 'certificate-unknown'}`}>
            <div className="certificate-status-top"><span className="certificate-icon"><FileCheck2 size={23} /></span><div><p>{t('certificate.heading')}</p><h3>{hasCertificate ? t('certificate.found') : t('certificate.notLinked')}</h3></div></div>
            {hasCertificate && <div className="certificate-reference"><span>{t('certificate.document')}</span><strong>{certificateDocuments.map((document) => document.record_key).filter(Boolean).join(' · ')}</strong></div>}
            <p className="certificate-explanation">{hasCertificate ? t('certificate.foundHelp') : t('certificate.notLinkedHelp')}</p>
            <details className="certificate-term"><summary><Info size={13} />{t('certificate.term')}</summary><p>{t('certificate.termHelp')}</p></details>
          </section>
          <div className="record-summary"><h3>{t('panel.registerRecords')}</h3><span>{t('panel.recordsCount', { n: count })}</span></div>
          {sources.length === 0 && <div className="no-records"><FileText size={25} /><p>{t('panel.noRecords')}</p><a href="https://nag.sofia.bg/RegisterCertificateForExploitationBuildings" target="_blank" rel="noreferrer">{t('panel.openSource')}<ArrowUpRight size={14} /></a></div>}
          <div className="source-cards">{sources.map((source) => <section className="source-card" key={source.code} style={{ '--source-color': REGISTER_COLORS[source.code] || (source.code.startsWith('exploitation_certificates') ? REGISTER_COLORS.exploitation_certificates : '#64748b') }}>
            <div className="source-card-header"><span className="source-kind">{t(`source.${source.code}`)}</span><h4>{lang === 'bg' ? source.label_bg : source.label_en}</h4><p>{source.snapshot_date ? t('dataset.snapshot', { date: displayDate(source.snapshot_date, lang) }) : t('dataset.dateUnknown')}</p><a href={source.source_url} target="_blank" rel="noreferrer">{t('panel.openSource')}<ArrowUpRight size={15} /></a></div>
            {(source.documents || []).map((document) => <RegisterDocument key={document.id} source={source} document={document} lang={lang} t={t} />)}
          </section>)}</div>
          <details className="evidence-details"><summary><Link2 size={15} />{t('panel.matchMethod')}</summary><p>{t('panel.matchHelp')}</p></details>
          <details className="evidence-details"><summary><MapPin size={15} />{t('panel.location')}</summary>{locationAvailable ? <><p className="coordinate-value">{Number(plot.lat).toFixed(6)}, {Number(plot.lng).toFixed(6)}</p><p>{t('panel.coordinateEvidence')}</p></> : <p>{t('panel.noCoordinateHelp')}</p>}</details>
          <p className="details-disclaimer">{t('panel.disclaimer')}</p>
        </>}
      </div>
    </div>
  );
}
