import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowDownRight, ArrowLeft, ArrowRight, ArrowUpRight, BarChart3, Bell, BellOff, CalendarDays, Check, ChevronDown, ChevronLeft, ChevronRight, CircleHelp, Clock3, ExternalLink, Filter, Info, Layers3, List, Loader2, Map as MapIcon, MapPin, RefreshCw, Search, ShieldCheck, TrendingDown, X } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { marketApi } from '@/api/marketApi';
import OffersMap from './OffersMap';
import './MarketDashboard.css';

const TEXT = {
  eyebrow: ['SOFIAPERMITS · ПАЗАРНИ ДАННИ', 'SOFIAPERMITS · MARKET DATA'],
  title: ['Пазарът в София, в числа.', 'Sofia’s market, in numbers.'],
  intro: ['Сравнете офертни цени по квартал и открийте обяви под цените на сходни апартаменти.', 'Compare asking prices by neighborhood and find listings priced below similar apartments.'],
  map: ['Към кадастралната карта', 'Back to the cadastral map'],
  refresh: ['Обнови изгледа', 'Refresh view'],
  backgroundError: ['Изгледът не можа да се обнови. Показана е последната заредена снимка.', 'The view could not refresh. The last loaded snapshot is still shown.'],
  loading: ['Зареждане на пазарните данни…', 'Loading market data…'],
  loadError: ['Пазарните данни временно не са достъпни.', 'Market data is temporarily unavailable.'],
  retry: ['Опитай отново', 'Try again'],
  archive: ['Архивна база', 'Historical baseline'],
  archiveHelp: ['Това са обяви от {period}. Наличността им сега не е проверена. Новите дневни снимки ще се показват отделно от тази отправна база.', 'These listings were captured in {period}. Their current availability has not been verified. New daily snapshots will be shown separately from this baseline.'],
  captured: ['Снимка към {date}', 'Snapshot captured {date}'],
  stale: ['По-стара снимка · известията са временно спрени', 'Older snapshot · alerts are temporarily paused'],
  baseline: ['Първа дневна снимка · отправна база за бъдещи промени', 'First daily snapshot · baseline for future changes'],
  scope: ['Обхват на наличните обяви', 'Coverage of available listings'],
  constructionScope: ['Заявена година на строеж: от {year} г.', 'Advertised construction year: {year} onwards'],
  ads: ['Обяви в набора', 'Listings in the dataset'],
  adHint: ['Уникални ID на обяви; не уникални имоти', 'Unique listing IDs, not unique properties'],
  neighborhoods: ['Квартали и населени места', 'Neighborhoods & settlements'],
  pricedHint: ['{n} обяви с известна цена и валута', '{n} listings with a known price and currency'],
  median: ['Медиана €/м²', 'Median €/m²'],
  medianHint: ['{n} обяви · {vat}', '{n} listings · {vat}'],
  opportunities: ['Под сравнимата медиана', 'Below the comparable median'],
  opportunityHint: ['Поне 20% под медианата · поне 8 сходни обяви', 'At least 20% below the median · at least 8 peers'],
  topTitle: ['По-ниска цена. По-ясно сравнение.', 'A lower price. A clearer comparison.'],
  topHelp: ['Оферти с поне 20% разлика спрямо медианата на сходни обяви в същия квартал. Това е повод за проверка, а не потвърдена изгодна сделка.', 'Listings at least 20% below similar asking prices in the same neighborhood. A reason to investigate, rather than a verified bargain.'],
  viewAll: ['Виж всички', 'View all'],
  noTop: ['Няма обяви с достатъчна извадка и избрания праг.', 'No listings meet the threshold with enough comparable peers.'],
  historicalOffer: ['Архивна обява', 'Historical listing'],
  newOffer: ['Нова обява', 'New listing'],
  priceDrop: ['Намаление на цената', 'Price reduced'],
  newlyEligible: ['Ново съвпадение', 'New match'],
  below: ['{n}% под медианата', '{n}% below median'],
  above: ['{n}% над медианата', '{n}% above median'],
  nearMedian: ['Близо до медианата', 'Near the median'],
  peers: ['Медиана на {n} сходни обяви', 'Median of {n} similar listings'],
  noComparison: ['Недостатъчно сходни обяви за сравнение', 'Not enough similar listings for comparison'],
  comparisonVatUnknown: ['Сравнение по заявена цена · ДДС е неизвестен', 'Quoted-price comparison · VAT is unknown'],
  review: ['Необичайна разлика · нужна проверка', 'Unusual difference · review needed'],
  source: ['Оригиналната обява в imot.bg', 'Original listing on imot.bg'],
  area: ['Площ', 'Area'],
  floor: ['Етаж', 'Floor'],
  year: ['Заявено строителство', 'Advertised construction'],
  unknown: ['Не е посочено', 'Not stated'],
  unit: ['€/м²', '€/m²'],
  derivedTotal: ['Обща цена, изчислена от €/м²', 'Total calculated from the €/m² quote'],
  sqm: ['м²', 'm²'],
  vatIncluded: ['Включен ДДС / не се начислява', 'VAT included / not charged'],
  vatExcluded: ['Без ДДС', 'VAT excluded'],
  vatUnknown: ['ДДС не е посочен', 'VAT not stated'],
  updated: ['Промяна в обявата: {date}', 'Listing updated: {date}'],
  observed: ['Наблюдавана: {date}', 'Observed: {date}'],
  tableTitle: ['Цените по квартали', 'Prices by neighborhood'],
  tableHelp: ['Използваме офертни цени с включен или неначисляван ДДС. При липса на такива обозначаваме отделна извадка с непосочен ДДС. Типовете апартаменти са смесени; картите сравняват отделни групи.', 'Figures use asking prices with VAT included or not charged. Where none exist, a separate sample with unstated VAT is labeled. Apartment types are combined here; listing cards compare separate groups.'],
  searchNeighborhood: ['Търси квартал…', 'Search neighborhoods…'],
  order: ['Подреди', 'Sort'],
  orderCount: ['По брой обяви', 'Most listings'],
  orderMedian: ['По най-ниска медиана', 'Lowest median'],
  orderMean: ['По най-ниска средна цена', 'Lowest mean price'],
  orderName: ['По име', 'By name'],
  neighborhood: ['Квартал', 'Neighborhood'],
  count: ['Обяви', 'Listings'],
  sample: ['Извадка с цена', 'Price sample'],
  mean: ['Средна €/м²', 'Mean €/m²'],
  medianColumn: ['Медиана €/м²', 'Median €/m²'],
  medianPrice: ['Медиана на цена', 'Median asking price'],
  viewNeighborhood: ['Виж обявите в {name}', 'View listings in {name}'],
  emptyNeighborhoods: ['Няма квартал с това име.', 'No neighborhoods match that name.'],
  tableRange: ['{from}–{to} от {total} квартала', '{from}–{to} of {total} neighborhoods'],
  smallSample: ['Малка извадка', 'Small sample'],
  alertTitle: ['Следете това, което ви интересува.', 'Follow what matters to you.'],
  alertHelp: ['Известия вътре в сайта за нови обяви и промени след завършена дневна снимка. Предпочитанията се пазят само в този браузър.', 'In-site alerts for new listings and changes after a completed daily snapshot. Preferences are stored only in this browser.'],
  alertEnabled: ['Следенето е включено', 'Watching is enabled'],
  alertDisabled: ['Следенето е изключено', 'Watching is off'],
  alertSave: ['Запази и включи следенето', 'Save and enable watching'],
  alertUpdate: ['Запази предпочитанията', 'Save preferences'],
  alertStop: ['Спри следенето', 'Stop watching'],
  alertSaved: ['Запазено. Следенето започва от следващата завършена снимка.', 'Saved. Watching starts with the next completed snapshot.'],
  alertMin: ['Минимум под медианата', 'Minimum below median'],
  alertHistorical: ['Архивните обяви не генерират нови известия. Можете да запазите предпочитанията си за бъдещи дневни снимки.', 'Historical listings do not generate new alerts. You can save preferences for future daily snapshots.'],
  alertBaseline: ['Първата дневна снимка установява отправна база. Известията започват при следващи нови обяви или промени.', 'The first daily snapshot sets a baseline. Alerts start with later new listings or changes.'],
  alertStale: ['Последната снимка е по-стара от 48 часа. Ще покажем нови известия след актуално завършено обновяване.', 'The latest snapshot is over 48 hours old. New alerts will appear after a fresh completed update.'],
  alertVatHelp: ['Известията включват само обяви с известна основа за ДДС и достатъчно сходни обяви.', 'Alerts include only listings with a known VAT basis and enough comparable peers.'],
  alertUnknownVatOption: ['Следи и офертни цени с непосочен ДДС', 'Also track asking prices with unreported VAT'],
  alertUnknownVatHelp: ['Сравняват се само с други обяви с непосочен ДДС. Крайният размер на ДДС остава неизвестен.', 'These are compared only with other unreported-VAT listings. The final VAT amount remains unknown.'],
  alertVatHelpOpted: ['Следенето включва и обяви с непосочен ДДС. Сравненията остават отделни за всяка ДДС група.', 'Watching also includes listings with unreported VAT. Comparisons remain separate for each VAT group.'],
  alertEmpty: ['Няма нови непрегледани съвпадения с предпочитанията ви.', 'No unseen new matches for your preferences.'],
  alertLoading: ['Проверяваме всички дневни съвпадения с предпочитанията ви…', 'Checking all daily matches for your preferences…'],
  alertError: ['Дневните съвпадения не се заредиха изцяло. Последният потвърден брой остава до успешно обновяване.', 'Daily matches could not load completely. The last confirmed count remains until a successful refresh.'],
  alertNewCount: ['{n} нови съвпадения', '{n} new matches'],
  alertSee: ['Покажи съвпаденията', 'Show matches'],
  alertMarkSeen: ['Отбележи като прегледани', 'Mark as seen'],
  alertStorage: ['Браузърът не позволи запазване. Следенето ще важи само докато страницата е отворена.', 'Your browser did not allow saving. Watching will last only while this page is open.'],
  listingsTitle: ['Разгледайте обявите', 'Explore the listings'],
  listingsHelp: ['Комбинирайте квартал, тип, цена и разлика спрямо сравнимите обяви.', 'Combine neighborhood, apartment type, price and difference from comparable listings.'],
  anyNeighborhood: ['Всички квартали', 'All neighborhoods'],
  type: ['Тип апартамент', 'Apartment type'],
  anyType: ['Всички типове', 'All types'],
  vat: ['ДДС в цената', 'VAT basis'],
  anyVat: ['Всички стойности', 'All values'],
  seller: ['Продавач', 'Seller'],
  anySeller: ['Всички продавачи', 'All sellers'],
  sellerAgency: ['Брокер / агенция', 'Broker / agency'],
  sellerPrivate: ['Частен продавач (по заявление)', 'Private seller (self-declared)'],
  sellerUnknown: ['Продавачът не е установен', 'Seller not established'],
  sellerAgencyEvidence: ['Профил на агенция в източника', 'Agency profile on the source website'],
  sellerPrivateEvidence: ['Изрично заявление в обявата; собствеността не е проверена', 'Explicit statement in the listing; ownership is not verified'],
  sellerConflicting: ['Противоречиви сигнали за продавача', 'Conflicting seller information'],
  precision: ['Местоположение в картата', 'Map location'],
  anyPrecision: ['Всички, включително без ориентир', 'All, including no reference'],
  precisionStreet: ['Ориентир по улица', 'Street reference'],
  precisionNeighborhood: ['Ориентир по квартал', 'Neighborhood reference'],
  precisionAddress: ['Адресен ориентир', 'Address reference'],
  precisionUnknown: ['Без достатъчно местоположение', 'Insufficient location information'],
  locatedCoverage: ['{n} обяви с приблизителен ориентир', '{n} listings with an approximate reference'],
  sellerCoverage: ['{n} обяви с установен тип продавач', '{n} listings with a classified seller type'],
  analysisCoverage: ['Анализирани описания: {n} от {total}', 'Descriptions analyzed: {n} of {total}'],
  analysisCoverageHelp: ['Обработката на описанията е постепенна при дневните обновявания. При останалите обяви се използват наличните полета; липсващото не се предполага.', 'Description analysis progresses with daily updates. Other listings use available source fields; missing information is not inferred.'],
  listView: ['Списък', 'List'],
  offersMap: ['Карта на обявите', 'Listings map'],
  viewMode: ['Изглед на обявите', 'Listings view'],
  referenceFilter: ['Референтна зона: {name}', 'Reference area: {name}'],
  clearReference: ['Премахни ограничението по зона', 'Remove reference-area filter'],
  askingEstimate: ['Ориентир по офертни цени', 'Asking-price benchmark'],
  askingRange: ['Средни 50% от сходните офертни цени', 'Middle 50% of comparable asking prices'],
  askingSample: ['{n} сходни обяви · медиана {price} €', '{n} comparable listings · median {price} €'],
  askingHelp: ['Диапазонът е изчислен от квартилите €/м² × заявената площ. Не е оценка по реални сделки; състоянието и площта са заявени от рекламодателя.', 'Range calculated from €/m² quartiles × stated area. It is not a transaction-based valuation; condition and area are advertiser statements.'],
  askingStreet: ['Сравнение по същата референтна улица', 'Comparison within the same street reference'],
  askingNeighborhood: ['Сравнение по квартал', 'Neighborhood comparison'],
  askingInsufficient: ['Недостатъчно сходни обяви за ценови ориентир', 'Not enough comparable listings for a price benchmark'],
  askingReview: ['Нужна е проверка преди ценово сравнение', 'Review needed before comparing prices'],
  askingInvalid: ['Недостатъчно надеждни цена или площ за изчисление', 'Insufficient price or area inputs for a calculation'],
  analysisTitle: ['Сведения от обявата', 'Listing statements'],
  analysisPartial: ['Описанието още не е анализирано; показани са наличните полета.', 'Description has not yet been analyzed; available source fields are shown.'],
  analysisChecked: ['Текстът е анализиран на {date}. Това са твърдения в обявата.', 'Text analyzed {date}. These are statements in the listing.'],
  completion: ['Етап', 'Completion'],
  completionPlanned: ['В строеж / планирано завършване', 'Under construction / planned completion'],
  completionCompleted: ['Заявено като завършено', 'Advertised as completed'],
  condition: ['Състояние', 'Condition'],
  conditionRenovated: ['Заявено като ремонтирано', 'Advertised as renovated'],
  conditionNeedsRenovation: ['Нужда от ремонт', 'Needs renovation'],
  areaBasis: ['Заявена основа на площта', 'Stated area basis'],
  areaNet: ['Чиста площ', 'Net area'],
  areaGross: ['С общи части', 'Including common areas'],
  areaTerrace: ['Включени тераси', 'Includes terraces'],
  riskShare: ['Дял / идеални части', 'Share / partial ownership sale'],
  riskAuction: ['Търг / публична продан', 'Auction / public sale'],
  riskTenanted: ['С наемател', 'Tenanted'],
  riskNonresidential: ['Нежилищен статут', 'Non-residential status'],
  riskExtra: ['Задължителен допълнителен разход', 'Mandatory additional cost'],
  minDiscount: ['Минимум под медианата · %', 'Minimum below median · %'],
  discountNone: ['Без праг', 'No threshold'],
  onlyDeals: ['Само обяви с поне 20% под медианата', 'Only listings at least 20% below median'],
  moreFilters: ['Площ, цена и промени', 'Area, price and changes'],
  minArea: ['Площ от · м²', 'Area from · m²'],
  maxArea: ['Площ до · м²', 'Area to · m²'],
  minPrice: ['Цена от · €', 'Price from · €'],
  maxPrice: ['Цена до · €', 'Price to · €'],
  change: ['Промяна между снимките', 'Change between snapshots'],
  anyChange: ['Всички', 'Any'],
  sortDiscount: ['Най-много под медианата', 'Largest difference below median'],
  sortUnit: ['Най-ниска цена на м²', 'Lowest price per m²'],
  sortPrice: ['Най-ниска обща цена', 'Lowest total price'],
  sortNewest: ['Най-скоро наблюдавани', 'Most recently observed'],
  apply: ['Покажи обявите', 'Show listings'],
  reset: ['Изчисти филтрите', 'Clear filters'],
  rangeError: ['Проверете диапазоните: минимумът трябва да е по-малък или равен на максимума.', 'Check the ranges: minimum must be no greater than maximum.'],
  resultCount: ['{n} обяви с тези условия', '{n} listings match these conditions'],
  emptyListings: ['Няма обяви с тези условия. Променете или изчистете филтрите.', 'No listings match these conditions. Change or clear the filters.'],
  listingsLoading: ['Зареждане на обявите…', 'Loading listings…'],
  listingsError: ['Обявите не се заредиха. Опитайте отново.', 'Listings could not load. Try again.'],
  page: ['Страница {page} от {pages}', 'Page {page} of {pages}'],
  previous: ['Предишна страница', 'Previous page'],
  next: ['Следваща страница', 'Next page'],
  methodology: ['Как се получават тези числа', 'How these numbers are calculated'],
  methodologyIntro: ['Прозрачно сравнение, с ясни ограничения.', 'Transparent comparisons with clear limits.'],
  methodologyPrice: ['Офертни, не продажни цени', 'Asking prices, not sale prices'],
  methodologyPriceHelp: ['Цените са заявени в обявите. Те не установяват стойността, наличността или състоянието на имота. Не смесваме неизвестна валута с евро; левовите цени се преобразуват по 1,95583 лв./€.', 'Prices are stated in listings. They do not establish a property’s value, availability or condition. Unknown currencies are not treated as euros; BGN prices use 1.95583 BGN/€.'],
  methodologyPeers: ['Сравняваме сходни обяви', 'Similar listings form the comparison'],
  methodologyPeersHelp: ['Същият квартал, тип апартамент, група година на строеж и основа за ДДС. Самата обява е изключена от медианата; нужни са поне 8 други обяви. Неизвестната година е отделна група, която може да смесва различни възрасти.', 'Peers share neighborhood, apartment type, construction-year band and VAT basis. The listing itself is excluded from its comparison median; at least 8 other listings are required. Unknown construction years form a separate group that may mix property ages.'],
  methodologyPeersV2Help: ['Същият квартал, тип, ДДС, възраст, етап и основа на площта; площ в ±25%, сходна етажна група и състояние, когато е посочено. При поне 8 сходни обяви по същата референтна улица използваме тях, иначе квартала. Самата обява е изключена. Диапазонът отразява квартилите на офертните цени, а не сигурност за продажна стойност.', 'Peers share neighborhood, type, VAT, age band, completion and area basis, with area within ±25%, a similar floor group and condition where known. At least 8 peers from the same street reference are used when available, otherwise the neighborhood. The candidate is excluded. The range reflects asking-price quartiles, rather than confidence in a sale valuation.'],
  methodologyDeals: ['Сигнал за проверка', 'A lead to investigate'],
  methodologyDealsHelp: ['Прагът е поне 20% под сравнимата медиана. Разлики от 60% или повече са отбелязани за проверка и не се изпращат като нови съвпадения. Площта и годината са заявени от рекламодателя.', 'The threshold is at least 20% below the comparable median. Differences of 60% or more are flagged for review and excluded from new alerts. Area and construction year are advertiser statements.'],
  methodologySource: ['Една обява ≠ един имот', 'One listing does not equal one property'],
  methodologySourceHelp: ['Премахваме повторенията по ID на обявата. Различни обяви за един физически имот може да останат отделни. Обявите не се свързват автоматично с кадастъра или с официален Акт 16.', 'Duplicate listing IDs are removed. Multiple listings for one physical property may remain separate. Listings are not automatically linked to the cadastre or official Act 16 evidence.'],
  history: ['История на завършените снимки', 'Completed snapshot history'],
  historyEmpty: ['Все още има само една отправна снимка. Измененията се изчисляват след следващи завършени обновявания.', 'Only one baseline snapshot is available so far. Changes are calculated after later completed updates.'],
  historyHelp: ['Последни {n} завършени снимки. Промяна в състава на обявите също може да промени медианата.', 'Last {n} completed snapshots. A change in the mix of listings can also change the median.'],
  sourceLink: ['Източник: imot.bg', 'Source: imot.bg'],
  noValue: ['—', '—'],
};

