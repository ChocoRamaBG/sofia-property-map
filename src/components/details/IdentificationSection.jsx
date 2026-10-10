import React from 'react';
import { Fingerprint } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { formatArea, formatNumber, hasValue } from '@/lib/cadastral';
import DetailSection from '@/components/details/DetailSection';
import FieldRow from '@/components/details/FieldRow';
import SourceLine from '@/components/details/SourceLine';

export default function IdentificationSection({ parcel, provenance, dataset, source }) {
  const { lang, t, pick } = useI18n();
  const hasGeometry =
    hasValue(parcel.vertex_count) || hasValue(parcel.centroid_lat) || hasValue(parcel.geometry_accuracy_m);

  return (
    <DetailSection
      title={t('section.identification')}
      icon={Fingerprint}
      meta={pick(source?.name_bg, source?.name_en)}
    >
      <dl className="divide-y divide-border">
        <FieldRow label={t('field.cadastral_id')} value={parcel.cadastral_id} />
        <FieldRow label={t('field.ekatte')} value={parcel.ekatte} />
        <FieldRow label={t('field.municipality')} value={pick(parcel.municipality_bg, parcel.municipality_en)} />
        <FieldRow label={t('field.region')} value={pick(parcel.region_bg, parcel.region_en)} />
        <FieldRow label={t('field.locality')} value={pick(parcel.locality_bg, parcel.locality_en)} />
        <FieldRow label={t('field.address')} value={pick(parcel.address_bg, parcel.address_en)} />
        <FieldRow label={t('field.area')} value={formatArea(parcel.area_sqm, lang)} />

        {hasGeometry ? (
          <>
            <FieldRow label={t('field.vertices')} value={formatNumber(parcel.vertex_count, lang)} />
            <FieldRow
              label={t('field.centroid')}
              value={
                hasValue(parcel.centroid_lat) && hasValue(parcel.centroid_lng)
                  ? `${Number(parcel.centroid_lat).toFixed(5)}, ${Number(parcel.centroid_lng).toFixed(5)}`
                  : null
              }
            />
            <FieldRow
              label={t('field.accuracy')}
              value={hasValue(parcel.geometry_accuracy_m) ? `± ${parcel.geometry_accuracy_m} ${t('unit.m')}` : null}
            />
            <FieldRow label={t('field.geometrySource')} value={parcel.geometry_source_code} />
          </>
        ) : (
          <FieldRow label={t('field.geometry')} value={null} />
        )}
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