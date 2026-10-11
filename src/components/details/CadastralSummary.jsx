import React from 'react';
import { AlertTriangle, ArrowUpRight, Database, Ruler } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { displayCount, displayDate } from '@/lib/registerUi';

function present(value) {
  return value !== null && value !== undefined && String(value).trim() !== '';
}

function codedValue(label, code) {
  if (!present(label)) return present(code) ? String(code) : null;
  return present(code) && String(code) !== String(label) ? `${label} (${code})` : String(label);
}

function capturedDate(value, lang) {
  if (!present(value)) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(lang === 'bg' ? 'bg-BG' : 'en-GB', {
    timeZone: 'Europe/Sofia', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(date);
}

function cadastralFields(cadastre, t) {
  return [
    { key: 'cadastral_id', label: t('field.cadastral_id'), value: cadastre.cadastral_id },
    { key: 'address', label: t('field.address'), value: cadastre.address },
    { key: 'district', label: t('cadastre.district'), value: cadastre.district_name },
    { key: 'purpose', label: t('field.purpose'), value: codedValue(cadastre.purpose, cadastre.purpose_code) },
    { key: 'use', label: t('field.land_use'), value: codedValue(cadastre.use, cadastre.use_code) },
    { key: 'property_type', label: t('cadastre.propertyType'), value: codedValue(cadastre.property_type, cadastre.property_type_code) },
    { key: 'approval_act', label: t('cadastre.approvalAct'), value: cadastre.approval_act },
  ];
}

function areaText(value, lang, t) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
    ? `≈ ${value.toLocaleString(lang === 'bg' ? 'bg-BG' : 'en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${t('unit.sqm')}`
    : t('value.notAvailable');
}

function cadastralSourceLabel(source, lang, t) {
  return (lang === 'bg' ? source.label_bg : source.label_en) || source.label_bg || source.label_en || t('cadastre.sourceName');
}

function CadastralConflict({ cadastre, t, lang }) {
  const variants = Array.isArray(cadastre.variants) ? cadastre.variants : [];
  return <section className="cadastre-summary cadastre-summary-conflict">
    <div className="cadastre-summary-heading"><AlertTriangle size={18} aria-hidden="true" /><div><h3>{t('cadastre.conflictTitle')}</h3><p>{t('cadastre.conflictStatus')}</p></div></div>
    <p className="cadastre-note">{t('cadastre.conflictHelp')}</p>
    <div className="cadastre-conflict-variants">{variants.map((variant, index) => {
      const source = variant.source || {};
      return <details className="cadastre-conflict-variant" key={index}>
        <summary><span>{t('cadastre.variant', { n: index + 1 })}</span><strong>{areaText(variant.area_m2, lang, t)}</strong></summary>
        <dl className="cadastre-fields">{cadastralFields({ ...variant, cadastral_id: variant.cadastral_id || cadastre.cadastral_id }, t).map((field) => <div className="register-field" key={field.key}><dt>{field.label}</dt><dd className={!present(field.value) ? 'register-field-empty' : undefined}>{present(field.value) ? field.value : t('value.notAvailable')}</dd></div>)}</dl>
        <div className="cadastre-source"><strong>{cadastralSourceLabel(source, lang, t)}</strong>{source.captured_at && <p>{t('cadastre.capturedAt', { date: capturedDate(source.captured_at, lang) })}</p>}{source.source_url && <a href={source.source_url} target="_blank" rel="noreferrer">{t('cadastre.openSource')}<ArrowUpRight size={14} /></a>}{source.catalogue_url && <a href={source.catalogue_url} target="_blank" rel="noreferrer">{t('cadastre.openCatalogue')}<ArrowUpRight size={13} /></a>}</div>
      </details>;
    })}</div>
    <p className="cadastre-note">{t('cadastre.areaHelp')}</p>
  </section>;
}

export default function CadastralSummary({ cadastre, status }) {
  const { t, lang } = useI18n();
  if (!cadastre) return <section className="cadastre-summary cadastre-summary-missing"><h3>{t('cadastre.title')}</h3><p className="cadastre-note">{t(status === 'unavailable' ? 'cadastre.unavailable' : 'cadastre.noMatch')}</p></section>;
  if (cadastre.status === 'ambiguous') return <CadastralConflict cadastre={cadastre} t={t} lang={lang} />;
  const source = cadastre.source || {};
  const sourceLabel = cadastralSourceLabel(source, lang, t);
  const fields = cadastralFields(cadastre, t);
  return <section className="cadastre-summary">
    <div className="cadastre-summary-heading"><Database size={17} aria-hidden="true" /><div><h3>{t('cadastre.title')}</h3><p>{t('cadastre.exactMatch')}</p></div></div>
    <div className="cadastre-area"><Ruler size={20} aria-hidden="true" /><div><span>{t('cadastre.geometricArea')}</span><strong className="cadastre-area-value">{areaText(cadastre.area_m2, lang, t)}</strong></div></div>
    <p className="cadastre-note">{t('cadastre.areaHelp')}</p>
    <dl className="cadastre-fields">{fields.map((field) => <div className="register-field" key={field.key}><dt>{field.label}</dt><dd className={!present(field.value) ? 'register-field-empty' : undefined}>{present(field.value) ? field.value : t('value.notAvailable')}</dd></div>)}</dl>
    <div className="cadastre-source"><strong>{sourceLabel}</strong>{source.captured_at && <p>{t('cadastre.capturedAt', { date: capturedDate(source.captured_at, lang) })}</p>}{source.source_url && <a href={source.source_url} target="_blank" rel="noreferrer">{t('cadastre.openSource')}<ArrowUpRight size={14} /></a>}</div>
    <details className="evidence-details cadastre-provenance"><summary><Database size={14} aria-hidden="true" />{t('cadastre.provenance')}</summary><dl>
      {cadastre.area_method && <div className="register-field"><dt>{t('cadastre.areaMethod')}</dt><dd>{cadastre.area_method === 'published_AREA_BGS2005_LCC' ? t('cadastre.publishedAreaMethod') : cadastre.area_method}</dd></div>}
      {source.published_at && <div className="register-field"><dt>{t('cadastre.publishedAt')}</dt><dd>{displayDate(source.published_at, lang)}</dd></div>}
      {source.catalogue_published_at && <div className="register-field"><dt>{t('cadastre.cataloguePublishedAt')}</dt><dd>{displayDate(source.catalogue_published_at, lang)}</dd></div>}
      {source.record_count != null && <div className="register-field"><dt>{t('cadastre.sourceRecordCount')}</dt><dd>{displayCount(source.record_count, lang)}</dd></div>}
      {source.zip_sha256 && <div className="register-field"><dt>{t('cadastre.archiveHash')}</dt><dd>{source.zip_sha256}</dd></div>}
      {source.zip_bytes != null && <div className="register-field"><dt>{t('cadastre.archiveSize')}</dt><dd>{displayCount(source.zip_bytes, lang)} {t('cadastre.bytes')}</dd></div>}
      {cadastre.generated_at && <div className="register-field"><dt>{t('cadastre.preparedAt')}</dt><dd>{capturedDate(cadastre.generated_at, lang)}</dd></div>}
    </dl>{source.catalogue_url && <a href={source.catalogue_url} target="_blank" rel="noreferrer">{t('cadastre.openCatalogue')}<ArrowUpRight size={13} /></a>}</details>
  </section>;
}