const EMPTY_FILTERS = { neighborhood: '', type: '', vat: '', seller: '', precision: '', location_key: '', min_discount: '', min_area: '', max_area: '', min_price: '', max_price: '', deals_only: false, change: '', sort: 'discount' };
const ALERT_KEY = 'sofiapermits.market.watching.v1';
const DEFAULT_ALERT = { enabled: false, neighborhood: '', type: '', minDiscount: 20, includeUnknownVat: false, seenKeys: [], baselineSnapshot: '' };

function useText() {
  const { lang } = useI18n();
  return { lang, tr: (key, vars = {}) => {
    let value = TEXT[key]?.[lang === 'bg' ? 0 : 1] || key;
    Object.entries(vars).forEach(([name, item]) => { value = value.replaceAll(`{${name}}`, String(item)); });
    return value;
  } };
}

function numeric(value) { return typeof value === 'number' && Number.isFinite(value) ? value : null; }
function formatNumber(value, lang, digits = 0) { const n = numeric(value); return n === null ? '—' : n.toLocaleString(lang === 'bg' ? 'bg-BG' : 'en-GB', { maximumFractionDigits: digits }); }
function formatDate(value, lang, withTime = false) {
  if (!value) return '—';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '—';
  return new Intl.DateTimeFormat(lang === 'bg' ? 'bg-BG' : 'en-GB', { day: 'numeric', month: 'short', year: 'numeric', ...(withTime && String(value).includes('T') ? { hour: '2-digit', minute: '2-digit' } : {}), timeZone: 'Europe/Sofia' }).format(date);
}
function safeOfferUrl(value) {
  try { const url = new URL(value); return url.protocol === 'https:' && ['imot.bg', 'www.imot.bg'].includes(url.hostname) ? url.href : null; } catch { return null; }
}
function vatText(value, tr) { return tr(value === 'included' ? 'vatIncluded' : value === 'excluded' ? 'vatExcluded' : 'vatUnknown'); }
function sellerText(value, tr) { return tr(value === 'agency' ? 'sellerAgency' : value === 'private' ? 'sellerPrivate' : 'sellerUnknown'); }
function precisionText(value, tr) { return tr(value === 'street' ? 'precisionStreet' : value === 'neighborhood' ? 'precisionNeighborhood' : value === 'address' ? 'precisionAddress' : 'precisionUnknown'); }
function typeText(value, lang) {
  if (lang === 'bg') return value;
  const normalized = String(value || '').trim().toLocaleUpperCase('bg-BG');
  return { '2-СТАЕН': '2-room apartment', '3-СТАЕН': '3-room apartment', '4-СТАЕН': '4-room apartment', 'МНОГОСТАЕН': 'Multi-room apartment', 'МЕЗОНЕТ': 'Maisonette' }[normalized] || value;
}
function constructionText(value, lang) {
  if (lang === 'bg' || typeof value !== 'string') return value;
  const text = value.trim();
  for (const [pattern, label] of [[/^Ще бъде въведен(?:а|о)? в експлоатация\s*/iu, 'Expected completion'], [/^Въведен(?:а|о)? в експлоатация\s*/iu, 'Completion stated']]) {
    if (pattern.test(text)) {
      const remainder = text.replace(pattern, '').replace(/\s*г\.?$/iu, '').trim();
      return remainder ? `${label} · ${remainder}` : label;
    }
  }
  return value;
}
function headlineMetric(row) {
  if ((row?.headline_priced_count || 0) > 0) return { ...row, priced_count: row.headline_priced_count, vat_basis: row.headline_vat_basis || 'included' };
  const unknown = (row?.by_vat_basis || []).find((item) => item.vat_basis === 'unknown' && item.priced_count > 0);
  return unknown || { ...row, priced_count: row?.headline_priced_count || 0, vat_basis: row?.headline_vat_basis || 'included' };
}
function alertEventKey(offer) { return `${offer.id}:${offer.change?.kind || ''}:${offer.price_eur ?? ''}:${offer.observed_at || offer.first_seen_at || ''}`; }
function initialAlerts() {
  try {
    const saved = JSON.parse(localStorage.getItem(ALERT_KEY) || 'null');
    if (!saved || typeof saved !== 'object') return { ...DEFAULT_ALERT };
    return { ...DEFAULT_ALERT, enabled: saved.enabled === true, neighborhood: typeof saved.neighborhood === 'string' ? saved.neighborhood : '', type: typeof saved.type === 'string' ? saved.type : '', minDiscount: [20, 25, 30, 40, 50].includes(saved.minDiscount) ? saved.minDiscount : 20, includeUnknownVat: saved.includeUnknownVat === true, seenKeys: Array.isArray(saved.seenKeys) ? saved.seenKeys.filter((key) => typeof key === 'string').slice(-600) : [], baselineSnapshot: typeof saved.baselineSnapshot === 'string' ? saved.baselineSnapshot : '' };
  } catch { return { ...DEFAULT_ALERT }; }
}

