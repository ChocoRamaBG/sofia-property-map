import React from 'react';
import { Building2, Info } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { formatNumber } from '@/lib/cadastral';
import DetailSection from '@/components/details/DetailSection';
import FieldRow from '@/components/details/FieldRow';
import StatusPill from '@/components/details/StatusPill';

function BuildingCard({ building, links, lang, t, pick }) {
  const relationship = links[0]?.relationship || 'unknown';
  const linkedPlots = links.map((l) => l.parcel_cadastral_id);
  return (
    <div className="rounded-md border border-border bg-background/60 p-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-xs font-semibold">
            {pick(building.name_bg, building.name_en) || building.building_id}
          </p>
          <p className="truncate text-[11px] text-muted-foreground">
            {pick(building.building_type_bg, building.building_type_en)}
          </p>
        </div>
        <StatusPill variant={relationship === 'crosses_plots' ? 'warning' : 'muted'}>
          {t(`building.relationship.${relationship}`)}
        </StatusPill>
      </div>

      <dl className="mt-2 divide-y divide-border">
        <FieldRow label={t('field.building_id')} value={building.building_id} />
        <FieldRow label={t('field.floors')} value={formatNumber(building.floors_count, lang)} />
        <FieldRow label={t('field.underground')} value={formatNumber(building.underground_floors, lang)} />
        <FieldRow
          label={t('field.height')}
          value={building.height_m ? `${formatNumber(building.height_m, lang)} ${t('unit.m')}` : null}
        />
        <FieldRow
          label={t('field.built_area')}
          value={building.built_area_sqm ? `${formatNumber(building.built_area_sqm, lang)} ${t('unit.sqm')}` : null}
        />
        <FieldRow
          label={t('field.total_area')}
          value={building.total_area_sqm ? `${formatNumber(building.total_area_sqm, lang)} ${t('unit.sqm')}` : null}
        />
        <FieldRow label={t('field.apartments')} value={formatNumber(building.apartments_count, lang)} />
        <FieldRow label={t('field.year_built')} value={formatNumber(building.year_built, lang)} />
        <FieldRow label={t('field.construction')} value={pick(building.construction_type_bg, building.construction_type_en)} />
        <FieldRow label={t('field.status')} value={pick(building.status_bg, building.status_en)} />
        {linkedPlots.length > 1 ? (
          <FieldRow label={t('field.linkedPlots')} value={linkedPlots.join(', ')} />
        ) : null}
      </dl>
    </div>
  );
}

export default function BuildingsSection({ buildings, linksByBuilding }) {
  const { lang, t, pick } = useI18n();

  return (
    <DetailSection
      title={t('section.buildings')}
      icon={Building2}
      meta={t('building.buildingData')}
    >
      {buildings.length === 0 ? (
        <div>
          <p className="text-xs text-muted-foreground">{t('building.none')}</p>
          <p className="mt-2 flex items-start gap-1.5 rounded-md bg-muted p-2 text-[11px] text-muted-foreground">
            <Info className="mt-0.5 h-3 w-3 shrink-0" aria-hidden="true" />
            {t('building.separateNote')}
          </p>
        </div>
      ) : (
        <div className="space-y-2.5">
          <p className="flex items-start gap-1.5 text-[11px] text-muted-foreground">
            <Info className="mt-0.5 h-3 w-3 shrink-0" aria-hidden="true" />
            {t('building.separateNote')}
          </p>
          {buildings.map((building) => (
            <BuildingCard
              key={building.building_id}
              building={building}
              links={linksByBuilding[building.building_id] || []}
              lang={lang}
              t={t}
              pick={pick}
            />
          ))}
        </div>
      )}
    </DetailSection>
  );
}