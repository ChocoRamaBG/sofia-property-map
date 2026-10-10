export const REGISTER_FILTERS = ['all', 'exploitation_certificates', 'building_permits', 'projecting_visas', 'no_records'];
export const REGISTER_COLORS = { exploitation_certificates: '#047857', building_permits: '#c17b1b', projecting_visas: '#6d5bb9', no_records: '#64748b' };

export function pointType(plot) {
  if (plot.has_exploitation_certificate) return 'exploitation_certificates';
  if (plot.has_building_permit) return 'building_permits';
  if (plot.has_projecting_visa) return 'projecting_visas';
  return 'no_records';
}

export function displayDate(value, lang = 'bg') {
  if (!value) return null;
  const text = String(value);
  if (/^\d{4}-\d{2}-\d{2}T/.test(text)) {
    const timestamp = new Date(text);
    if (!Number.isNaN(timestamp.getTime())) {
      const parts = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Sofia', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(timestamp);
      const date = Object.fromEntries(parts.map(({ type, value: part }) => [type, part]));
      return lang === 'bg' ? `${date.day}.${date.month}.${date.year}` : `${date.year}-${date.month}-${date.day}`;
    }
  }
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return match ? (lang === 'bg' ? `${match[3]}.${match[2]}.${match[1]}` : `${match[1]}-${match[2]}-${match[3]}`) : String(value);
}

export function displayCount(value, lang = 'bg') {
  return Number(value || 0).toLocaleString(lang === 'bg' ? 'bg-BG' : 'en-GB');
}

// Certificate column order is verified against the official municipal register.
// Other unlabelled columns retain a neutral label until their meaning is verified.
const COLUMN_LABELS = {
  exploitation_certificates: {
    1: ['Номер и дата', 'Number and date'], 3: ['Издател', 'Issuer'],
    4: ['Строителен надзор', 'Construction supervision'], 5: ['Строеж / обект', 'Construction / project'],
    6: ['Район', 'District'], 7: ['Обхват и идентификатори', 'Scope and identifiers'],
  },
  building_permits: {
    1: ['Номер и дата', 'Number and date'], 5: ['Издател', 'Issuer'],
    7: ['Строеж / обект', 'Construction / project'], 8: ['Район', 'District'],
    9: ['Обхват и идентификатори', 'Scope and identifiers'],
  },
  projecting_visas: {
    1: ['Дата', 'Date'], 2: ['Влязъл в сила', 'Effective date'], 3: ['Основание', 'Legal basis'],
    4: ['Издател', 'Issuer'], 5: ['Район', 'District'], 6: ['Обхват и идентификатори', 'Scope and identifiers'],
  },
};

export function fieldLabel(sourceCode, label, lang = 'bg') {
  const match = String(label).match(/^Column\s+(\d+)$/i);
  if (!match) return label;
  const mapped = COLUMN_LABELS[sourceCode]?.[Number(match[1])];
  return mapped ? mapped[lang === 'bg' ? 0 : 1] : `${lang === 'bg' ? 'Поле от регистъра' : 'Register field'} ${match[1]}`;
}

export function fieldValue(sourceCode, label, value, lang = 'bg') {
  if (sourceCode === 'projecting_visas' && /^Column\s+[12]$/i.test(label) && typeof value === 'number' && value > 20000 && value < 70000) {
    return displayDate(new Date(Date.UTC(1899, 11, 30) + value * 86400000).toISOString(), lang);
  }
  return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value ?? '');
}