function AskingEstimate({ estimate }) {
  const { lang, tr } = useText();
  if (!estimate) return null;
  const available = estimate.status === 'available' && estimate.peer_count >= 8 && numeric(estimate.range_low_eur) !== null && numeric(estimate.range_high_eur) !== null;
  return <div className={`market-asking-estimate${available ? '' : ' is-unavailable'}`}>
    <span><BarChart3 size={13} />{tr('askingEstimate')}</span>
    {available ? <><strong>{formatNumber(estimate.range_low_eur, lang)}–{formatNumber(estimate.range_high_eur, lang)} €</strong><p>{tr('askingSample', { n: estimate.peer_count, price: formatNumber(estimate.indicated_price_eur, lang) })}</p><small>{tr(estimate.location_basis === 'street' ? 'askingStreet' : 'askingNeighborhood')}</small><details><summary>{tr('askingRange')}<CircleHelp size={12} /></summary><p>{tr('askingHelp')}</p></details></> : <p>{tr(estimate.status === 'needs_review' ? 'askingReview' : estimate.status === 'invalid_inputs' ? 'askingInvalid' : 'askingInsufficient')}</p>}
  </div>;
}

function ListingAnalysis({ offer }) {
  const { lang, tr } = useText();
  const analysis = offer.analysis;
  if (!analysis) return null;
  const facts = [];
  if (analysis.completion_stage !== 'unknown') facts.push(['completion', analysis.completion_stage === 'planned' ? 'completionPlanned' : 'completionCompleted']);
  if (analysis.condition !== 'unknown') facts.push(['condition', analysis.condition === 'renovated' ? 'conditionRenovated' : 'conditionNeedsRenovation']);
  if (analysis.area_basis !== 'unknown') facts.push(['areaBasis', { net: 'areaNet', gross: 'areaGross', terrace_included: 'areaTerrace' }[analysis.area_basis]]);
  const risks = { share_sale: 'riskShare', auction: 'riskAuction', tenanted: 'riskTenanted', nonresidential: 'riskNonresidential', mandatory_extra_cost: 'riskExtra' };
  return <div className="market-listing-analysis">
    {analysis.risk_flags?.length > 0 && <div className="market-risk-flags">{analysis.risk_flags.filter((key) => risks[key]).map((key) => <span key={key}><Info size={12} />{tr(risks[key])}</span>)}</div>}
    <details><summary>{tr('analysisTitle')}<ChevronDown size={13} /></summary><dl>{facts.map(([label, value]) => <div key={label}><dt>{tr(label)}</dt><dd>{tr(value)}</dd></div>)}</dl><p>{analysis.description_analyzed ? tr('analysisChecked', { date: formatDate(analysis.checked_at, lang) }) : tr('analysisPartial')}</p></details>
  </div>;
}

