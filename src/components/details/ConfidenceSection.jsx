import React from 'react';
import { Gauge } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { FIELD_LABEL_KEYS, daysSince, formatDateTime } from '@/lib/cadastral';
import DetailSection from '@/components/details/DetailSection';
import FieldRow from '@/components/details/FieldRow';
import StatusPill from '@/components/details/StatusPill';

export default function ConfidenceSection({ parcel }) {
  const { t, lang } = useI18n();
  const age = daysSince(parcel.retrieved_date);
  const freshness = age === null ? null : age === 0 ? t('time.today') : t('time.daysAgo', { n: age });

  const parseVariant =
    parcel.parse_status === 'ok' ? 'ok' : parcel.parse_status === 'failed' ? 'failed' : 'partial';
  const confidenceVariant =
    parcel.data_confidence === 'high' ? 'ok' : parcel.data_confidence === 'low' ? 'warning' : 'info';

  const missing = parcel.missing_fields || [];

  return (
    <DetailSection title={t('section.confidence')} icon={Gauge} meta={t('status.active')}>
      <div className="mb-3 flex flex-wrap gap-1.5">
        <StatusPill variant={parseVariant}>{t(`status.${parcel.parse_status}`)}</StatusPill>
        <StatusPill variant={confidenceVariant}>
          {t('field.confidence')}: {t(`confidence.${parcel.data_confidence}`)}
        </StatusPill>
        <StatusPill variant="muted">
          {t('field.freshness')}: {freshness || t('value.notAvailable')}
        </StatusPill>
      </div>

      <dl className="divide-y divide-border">
        <FieldRow label={t('field.first_seen')} value={formatDateTime(parcel.first_seen, lang)} />
        <FieldRow label={t('field.last_update')} value={formatDateTime(parcel.last_updated, lang)} />
        <FieldRow label={t('field.retrieved')} value={formatDateTime(parcel.retrieved_date, lang)} />
        <FieldRow label={t('field.source_date')} value={formatDateTime(parcel.source_record_date, lang)} />
      </dl>

      <div className="mt-3">
        <h4 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          {t('value.missingValues')}
        </h4>
        {missing.length ? (
          <ul className="mt-1 flex flex-wrap gap-1.5">
            {missing.map((field) => (
              <li key={field}>
                <StatusPill variant="warning">
                  {FIELD_LABEL_KEYS[field] ? t(FIELD_LABEL_KEYS[field]) : field}
                </StatusPill>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-[11px] text-muted-foreground">{t('value.noneMissing')}</p>
        )}
      </div>
    </DetailSection>
  );
}