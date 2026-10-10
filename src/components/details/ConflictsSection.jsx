import React from 'react';
import { AlertTriangle } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import DetailSection from '@/components/details/DetailSection';
import StatusPill from '@/components/details/StatusPill';

export default function ConflictsSection({ conflicts }) {
  const { t } = useI18n();
  if (!conflicts?.length) return null;

  return (
    <DetailSection title={t('section.conflicts')} icon={AlertTriangle} meta={t('conflict.warning')}>
      <p className="mb-3 rounded-md border border-amber-200 bg-amber-50 p-2 text-[11px] text-amber-900">
        {t('conflict.warning')}
      </p>
      <div className="space-y-2.5">
        {conflicts.map((conflict) => (
          <div key={conflict.id} className="rounded-md border border-border bg-background/60 p-2.5">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs font-semibold">{conflict.field_name}</span>
              <StatusPill variant="warning">{t(`conflict.type.${conflict.conflict_type}`)}</StatusPill>
              <StatusPill variant={conflict.status === 'open' ? 'warning' : 'ok'}>
                {conflict.status === 'open' ? t('conflict.open') : t('conflict.resolved')}
              </StatusPill>
            </div>
            <ul className="mt-2 space-y-1.5">
              {(conflict.values || []).map((value, index) => (
                <li key={index} className="rounded border border-border bg-card p-2">
                  <p className="text-xs font-medium break-words">
                    {value.value === '' || value.value === undefined ? (
                      <span className="italic text-muted-foreground">{t('value.notAvailable')}</span>
                    ) : (
                      value.value
                    )}
                  </p>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">
                    {t('field.source')}: {value.source_code}
                    {value.dataset_code ? ` · ${value.dataset_code}` : ''}
                    {value.retrieved_date ? ` · ${value.retrieved_date}` : ''}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </DetailSection>
  );
}