function OfferCard({ offer, mode }) {
  const { lang, tr } = useText();
  const comparison = offer.comparison || {};
  const discount = numeric(comparison.below_median_pct);
  const unusual = discount !== null && discount >= 60;
  const historical = mode === 'historical_bootstrap' || offer.historical;
  const link = safeOfferUrl(offer.url);
  const change = offer.change?.kind;
  const quotedUnitPrice = numeric(offer.quoted_eur_per_sqm);
  const sellerEvidence = tr(offer.seller_evidence === 'agency_profile' ? 'sellerAgencyEvidence' : offer.seller_evidence === 'explicit_private_claim' ? 'sellerPrivateEvidence' : offer.seller_evidence === 'conflicting_signals' ? 'sellerConflicting' : 'sellerUnknown');
  return <article className={`market-offer-card${comparison.eligible ? ' is-comparable-deal' : ''}`}>
    <div className="market-offer-top"><span className="market-offer-type">{typeText(offer.type_bg, lang) || tr('unknown')}</span>{historical ? <span className="market-status-badge is-historical"><Clock3 size={11} />{tr('historicalOffer')}</span> : ['new', 'price_drop', 'became_eligible'].includes(change) ? <span className="market-status-badge">{change === 'price_drop' ? <TrendingDown size={11} /> : <Check size={11} />}{tr(change === 'price_drop' ? 'priceDrop' : change === 'new' ? 'newOffer' : 'newlyEligible')}</span> : null}</div>
    <h3><MapPin size={15} />{offer.neighborhood_bg || tr('unknown')}</h3>
    <div className="market-seller-row"><span className={`market-seller-badge is-${offer.seller_type || 'unknown'}`} title={`${sellerEvidence}${offer.seller_checked_at ? ` · ${formatDate(offer.seller_checked_at, lang)}` : ''}`}>{sellerText(offer.seller_type, tr)}</span></div>
    {offer.address_bg && <p className="market-offer-address">{offer.address_bg}</p>}
    {offer.location && <p className="market-offer-reference"><MapPin size={11} /><span>{precisionText(offer.location.precision, tr)} · {offer.location.label_bg}</span></p>}
    <dl className="market-offer-facts"><div><dt>{tr('area')}</dt><dd>{formatNumber(offer.area_sqm, lang, 1)} {tr('sqm')}</dd></div>{offer.floor_bg && <div><dt>{tr('floor')}</dt><dd>{offer.floor_bg}</dd></div>}<div className="market-construction-fact"><dt>{tr('year')}</dt><dd>{constructionText(offer.construction_label_bg, lang) || offer.construction_year || tr('unknown')}</dd></div></dl>
    <div className="market-offer-price"><strong>{formatNumber(offer.price_eur, lang)}{numeric(offer.price_eur) !== null && <span> €</span>}</strong><span>{formatNumber(quotedUnitPrice ?? offer.eur_per_sqm, lang, quotedUnitPrice === null ? 0 : 2)} {tr('unit')}</span></div>
    {offer.price_total_derived === true && <p className="market-price-derived"><Info size={11} />{tr('derivedTotal')}</p>}
    <p className={`market-offer-vat${offer.vat_basis === 'unknown' ? ' is-unknown' : ''}`}>{offer.vat_basis === 'unknown' && <Info size={11} />}{vatText(offer.vat_basis, tr)}</p>
    <ListingAnalysis offer={offer} />
    <AskingEstimate estimate={offer.asking_estimate} />
    <div className={`market-offer-comparison${unusual ? ' needs-review' : ''}`}>
      {discount !== null && (comparison.peer_count || 0) >= 8 ? <><strong>{discount > 0 ? <ArrowDownRight size={17} /> : <BarChart3 size={17} />}{discount > 0 ? tr('below', { n: formatNumber(discount, lang, 1) }) : discount < 0 ? tr('above', { n: formatNumber(Math.abs(discount), lang, 1) }) : tr('nearMedian')}</strong><span>{tr('peers', { n: comparison.peer_count })} · {formatNumber(comparison.median_eur_per_sqm, lang)} {tr('unit')}</span>{offer.vat_basis === 'unknown' && <em>{tr('comparisonVatUnknown')}</em>}{unusual && <em><Info size={12} />{tr('review')}</em>}</> : <span>{tr('noComparison')}</span>}
    </div>
    <p className="market-offer-date">{offer.last_modified_at ? tr('updated', { date: formatDate(offer.last_modified_at, lang) }) : tr('observed', { date: formatDate(offer.observed_at, lang) })}</p>
    {link && <a className="market-offer-link" href={link} target="_blank" rel="noreferrer">{tr('source')}<ArrowUpRight size={16} /></a>}
  </article>;
}

function Pagination({ page, pages, onPage, busy = false }) {
  const { tr } = useText();
  if (pages <= 1) return null;
  return <nav className="market-pagination" aria-label={tr('page', { page, pages })}><button type="button" disabled={busy || page <= 1} onClick={() => onPage(page - 1)} aria-label={tr('previous')}><ChevronLeft size={17} /></button><span>{tr('page', { page, pages })}</span><button type="button" disabled={busy || page >= pages} onClick={() => onPage(page + 1)} aria-label={tr('next')}><ChevronRight size={17} /></button></nav>;
}

