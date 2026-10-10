import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useI18n } from '@/lib/i18n';
import { formatDateTime, formatDuration } from '@/lib/cadastral';
import StatusPill from '@/components/details/StatusPill';

const STAT_KEYS = [
  ['parcels_new', 'admin.records_imported'],
  ['parcels_updated', 'admin.records_updated'],
  ['parcels_removed', 'admin.records_removed'],
  ['records_rejected', 'admin.records_rejected'],
  ['errors_count', 'admin.errors'],
  ['conflicts_detected', 'admin.conflicts'],
];

export default function RunSummaryCard({ title, run }) {
  const { t, lang } = useI18n();

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {!run ? (
          <p className="text-xs text-muted-foreground">{t('admin.never')}</p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-1.5">
              <StatusPill variant={run.status}>{t(`admin.runStatus.${run.status}`)}</StatusPill>
              <StatusPill variant="muted">{t(`admin.trigger.${run.trigger}`)}</StatusPill>
              <span className="text-[11px] text-muted-foreground">{run.run_code}</span>
            </div>
            <p className="mt-2 text-xs font-medium">
              {formatDateTime(run.finished_at || run.started_at, lang)}
              {run.duration_ms ? ` · ${formatDuration(run.duration_ms)}` : ''}
            </p>
            <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 sm:grid-cols-3">
              <div>
                <dt className="text-[11px] text-muted-foreground">{t('admin.processed')}</dt>
                <dd className="text-sm font-semibold">{run.parcels_processed ?? 0}</dd>
              </div>
              {STAT_KEYS.map(([field, label]) => (
                <div key={field}>
                  <dt className="text-[11px] text-muted-foreground">{t(label)}</dt>
                  <dd className="text-sm font-semibold">{run[field] ?? 0}</dd>
                </div>
              ))}
            </dl>
            {run.log_summary ? (
              <p className="mt-3 rounded-md bg-muted p-2 text-[11px] text-muted-foreground">{run.log_summary}</p>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}