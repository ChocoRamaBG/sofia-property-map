import React from 'react';
import { Check, FileCheck2, SlidersHorizontal } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { REGISTER_FILTERS, REGISTER_COLORS, displayCount } from '@/lib/registerUi';

export default function RegisterFilters({ value, onChange, counts }) {
  const { t, lang } = useI18n();
  return (
    <section className="register-filters">
      <div className="section-heading"><SlidersHorizontal size={16} /><h2>{t('filter.title')}</h2></div>
      <p>{t('filter.description')}</p>
      <div className="filter-options" role="group" aria-label={t('filter.title')}>
        {REGISTER_FILTERS.map((code) => {
          const count = code === 'all' ? counts?.plots : code === 'no_records' ? null : code === 'exploitation_certificates' ? counts?.plots_with_exploitation_certificate : counts?.plots_by_source?.[code];
          return <button type="button" key={code} className={`filter-option ${value === code ? 'is-active' : ''} ${code === 'exploitation_certificates' ? 'certificate-filter' : ''}`} onClick={() => onChange(code)} aria-pressed={value === code}>
            <span className="filter-symbol" style={{ color: REGISTER_COLORS[code] || '#173b42' }}>{code === 'exploitation_certificates' ? <FileCheck2 size={18} /> : <span className="filter-dot" style={{ backgroundColor: REGISTER_COLORS[code] || '#173b42' }} />}</span>
            <span className="filter-label">{t(`filter.${code}`)}{code === 'exploitation_certificates' && <small>{t('filter.certificateHint')}</small>}</span>
            {count !== null && count !== undefined ? <span className="filter-count">{displayCount(count, lang)}</span> : null}
            <span className="filter-check">{value === code && <Check size={13} />}</span>
          </button>;
        })}
      </div>
      <p className="filter-footnote">{t('filter.note')}</p>
    </section>
  );
}