function AlertPanel({ summary, onCountChange }) {
  const { lang, tr } = useText();
  const [preferences, setPreferences] = useState(initialAlerts);
  const [draft, setDraft] = useState(() => { const p = initialAlerts(); return { neighborhood: p.neighborhood, type: p.type, minDiscount: p.minDiscount, includeUnknownVat: p.includeUnknownVat }; });
  const [expanded, setExpanded] = useState(false);
  const [alertPage, setAlertPage] = useState(1);
  const [saved, setSaved] = useState(false);
  const [storageError, setStorageError] = useState(false);
  const [candidateState, setCandidateState] = useState({ key: '', loading: false, error: false, items: [] });
  const [candidateRevision, setCandidateRevision] = useState(0);
  const options = summary.filter_options || {};
  const historical = summary.mode !== 'daily';
  const firstBaseline = summary.history?.baseline === true;
  const capture = Date.parse(summary.captured_at);
  const fresh = Number.isFinite(capture) && Date.now() - capture <= 48 * 3600 * 1000 && capture - Date.now() <= 6 * 3600 * 1000;
  const suppressed = historical || firstBaseline || !fresh;
  const candidateQueryKey = preferences.enabled && !suppressed && preferences.baselineSnapshot !== summary.snapshot_id ? JSON.stringify({ snapshot: summary.snapshot_id, captured: summary.captured_at, neighborhood: preferences.neighborhood, type: preferences.type, minDiscount: preferences.minDiscount, includeUnknownVat: preferences.includeUnknownVat }) : '';
  useEffect(() => {
    if (!candidateQueryKey) return undefined;
    const query = JSON.parse(candidateQueryKey);
    const controller = new AbortController();
    setCandidateState((previous) => ({ ...previous, key: candidateQueryKey, loading: true, error: false }));
    async function loadCandidates() {
      const items = new Map();
      let pages = 1;
      let expectedTotal = null;
      for (let page = 1; page <= pages; page += 1) {
        const data = await marketApi.listings({ daily_only: 1, deals_only: 1, include_unknown_vat: query.includeUnknownVat ? 1 : undefined, min_discount: query.minDiscount, neighborhood: query.neighborhood, type: query.type, sort: 'newest', page_size: 60, page }, controller.signal);
        if (controller.signal.aborted) return;
        if (!Array.isArray(data?.items) || data.items.length > 60 || !Number.isSafeInteger(data.total) || data.total < 0 || data.total > 50000 || !Number.isSafeInteger(data.pages) || data.pages < 1 || data.pages > 834 || data.pages !== Math.max(1, Math.ceil(data.total / 60)) || data.page !== page || data.mode !== 'daily' || data.snapshot_id !== query.snapshot || data.captured_at !== query.captured || (expectedTotal !== null && (data.total !== expectedTotal || data.pages !== pages))) throw new Error('Incomplete or changing daily alert snapshot.');
        pages = data.pages; expectedTotal = data.total;
        for (const offer of data.items) {
          if (!offer || typeof offer.id !== 'string') throw new Error('Invalid daily alert record.');
          items.set(offer.id, offer);
        }
      }
      if (items.size !== expectedTotal) throw new Error('Incomplete daily alert results.');
      if (!controller.signal.aborted) setCandidateState({ key: candidateQueryKey, loading: false, error: false, items: [...items.values()] });
    }
    loadCandidates().catch(() => { if (!controller.signal.aborted) setCandidateState((previous) => ({ ...previous, key: candidateQueryKey, loading: false, error: true })); });
    return () => controller.abort();
  }, [candidateQueryKey, candidateRevision]);
  const candidatesLoading = Boolean(candidateQueryKey) && (candidateState.key !== candidateQueryKey || candidateState.loading);
  const candidatesError = Boolean(candidateQueryKey) && candidateState.key === candidateQueryKey && candidateState.error;
  const candidatesReady = Boolean(candidateQueryKey) && candidateState.key === candidateQueryKey && !candidateState.loading && !candidateState.error;
  const seenKeys = new Set(preferences.seenKeys);
  const candidates = candidateState.items.filter((offer) => {
    const discount = numeric(offer.comparison?.below_median_pct);
    const knownVatAllowed = ['included', 'excluded'].includes(offer.vat_basis) && offer.comparison?.alert_eligible === true;
    const unknownVatAllowed = preferences.includeUnknownVat === true && offer.vat_basis === 'unknown' && offer.change?.area_changed !== true && offer.change?.price_basis_changed !== true;
    return !offer.historical && offer.comparison?.eligible === true && (knownVatAllowed || unknownVatAllowed) && discount !== null && discount >= preferences.minDiscount && discount < 60
      && (!preferences.neighborhood || offer.neighborhood_key === preferences.neighborhood) && (!preferences.type || offer.type_key === preferences.type)
      && ['new', 'price_drop', 'became_eligible'].includes(offer.change?.kind) && !seenKeys.has(alertEventKey(offer));
  });
  const unseen = candidateQueryKey ? candidates : [];
  useEffect(() => { if (!candidateQueryKey || candidatesReady) onCountChange?.(unseen.length); }, [onCountChange, unseen.length, candidateQueryKey, candidatesReady]);
  function savePreferences(next) {
    setPreferences(next);
    try { localStorage.setItem(ALERT_KEY, JSON.stringify(next)); setStorageError(false); } catch { setStorageError(true); }
  }
  function enable(event) {
    event.preventDefault();
    const keys = [...(summary.daily_candidates || []), ...candidateState.items].map(alertEventKey);
    savePreferences({ ...preferences, ...draft, enabled: true, baselineSnapshot: summary.snapshot_id, seenKeys: [...new Set([...preferences.seenKeys, ...keys])].slice(-600) });
    setSaved(true); setExpanded(false); setAlertPage(1);
  }
  function markSeen() {
    savePreferences({ ...preferences, baselineSnapshot: summary.snapshot_id, seenKeys: [...new Set([...preferences.seenKeys, ...unseen.map(alertEventKey)])].slice(-600) });
    setExpanded(false); setAlertPage(1);
  }
  return <section className="market-alerts" aria-labelledby="market-alert-title">
    <div className="market-alert-intro"><div className="market-section-icon"><Bell size={20} /></div><div><div className="market-eyebrow">{tr(preferences.enabled ? 'alertEnabled' : 'alertDisabled')}</div><h2 id="market-alert-title">{tr('alertTitle')}</h2><p>{tr('alertHelp')}</p></div>{candidatesReady && unseen.length > 0 && <button className="market-alert-count" type="button" onClick={() => setExpanded(!expanded)}><Bell size={14} />{tr('alertNewCount', { n: unseen.length })}<ChevronDown size={14} /></button>}</div>
    <form className="market-alert-form" onSubmit={enable}>
      <label><span>{tr('neighborhood')}</span><select value={draft.neighborhood} onChange={(event) => { setDraft({ ...draft, neighborhood: event.target.value }); setSaved(false); }}><option value="">{tr('anyNeighborhood')}</option>{(options.neighborhoods || []).map((item) => <option value={item.key} key={item.key}>{item.label_bg}</option>)}</select></label>
      <label><span>{tr('type')}</span><select value={draft.type} onChange={(event) => { setDraft({ ...draft, type: event.target.value }); setSaved(false); }}><option value="">{tr('anyType')}</option>{(options.types || []).map((item) => <option value={item.key} key={item.key}>{typeText(item.label_bg, lang)}</option>)}</select></label>
      <label><span>{tr('alertMin')}</span><select value={draft.minDiscount} onChange={(event) => { setDraft({ ...draft, minDiscount: Number(event.target.value) }); setSaved(false); }}>{[20, 25, 30, 40, 50].map((n) => <option key={n} value={n}>{n}%</option>)}</select></label>
      <label className="market-alert-vat-option"><input type="checkbox" checked={draft.includeUnknownVat} onChange={(event) => { setDraft({ ...draft, includeUnknownVat: event.target.checked }); setSaved(false); }} /><span><strong>{tr('alertUnknownVatOption')}</strong><small>{tr('alertUnknownVatHelp')}</small></span></label>
      <div className="market-alert-save-actions"><button className="market-button is-primary" type="submit"><Bell size={15} />{tr(preferences.enabled ? 'alertUpdate' : 'alertSave')}</button>{preferences.enabled && <button className="market-button is-quiet" type="button" onClick={() => { savePreferences({ ...preferences, enabled: false }); setSaved(false); }}><BellOff size={15} />{tr('alertStop')}</button>}</div>
    </form>
    {storageError && <p className="market-inline-note is-warning" role="status">{tr('alertStorage')}</p>}
    {saved && <p className="market-inline-note" role="status"><Check size={14} />{tr('alertSaved')}</p>}
    {suppressed ? <p className="market-inline-note"><Info size={14} />{tr(historical ? 'alertHistorical' : firstBaseline ? 'alertBaseline' : 'alertStale')}</p> : candidatesLoading ? <p className="market-inline-note" role="status"><Loader2 size={14} className="animate-spin" />{tr('alertLoading')}</p> : candidatesError ? <div className="market-inline-note is-warning" role="status"><Info size={14} /><span>{tr('alertError')} <button className="market-alert-retry" type="button" onClick={() => setCandidateRevision((n) => n + 1)}>{tr('retry')}</button></span></div> : preferences.enabled && unseen.length === 0 ? <p className="market-inline-note">{tr('alertEmpty')}</p> : null}
    <p className="market-inline-note">{tr(preferences.includeUnknownVat ? 'alertVatHelpOpted' : 'alertVatHelp')}</p>
    {expanded && candidatesReady && unseen.length > 0 && <div className="market-alert-matches"><div className="market-alert-matches-heading"><strong>{tr('alertNewCount', { n: unseen.length })}</strong><button type="button" onClick={markSeen}>{tr('alertMarkSeen')}<Check size={14} /></button></div><div className="market-offer-grid">{unseen.slice((Math.min(alertPage, Math.ceil(unseen.length / 6)) - 1) * 6, Math.min(alertPage, Math.ceil(unseen.length / 6)) * 6).map((offer) => <OfferCard key={offer.id} offer={offer} mode={summary.mode} />)}</div><Pagination page={Math.min(alertPage, Math.ceil(unseen.length / 6))} pages={Math.ceil(unseen.length / 6)} onPage={setAlertPage} /></div>}
  </section>;
}

