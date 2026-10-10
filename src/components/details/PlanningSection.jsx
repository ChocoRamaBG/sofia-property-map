import React from 'react';
import { Ruler } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { formatNumber, hasValue } from '@/lib/cadastral';
import DetailSection from '@/components/details/DetailSection';
import FieldRow from '@/components/details/FieldRow';
import SourceLine from '@/components/details/SourceLine';

export default function PlanningSection({ parcel, provenance, dataset, source }) {
  const { lang, t, pick } = useI18n();

  return (
    <DetailSection title={t('section.planning')} icon={Ruler} meta={pick(source?.name_bg, source?.name_en)}>
      <dl className="divide-y divide-border">
        <FieldRow label={t('field.zoning')} value={pick(parcel.zoning_bg, parcel.zoning_en)} />
        <FieldRow label={t('field.planning_status')} value={pick(parcel.planning_status_bg, parcel.planning_status_en)} />
        <FieldRow
          label={t('field.max_height')}
          value={hasValue(parcel.max_building_height_m) ? `${formatNumber(parcel.max_building_height_m, lang)} ${t('unit.m')}` : null}
        />
        <FieldRow
          label={t('field.max_density')}
          value={hasValue(parcel.max_density_pct) ? `${formatNumber(parcel.max_density_pct, lang)} ${t('unit.percent')}` : null}
        />
        <FieldRow label={t('field.protected_area')} value={pick(parcel.protected_area_bg, parcel.protected_area_en)} />
        <FieldRow
          label={t('field.restrictions')}
          value={parcel.restrictions && parcel.restrictions.length ? parcel.restrictions.join('; ') : null}
        />
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