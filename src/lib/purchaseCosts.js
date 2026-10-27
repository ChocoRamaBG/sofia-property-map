// Budget assumptions are separate from advertised facts and comparable asking prices.
export const PURCHASE_RULES = Object.freeze({
  checkedAt: '2026-10-27',
  bgnPerEur: 1.95583,
  vatPercent: 20,
  registrationPercent: 0.1,
  registrationMinimumEur: 5.11,
  sofiaTaxPercent: 3,
  sources: [
    { key: 'sofia', labelBg: 'СОС · данък придобиване 3% (от 01.01.2020)', labelEn: 'Sofia Council · acquisition tax 3% (from 1 Jan 2020)', url: 'https://council.sofia.bg/documents/20182/799847/R.51.pdf/c11d58ac-1f7c-4652-917e-f4299e49c7c8' },
    { key: 'base', labelBg: 'Министерство на финансите · данъчна основа', labelEn: 'Ministry of Finance · taxable value', url: 'https://www.minfin.bg/bg/784' },
    { key: 'notary', labelBg: 'Нотариална камара · тарифа, т. 8 и т. 20', labelEn: 'Notary Chamber · tariff, items 8 and 20', url: 'https://notary-chamber.bg/sites/default/files/tarifa_za_notarialnite_taksi_km_zakona_za_notariusite_i_notarialnata_deynost.pdf' },
    { key: 'registration', labelBg: 'Агенция по вписванията · тарифа и евро', labelEn: 'Registry Agency · tariff and euro', url: 'https://www.registryagency.bg/bg/prestsentar/novini/drzhavni-taksi/' },
    { key: 'vat', labelBg: 'НАП · стандартна ставка ДДС 20%', labelEn: 'NRA · standard VAT rate 20%', url: 'https://www.nra.bg/wps/portal/egov/vashata%20evropa/danatsi/DDS%20informatsia%20otnosno%20obshtite%20pravila%2C%20stavkite%20i%20osvobozhdavaniyata%20ot%20danak' },
    { key: 'conversion', labelBg: 'КЗП · пълен курс и закръгляване в евро', labelEn: 'Consumer Protection Commission · euro conversion', url: 'https://kzp.bg/bg/za-evroto/faq' },
  ],
});

export const DEFAULT_PURCHASE_ASSUMPTIONS = Object.freeze({
  brokerPercent: 3,
  brokerVat: 'included',
  unknownSeller: 'agency',
  municipality: 'sofia',
  acquisitionTaxPercent: 3,
  buyerFeesSharePercent: 100,
  notaryVat: true,
  includeDrafting: false,
});
const STORAGE_KEY = 'sofia-purchase-assumptions-v1';
const MAX_EUR = 1_000_000_000;
export function roundMoney(value) { return Math.round((value + Number.EPSILON) * 100) / 100; }

function decimal(value) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value !== 'string' || !/^\d+(?:[.,]\d+)?$/.test(value.trim())) return null;
  const number = Number(value.trim().replace(',', '.'));
  return Number.isFinite(number) ? number : null;
}
function bounded(value, maximum) {
  const number = decimal(value);
  return number !== null && number >= 0 && number <= maximum ? number : null;
}

// The Chamber publishes the tariff in BGN. Apply it at the full fixed rate,
// convert the resulting fee to EUR, then round once to cents (Euro Act arts 12–13).
export function notaryTariffEur(materialInterestEur) {
  if (bounded(materialInterestEur, MAX_EUR * 1.2) === null) return null;
  const base = materialInterestEur * PURCHASE_RULES.bgnPerEur;
  let fee;
  if (base <= 100) fee = 30;
  else if (base <= 1000) fee = 30 + (base - 100) * 0.015;
  else if (base <= 10000) fee = 43.5 + (base - 1000) * 0.013;
  else if (base <= 50000) fee = 160.5 + (base - 10000) * 0.008;
  else if (base <= 100000) fee = 480.5 + (base - 50000) * 0.005;
  else if (base <= 500000) fee = 730.5 + (base - 100000) * 0.002;
  else fee = Math.min(6000, 1530.5 + (base - 500000) * 0.001);
  return roundMoney(fee / PURCHASE_RULES.bgnPerEur);
}

export function readPurchaseAssumptions() {
  try {
    const raw = JSON.parse(window.localStorage.getItem(STORAGE_KEY));
    return sanitizePurchaseAssumptions(raw);
  } catch { return { ...DEFAULT_PURCHASE_ASSUMPTIONS }; }
}
export function sanitizePurchaseAssumptions(value) {
  const result = { ...DEFAULT_PURCHASE_ASSUMPTIONS };
  if (!value || typeof value !== 'object' || Array.isArray(value)) return result;
  for (const [key, max] of [['brokerPercent', 20], ['acquisitionTaxPercent', 3], ['buyerFeesSharePercent', 100]]) {
    if (bounded(value[key], max) !== null) result[key] = bounded(value[key], max);
  }
  if (['included', 'excluded'].includes(value.brokerVat)) result.brokerVat = value.brokerVat;
  if (['agency', 'private'].includes(value.unknownSeller)) result.unknownSeller = value.unknownSeller;
  if (['sofia', 'other'].includes(value.municipality)) result.municipality = value.municipality;
  for (const key of ['notaryVat', 'includeDrafting']) if (typeof value[key] === 'boolean') result[key] = value[key];
  return result;
}
export function savePurchaseAssumptions(value) {
  try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(sanitizePurchaseAssumptions(value))); } catch { /* Storage is optional. */ }
}

