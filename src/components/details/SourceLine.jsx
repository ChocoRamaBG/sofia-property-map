import React from 'react';
import { ExternalLink } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { formatDate } from '@/lib/cadastral';
import StatusPill from '@/components/details/StatusPill';

/**
 * Renders exactly where a group of values came from: organisation, dataset,
 * identifier, original URL, parser, source data date and retrieval date.
 */
export default function SourceLine({ provenance, dataset, source }) {
  const { lang, t, pick } = useI18n();
  const sourceName = pick(provenance?.source_name_bg, provenance?.source_name_en)
    || pick(source?.name_bg, source?.name_en)
    || provenance?.source_code;

  const isDemo = (source && source.is_demo) || provenance?.is_demo;
  const isOfficial = source ? source.is_official === true : false;

  return (
    <div className="rounded-md border border-border bg-background/60 p-2.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-xs font-semibold">{sourceName}</span>
        {isDemo ? (
          <StatusPill variant="warning">{t('prov.synthetic')}</StatusPill>
        ) : isOfficial ? (
          <StatusPill variant="ok">{t('prov.official')}</StatusPill>
        ) : (
          <StatusPill variant="muted">{t('value.noData')}</StatusPill>
        )}
      </div>

      <dl className="mt-2 space-y-1">
        <Row label={t('field.dataset')} value={pick(dataset?.name_bg, dataset?.name_en) || provenance?.dataset_code} />
        <Row label={t('field.dataset_id')} value={dataset?.dataset_identifier || provenance?.dataset_identifier} />
        <Row label={t('field.source')} value={source?.organization} />
        <Row label={t('field.parser')} value={provenance?.parser_name} />
        <Row label={t('field.source_date')} value={formatDate(provenance?.source_data_date, lang)} />
        <Row label={t('field.retrieved')} value={formatDate(provenance?.retrieved_date, lang)} />
        <Row label={t('field.last_update')} value={formatDate(dataset?.last_successful_update, lang)} />
      </dl>

      {provenance?.source_url ? (
        <a
          href={provenance.source_url}
          target="_blank"
          rel="noreferrer noopener"
          className="mt-2 inline-flex items-center gap-1 text-[11px] font-medium text-primary underline-offset-2 hover:underline"
        >
          {t('field.source_url')}
          <ExternalLink className="h-3 w-3" aria-hidden="true" />
        </a>
      ) : (
        <p className="mt-2 text-[11px] text-muted-foreground italic">{t('value.notAvailable')}</p>
      )}
    </div>
  );
}

function Row({ label, value }) {
  const { t } = useI18n();
  return (
    <div className="grid grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] gap-2">
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd className="text-[11px] break-words">
        {value ? <span className="font-medium">{value}</span> : <span className="italic text-muted-foreground">{t('value.notAvailable')}</span>}
      </dd>
    </div>
  );
}