function NeighborhoodTable({ summary, onSelect }) {
  const { lang, tr } = useText();
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState('count');
  const [page, setPage] = useState(1);
  const rows = useMemo(() => (summary.neighborhoods || []).filter((row) => row.label_bg.toLocaleLowerCase('bg-BG').includes(query.trim().toLocaleLowerCase('bg-BG'))).sort((a, b) => {
    if (sort === 'name') return a.label_bg.localeCompare(b.label_bg, 'bg');
    if (sort === 'count') return b.count - a.count || a.label_bg.localeCompare(b.label_bg, 'bg');
    const key = sort === 'mean' ? 'mean_eur_per_sqm' : 'median_eur_per_sqm';
    return (numeric(headlineMetric(a)[key]) ?? Infinity) - (numeric(headlineMetric(b)[key]) ?? Infinity) || b.count - a.count;
  }), [summary.neighborhoods, query, sort]);
  const pages = Math.max(1, Math.ceil(rows.length / 12));
  const currentPage = Math.min(page, pages);
  const visible = rows.slice((currentPage - 1) * 12, currentPage * 12);
  const maxMedian = Math.max(1, ...rows.map((row) => numeric(headlineMetric(row).median_eur_per_sqm) || 0));
  return <section className="market-section market-neighborhood-section" aria-labelledby="market-neighborhood-title">
    <div className="market-section-heading"><div><div className="market-eyebrow">SOFIA · {tr('neighborhoods')}</div><h2 id="market-neighborhood-title">{tr('tableTitle')}</h2><p>{tr('tableHelp')}</p></div><div className="market-table-controls"><label className="market-search-field"><Search size={16} /><input type="search" value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder={tr('searchNeighborhood')} aria-label={tr('searchNeighborhood')} /></label><select value={sort} onChange={(event) => { setSort(event.target.value); setPage(1); }} aria-label={tr('order')}><option value="count">{tr('orderCount')}</option><option value="median">{tr('orderMedian')}</option><option value="mean">{tr('orderMean')}</option><option value="name">{tr('orderName')}</option></select></div></div>
    <div className="market-table-wrap"><table className="market-neighborhood-table"><thead><tr><th scope="col">{tr('neighborhood')}</th><th scope="col">{tr('count')}</th><th scope="col">{tr('sample')}</th><th scope="col">{tr('mean')}</th><th scope="col">{tr('medianColumn')}</th><th scope="col">{tr('medianPrice')}</th></tr></thead><tbody>{visible.map((row) => { const metric = headlineMetric(row); return <tr key={row.key}><th scope="row"><button type="button" onClick={() => onSelect(row.key)} aria-label={tr('viewNeighborhood', { name: row.label_bg })}>{row.label_bg}<ArrowUpRight size={13} /></button></th><td>{formatNumber(row.count, lang)}</td><td>{formatNumber(metric.priced_count, lang)}{metric.vat_basis === 'unknown' && <small>{tr('vatUnknown')}</small>}{metric.priced_count < 8 && <small>{tr('smallSample')}</small>}</td><td>{formatNumber(metric.mean_eur_per_sqm, lang)}</td><td className="market-median-cell"><strong>{formatNumber(metric.median_eur_per_sqm, lang)}</strong><span className="market-price-bar" aria-hidden="true"><i style={{ width: `${Math.max(0, Math.min(100, (numeric(metric.median_eur_per_sqm) || 0) / maxMedian * 100))}%` }} /></span></td><td>{formatNumber(metric.median_price_eur, lang)}{numeric(metric.median_price_eur) !== null && ' €'}</td></tr>; })}</tbody></table>{visible.length === 0 && <p className="market-empty">{tr('emptyNeighborhoods')}</p>}</div>
    <div className="market-table-footer"><span>{tr('tableRange', { from: rows.length ? (currentPage - 1) * 12 + 1 : 0, to: Math.min(currentPage * 12, rows.length), total: rows.length })}</span><Pagination page={currentPage} pages={pages} onPage={setPage} /></div>
  </section>;
}

