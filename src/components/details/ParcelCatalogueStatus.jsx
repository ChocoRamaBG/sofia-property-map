import React from 'react';
import { ArrowUpRight, ChevronDown, Info, Layers3 } from 'lucide-react';
import { displayDate } from '@/lib/registerUi';
import './ParcelCatalogueStatus.css';

const OFFICIAL_CATALOGUE = 'https://kais.cadastre.bg/bg/OpenData';

function captureLabel(source, lang) {
  const value = source?.captured_at;
  return typeof value === 'string' && Number.isFinite(Date.parse(value))
    ? displayDate(value, lang) : (lang === 'bg' ? 'Датата на изтегляне не е посочена' : 'Download date not stated');
}

export default function ParcelCatalogueStatus({ status, source, lang = 'bg' }) {
  const pick = (bg, en) => lang === 'bg' ? bg : en;
  const current = status === 'current';
  const historical = status === 'not_in_latest_snapshot';
  const provenance = <div className="parcel-catalogue-provenance"><p>{pick('Изтеглено извлечение:', 'Downloaded snapshot:')} {captureLabel(source, lang)}</p>{source?.district && <p>{pick('Район в източника:', 'Source district:')} {source.district}</p>}<a href={OFFICIAL_CATALOGUE} target="_blank" rel="noreferrer">{pick('Официален каталог · АГКК / КАИС', 'Official catalogue · AGCC / KAIS')}<ArrowUpRight size={13} aria-hidden="true" /></a><p>{pick('Това е изтеглено извлечение, а не проверка в реално време. Проверете актуалните данни в официалния източник.', 'This is a downloaded snapshot, not a real-time check. Consult the official source for current information.')}</p></div>;

  if (historical) return <section className="parcel-catalogue-status is-historical" role="note" aria-label={pick('Наличие в кадастралния каталог', 'Presence in the cadastral catalogue')}>
    <div className="parcel-catalogue-heading"><Info size={17} aria-hidden="true" /><h3>{pick('Идентификаторът не е в последното изтеглено извлечение', 'Identifier not present in the latest downloaded catalogue')}</h3></div>
    <p>{pick('По-старите свързани документи са запазени. Липсата в това извлечение сама по себе си не доказва, че идентификаторът е заличен.', 'Older linked documents are retained. Absence from this snapshot alone is not official proof that the identifier has been cancelled.')}</p>
    <details><summary>{pick('Източник и дата на проверяваното извлечение', 'Source and snapshot date')}<ChevronDown size={14} aria-hidden="true" /></summary>{provenance}</details>
  </section>;

  if (current) return <details className="parcel-catalogue-status is-current">
    <summary><Layers3 size={16} aria-hidden="true" /><span>{pick('В последното заредено кадастрално извлечение', 'Present in the latest loaded cadastral snapshot')}<small>{captureLabel(source, lang)}</small></span><ChevronDown size={14} aria-hidden="true" /></summary>
    <p>{pick('Идентификаторът е намерен в зареденото извлечение на АГКК. Това не установява собственик, придобиване или промени след датата на изтегляне.', 'The identifier is present in the loaded AGCC extract. This establishes neither ownership, acquisition nor changes after the download date.')}</p>{provenance}
  </details>;

  return <details className="parcel-catalogue-status is-unavailable">
    <summary><Info size={16} aria-hidden="true" /><span>{pick('Наличието в последното извлечение не е проверено', 'Presence in the latest snapshot has not been checked')}</span><ChevronDown size={14} aria-hidden="true" /></summary>
    <p>{pick('Проверката в последното кадастрално извлечение не е налична за този запис. Не може да се заключи дали идентификаторът присъства в него.', 'A check against the latest cadastral extract is unavailable for this record. No conclusion can be drawn about whether the identifier is present in it.')}</p>
    <a href={OFFICIAL_CATALOGUE} target="_blank" rel="noreferrer">{pick('Проверете в АГКК / КАИС', 'Check AGCC / KAIS')}<ArrowUpRight size={13} aria-hidden="true" /></a>
  </details>;
}
