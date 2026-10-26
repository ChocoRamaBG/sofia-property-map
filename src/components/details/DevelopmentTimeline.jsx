import React from 'react';
import { ArrowDown, FileCheck2, HardHat, PenTool } from 'lucide-react';
import { displayDate } from '@/lib/registerUi';

const STAGES = [
  { codes: ['projecting_visas'], Icon: PenTool, bg: 'Виза за проектиране', en: 'Design visa', helpBg: 'Параметри за проектиране по устройствен план.', helpEn: 'Design parameters under the development plan.' },
  { codes: ['building_permits'], Icon: HardHat, bg: 'Разрешение за строеж', en: 'Building permit', helpBg: 'Разрешен строеж; началото му се установява отделно.', helpEn: 'An authorized project; its actual start is recorded separately.' },
  { codes: ['exploitation_certificates', 'exploitation_certificates_legacy'], Icon: FileCheck2, bg: 'Въвеждане в експлоатация', en: 'Putting into use', helpBg: 'Свързан документ за въвеждане на строеж в експлоатация.', helpEn: 'A linked record for putting a construction into use.' },
];

export default function DevelopmentTimeline({ sources, lang, onOpenSource }) {
  const bg = lang === 'bg';
  return <section className="property-development-timeline" aria-label={bg ? 'Документални етапи' : 'Documentary stages'}>
    <div className="property-development-heading"><h3>{bg ? 'Документи за развитие' : 'Development records'}</h3><span>{bg ? 'Официални регистри' : 'Official registers'}</span></div>
    <ol>{STAGES.map(({ codes, Icon, bg: labelBg, en, helpBg, helpEn }) => {
      const records = sources.filter((source) => codes.includes(source.code)).flatMap((source) => (source.documents || []).map((document) => ({ ...document, source })));
      const known = records.filter((document) => document.issued_at).sort((a, b) => b.issued_at.localeCompare(a.issued_at));
      const latest = known[0];
      const firstSource = latest?.source || records[0]?.source;
      return <li key={codes[0]} className={records.length ? 'has-record' : ''}>
        <span className="development-stage-icon"><Icon size={16} /></span><div><strong>{bg ? labelBg : en}</strong><p>{bg ? helpBg : helpEn}</p>
          {records.length ? <button type="button" onClick={() => onOpenSource(firstSource.code)}>{latest ? `${bg ? 'Последна дата: ' : 'Latest date: '}${displayDate(latest.issued_at, lang)}` : bg ? 'Няма известна дата на издаване' : 'Issue date unavailable'}<ArrowDown size={12} /><small>{records.length} {bg ? 'записа' : 'records'}</small></button> : <small>{bg ? 'Няма свързан запис в наличните данни' : 'No linked record in the available data'}</small>}
        </div>
      </li>;
    })}</ol>
    <p className="development-stage-evidence">{bg ? 'Документите могат да са за различни строежи в един имот. Те не доказват покупка на терена, смяна на собственик или наличие на дял за продажба.' : 'Documents may concern different constructions on one parcel. They do not prove a land purchase, ownership change or a share available for sale.'}</p>
  </section>;
}