function MarketListings({ summary, sectionRef, externalSelection }) {
  const { lang, tr } = useText();
  const [draft, setDraft] = useState({ ...EMPTY_FILTERS });
  const [filters, setFilters] = useState({ ...EMPTY_FILTERS });
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [rangeError, setRangeError] = useState(false);
  const [view, setView] = useState('list');
  const [mapVisited, setMapVisited] = useState(false);
  const [referenceLabel, setReferenceLabel] = useState('');
  const [state, setState] = useState({ loading: true, error: false, data: null });
  const options = summary.filter_options || {};
  useEffect(() => {
    if (!externalSelection) return;
    const next = { ...EMPTY_FILTERS, ...externalSelection.filters };
    setDraft(next); setFilters(next); setPage(1); setRangeError(false); setReferenceLabel(''); setView('list');
  }, [externalSelection]);
  useEffect(() => {
    if (view !== 'list') return undefined;
    const controller = new AbortController();
    setState((previous) => ({ ...previous, loading: true, error: false }));
    marketApi.listings({ ...filters, deals_only: filters.deals_only ? 1 : undefined, page, page_size: 24 }, controller.signal).then((data) => { if (!controller.signal.aborted) setState({ loading: false, error: false, data }); }).catch(() => { if (!controller.signal.aborted) setState({ loading: false, error: true, data: null }); });
    return () => controller.abort();
  }, [filters, page, revision, summary.snapshot_id, view]);
  function update(key, value) { setDraft((previous) => ({ ...previous, [key]: value })); setRangeError(false); }
  function apply(event) {
    event.preventDefault();
    for (const [min, max] of [['min_area', 'max_area'], ['min_price', 'max_price']]) {
      if ((draft[min] !== '' && (!Number.isFinite(Number(draft[min])) || Number(draft[min]) < 0)) || (draft[max] !== '' && (!Number.isFinite(Number(draft[max])) || Number(draft[max]) < 0)) || (draft[min] !== '' && draft[max] !== '' && Number(draft[min]) > Number(draft[max]))) { setRangeError(true); return; }
    }
    setFilters({ ...draft }); setPage(1); setRangeError(false);
  }
  function chooseReference(area) {
    const next = { ...filters, location_key: area.key };
    setDraft(next); setFilters(next); setReferenceLabel(area.label_bg); setPage(1); setView('list'); setRangeError(false);
  }
  function clearReference() {
    setDraft((previous) => ({ ...previous, location_key: '' }));
    setFilters((previous) => ({ ...previous, location_key: '' }));
    setReferenceLabel(''); setPage(1);
  }
  const items = Array.isArray(state.data?.items) ? state.data.items : [];
  return <section className="market-section market-listings-section" ref={sectionRef} aria-labelledby="market-listings-title">
    <div className="market-section-heading"><div><div className="market-eyebrow">{tr('count')} · IMOT.BG</div><h2 id="market-listings-title">{tr('listingsTitle')}</h2><p>{tr('listingsHelp')}</p></div><div className="market-view-toggle" role="group" aria-label={tr('viewMode')}><button type="button" aria-pressed={view === 'list'} onClick={() => setView('list')}><List size={15} />{tr('listView')}</button><button type="button" aria-pressed={view === 'map'} onClick={() => { setMapVisited(true); setView('map'); }}><MapIcon size={15} />{tr('offersMap')}</button></div></div>
    <form className="market-filter-form" onSubmit={apply}>
      <div className="market-filter-grid"><label><span>{tr('neighborhood')}</span><select value={draft.neighborhood} onChange={(event) => update('neighborhood', event.target.value)}><option value="">{tr('anyNeighborhood')}</option>{(options.neighborhoods || []).map((item) => <option value={item.key} key={item.key}>{item.label_bg} ({item.count})</option>)}</select></label><label><span>{tr('type')}</span><select value={draft.type} onChange={(event) => update('type', event.target.value)}><option value="">{tr('anyType')}</option>{(options.types || []).map((item) => <option value={item.key} key={item.key}>{typeText(item.label_bg, lang)} ({item.count})</option>)}</select></label><label><span>{tr('vat')}</span><select value={draft.vat} onChange={(event) => update('vat', event.target.value)}><option value="">{tr('anyVat')}</option>{(options.vat_bases || []).map((item) => <option value={item.key} key={item.key}>{vatText(item.key, tr)} ({item.count})</option>)}</select></label><label><span>{tr('minDiscount')}</span><select value={draft.min_discount} onChange={(event) => update('min_discount', event.target.value)}><option value="">{tr('discountNone')}</option>{[10, 20, 25, 30, 40, 50].map((n) => <option key={n} value={n}>{n}%</option>)}</select></label></div>
      <div className="market-filter-grid market-location-filter-grid"><label><span>{tr('seller')}</span><select value={draft.seller} onChange={(event) => update('seller', event.target.value)}><option value="">{tr('anySeller')}</option>{['agency', 'private', 'unknown'].map((key) => <option key={key} value={key}>{sellerText(key, tr)}</option>)}</select></label><label><span>{tr('precision')}</span><select value={draft.precision} onChange={(event) => update('precision', event.target.value)}><option value="">{tr('anyPrecision')}</option>{['street', 'neighborhood', 'unknown'].map((key) => <option key={key} value={key}>{precisionText(key, tr)}</option>)}</select></label></div>
      {filters.location_key && <div className="market-reference-filter"><MapPin size={13} /><span>{tr('referenceFilter', { name: referenceLabel || filters.location_key })}</span><button type="button" onClick={clearReference} aria-label={tr('clearReference')}><X size={14} /></button></div>}
      <div className="market-filter-second-row"><label className="market-checkbox"><input type="checkbox" checked={draft.deals_only} onChange={(event) => update('deals_only', event.target.checked)} /><span>{tr('onlyDeals')}</span></label><label className="market-sort-field"><span>{tr('order')}</span><select value={draft.sort} onChange={(event) => update('sort', event.target.value)}><option value="discount">{tr('sortDiscount')}</option><option value="eur_per_sqm">{tr('sortUnit')}</option><option value="price">{tr('sortPrice')}</option><option value="newest">{tr('sortNewest')}</option></select></label></div>
      <details className="market-more-filters"><summary><Filter size={14} />{tr('moreFilters')}<ChevronDown size={14} /></summary><div className="market-filter-grid is-advanced">{['min_area', 'max_area', 'min_price', 'max_price'].map((key) => <label key={key}><span>{tr({ min_area: 'minArea', max_area: 'maxArea', min_price: 'minPrice', max_price: 'maxPrice' }[key])}</span><input type="number" min="0" max={key.endsWith('area') ? 100000 : 10000000000} step="any" value={draft[key]} onChange={(event) => update(key, event.target.value)} placeholder="—" /></label>)}<label><span>{tr('change')}</span><select value={draft.change} onChange={(event) => update('change', event.target.value)}><option value="">{tr('anyChange')}</option>{[['new', 'newOffer'], ['price_drop', 'priceDrop'], ['became_eligible', 'newlyEligible']].map(([value, key]) => <option key={value} value={value}>{tr(key)}</option>)}</select></label></div></details>
      {rangeError && <p className="market-inline-note is-warning" role="alert">{tr('rangeError')}</p>}
      <div className="market-filter-actions"><button className="market-button is-primary" type="submit"><Search size={15} />{tr('apply')}</button><button className="market-button is-quiet" type="button" onClick={() => { setDraft({ ...EMPTY_FILTERS }); setFilters({ ...EMPTY_FILTERS }); setPage(1); setRangeError(false); setReferenceLabel(''); }}><X size={14} />{tr('reset')}</button>{view === 'list' && !state.loading && !state.error && <span className="market-result-count" aria-live="polite">{tr('resultCount', { n: formatNumber(state.data?.total, lang) })}</span>}</div>
    </form>
    <div hidden={view !== 'list'} className="market-listings-results" aria-live="polite" aria-busy={view === 'list' && state.loading}>{state.loading ? <div className="market-loading is-inline"><Loader2 size={21} className="animate-spin" /><span>{tr('listingsLoading')}</span></div> : state.error ? <div className="market-empty" role="alert"><p>{tr('listingsError')}</p><button className="market-button" type="button" onClick={() => setRevision((n) => n + 1)}><RefreshCw size={15} />{tr('retry')}</button></div> : items.length === 0 ? <p className="market-empty">{tr('emptyListings')}</p> : <><div className="market-offer-grid">{items.map((offer) => <OfferCard key={offer.id} offer={offer} mode={state.data?.mode || summary.mode} />)}</div><Pagination page={state.data?.page || page} pages={state.data?.pages || 1} onPage={(next) => { setPage(next); sectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }} /></>}</div>
    {mapVisited && <div hidden={view !== 'map'}><OffersMap summary={summary} filters={filters} active={view === 'map'} onSelectReference={chooseReference} /></div>}
  </section>;
}

function EnrichmentCoverage({ summary }) {
  const { lang, tr } = useText();
  const counts = summary.counts || {};
  if (numeric(counts.description_analyzed_count) === null && numeric(counts.located_count) === null) return null;
  const classified = (numeric(counts.seller_types?.agency) || 0) + (numeric(counts.seller_types?.private) || 0);
  return <aside className="market-enrichment-coverage" aria-label={tr('analysisTitle')}><div>{numeric(counts.located_count) !== null && <span><MapPin size={14} />{tr('locatedCoverage', { n: formatNumber(counts.located_count, lang) })}</span>}<span><ShieldCheck size={14} />{tr('sellerCoverage', { n: formatNumber(classified, lang) })}</span>{numeric(counts.description_analyzed_count) !== null && <span><Layers3 size={14} />{tr('analysisCoverage', { n: formatNumber(counts.description_analyzed_count, lang), total: formatNumber(counts.listing_count, lang) })}</span>}</div><p>{tr('analysisCoverageHelp')}</p></aside>;
}

