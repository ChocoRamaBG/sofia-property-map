const db = globalThis.__B44_DB__ || { auth:{ isAuthenticated: async()=>false, me: async()=>null }, entities:new Proxy({}, { get:()=>({ filter:async()=>[], get:async()=>null, create:async()=>({}), update:async()=>({}), delete:async()=>({}) }) }), integrations:{ Core:{ UploadFile:async()=>({ file_url:'' }) } } };

import React, { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, Loader2, RefreshCw, ShieldAlert } from 'lucide-react';

import { useToast } from '@/components/ui/use-toast';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import AppHeader from '@/components/AppHeader';
import { useI18n } from '@/lib/i18n';
import { toItems } from '@/hooks/useViewportParcels';
import { formatDateTime } from '@/lib/cadastral';
import RunSummaryCard from '@/components/admin/RunSummaryCard';
import ParserLogTable from '@/components/admin/ParserLogTable';
import DatasetsTable, { SourcesTable } from '@/components/admin/DatasetsTable';
import StatusPill from '@/components/details/StatusPill';

export default function Admin() {
  const { t, lang } = useI18n();
  const { toast } = useToast();
  const [allowed, setAllowed] = useState(null);
  const [runs, setRuns] = useState([]);
  const [logs, setLogs] = useState([]);
  const [datasets, setDatasets] = useState([]);
  const [sources, setSources] = useState([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [runRes, dsRes, srcRes] = await Promise.all([
        db.entities.UpdateRun.list({ sort: '-started_at', limit: 20 }),
        db.entities.Dataset.list({ limit: 100 }),
        db.entities.DataSource.list({ limit: 100 }),
      ]);
      const runList = toItems(runRes);
      setRuns(runList);
      setDatasets(toItems(dsRes));
      setSources(toItems(srcRes));
      if (runList[0]) {
        const logRes = await db.entities.ParserLog.filter(
          { run_code: runList[0].run_code },
          { limit: 50 }
        );
        setLogs(toItems(logRes));
      } else {
        setLogs([]);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const me = await db.auth.me();
        if (!me || me.role !== 'admin') {
          setAllowed(false);
          setLoading(false);
          return;
        }
        setAllowed(true);
        await load();
      } catch {
        setAllowed(false);
        setLoading(false);
      }
    })();
  }, [load]);

  const handleRun = useCallback(async () => {
    setRunning(true);
    try {
      const response = await db.functions.invoke('runUpdatePipeline', { trigger: 'manual' });
      const payload = response.data || {};
      toast({
        title: t('admin.runs'),
        description: payload.summary || t('admin.runStatus.success'),
      });
      await load();
    } catch (error) {
      toast({
        title: t('admin.runs'),
        description: String((error && error.message) || error),
        variant: 'destructive',
      });
    } finally {
      setRunning(false);
    }
  }, [load, t, toast]);

  const successful = runs.find((run) => run.status === 'success' || run.status === 'partial');

  if (allowed === false) {
    return (
      <div className="flex h-screen flex-col overflow-hidden bg-background">
        <AppHeader />
        <div className="flex flex-1 items-center justify-center p-6">
          <Card className="max-w-sm">
            <CardContent className="flex flex-col items-center gap-3 py-8 text-center">
              <ShieldAlert className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
              <p className="text-sm text-muted-foreground">{t('admin.restricted')}</p>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <AppHeader />
      <main className="mx-auto w-full max-w-6xl space-y-4 p-4">
        <Card>
          <CardHeader className="pb-2">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <CardTitle className="font-heading text-base">{t('admin.title')}</CardTitle>
                <p className="mt-1 text-xs text-muted-foreground">{t('admin.subtitle')}</p>
              </div>
              <Button onClick={handleRun} disabled={running}>
                {running ? (
                  <Loader2 className="mr-1.5 h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <RefreshCw className="mr-1.5 h-4 w-4" aria-hidden="true" />
                )}
                {running ? t('admin.running') : t('admin.runUpdate')}
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-[11px] font-medium text-muted-foreground">{t('admin.pipeline')}</p>
            <p className="mt-1 flex items-start gap-1.5 text-[11px] text-muted-foreground">
              <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-emerald-600" aria-hidden="true" />
              {t('admin.pipelineNote')}
            </p>
          </CardContent>
        </Card>

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-12 text-xs text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            {t('admin.running')}
          </div>
        ) : (
          <>
            <div className="grid gap-4 md:grid-cols-2">
              <RunSummaryCard title={t('admin.lastSuccess')} run={successful} />
              <RunSummaryCard title={t('admin.lastAttempt')} run={runs[0]} />
            </div>

            <ParserLogTable logs={logs} />

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold">{t('admin.runs')}</CardTitle>
              </CardHeader>
              <CardContent>
                {!runs.length ? (
                  <p className="text-xs text-muted-foreground">{t('admin.noRuns')}</p>
                ) : (
                  <ul className="divide-y divide-border">
                    {runs.map((run) => (
                      <li key={run.id} className="flex flex-wrap items-center gap-2 py-2">
                        <StatusPill variant={run.status}>{t(`admin.runStatus.${run.status}`)}</StatusPill>
                        <span className="text-xs font-medium">{run.run_code}</span>
                        <span className="text-[11px] text-muted-foreground">
                          {formatDateTime(run.started_at, lang)}
                        </span>
                        <span className="text-[11px] text-muted-foreground">
                          {t(`admin.trigger.${run.trigger}`)}
                        </span>
                        <span className="ml-auto text-[11px] text-muted-foreground">{run.log_summary}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>

            <DatasetsTable
              datasets={datasets}
              sourcesByCode={Object.fromEntries(sources.map((source) => [source.code, source]))}
            />
            <SourcesTable sources={sources} />
          </>
        )}
      </main>
    </div>
  );
}