import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useI18n } from '@/lib/i18n';
import { formatDuration } from '@/lib/cadastral';
import StatusPill from '@/components/details/StatusPill';

export default function ParserLogTable({ logs }) {
  const { t } = useI18n();

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold">{t('admin.parserLogs')}</CardTitle>
      </CardHeader>
      <CardContent>
        {!logs.length ? (
          <p className="text-xs text-muted-foreground">{t('admin.noRuns')}</p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('admin.dataset')}</TableHead>
                  <TableHead>{t('admin.parser')}</TableHead>
                  <TableHead>{t('admin.status')}</TableHead>
                  <TableHead className="text-right">{t('admin.read')}</TableHead>
                  <TableHead className="text-right">{t('admin.valid')}</TableHead>
                  <TableHead className="text-right">{t('admin.written')}</TableHead>
                  <TableHead className="text-right">{t('admin.updated')}</TableHead>
                  <TableHead className="text-right">{t('admin.removed')}</TableHead>
                  <TableHead className="text-right">{t('admin.errors')}</TableHead>
                  <TableHead className="text-right">{t('admin.duration')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {logs.map((log) => (
                  <TableRow key={log.id}>
                    <TableCell className="font-medium">{log.dataset_code}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{log.parser_name}</TableCell>
                    <TableCell>
                      <StatusPill variant={log.status}>{t(`admin.runStatus.${log.status === 'skipped' ? 'partial' : log.status}`)}</StatusPill>
                    </TableCell>
                    <TableCell className="text-right">{log.records_read ?? 0}</TableCell>
                    <TableCell className="text-right">{log.records_valid ?? 0}</TableCell>
                    <TableCell className="text-right">{log.records_written ?? 0}</TableCell>
                    <TableCell className="text-right">{log.records_updated ?? 0}</TableCell>
                    <TableCell className="text-right">{log.records_removed ?? 0}</TableCell>
                    <TableCell className="text-right">{log.errors_count ?? 0}</TableCell>
                    <TableCell className="text-right text-xs text-muted-foreground">
                      {formatDuration(log.duration_ms) || '—'}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        {logs.filter((l) => l.error_message || (l.messages && l.messages.length)).length ? (
          <div className="mt-3 space-y-2">
            {logs
              .filter((l) => l.error_message || (l.messages && l.messages.length))
              .map((log) => (
                <div key={`${log.id}-msg`} className="rounded-md border border-border bg-background/60 p-2.5">
                  <p className="text-[11px] font-semibold">
                    {log.dataset_code}
                    {log.error_message ? (
                      <span className="ml-1.5 font-normal text-rose-700">
                        {t('admin.errorMessage')}: {log.error_message}
                      </span>
                    ) : null}
                  </p>
                  {log.messages && log.messages.length ? (
                    <ul className="mt-1 space-y-0.5">
                      {log.messages.map((message, index) => (
                        <li key={index} className="text-[11px] text-muted-foreground">
                          {message}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ))}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}