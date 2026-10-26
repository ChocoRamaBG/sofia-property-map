import React, { useEffect, useId, useState } from 'react';
import * as SliderPrimitive from '@radix-ui/react-slider';
import { CalendarDays, ChevronDown, RotateCcw, X } from 'lucide-react';
import DocumentTypeIcon from '@/components/DocumentTypeIcon';
import { useI18n } from '@/lib/i18n';
import { displayDate, REGISTER_COLORS } from '@/lib/registerUi';

const TYPES = [
  ['building_permits', 'Разрешения за строеж', 'Building permits'],
  ['projecting_visas', 'Визи за проектиране', 'Design visas'],
  ['exploitation_certificates', 'Въвеждане в експлоатация · Акт 16', 'Putting into use · Act 16'],
];
const DAY_MS = 86400000;

function dateDay(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith('0000')) return null;
  const timestamp = Date.parse(`${value}T00:00:00Z`);
  return Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 10) === value ? Math.round(timestamp / DAY_MS) : null;
}
function dayDate(value) { return new Date(Math.round(value) * DAY_MS).toISOString().slice(0, 10); }
function monthRange(year, month) {
  if (!year) return { from: '', to: '' };
  if (!month) return { from: `${year}-01-01`, to: `${year}-12-31` };
  const end = new Date(Date.UTC(Number(year), Number(month), 0)).getUTCDate();
  return { from: `${year}-${month}-01`, to: `${year}-${month}-${end}` };
}

function PeriodSlider({ id, label, range, available, disabled, lang, onChange }) {
  const [draft, setDraft] = useState(null);
  const bg = lang === 'bg';
  const sourceMin = dateDay(available?.date_min);
  const sourceMax = dateDay(available?.date_max);
  const from = dateDay(range.from);
  const to = dateDay(range.to);
  const known = sourceMin !== null && sourceMax !== null && sourceMin <= sourceMax;
  const invalid = from !== null && to !== null && from > to;
  // Preserve saved exact-date filters outside the current source extent.
  const extent = [sourceMin, sourceMax, from, to].filter((value) => value !== null);
  const minimum = known ? Math.min(...extent) : 0;
  const maximum = known ? Math.max(...extent) : 1;
  const movable = known && minimum < maximum && !invalid && !disabled;
  const selected = known && !invalid ? [from ?? minimum, to ?? maximum] : [minimum, maximum];
  const values = draft || selected;
  useEffect(() => { setDraft(null); }, [range.from, range.to, sourceMin, sourceMax, disabled]);
  const formatted = (value) => displayDate(dayDate(value), lang);
  return <div className="document-timeframe">
    <div className="document-timeframe-values">
      <span><small>{bg ? 'От' : 'From'}</small><strong>{known ? formatted(values[0]) : '—'}</strong></span>
      <span><small>{bg ? 'До' : 'To'}</small><strong>{known ? formatted(values[1]) : '—'}</strong></span>
    </div>
    <SliderPrimitive.Root className="document-timeframe-slider" value={values} min={minimum} max={maximum > minimum ? maximum : minimum + 1} step={1} minStepsBetweenThumbs={0} disabled={!movable}
      aria-label={label} aria-describedby={id + '-extent'}
      onValueChange={setDraft}
      onValueCommit={(next) => {
        setDraft(null);
        if (movable) onChange({ from: dayDate(next[0]), to: dayDate(next[1]) });
      }}>
      <SliderPrimitive.Track className="document-timeframe-track"><SliderPrimitive.Range className="document-timeframe-range" /></SliderPrimitive.Track>
      {[0, 1].map((index) => <SliderPrimitive.Thumb key={index} className="document-timeframe-thumb" aria-label={`${label} — ${index === 0 ? (bg ? 'начална дата' : 'start date') : (bg ? 'крайна дата' : 'end date')}`} aria-valuetext={known ? formatted(values[index]) : (bg ? 'Няма налични дати' : 'No available dates')} aria-describedby={id + '-extent'} />)}
    </SliderPrimitive.Root>
    <p className="document-timeframe-extent" id={id + '-extent'}>{known ? `${bg ? 'Налични дати:' : 'Available dates:'} ${displayDate(available.date_min, lang)} – ${displayDate(available.date_max, lang)}` : bg ? 'Няма налични дати за плъзгача.' : 'No available dates for the slider.'}</p>
  </div>;
}

