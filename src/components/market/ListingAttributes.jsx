import React from 'react';
import { Building2, ChevronDown, ExternalLink, Phone } from 'lucide-react';
import './ListingAttributes.css';

export const FEATURE_LABELS = {
  construction_type: { brick: ['Тухла', 'Brick'], panel: ['Панел', 'Panel'], epk: ['ЕПК', 'Large-panel formwork'], monolithic: ['Монолитно', 'Monolithic'], other: ['Друга конструкция', 'Other construction'], unknown: ['Неизвестна конструкция', 'Construction unknown'] },
  furnishing: { furnished: ['Обзаведен', 'Furnished'], partial: ['Частично обзаведен', 'Partly furnished'], unfurnished: ['Необзаведен', 'Unfurnished'], unknown: ['Неизвестно обзавеждане', 'Furnishing unknown'] },
  elevator: { yes: ['С асансьор', 'Lift'], no: ['Без асансьор', 'No lift'], unknown: ['Асансьор: неизвестно', 'Lift unknown'] },
};
export function featureLabel(field, value, lang) {
  return (FEATURE_LABELS[field]?.[value] || FEATURE_LABELS[field]?.unknown)?.[lang === 'bg' ? 0 : 1] || value;
}
function safeLink(value, profile = false) {
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || url.port) return null;
    if (profile && url.hostname !== 'imot.bg' && !url.hostname.endsWith('.imot.bg')) return null;
    return url.href;
  } catch { return null; }
}

export default function ListingAttributes({ offer, lang = 'bg' }) {
  const bg = lang === 'bg';
  const features = offer.property_features || {};
  const agency = offer.seller_type === 'agency' && offer.agency?.evidence === 'professional_profile' ? offer.agency : null;
  const profile = agency && safeLink(agency.profile_url, true);
  const website = agency && safeLink(agency.website);
  const phone = agency && /^\+?[0-9]{7,15}$/.test(agency.phone || '') ? agency.phone : null;
  const year = Number.isInteger(features.building_year) ? features.building_year : null;
  const age = year && ['built', 'commissioned'].includes(features.year_basis) && year <= new Date().getFullYear() ? new Date().getFullYear() - year : null;
  return <div className="listing-attributes">
    <div className="listing-feature-tags" aria-label={bg ? 'Характеристики от обявата' : 'Advertised features'}>
      {['construction_type', 'furnishing'].map((field) => <span key={field} className={!features[field] || features[field] === 'unknown' ? 'is-unknown' : ''}>{featureLabel(field, features[field] || 'unknown', lang)}</span>)}
      {features.elevator && features.elevator !== 'unknown' && <span>{featureLabel('elevator', features.elevator, lang)}</span>}
      {year && <span>{features.year_basis === 'planned' ? (bg ? 'Планирано: ' : 'Planned: ') : ''}{year}{age !== null && <> · {age === 0 ? (bg ? 'нова сграда' : 'new building') : `${age} ${bg ? 'г.' : 'years'}`}</>}</span>}
    </div>
    {agency && <details className="listing-agency"><summary><Building2 size={14} aria-hidden="true" /><span>{agency.name}</span><ChevronDown size={14} aria-hidden="true" /></summary><div>
      {phone && <a href={`tel:${phone}`}><Phone size={14} aria-hidden="true" />{phone}</a>}
      {profile && <a href={profile} target="_blank" rel="noreferrer">{bg ? 'Профил на агенцията' : 'Agency profile'}<ExternalLink size={13} aria-hidden="true" /></a>}
      {website && <a href={website} target="_blank" rel="noreferrer">{bg ? 'Сайт на агенцията' : 'Agency website'}<ExternalLink size={13} aria-hidden="true" /></a>}
      <small>{bg ? 'Публични професионални данни от обявата. Комисионата се договаря отделно.' : 'Public professional details from the listing. Commission is agreed separately.'}</small>
    </div></details>}
  </div>;
}
