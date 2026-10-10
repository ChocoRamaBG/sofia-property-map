import React from 'react';
import { History } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { formatDateTime } from '@/lib/cadastral';
import DetailSection from '@/components/details/DetailSection';
import StatusPill from '@/components/details/StatusPill';

const VARIANT = { created: 'ok', updated: 'info', removed: 'warning', restored: 'ok' };

export default function HistorySection({ history }) {
  const { t, lang } = useI18n();

  return (
    <DetailSection title={t('section.history')} icon={History} meta={t('section.history')}>
      {!history?.length ? (
        <p className="text-xs text-muted-foreground">{t('history.none')}</p>
      ) : (
        <ol className="space-y-3">
          {history.map((entry) => (
            <li key={entry.id} className="border-l-2 border-border pl-3">
              <div className="flex flex-wrap items-center gap-1.5">
                <StatusPill variant={VARIANT[entry.change_type] || 'info'}>
                  {t(`history.${entry.change_type}`)}
                </StatusPill>
                <span className="text-[11px] text-muted-foreground">{formatDateTime(entry.changed_at, lang)}</span>
              </div>
              {entry.run_code ? (
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  {t('admin.runs')}: {entry.run_code}
                </p>
              ) : null}
              {entry.changed_fields && entry.changed_fields.length ? (
                <ul className="mt-1 space-y-0.5">
                  {entry.changed_fields.map((change, index) => (
                    <li key={index} className="text-[11px]">
                      <span className="font-medium">{change.field}</span>
                      {change.field === 'record' ? null : (
                        <>
                          {change.previous_value ? (
                            <span className="text-muted-foreground"> — {t('history.previous')}: {change.previous_value}</span>
                          ) : null}
                          {change.new_value ? <span> → {change.new_value}</span> : null}
                        </>
                      )}
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          ))}
        </ol>
      )}
    </DetailSection>
  );
}