/** Per-listing inputs (tax valuation, negotiated price, extras) are never shared or persisted. */
export function calculatePurchaseCosts(offer, assumptions = {}, inputs = {}) {
  const prefs = { ...DEFAULT_PURCHASE_ASSUMPTIONS, ...assumptions };
  const errors = [];
  const rate = (key, maximum) => {
    const value = bounded(prefs[key], maximum);
    if (value === null) errors.push(key);
    return value;
  };
  const brokerRate = rate('brokerPercent', 20);
  const taxRate = prefs.municipality === 'sofia' ? PURCHASE_RULES.sofiaTaxPercent : rate('acquisitionTaxPercent', 3);
  const feesShare = rate('buyerFeesSharePercent', 100);
  if (!['sofia', 'other'].includes(prefs.municipality)) errors.push('municipality');
  if (!['included', 'excluded'].includes(prefs.brokerVat)) errors.push('brokerVat');
  if (!['agency', 'private'].includes(prefs.unknownSeller)) errors.push('unknownSeller');
  for (const key of ['notaryVat', 'includeDrafting']) if (typeof prefs[key] !== 'boolean') errors.push(key);
  const optionalMoney = (key) => {
    if (inputs[key] === '' || inputs[key] === null || inputs[key] === undefined) return 0;
    const value = bounded(inputs[key], MAX_EUR);
    if (value === null) errors.push(key);
    return value;
  };
  const taxValuation = optionalMoney('taxValuationEur');
  const additionalCosts = optionalMoney('additionalCostsEur');
  const rawPrice = inputs.agreedPriceEur === '' || inputs.agreedPriceEur === undefined ? offer?.price_eur : inputs.agreedPriceEur;
  const price = bounded(rawPrice, MAX_EUR);
  const sourcePriceAvailable = price !== null && price > 0;
  if (inputs.agreedPriceEur !== '' && inputs.agreedPriceEur !== undefined && !sourcePriceAvailable) errors.push('agreedPriceEur');
  const seller = ['agency', 'private'].includes(offer?.seller_type) ? offer.seller_type : 'unknown';
  const commissionChoice = inputs.commissionChoice || 'auto';
  if (!['auto', 'charge', 'none'].includes(commissionChoice)) errors.push('commissionChoice');
  const commissionApplies = commissionChoice === 'charge' || (commissionChoice === 'auto' && (seller === 'agency' || (seller === 'unknown' && prefs.unknownSeller === 'agency')));
  const sourceVat = ['included', 'excluded'].includes(offer?.vat_basis) ? offer.vat_basis : 'unknown';
  const vatChoice = inputs.propertyVat || 'source';
  if (!['source', 'included', 'excluded'].includes(vatChoice)) errors.push('propertyVat');
  const vatBasis = vatChoice === 'source' ? sourceVat : vatChoice;
  const common = { valid: errors.length === 0, errors, sourcePriceAvailable, seller, sellerUnknown: seller === 'unknown', vatBasis, sourceVat, commissionApplies, brokerPercent: commissionApplies ? brokerRate : 0, taxPercent: taxRate, taxValuationKnown: taxValuation > 0, municipality: prefs.municipality, scenarios: [], totalLowEur: null, totalHighEur: null };
  if (errors.length || !sourcePriceAvailable) return common;
  const cases = vatBasis === 'unknown' ? ['included', 'excluded'] : [vatBasis];
  const scenarios = cases.map((vatCase) => {
    const propertyVatEur = vatCase === 'excluded' ? roundMoney(price * 0.2) : 0;
    const purchasePriceEur = roundMoney(price + propertyVatEur);
    // Conservative full consideration including property VAT is assumed. A deed may
    // specify a different legally applicable base; the notary must confirm it.
    const materialInterestEur = Math.max(purchasePriceEur, taxValuation);
    const acquisitionTaxEur = roundMoney(materialInterestEur * taxRate / 100);
    const registrationFullEur = roundMoney(Math.max(PURCHASE_RULES.registrationMinimumEur, materialInterestEur * 0.001));
    const registrationEur = roundMoney(registrationFullEur * feesShare / 100);
    const notaryBaseEur = notaryTariffEur(materialInterestEur);
    const notaryVatEur = prefs.notaryVat ? roundMoney(notaryBaseEur * 0.2) : 0;
    const notaryFullEur = roundMoney(notaryBaseEur + notaryVatEur);
    const notaryEur = roundMoney(notaryFullEur * feesShare / 100);
    const draftingEur = prefs.includeDrafting ? notaryEur : 0;
    const brokerBaseEur = commissionApplies ? roundMoney(purchasePriceEur * brokerRate / 100) : 0;
    const brokerVatEur = prefs.brokerVat === 'excluded' ? roundMoney(brokerBaseEur * 0.2) : 0;
    const brokerEur = roundMoney(brokerBaseEur + brokerVatEur);
    const extraCostsEur = roundMoney(additionalCosts);
    const feesEur = roundMoney(acquisitionTaxEur + registrationEur + notaryEur + draftingEur + brokerEur + extraCostsEur);
    return { vatCase, advertisedBasisPriceEur: roundMoney(price), propertyVatEur, purchasePriceEur, materialInterestEur, acquisitionTaxEur, registrationFullEur, registrationEur, notaryBaseEur, notaryVatEur, notaryFullEur, notaryEur, draftingEur, brokerBaseEur, brokerVatEur, brokerEur, extraCostsEur, feesEur, totalEur: roundMoney(purchasePriceEur + feesEur) };
  });
  return { ...common, scenarios, totalLowEur: Math.min(...scenarios.map((row) => row.totalEur)), totalHighEur: Math.max(...scenarios.map((row) => row.totalEur)) };
}
