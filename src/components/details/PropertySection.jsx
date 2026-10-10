import React from 'react';
import { FileText } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { OWNERSHIP_KEYS, formatArea, formatNumber, hasValue } from '@/lib/cadastral';
import DetailSection from '@/components/details/DetailSection';
import FieldRow from '@/components/details/FieldRow';
import SourceLine from '@/components/details/SourceLine';

export default function PropertySection({ parcel, provenance, dataset, source }) {
  const { lang, t, pick } = useI18n();
  const ownership = parcel.ownership_type ? pick(OWNERSHIP_KEYS[parcel.ownership_type]?.bg, OWNERSHIP_KEYS[parcel.ownership_type]?.en) : null;

  return (
    <DetailSection title={t('section.property')} icon={FileText} meta={pick(source?.name_bg, source?.name_en)}>
      <dl className="divide-y divide-border">
        <FieldRow label={t('field.land_use')} value={pick(parcel.land_use_bg, parcel.land_use_en)} />
        <FieldRow label={t('field.purpose')} value={pick(parcel.purpose_bg, parcel.purpose_en)} />
        <FieldRow label={t('field.ownership')} value={ownership} />
        <FieldRow label={t('field.area')} value={formatArea(parcel.area_sqm, lang)} hint={t('field.source_date') + ': ' + (parcel.source_record_date || '—')} />
        <FieldRow
          label={t('field.status')}
          value={t(parcel.status === 'archived' ? 'status.archived' : 'status.active')}
        />
        {hasValue(parcel.max_built_ratio) ? (
          <FieldRow label={t('field.max_ratio')} value={formatNumber(parcel.max_built_ratio, lang)} />
        ) : null}
      </dl>

      {provenance?.length ? (
        <div className="mt-3 space-y-2">
          {provenance.map((row, index) => (
            <SourceLine key={index} provenance={row} dataset={dataset} source={source} />
          ))}
        </div>
      ) : null}
    </DetailSection>
  );
}