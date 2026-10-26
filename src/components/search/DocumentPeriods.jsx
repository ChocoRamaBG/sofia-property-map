import React, { useId } from 'react';
import { CalendarDays, ChevronDown, RotateCcw } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { displayDate } from '@/lib/registerUi';

const TYPES = [
  ['building_permits', 'Разрешения за строеж', 'Building permits'],
  ['projecting_visas', 'Визи за проектиране', 'Design visas'],
  ['exploitation_certificates', 'Въвеждане в експлоатация', 'Putting into use'],
];

export default function DocumentPeriods({ filters, options, disabled, onChange }) {
  const { lang } = useI18n();
  const id = useId();
  const bg = lang === 'bg';
  const update = (type, range) => onChange(type, range);
  const active = TYPES.filter(([type]) => filters.documentDates[type]?.from || filters.documentDates[type]?.to).length;
  return <details className="document-periods filter-disclosure filter-period-disclosure">
    <summary className="filter-disclosure-heading"><CalendarDays size={17} aria-hidden="true" /><span><strong id={id + '-title'}>{bg ? 'Дата на документите' : 'Document dates'}</strong><small>{active ? (bg ? `${active} зададени периода по вид документ` : `${active} selected document periods`) : bg ? 'Година, месец или точни дати за всеки вид' : 'Year, month or exact dates for each type'}</small></span>{active > 0 && <span className="filter-active-count">{active}</span>}<ChevronDown size={17} aria-hidden="true" /></summary>
    <div className="document-periods-body" aria-labelledby={id + '-title'}>
    <p className="document-periods-explanation">{bg ? 'Изберете документа, после периода. Използваме датата на издаване.' : 'Choose the document, then its period. Dates refer to issue dates.'}</p>
    {TYPES.map(([type, labelBg, labelEn]) => {
      const range = filters.documentDates[type] || { from: '', to: '' };
      const available = options?.document_date_ranges?.[type];
      const label = bg ? labelBg : labelEn;
      const hasRange = Boolean(range.from || range.to);
      const minYear = Number(String(available?.date_min || '').slice(0, 4));
      const maxYear = Number(String(available?.date_max || '').slice(0, 4));
      const years = minYear > 1800 && maxYear >= minYear ? Array.from({ length: Math.min(150, maxYear - minYear + 1) }, (_, i) => maxYear - i) : [];
      const selectedYear = range.from && range.to && range.from.slice(0, 4) === range.to.slice(0, 4) ? range.from.slice(0, 4) : '';
      if (selectedYear && !years.includes(Number(selectedYear))) years.unshift(Number(selectedYear));
      const invalid = range.from && range.to && range.from > range.to;
      const selectedMonth = selectedYear && range.from.slice(0, 7) === range.to.slice(0, 7) ? range.from.slice(5, 7) : '';
      const monthRange = (year, month) => {
        if (!year) return { from: '', to: '' };
        if (!month) return { from: `${year}-01-01`, to: `${year}-12-31` };
        const end = new Date(Date.UTC(Number(year), Number(month), 0)).getUTCDate();
        return { from: `${year}-${month}-01`, to: `${year}-${month}-${end}` };
      };
      return <details key={type} className={'document-period-row ' + (hasRange ? 'is-active' : '')}>
        <summary><span><strong>{label}</strong><small>{hasRange ? `${range.from ? displayDate(range.from, lang) : '…'} – ${range.to ? displayDate(range.to, lang) : '…'}` : bg ? 'Всички налични дати' : 'All available dates'}</small></span><ChevronDown size={16} /></summary>
        <fieldset disabled={disabled} className="document-period-controls"><legend className="sr-only">{label}</legend>
          <div className="filter-date-fields">
            <label className="filter-field"><span>{bg ? 'Година' : 'Year'}</span><select value={selectedYear} onChange={(event) => update(type, monthRange(event.target.value, ''))}><option value="">{bg ? 'Изберете година' : 'Choose year'}</option>{years.map((year) => <option value={year} key={year}>{year}</option>)}</select></label>
            <label className="filter-field"><span>{bg ? 'Месец' : 'Month'}</span><select value={selectedMonth} disabled={!selectedYear} onChange={(event) => update(type, monthRange(selectedYear, event.target.value))}><option value="">{bg ? 'Цялата година' : 'Entire year'}</option>{Array.from({ length: 12 }, (_, month) => <option key={month} value={String(month + 1).padStart(2, '0')}>{new Intl.DateTimeFormat(bg ? 'bg-BG' : 'en-GB', { month: 'long', timeZone: 'UTC' }).format(new Date(Date.UTC(2024, month, 1)))}</option>)}</select></label>
          </div>
          <details className="document-custom-range"><summary>{bg ? 'Задай точни начална и крайна дата' : 'Set exact start and end dates'}<ChevronDown size={14} aria-hidden="true" /></summary><div className="filter-date-fields">
            <label className="filter-field"><span>{bg ? 'От дата' : 'From date'}</span><input type="date" value={range.from} max={range.to || undefined} aria-label={`${label} — ${bg ? 'от дата' : 'from date'}`} aria-invalid={invalid || undefined} aria-describedby={invalid ? `${id}-${type}-error` : undefined} onChange={(event) => update(type, { ...range, from: event.target.value })} /></label>
            <label className="filter-field"><span>{bg ? 'До дата' : 'To date'}</span><input type="date" value={range.to} min={range.from || undefined} aria-label={`${label} — ${bg ? 'до дата' : 'to date'}`} aria-invalid={invalid || undefined} aria-describedby={invalid ? `${id}-${type}-error` : undefined} onChange={(event) => update(type, { ...range, to: event.target.value })} /></label>
          </div></details>
          {invalid && <p id={`${id}-${type}-error`} className="filter-field-error" role="alert">{bg ? 'Началната дата трябва да е преди крайната.' : 'The start date must precede the end date.'}</p>}
          <div className="filter-date-presets">
            {available?.date_max && <button type="button" onClick={() => update(type, monthRange(available.date_max.slice(0, 4), available.date_max.slice(5, 7)))}>{bg ? 'Най-новият месец в набора' : 'Latest month in the dataset'}</button>}
            {available?.date_max && <button type="button" onClick={() => { const end = available.date_max; const start = new Date(end + 'T12:00:00Z'); start.setUTCDate(start.getUTCDate() - 89); update(type, { from: start.toISOString().slice(0, 10), to: end }); }}>{bg ? 'Най-новите 90 дни в набора' : 'Latest 90 days in the dataset'}</button>}
            {hasRange && <button type="button" onClick={() => update(type, { from: '', to: '' })}><RotateCcw size={12} />{bg ? 'Изчисти периода' : 'Clear period'}</button>}
          </div>
          {available?.date_max && <p className="filter-field-help">{bg ? 'Последна налична дата на издаване: ' : 'Latest available issue date: '}{displayDate(available.date_max, lang)}</p>}
        </fieldset>
      </details>;
    })}
    {active > 1 && <p className="filter-field-help">{bg ? 'Всеки зададен период изисква съответния документ за имота. За сравнение на общия брой документи отворете „Строителна активност“.' : 'Each selected period requires its named document for the parcel. Use Construction activity to compare document totals.'}</p>}
    {disabled && <p className="filter-field-help">{bg ? 'Периодите изискват свързани документи и заредени регистрови дати.' : 'Periods require linked records and loaded registry dates.'}</p>}
    </div>
  </details>;
}
