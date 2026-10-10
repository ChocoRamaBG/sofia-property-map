import React from 'react';
import { ExternalLink } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useI18n } from '@/lib/i18n';
import { formatDate } from '@/lib/cadastral';
import StatusPill from '@/components/details/StatusPill';

export default function DatasetsTable({ datasets, sourcesByCode }) {
  const { t, lang, pick } = useI18n();

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold">{t('admin.datasets')}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('admin.dataset')}</TableHead>
                <TableHead>{t('admin.source')}</TableHead>
                <TableHead>{t('admin.format')}</TableHead>
                <TableHead>{t('field.source_date')}</TableHead>
                <TableHead>{t('field.retrieved')}</TableHead>
                <TableHead>{t('field.last_update')}</TableHead>
                <TableHead>{t('field.parser')}</TableHead>
                <TableHead className="text-right">{t('admin.records')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {datasets.map((dataset) => {
                const source = sourcesByCode[dataset.source_code];
                return (
                  <TableRow key={dataset.id}>
                    <TableCell>
                      <span className="block font-medium">{dataset.dataset_code}</span>
                      <span className="block text-[11px] text-muted-foreground">
                        {pick(dataset.name_bg, dataset.name_en)}
                      </span>
                    </TableCell>
                    <TableCell className="text-xs">
                      {source ? (
                        <>
                          <span className="block">{pick(source.name_bg, source.name_en)}</span>
                          <span className="block text-[11px] text-muted-foreground">
                            {source.is_official ? t('admin.official') : t('admin.synthetic')}
                          </span>
                        </>
                      ) : (
                        dataset.source_code
                      )}
                    </TableCell>
                    <TableCell className="text-xs">{dataset.format}</TableCell>
                    <TableCell className="text-xs">{formatDate(dataset.source_data_date, lang) || '—'}</TableCell>
                    <TableCell className="text-xs">{formatDate(dataset.retrieved_date, lang) || '—'}</TableCell>
                    <TableCell className="text-xs">{formatDate(dataset.last_successful_update, lang) || '—'}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{dataset.parser_name}</TableCell>
                    <TableCell className="text-right text-xs">{dataset.record_count ?? 0}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
}

export function SourcesTable({ sources }) {
  const { t, pick } = useI18n();
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold">{t('admin.sources')}</CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="divide-y divide-border">
          {sources.map((source) => (
            <li key={source.id} className="flex flex-wrap items-start gap-2 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold">{pick(source.name_bg, source.name_en)}</p>
                <p className="text-[11px] text-muted-foreground">{source.organization}</p>
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  {pick(source.description_bg, source.description_en)}
                </p>
                {source.homepage_url ? (
                  <a
                    href={source.homepage_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="mt-1 inline-flex items-center gap-1 text-[11px] font-medium text-primary hover:underline"
                  >
                    {source.homepage_url}
                    <ExternalLink className="h-3 w-3" aria-hidden="true" />
                  </a>
                ) : null}
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1">
                <StatusPill variant={source.is_official ? 'ok' : 'warning'}>
                  {source.is_official ? t('admin.official') : t('admin.synthetic')}
                </StatusPill>
                <StatusPill variant={source.ingestion_status === 'connected' ? 'ok' : 'muted'}>
                  {t(
                    source.ingestion_status === 'connected'
                      ? 'admin.connected'
                      : source.ingestion_status === 'error'
                        ? 'admin.ingestError'
                        : 'admin.notConnected'
                  )}
                </StatusPill>
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}