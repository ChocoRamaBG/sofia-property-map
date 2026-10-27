import React, { useEffect, useId, useRef, useState } from 'react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { ArrowUpRight, BarChart3, ChevronDown, Info, Loader2, RefreshCw } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { displayDate } from '@/lib/registerUi';
import './TransactionsContext.css';

const DATA_URL = '/data/transactions-context.json';
const SOURCE_URL = 'https://www.registryagency.bg/bg/registri/imoten-registar/statistika/';
const PERIOD = /^(20\d{2})-Q([1-4])$/;
const MAX_BODY_CHARS = 256 * 1024;

function ordinal(period) { const match = PERIOD.exec(period); return match ? Number(match[1]) * 4 + Number(match[2]) - 1 : null; }
function periodFromOrdinal(value) { return `${Math.floor(value / 4)}-Q${value % 4 + 1}`; }
function periodLabel(period, lang, short = false) {
  const match = PERIOD.exec(period || '');
  if (!match) return '—';
  const quarter = Number(match[2]);
  return short ? `${lang === 'bg' ? ['I', 'II', 'III', 'IV'][quarter - 1] : `Q${quarter}`} '${match[1].slice(2)}` : lang === 'bg' ? `${['I', 'II', 'III', 'IV'][quarter - 1]} трим. ${match[1]}` : `Q${quarter} ${match[1]}`;
}
function count(value, lang) { return Number.isSafeInteger(value) && value >= 0 ? new Intl.NumberFormat(lang === 'bg' ? 'bg-BG' : 'en-GB').format(value) : '—'; }
function percent(value, lang) { return typeof value === 'number' && Number.isFinite(value) ? `${value > 0 ? '+' : ''}${new Intl.NumberFormat(lang === 'bg' ? 'bg-BG' : 'en-GB', { maximumFractionDigits: 1 }).format(value)}%` : '—'; }
function officialUrl(value) {
  try { const url = new URL(value); return url.protocol === 'https:' && ['www.registryagency.bg', 'registryagency.bg'].includes(url.hostname) && !url.username && !url.password && (!url.port || url.port === '443') ? url.href : null; } catch { return null; }
}
function dateValid(value) {
  if (typeof value !== 'string' || !/^20\d{2}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}
function timestampValid(value) { return typeof value === 'string' && /^20\d{2}-\d{2}-\d{2}T/.test(value) && Number.isFinite(Date.parse(value)); }
function optionalRegistrationCount(value) {
  if (value === null || value === undefined) return null;
  if (!Number.isSafeInteger(value) || value < 0 || value > 10000000) throw new Error('Invalid mortgage registration count.');
  return value;
}

// A damaged or incomplete response must not turn into an apparently valid
// series with discarded quarters or fabricated zero observations.
function checkedContext(value) {
  if (value?.schema_version !== 1 || value.status !== 'available' || value.metric !== 'registered_sales' || value.unit !== 'registrations'
    || value.geography?.code !== 'registry-office-sofia' || value.geography.scope !== 'registration_office_jurisdiction'
    || value.source?.url !== SOURCE_URL || !timestampValid(value.retrieved_at)
    || !Array.isArray(value.series) || value.series.length < 1 || value.series.length > 256) throw new Error('Invalid registered-sales context.');
  const seen = new Set();
  const series = value.series.map((row) => {
    const source = row?.source;
    if (!PERIOD.test(row?.period || '') || seen.has(row.period) || !Number.isSafeInteger(row.sales) || row.sales < 0 || row.sales > 10000000
      || !officialUrl(source?.url) || source?.page_url !== SOURCE_URL || !timestampValid(source?.retrieved_at)
      || (source.published_at !== null && !dateValid(source.published_at)) || !/^[a-f0-9]{64}$/.test(source?.sha256 || '')) throw new Error('Invalid registered-sales observation.');
    seen.add(row.period);
    return { period: row.period, sales: row.sales, contractual_mortgages: optionalRegistrationCount(row.contractual_mortgages), legal_mortgages: optionalRegistrationCount(row.legal_mortgages), source: { ...source, url: officialUrl(source.url) } };
  }).sort((left, right) => left.period.localeCompare(right.period));
  const first = ordinal(series[0].period); const last = ordinal(series[series.length - 1].period);
  if (last - first > 255) throw new Error('Registered-sales history exceeds its period limit.');
  const missing = Array.from({ length: last - first + 1 }, (_, index) => periodFromOrdinal(first + index)).filter((period) => !seen.has(period));
  if (value.coverage?.from !== series[0].period || value.coverage.to !== series[series.length - 1].period || value.coverage.periods !== series.length
    || !Array.isArray(value.coverage.missing_periods) || value.coverage.missing_periods.length !== missing.length
    || value.coverage.missing_periods.some((period, index) => period !== missing[index])) throw new Error('Registered-sales coverage does not reconcile.');
  return { ...value, series, missing };
}

function SourceLink({ source, lang, pick }) {
  return <div className="transactions-row-source"><a href={source.url} target="_blank" rel="noreferrer">{pick('Официална справка · PDF', 'Official report · PDF')}<ArrowUpRight size={12} aria-hidden="true" /></a><small>{pick('Публикувана:', 'Published:')} {source.published_at ? displayDate(source.published_at, lang) : pick('датата не е потвърдена', 'date unconfirmed')}</small><small>{pick('Извлечена:', 'Retrieved:')} {displayDate(source.retrieved_at, lang)}</small></div>;
}

export default function TransactionsContext({ active = true }) {
  const { lang, pick } = useI18n();
  const id = useId();
  const section = useRef(null);
  const scrollRequested = useRef(new URLSearchParams(window.location.search).get('section') === 'transactions');
  const loaded = useRef(false);
  const [state, setState] = useState({ status: 'loading', data: null });
  const [attempt, setAttempt] = useState(0);
  const [windowSize, setWindowSize] = useState('20');
  useEffect(() => {
    if (!active || state.status === 'loading' || !scrollRequested.current) return undefined;
    let frame;
    const jump = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        const fragment = window.location.hash.slice(1);
        const workspace = ['map', 'offers', 'activity'].includes(fragment) ? fragment : new URLSearchParams(window.location.search).get('view');
        if (!scrollRequested.current || workspace !== 'activity' || !section.current?.getClientRects().length) return;
        section.current.scrollIntoView({ block: 'start', behavior: 'auto' }); section.current.focus({ preventScroll: true }); scrollRequested.current = false;
      });
    };
    jump(); window.addEventListener('hashchange', jump);
    return () => { window.cancelAnimationFrame(frame); window.removeEventListener('hashchange', jump); };
  }, [active, state.status]);
  useEffect(() => {
    if (!active || loaded.current) return undefined;
    const controller = new AbortController();
    setState({ status: 'loading', data: null });
    fetch(DATA_URL, { signal: controller.signal, cache: 'no-cache', headers: { Accept: 'application/json' } }).then(async (response) => {
      if (!response.ok || Number(response.headers.get('content-length')) > MAX_BODY_CHARS) throw new Error('Registered-sales context unavailable.');
      const text = await response.text();
      if (text.length > MAX_BODY_CHARS) throw new Error('Registered-sales context exceeds its limit.');
      return checkedContext(JSON.parse(text));
    }).then((data) => { if (!controller.signal.aborted) { loaded.current = true; setState({ status: 'ready', data }); } }).catch((error) => { if (!controller.signal.aborted && error.name !== 'AbortError') setState({ status: 'error', data: null }); });
    return () => controller.abort();
  }, [active, attempt]);
  const retry = () => { loaded.current = false; setAttempt((value) => value + 1); };
  if (!active) return null;
  const data = state.data;
  const series = data?.series || [];
  const byPeriod = new Map(series.map((row) => [row.period, row]));
  const latest = series[series.length - 1];
  const priorYear = latest ? byPeriod.get(`${Number(latest.period.slice(0, 4)) - 1}${latest.period.slice(4)}`) : null;
  const change = priorYear?.sales > 0 ? (latest.sales / priorYear.sales - 1) * 100 : null;
  const lastOrdinal = latest ? ordinal(latest.period) : null;
  const four = latest ? Array.from({ length: 4 }, (_, index) => byPeriod.get(periodFromOrdinal(lastOrdinal - 3 + index))) : [];
  const fourComplete = four.length === 4 && four.every(Boolean);
  const fourTotal = fourComplete ? four.reduce((sum, row) => sum + row.sales, 0) : null;
  const calendar = latest ? Array.from({ length: lastOrdinal - ordinal(series[0].period) + 1 }, (_, index) => {
    const period = periodFromOrdinal(ordinal(series[0].period) + index);
    return byPeriod.get(period) || { period, sales: null, source: null };
  }) : [];
  const chartRows = windowSize === 'all' ? calendar : calendar.slice(-Number(windowSize));
  return <section id="sales-statistics" ref={section} tabIndex={-1} className="transactions-context" aria-labelledby={id + '-title'} style={{ scrollMarginTop: 16 }}>
    <div className="transactions-heading"><div><p className="development-eyebrow">{pick('АГЕНЦИЯ ПО ВПИСВАНИЯТА · СВ СОФИЯ', 'REGISTRY AGENCY · SOFIA OFFICE')}</p><h3 id={id + '-title'}>{pick('Колко продажби се вписват', 'How many sales are registered')}</h3><p>{pick('Тримесечна активност за района на Служба по вписванията — София. Обхваща продажби на различни видове недвижими имоти; броят не е само за апартаменти и не е брой уникални имоти.', 'Quarterly activity in the jurisdiction of Registry Office — Sofia. Sales cover different property types; the count is not limited to apartments and does not count unique properties.')}</p></div>{latest && <span className="transactions-quarter">{periodLabel(latest.period, lang)}</span>}</div>
    {state.status === 'loading' ? <div className="transactions-message" role="status"><Loader2 size={18} className="animate-spin" aria-hidden="true" /><p>{pick('Зареждане на официалната статистика за продажбите…', 'Loading official sales statistics…')}</p></div> : state.status === 'error' ? <div className="transactions-message" role="status"><Info size={18} aria-hidden="true" /><div><p>{pick('Статистиката за продажбите временно не е налична. Можете да отворите официалните справки.', 'Sales statistics are temporarily unavailable. The official reports remain available.')}</p><button type="button" className="development-button is-quiet" onClick={retry}><RefreshCw size={14} aria-hidden="true" />{pick('Опитай отново', 'Try again')}</button></div></div> : <>
      <div className="transactions-metrics">
        <article><h4>{pick('Вписани продажби', 'Registered sales')}</h4><strong>{count(latest.sales, lang)}</strong><p>{periodLabel(latest.period, lang)}</p></article>
        <article><h4>{pick('Промяна за година', 'Year-on-year change')}</h4><strong>{percent(change, lang)}</strong><p>{priorYear ? `${pick('Спрямо', 'Compared with')} ${periodLabel(priorYear.period, lang)} · ${count(priorYear.sales, lang)} ${pick('продажби', 'sales')}` : pick('Липсва същото тримесечие на предходната година.', 'The same quarter of the preceding year is missing.')}{priorYear?.sales === 0 && <> {pick('При нулева база процент не се изчислява.', 'A percentage cannot be calculated from a zero baseline.')}</>}</p></article>
        <article><h4>{pick('Последни 4 тримесечия', 'Latest 4 quarters')}</h4><strong>{count(fourTotal, lang)}</strong><p>{fourComplete ? `${periodLabel(four[0].period, lang)} – ${periodLabel(four[3].period, lang)}` : pick('Нужни са четири последователни наблюдения.', 'Four consecutive observations are required.')}</p></article>
      </div>
      <div className="transactions-chart-heading"><strong><BarChart3 size={16} aria-hidden="true" />{pick('Продажби по тримесечия', 'Sales by quarter')}</strong><label><span>{pick('Обхват', 'Window')}</span><select value={windowSize} onChange={(event) => setWindowSize(event.target.value)}><option value="12">{pick('Последни 3 години', 'Latest 3 years')}</option><option value="20">{pick('Последни 5 години', 'Latest 5 years')}</option><option value="all">{pick('Цялата история', 'All history')}</option></select></label></div>
      <div className="transactions-chart" role="img" aria-label={pick('Колони за вписаните продажби по тримесечия. Липсващите периоди са празни. Всички стойности и източници са в таблицата отдолу.', 'Bars show quarterly registered sales. Missing periods are blank. All values and sources are available in the table below.')}>
        <ResponsiveContainer width="100%" height="100%"><BarChart data={chartRows} margin={{ top: 12, right: 8, left: -10, bottom: 8 }}><CartesianGrid strokeDasharray="3 5" vertical={false} stroke="#e3eae4" /><XAxis dataKey="period" tickFormatter={(period) => periodLabel(period, lang, true)} tick={{ fill: '#657c6d', fontSize: 10 }} axisLine={false} tickLine={false} minTickGap={24} /><YAxis allowDecimals={false} tick={{ fill: '#657c6d', fontSize: 10 }} axisLine={false} tickLine={false} width={60} /><Tooltip cursor={{ fill: '#eef4ef' }} content={({ active: shown, label }) => shown && PERIOD.test(label || '') ? <div className="transactions-tooltip"><strong>{periodLabel(label, lang)}</strong><span>{byPeriod.has(label) ? `${count(byPeriod.get(label).sales, lang)} ${pick('вписани продажби', 'registered sales')}` : pick('Няма налични данни', 'No available data')}</span></div> : null} /><Bar dataKey="sales" fill="#3c7566" maxBarSize={42} radius={[3, 3, 0, 0]} isAnimationActive={false} /></BarChart></ResponsiveContainer>
      </div>
      {data.missing.length > 0 && <p className="transactions-gap-note">{pick('Липсващи периоди в историята:', 'Missing periods in the history:')} {data.missing.map((period) => periodLabel(period, lang)).join(', ')}. {pick('Те не се заместват с нула и не участват в суми за четири тримесечия.', 'They are not replaced with zero and cannot form a complete four-quarter total.')}</p>}
      <p className="transactions-gap-note">{pick('Договорните и законните ипотеки в таблицата са отделни вписвания. Те не измерват дела на покупките, финансирани с кредит.', 'Contractual and legal mortgages in the table are separate registrations. They do not measure the share of credit-financed purchases.')}</p>
      <details className="transactions-history"><summary>{pick('Всички стойности и източници', 'All values and sources')}<span>{count(series.length, lang)} {pick('тримесечия', 'quarters')}</span><ChevronDown size={15} aria-hidden="true" /></summary><div className="transactions-table-scroll"><table><caption>{pick('Вписани продажби и ипотеки · Служба по вписванията — София', 'Registered sales and mortgages · Registry Office — Sofia')}</caption><thead><tr><th scope="col">{pick('Тримесечие', 'Quarter')}</th><th scope="col">{pick('Продажби', 'Sales')}</th><th scope="col">{pick('Промяна за година', 'Year-on-year change')}</th><th scope="col">{pick('Договорни ипотеки', 'Contractual mortgages')}</th><th scope="col">{pick('Законни ипотеки', 'Legal mortgages')}</th><th scope="col">{pick('Официален източник', 'Official source')}</th></tr></thead><tbody>{[...calendar].reverse().map((row) => {
        const earlier = byPeriod.get(`${Number(row.period.slice(0, 4)) - 1}${row.period.slice(4)}`);
        const rowChange = row.sales !== null && earlier?.sales > 0 ? (row.sales / earlier.sales - 1) * 100 : null;
        return <tr key={row.period} className={row.source ? undefined : 'is-missing'}><th scope="row">{periodLabel(row.period, lang)}</th><td>{count(row.sales, lang)}</td><td>{percent(rowChange, lang)}</td><td>{count(row.contractual_mortgages, lang)}</td><td>{count(row.legal_mortgages, lang)}</td><td>{row.source ? <SourceLink source={row.source} lang={lang} pick={pick} /> : pick('Липсваща справка в набора', 'Report missing from this dataset')}</td></tr>;
      })}</tbody></table></div></details>
      <details className="transactions-method"><summary><Info size={15} aria-hidden="true" />{pick('Как помага за анализ на цените?', 'How does this help analyse prices?')}<ChevronDown size={15} aria-hidden="true" /></summary><div><p>{pick('Броят продажби измерва пазарна активност. Сравнението със същото тримесечие на предходната година намалява влиянието на сезонността. Спадът на броя сделки сам по себе си не доказва, че цените ще паднат след определен срок.', 'Sales counts measure market activity. Comparing the same quarter of the preceding year reduces seasonal effects. Falling transaction counts alone do not establish that prices will decline after a particular delay.')}</p><p>{pick('За ценова прогноза трябва да се съчетаят историята на продажбите, индексът на НСИ, кредитът, лихвите и новото предлагане, със съпоставими география и периоди. Моделът трябва да се провери върху по-късни периоди, които не е използвал при обучението, и да показва грешката и несигурността на прогнозата.', 'A price forecast needs sales history, the NSI index, lending, interest rates and new supply, with compatible geography and periods. A model must be evaluated on later periods excluded from training and report forecast error and uncertainty.')}</p><p>{pick('Тази серия обхваща района на службата по вписванията и различни видове имоти. Индексът на НСИ е за жилища в гр. София, а обявите съдържат офертни цени. Разликите в обхвата остават видими при съпоставка.', 'This series covers the registration office jurisdiction and different property types. The NSI index covers housing in Sofia city, while listings contain asking prices. Scope differences must remain explicit in comparisons.')}</p></div></details>
    </>}
    <div className="transactions-source"><a href={SOURCE_URL} target="_blank" rel="noreferrer">{pick('Източник: Агенция по вписванията · статистика', 'Source: Registry Agency · statistics')}<ArrowUpRight size={13} aria-hidden="true" /></a>{data?.retrieved_at && <span>{pick('Наборът е обновен:', 'Dataset updated:')} {displayDate(data.retrieved_at, lang)}</span>}</div>
  </section>;
}
