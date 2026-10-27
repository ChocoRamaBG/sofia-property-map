import test from 'node:test';
import assert from 'node:assert/strict';
import { calculatePurchaseCosts, DEFAULT_PURCHASE_ASSUMPTIONS, notaryTariffEur, PURCHASE_RULES, sanitizePurchaseAssumptions } from '../src/lib/purchaseCosts.js';

const offer = { id: 'test', price_eur: 100000, seller_type: 'agency', vat_basis: 'included' };
const result = (data = offer, settings = {}, inputs = {}) => calculatePurchaseCosts(data, settings, inputs);

test('Sofia buyer budget includes tax, notarisation with VAT, registration and stated assumed commission', () => {
  const actual = result();
  assert.equal(actual.valid, true);
  assert.equal(actual.scenarios.length, 1);
  assert.equal(actual.scenarios[0].notaryBaseEur, 471.24);
  assert.equal(actual.scenarios[0].notaryVatEur, 94.25);
  assert.equal(actual.scenarios[0].acquisitionTaxEur, 3000);
  assert.equal(actual.scenarios[0].registrationEur, 100);
  assert.equal(actual.scenarios[0].brokerEur, 3000);
  assert.equal(actual.totalLowEur, 106665.49);
});
test('private sellers have no assumed broker fee; buyer can explicitly add their own broker', () => {
  const data = { ...offer, seller_type: 'private' };
  assert.equal(result(data).scenarios[0].brokerEur, 0);
  assert.equal(result(data).totalLowEur, 103665.49);
  assert.equal(result(data, {}, { commissionChoice: 'charge' }).scenarios[0].brokerEur, 3000);
});
test('unknown seller has visible metadata and conservative editable commission assumption', () => {
  const data = { ...offer, seller_type: 'unknown' };
  assert.equal(result(data).sellerUnknown, true);
  assert.equal(result(data).scenarios[0].brokerEur, 3000);
  assert.equal(result(data, { unknownSeller: 'private' }).scenarios[0].brokerEur, 0);
});
test('known excluded property VAT is added once before taxes and commission; commission VAT is independent', () => {
  const actual = result({ ...offer, vat_basis: 'excluded' }, { brokerVat: 'excluded' }).scenarios[0];
  assert.equal(actual.propertyVatEur, 20000);
  assert.equal(actual.purchasePriceEur, 120000);
  assert.equal(actual.acquisitionTaxEur, 3600);
  assert.equal(actual.brokerBaseEur, 3600);
  assert.equal(actual.brokerVatEur, 720);
  assert.equal(actual.brokerEur, 4320);
});
test('unknown property VAT produces two scenarios, never a single supposedly final cost', () => {
  const actual = result({ ...offer, vat_basis: 'unknown' });
  assert.equal(actual.vatBasis, 'unknown');
  assert.deepEqual(actual.scenarios.map((row) => row.vatCase), ['included', 'excluded']);
  assert.ok(actual.totalHighEur > actual.totalLowEur + 20000);
  const selected = result({ ...offer, vat_basis: 'unknown' }, {}, { propertyVat: 'included' });
  assert.equal(selected.sourceVat, 'unknown');
  assert.equal(selected.scenarios.length, 1);
});
test('higher tax valuation changes tax/registry/notary but never seller consideration or commission', () => {
  const actual = result(offer, {}, { taxValuationEur: '150000' }).scenarios[0];
  assert.equal(actual.materialInterestEur, 150000);
  assert.equal(actual.acquisitionTaxEur, 4500);
  assert.equal(actual.registrationEur, 150);
  assert.equal(actual.brokerEur, 3000);
  assert.equal(actual.purchasePriceEur, 100000);
});
test('tariff handles every official threshold continuously and caps the pre-VAT fee', () => {
  for (const [bgn, fee] of [[100,30],[1000,43.5],[10000,160.5],[50000,480.5],[100000,730.5],[500000,1530.5]]) {
    assert.equal(notaryTariffEur(bgn / PURCHASE_RULES.bgnPerEur), Math.round(fee / PURCHASE_RULES.bgnPerEur * 100) / 100);
  }
  assert.equal(notaryTariffEur(20_000_000), 3067.75);
  assert.equal(notaryTariffEur(-1), null);
});
test('registration has converted minimum; optional fee sharing and deed drafting are explicit', () => {
  const tiny = result({ ...offer, price_eur: 1000 }).scenarios[0];
  assert.equal(tiny.registrationEur, 5.11);
  const shared = result(offer, { buyerFeesSharePercent: 50, includeDrafting: true }).scenarios[0];
  assert.equal(shared.notaryEur, 282.75);
  assert.equal(shared.registrationEur, 50);
  assert.equal(shared.draftingEur, 282.75);
  assert.equal(shared.acquisitionTaxEur, 3000);
});
test('another municipality uses its chosen rate, not a falsely attributed Sofia rate', () => {
  const actual = result(offer, { municipality: 'other', acquisitionTaxPercent: '2,5' });
  assert.equal(actual.municipality, 'other');
  assert.equal(actual.scenarios[0].acquisitionTaxEur, 2500);
});
test('negotiated price and additional budget affect only that calculation; missing price stays unpriced', () => {
  const edited = result(offer, {}, { agreedPriceEur: '90000', additionalCostsEur: '1234,56' });
  assert.equal(edited.scenarios[0].purchasePriceEur, 90000);
  assert.equal(edited.scenarios[0].extraCostsEur, 1234.56);
  assert.equal(result().scenarios[0].purchasePriceEur, 100000);
  assert.equal(result({ ...offer, price_eur: null }).totalLowEur, null);
});
test('invalid values suppress a misleading total instead of silently becoming zero or defaults', () => {
  for (const settings of [{ brokerPercent: '' }, { brokerPercent: -1 }, { brokerPercent: 'Infinity' }, { buyerFeesSharePercent: 101 }, { municipality: 'other', acquisitionTaxPercent: 4 }]) {
    const actual = result(offer, settings);
    assert.equal(actual.valid, false);
    assert.equal(actual.totalLowEur, null);
  }
  assert.equal(result(offer, {}, { taxValuationEur: 'oops' }).valid, false);
  assert.equal(result(offer, {}, { agreedPriceEur: '0' }).valid, false);
});
test('stored preferences are allowlisted, bounded and contain no individual property values', () => {
  const actual = sanitizePurchaseAssumptions({ ...DEFAULT_PURCHASE_ASSUMPTIONS, brokerPercent: '2,5', taxValuationEur: 999999, additionalCostsEur: 999999, buyerFeesSharePercent: 999, malicious: true });
  assert.equal(actual.brokerPercent, 2.5);
  assert.equal(actual.buyerFeesSharePercent, 100);
  assert.equal('taxValuationEur' in actual, false);
  assert.equal('additionalCostsEur' in actual, false);
  assert.equal('malicious' in actual, false);
});
test('maximum input price with added VAT remains finite and respects the notary cap', () => {
  const actual = result({ ...offer, price_eur: 1_000_000_000, vat_basis: 'excluded' });
  assert.equal(actual.valid, true);
  assert.ok(Number.isFinite(actual.totalHighEur));
  assert.equal(actual.scenarios[0].notaryBaseEur, 3067.75);
});