function Methodology({ summary }) {
  const { lang, tr } = useText();
  const series = Array.isArray(summary.history?.series) ? summary.history.series.slice(-8) : [];
  return <section className="market-section market-methodology" aria-labelledby="market-methodology-title"><div className="market-section-heading"><div><div className="market-eyebrow">{tr('methodologyIntro')}</div><h2 id="market-methodology-title">{tr('methodology')}</h2></div><ShieldCheck className="market-heading-icon" size={25} /></div><div className="market-method-grid">{[['Price', BarChart3], ['Peers', Layers3], ['Deals', CircleHelp], ['Source', ExternalLink]].map(([key, Icon]) => <article key={key}><Icon size={20} /><h3>{tr(`methodology${key}`)}</h3><p>{tr(key === 'Peers' && summary.methodology?.method_version === 2 ? 'methodologyPeersV2Help' : `methodology${key}Help`)}</p></article>)}</div><details className="market-history"><summary><CalendarDays size={16} />{tr('history')}<ChevronDown size={16} /></summary>{series.length <= 1 ? <p>{tr('historyEmpty')}</p> : <><p>{tr('historyHelp', { n: series.length })}</p><div className="market-history-series">{series.map((point, index) => <div key={`${point.captured_at}-${index}`}><span>{formatDate(point.captured_at, lang)}</span><strong>{formatNumber(point.median_eur_per_sqm, lang)} {tr('unit')}</strong><small>{formatNumber(point.listing_count, lang)} {tr('count').toLocaleLowerCase()}</small></div>)}</div></>}</details><div className="market-method-footer"><a href="https://www.imot.bg/" target="_blank" rel="noreferrer">{tr('sourceLink')}<ArrowUpRight size={14} /></a><span>{tr('captured', { date: formatDate(summary.captured_at, lang, true) })}</span></div></section>;
}

export default function MarketDashboard({ onBackToMap, onSummaryChange, onAlertCountChange }) {
  const { lang, tr } = useText();
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState({ loading: true, error: false, backgroundError: false, data: null });
  const [selection, setSelection] = useState(null);
  const listingsRef = useRef(null);
  useEffect(() => {
    const controller = new AbortController();
    let pending = false;
    let lastAttempt = 0;
    async function load(quiet) {
      if (pending || controller.signal.aborted) return;
      pending = true; lastAttempt = Date.now();
      if (!quiet) setState((previous) => ({ ...previous, loading: !previous.data, error: false, backgroundError: false }));
      try {
        const data = await marketApi.summary(controller.signal);
        if (!controller.signal.aborted) setState((previous) => ({ loading: false, error: false, backgroundError: false, checkedAt: Date.now(), data: previous.data?.snapshot_id === data?.snapshot_id ? previous.data : data }));
      } catch {
        if (!controller.signal.aborted) setState((previous) => ({ ...previous, loading: false, error: !previous.data, backgroundError: Boolean(previous.data) }));
      } finally { pending = false; }
    }
    load(false);
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') load(true); }, 60000);
    function onVisible() { if (document.visibilityState === 'visible' && Date.now() - lastAttempt >= 60000) load(true); }
    document.addEventListener('visibilitychange', onVisible);
    return () => { controller.abort(); window.clearInterval(timer); document.removeEventListener('visibilitychange', onVisible); };
  }, [revision]);
  function showListings(filters) { setSelection({ filters, id: Date.now() }); listingsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
  const summary = state.data;
  const historical = summary?.mode === 'historical_bootstrap';
  const captured = Date.parse(summary?.captured_at || '');
  const stale = summary && !historical && (!Number.isFinite(captured) || Date.now() - captured > 48 * 3600 * 1000);
  const range = summary?.coverage?.source_date_min && summary?.coverage?.source_date_max ? `${formatDate(summary.coverage.source_date_min, lang)} – ${formatDate(summary.coverage.source_date_max, lang)}` : formatDate(summary?.captured_at, lang);
  const headline = headlineMetric(summary?.totals);
  useEffect(() => { if (summary) onSummaryChange?.(summary); }, [onSummaryChange, summary]);
  return <main className="market-workspace"><div className="market-shell">
    <header className="market-hero"><div className="market-hero-copy"><p className="market-eyebrow">{tr('eyebrow')}</p><h1>{tr('title')}</h1><p>{tr('intro')}</p><div className="market-hero-meta"><span><CalendarDays size={14} />{summary ? tr('captured', { date: formatDate(summary.captured_at, lang, true) }) : tr('loading')}</span><a href="#market-methodology-title"><Info size={14} />{tr('methodology')}</a></div></div><div className="market-hero-actions">{onBackToMap && <button className="market-button" type="button" onClick={onBackToMap}><ArrowLeft size={15} />{tr('map')}</button>}<button className="market-button is-quiet" type="button" disabled={state.loading} onClick={() => setRevision((n) => n + 1)}><RefreshCw size={15} className={state.loading ? 'animate-spin' : ''} />{tr('refresh')}</button></div></header>
    {state.loading ? <div className="market-loading"><Loader2 size={28} className="animate-spin" /><span>{tr('loading')}</span></div> : state.error || !summary ? <div className="market-empty market-main-error" role="alert"><Info size={25} /><p>{tr('loadError')}</p><button className="market-button is-primary" type="button" onClick={() => setRevision((n) => n + 1)}><RefreshCw size={15} />{tr('retry')}</button></div> : <>
      {state.backgroundError && <p className="market-inline-note is-warning" role="status"><Info size={15} />{tr('backgroundError')}</p>}
      {historical && <div className="market-data-notice"><div className="market-notice-icon"><Clock3 size={22} /></div><div><strong>{tr('archive')} · {range}</strong><p>{tr('archiveHelp', { period: range })}</p></div></div>}
      {!historical && (stale || summary.history?.baseline) && <p className="market-inline-note is-warning"><Info size={15} />{tr(stale ? 'stale' : 'baseline')}</p>}
      <div className="market-stats-grid"><article><span>{tr('ads')}</span><strong>{formatNumber(summary.counts?.listing_count, lang)}</strong><p>{tr('adHint')}</p></article><article><span>{tr('neighborhoods')}</span><strong>{formatNumber(summary.coverage?.neighborhood_count ?? summary.neighborhoods?.length, lang)}</strong><p>{tr('pricedHint', { n: formatNumber(summary.counts?.priced_count, lang) })}</p></article><article className="is-emphasis"><span>{tr('median')}</span><strong>{formatNumber(headline.median_eur_per_sqm, lang)}<small> €</small></strong><p>{tr('medianHint', { n: formatNumber(headline.priced_count, lang), vat: vatText(headline.vat_basis, tr) })}</p></article><article><span>{tr('opportunities')}</span><strong>{formatNumber(summary.counts?.eligible_count, lang)}</strong><p>{tr('opportunityHint')}</p></article></div>
      <div className="market-scope"><span>{tr('scope')}</span><p>{lang === 'bg' ? summary.coverage?.scope_bg || 'Обяви за апартаменти в София и населените места в каталога' : 'Apartment listings in Sofia and settlements in the source catalogue · advertised asking prices'}{summary.coverage?.construction_year_min && <small>{tr('constructionScope', { year: summary.coverage.construction_year_min })}</small>}</p></div>
      <EnrichmentCoverage summary={summary} />
      <section className="market-section market-top-section" aria-labelledby="market-top-title"><div className="market-section-heading"><div><div className="market-eyebrow"><TrendingDown size={13} />{tr('opportunities')}</div><h2 id="market-top-title">{tr('topTitle')}</h2><p>{tr('topHelp')}</p></div><button className="market-button" type="button" onClick={() => showListings({ deals_only: true, min_discount: 20 })}>{tr('viewAll')}<ArrowRight size={15} /></button></div>{summary.top_offers?.length ? <div className="market-offer-grid">{summary.top_offers.slice(0, 6).map((offer) => <OfferCard key={offer.id} offer={offer} mode={summary.mode} />)}</div> : <p className="market-empty">{tr('noTop')}</p>}</section>
      <NeighborhoodTable summary={summary} onSelect={(neighborhood) => showListings({ neighborhood })} />
      <AlertPanel summary={summary} onCountChange={onAlertCountChange} />
      <MarketListings summary={summary} sectionRef={listingsRef} externalSelection={selection} />
      <Methodology summary={summary} />
    </>}
  </div></main>;
}

export function MarketTeaser({ onOpen, alertCount = 0 }) {
  const { tr } = useText();
  return <button className="market-teaser" type="button" onClick={onOpen}><span className="market-section-icon"><BarChart3 size={19} /></span><span><strong>{tr('title')}</strong><small>{tr('intro')}</small>{alertCount > 0 && <em className="market-teaser-alert-count"><Bell size={12} />{tr('alertNewCount', { n: alertCount })}</em>}</span><ArrowRight size={16} /></button>;
}
