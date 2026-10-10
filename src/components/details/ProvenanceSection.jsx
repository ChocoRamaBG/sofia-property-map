import React from 'react';
import { Link2 } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { FIELD_LABEL_KEYS, GROUP_KEYS } from '@/lib/cadastral';
import DetailSection from '@/components/details/DetailSection';
import SourceLine from '@/components/details/SourceLine';
import StatusPill from '@/components/details/StatusPill';

const GROUP_LABEL = {
  identification: 'prov.group.identification',
  property: 'prov.group.property',
  planning: 'prov.group.planning',
  geometry: 'prov.group.geometry',
};

function fieldLabel(t, field) {
  const key = FIELD_LABEL_KEYS[field];
  return key ? t(key) : field;
}

export default function ProvenanceSection({ provenanceByGroup, datasetsByCode, sourcesByCode }) {
  const { t } = useI18n();

  const sourceCodes = new Set();
  const groupCount = GROUP_KEYS.filter((g) => (provenanceByGroup[g] || []).length);
  groupCount.forEach((g) => (provenanceByGroup[g] || []).forEach((row) => sourceCodes.add(row.source_code)));
  const multiSource = sourceCodes.size > 1;

  return (
    <DetailSection title={t('section.provenance')} icon={Link2} meta={t('section.provenance')}>
      {multiSource ? (
        <p className="mb-3 rounded-md border border-sky-200 bg-sky-50 p-2 text-[11px] text-sky-900">
          {t('prov.multiSource')}
        </p>
      ) : null}

      <div className="space-y-4">
        {groupCount.map((group) => (
          <div key={group}>
            <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              {t(GROUP_LABEL[group] || 'section.provenance')}
            </h4>
            <div className="space-y-2">
              {(provenanceByGroup[group] || []).map((row, index) => (
                <div key={index}>
                  <SourceLine
                    provenance={row}
                    dataset={datasetsByCode[row.dataset_code]}
                    source={sourcesByCode[row.source_code]}
                  />
                  {row.entries && row.entries.length ? (
                    <ul className="mt-1.5 space-y-0.5 pl-1">
                      {row.entries.map((entry, i) => (
                        <li key={i} className="flex flex-wrap items-baseline gap-1.5 text-[11px]">
                          <span className="text-muted-foreground">{fieldLabel(t, entry.field)}:</span>
                          <span className="font-medium break-words">{entry.value}</span>
                          {entry.parse_status !== 'ok' ? (
                            <StatusPill variant="warning">{t(`status.${entry.parse_status}`)}</StatusPill>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </DetailSection>
  );
}