export default function DocumentPeriods({ filters, options, disabled, onChange }) {
  const { lang } = useI18n();
  const id = useId();
  const bg = lang === 'bg';
  const active = TYPES.filter(([type]) => filters.documentDates[type]?.from || filters.documentDates[type]?.to).length;
  return <details className="document-periods filter-disclosure filter-period-disclosure" open>
    <summary className="filter-disclosure-heading"><CalendarDays size={17} aria-hidden="true" /><span><strong id={id + '-title'}>{bg ? 'Период по документ' : 'Period by document'}</strong><small>{active ? (bg ? `${active} избрани периода` : `${active} selected periods`) : bg ? 'От и до за разрешения, визи и Акт 16' : 'From and to for permits, visas and Act 16'}</small></span>{active > 0 && <span className="filter-active-count">{active}</span>}<ChevronDown size={17} aria-hidden="true" /></summary>
    <div className="document-periods-body" aria-labelledby={id + '-title'}>
      <p className="document-periods-explanation">{bg ? 'Плъзнете началото и края на периода. Картата се обновява при отпускане. Използва се датата на издаване; записи без дата не участват в избран период.' : 'Drag the start and end of the period. The map updates on release. Filters use issue dates; undated records do not match a selected period.'}</p>
      {TYPES.map(([type, labelBg, labelEn]) => {
        const range = filters.documentDates[type] || { from: '', to: '' };
        const available = options?.document_date_ranges?.[type];
        const label = bg ? labelBg : labelEn;
        const rowId = `${id}-${type}`;
        const hasRange = Boolean(range.from || range.to);
        const minYear = Number(String(available?.date_min || '').slice(0, 4));
        const maxYear = Number(String(available?.date_max || '').slice(0, 4));
        const years = minYear > 1800 && maxYear >= minYear ? Array.from({ length: Math.min(150, maxYear - minYear + 1) }, (_, index) => maxYear - index) : [];
        const selectedYear = range.from && range.to && range.from.slice(0, 4) === range.to.slice(0, 4) ? range.from.slice(0, 4) : '';
        if (selectedYear && !years.includes(Number(selectedYear))) years.unshift(Number(selectedYear));
        const invalid = Boolean(range.from && range.to && range.from > range.to);
        const selectedMonth = selectedYear && range.from.slice(0, 7) === range.to.slice(0, 7) ? range.from.slice(5, 7) : '';
        const update = (next) => onChange(type, next);
        return <section key={type} className={'document-period-row ' + (hasRange ? 'is-active' : '')} aria-labelledby={rowId + '-title'} style={{ '--period-color': REGISTER_COLORS[type] }}>
          <div className="document-period-label"><DocumentTypeIcon type={type} size={18} /><div><h3 id={rowId + '-title'}>{label}</h3><small>{hasRange ? `${range.from ? displayDate(range.from, lang) : '…'} – ${range.to ? displayDate(range.to, lang) : '…'}` : bg ? 'Без ограничение по дата' : 'No date restriction'}</small></div>{hasRange && <button type="button" className="document-period-clear" onClick={() => update({ from: '', to: '' })} aria-label={`${bg ? 'Изчисти периода:' : 'Clear period:'} ${label}`} title={bg ? 'Изчисти периода' : 'Clear period'}><X size={15} aria-hidden="true" /></button>}</div>
          <fieldset disabled={disabled} className="document-period-controls"><legend className="sr-only">{label}</legend>
            <PeriodSlider id={rowId} label={label} range={range} available={available} disabled={disabled} lang={lang} onChange={update} />
            <details className="document-custom-range"><summary>{bg ? 'Точни дати и бърз избор' : 'Exact dates and quick choices'}<ChevronDown size={14} aria-hidden="true" /></summary><div>
              <div className="filter-date-fields">
                <label className="filter-field"><span>{bg ? 'От дата' : 'From date'}</span><input type="date" value={range.from} max={range.to || undefined} aria-label={`${label} — ${bg ? 'от дата' : 'from date'}`} aria-invalid={invalid || undefined} aria-describedby={invalid ? rowId + '-error' : undefined} onChange={(event) => update({ ...range, from: event.target.value })} /></label>
                <label className="filter-field"><span>{bg ? 'До дата' : 'To date'}</span><input type="date" value={range.to} min={range.from || undefined} aria-label={`${label} — ${bg ? 'до дата' : 'to date'}`} aria-invalid={invalid || undefined} aria-describedby={invalid ? rowId + '-error' : undefined} onChange={(event) => update({ ...range, to: event.target.value })} /></label>
              </div>
              <div className="filter-date-fields document-period-shortcuts">
                <label className="filter-field"><span>{bg ? 'Година' : 'Year'}</span><select value={selectedYear} onChange={(event) => update(monthRange(event.target.value, ''))}><option value="">{bg ? 'Изберете година' : 'Choose year'}</option>{years.map((year) => <option value={year} key={year}>{year}</option>)}</select></label>
                <label className="filter-field"><span>{bg ? 'Месец' : 'Month'}</span><select value={selectedMonth} disabled={!selectedYear} onChange={(event) => update(monthRange(selectedYear, event.target.value))}><option value="">{bg ? 'Цялата година' : 'Entire year'}</option>{Array.from({ length: 12 }, (_, month) => <option key={month} value={String(month + 1).padStart(2, '0')}>{new Intl.DateTimeFormat(bg ? 'bg-BG' : 'en-GB', { month: 'long', timeZone: 'UTC' }).format(new Date(Date.UTC(2024, month, 1)))}</option>)}</select></label>
              </div>
              <div className="filter-date-presets">
                {available?.date_max && <button type="button" onClick={() => update(monthRange(available.date_max.slice(0, 4), available.date_max.slice(5, 7)))}>{bg ? 'Най-новият месец' : 'Latest month'}</button>}
                {available?.date_max && <button type="button" onClick={() => update({ from: dayDate(dateDay(available.date_max) - 89), to: available.date_max })}>{bg ? 'Най-новите 90 дни' : 'Latest 90 days'}</button>}
                {hasRange && <button type="button" onClick={() => update({ from: '', to: '' })}><RotateCcw size={12} aria-hidden="true" />{bg ? 'Изчисти периода' : 'Clear period'}</button>}
              </div>
            </div></details>
            {invalid && <p id={rowId + '-error'} className="filter-field-error" role="alert">{bg ? 'Началната дата трябва да е преди или на крайната.' : 'The start date must be on or before the end date.'}</p>}
          </fieldset>
        </section>;
      })}
      {active > 1 && <p className="filter-field-help">{bg ? 'Всеки избран период изисква съответния документ за имота. За общите бройки отворете „Строителни документи“.' : 'Each selected period requires its named document for the parcel. Open Construction documents for overall totals.'}</p>}
      {disabled && <p className="filter-field-help">{bg ? 'Периодите изискват свързани документи и заредени регистрови дати.' : 'Periods require linked records and loaded registry dates.'}</p>}
    </div>
  </details>;
}
