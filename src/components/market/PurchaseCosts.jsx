import React, { createContext, useContext, useEffect, useId, useState } from 'react';
import { Calculator, ChevronDown, ExternalLink, Info } from 'lucide-react';
import { calculatePurchaseCosts, DEFAULT_PURCHASE_ASSUMPTIONS, PURCHASE_RULES, readPurchaseAssumptions, savePurchaseAssumptions } from '@/lib/purchaseCosts';
import './PurchaseCosts.css';

const PurchaseCostContext = createContext(null);
export function PurchaseCostProvider({ children }) {
  const [assumptions, setAssumptions] = useState(readPurchaseAssumptions);
  useEffect(() => { savePurchaseAssumptions(assumptions); }, [assumptions]);
  return <PurchaseCostContext.Provider value={{ assumptions, update: (patch) => setAssumptions((current) => ({ ...current, ...patch })) }}>{children}</PurchaseCostContext.Provider>;
}

export default function PurchaseCosts({ offer, lang = 'bg', assumptions: supplied, onAssumptionsChange }) {
  const shared = useContext(PurchaseCostContext);
  const [local, setLocal] = useState(() => ({ ...DEFAULT_PURCHASE_ASSUMPTIONS }));
  const [inputs, setInputs] = useState({ agreedPriceEur: '', taxValuationEur: '', additionalCostsEur: '', commissionChoice: 'auto', propertyVat: 'source' });
  useEffect(() => { setInputs({ agreedPriceEur: '', taxValuationEur: '', additionalCostsEur: '', commissionChoice: 'auto', propertyVat: 'source' }); }, [offer?.id]);
  const assumptions = supplied || shared?.assumptions || local;
  const updateAssumptions = (patch) => {
    if (supplied && onAssumptionsChange) onAssumptionsChange({ ...supplied, ...patch });
    else if (!supplied && shared) shared.update(patch);
    else setLocal((current) => ({ ...current, ...patch }));
  };
  const updateInput = (key, value) => setInputs((current) => ({ ...current, [key]: value }));
  const id = useId();
  const bg = lang === 'bg';
  const text = (a, b) => bg ? a : b;
  const money = (value) => new Intl.NumberFormat(bg ? 'bg-BG' : 'en-GB', { style: 'currency', currency: 'EUR', maximumFractionDigits: 2 }).format(value);
  const result = calculatePurchaseCosts(offer, assumptions, inputs);
  const ranges = result.scenarios.length > 1;
  const commissionPercent = result.brokerPercent ?? 0;
  const amount = result.totalLowEur === null ? '—' : ranges ? `${money(result.totalLowEur)} – ${money(result.totalHighEur)}` : money(result.totalLowEur);
  const area = typeof offer?.area_sqm === 'number' && Number.isFinite(offer.area_sqm) && offer.area_sqm > 0 ? offer.area_sqm : null;
  const field = (key, label, value, onChange, options = {}) => <label className="purchase-cost-field" htmlFor={`${id}-${key}`}><span>{label}</span><input id={`${id}-${key}`} type="text" inputMode="decimal" autoComplete="off" maxLength={16} value={value} placeholder={options.placeholder || '0'} aria-invalid={result.errors.includes(key) || undefined} onChange={(event) => onChange(event.target.value)} /></label>;
  const row = (label, value, className = '') => <div className={className}><dt>{label}</dt><dd>{money(value)}</dd></div>;
  return <section className="purchase-costs" aria-label={text('Бюджет за покупка', 'Purchase budget')}>
    <div className="purchase-cost-heading"><span><Calculator size={15} aria-hidden="true" />{text('Ориентировъчен общ бюджет', 'Estimated total purchase budget')}</span><strong className={ranges ? 'is-range' : ''}>{amount}</strong></div>
    {area && result.totalLowEur !== null && <p className="purchase-cost-basis">{ranges ? `${money(result.totalLowEur / area)} – ${money(result.totalHighEur / area)}` : money(result.totalLowEur / area)}{text(' / м² по заявената площ, с разходите', ' / m² of advertised area, including costs')}</p>}
    <p className="purchase-cost-basis">{assumptions.municipality === 'sofia' ? text('Модел за София · данък 3%', 'Sofia model · acquisition tax 3%') : text(`Избрана местна ставка ${assumptions.acquisitionTaxPercent}%`, `Selected local tax ${assumptions.acquisitionTaxPercent}%`)} · {text('комисиона', 'commission')} {commissionPercent}%{commissionPercent > 0 && assumptions.brokerVat === 'excluded' ? text(' + ДДС', ' + VAT') : commissionPercent > 0 ? text(' с включен ДДС', ' including VAT') : ''}</p>
    {result.vatBasis === 'unknown' && <p className="purchase-cost-warning"><Info size={13} aria-hidden="true" />{text('ДДС на имота не е уточнен: показани са два отделни сценария — без добавяне и с добавяне на 20%.', 'Property VAT is unspecified: two separate scenarios show no addition and 20% added.')}</p>}
    {result.sellerUnknown && <p className="purchase-cost-warning"><Info size={13} aria-hidden="true" />{text('Продавачът е неустановен. Комисионата е допускане, което можете да промените.', 'Seller type is unknown. The commission is an editable assumption.')}</p>}
    <p className="purchase-cost-scope">{text('Допускане: купувачът плаща данъка и избрания дял от нотариус/вписване. Непосочени кредитни разходи, документи и адвокат не са добавени.', 'Assumes the buyer pays acquisition tax and the selected notary/registration share. Unspecified financing, document and legal costs are not added.')}{!assumptions.includeDrafting && text(' Проект на нотариалния акт не е включен.', ' Deed drafting is not included.')}</p>
    <details className="purchase-cost-breakdown">
      <summary>{text('Разбивка и мои допускания', 'Breakdown and my assumptions')}<ChevronDown size={15} aria-hidden="true" /></summary>
      {!result.sourcePriceAvailable && <p className="purchase-cost-warning">{text('Няма посочена обща цена. Въведете цена по-долу, за да изчислите бюджет.', 'No total price is stated. Enter a price below to calculate a budget.')}</p>}
      {!result.valid && <p className="purchase-cost-warning" role="alert">{text('Проверете маркираните стойности. Сумите трябва да са положителни числа, данъкът — от 0 до 3%, комисионата — от 0 до 20%, делът — от 0 до 100%.', 'Check the marked values. Use non-negative amounts, tax 0–3%, commission 0–20%, and a 0–100% share.')}</p>}
      {result.scenarios.map((scenario) => <div className="purchase-cost-scenario" key={scenario.vatCase}>
        {ranges && <h4>{scenario.vatCase === 'excluded' ? text('Ако се добавя 20% ДДС', 'If 20% VAT is added') : text('Ако ДДС е включен / не се начислява', 'If VAT is included / not charged')}</h4>}
        <dl>
          {row(text('Обявена / въведена цена', 'Advertised / entered price'), scenario.advertisedBasisPriceEur)}
          {scenario.propertyVatEur > 0 && row(text('ДДС върху имота · 20%', 'Property VAT · 20%'), scenario.propertyVatEur)}
          {row(text(`Данък придобиване · ${result.taxPercent}%`, `Acquisition tax · ${result.taxPercent}%`), scenario.acquisitionTaxEur)}
          {row(text(`Вписване · 0,1% · ваш дял ${assumptions.buyerFeesSharePercent}%`, `Registration · 0.1% · your share ${assumptions.buyerFeesSharePercent}%`), scenario.registrationEur)}
          {row(text(`Нотариус · т. 8${assumptions.notaryVat ? ' с ДДС' : ' без ДДС'} · ваш дял ${assumptions.buyerFeesSharePercent}%`, `Notary · item 8${assumptions.notaryVat ? ' incl. VAT' : ' no VAT'} · your share ${assumptions.buyerFeesSharePercent}%`), scenario.notaryEur)}
          {assumptions.includeDrafting && row(text('Проект на акта · т. 20 · ваш дял', 'Deed drafting · item 20 · your share'), scenario.draftingEur)}
          {row(text(`Брокер · ${commissionPercent}%${assumptions.brokerVat === 'excluded' && commissionPercent ? ' + 20% ДДС' : ''}`, `Broker · ${commissionPercent}%${assumptions.brokerVat === 'excluded' && commissionPercent ? ' + 20% VAT' : ''}`), scenario.brokerEur)}
          {row(text('Мой допълнителен бюджет', 'My additional budget'), scenario.extraCostsEur)}
          {row(text('Общо', 'Total'), scenario.totalEur, 'purchase-cost-total-row')}
        </dl>
        <p className="purchase-cost-material">{text('Използван материален интерес:', 'Assumed taxable/material value:')} {money(scenario.materialInterestEur)}</p>
      </div>)}
      {!result.taxValuationKnown && <p className="purchase-cost-warning">{text('Данъчната оценка липсва. Използваме пълната цена с евентуален ДДС; ако данъчната оценка е по-висока, таксите ще нараснат.', 'Tax valuation is missing. The full price including any added VAT is used; a higher tax valuation increases the fees.')}</p>}
      <div className="purchase-cost-local-settings">
        <h4>{text('Само за тази обява', 'This listing only')}</h4>
        <div className="purchase-cost-fields">
          {field('agreedPriceEur', text('Договорена цена · € (в същата основа за ДДС)', 'Negotiated price · € (same VAT basis)'), inputs.agreedPriceEur, (value) => updateInput('agreedPriceEur', value), { placeholder: offer?.price_eur ? String(offer.price_eur) : text('Въведете цена', 'Enter price') })}
          {field('taxValuationEur', text('Данъчна оценка · €', 'Tax valuation · €'), inputs.taxValuationEur, (value) => updateInput('taxValuationEur', value), { placeholder: text('Не е известна', 'Unknown') })}
          <label className="purchase-cost-field" htmlFor={`${id}-propertyVat`}><span>{text('ДДС на имота', 'Property VAT')}</span><select id={`${id}-propertyVat`} value={inputs.propertyVat} onChange={(event) => updateInput('propertyVat', event.target.value)}><option value="source">{text('Както е в обявата', 'Use listing statement')}</option><option value="included">{text('Приемам: включен / не се начислява', 'Assume included / not charged')}</option><option value="excluded">{text('Приемам: добавя се 20%', 'Assume 20% is added')}</option></select></label>
          <label className="purchase-cost-field" htmlFor={`${id}-commissionChoice`}><span>{text('Комисиона за купувача', 'Buyer commission')}</span><select id={`${id}-commissionChoice`} value={inputs.commissionChoice} onChange={(event) => updateInput('commissionChoice', event.target.value)}><option value="auto">{text('Според типа продавач', 'Based on seller type')}</option><option value="none">{text('Няма комисиона', 'No commission')}</option><option value="charge">{text('Има брокерска комисиона', 'Broker commission applies')}</option></select></label>
          {field('additionalCostsEur', text('Кредит, адвокат, документи и други · €', 'Financing, legal, documents and other · €'), inputs.additionalCostsEur, (value) => updateInput('additionalCostsEur', value))}
        </div>
      </div>
      <details className="purchase-cost-shared-settings">
        <summary>{text(shared && !supplied ? 'Настройки за всички обяви' : 'Настройки на изчислението', shared && !supplied ? 'Settings for all listings' : 'Calculation settings')}<ChevronDown size={14} aria-hidden="true" /></summary>
        <div className="purchase-cost-fields">
          <label className="purchase-cost-field" htmlFor={`${id}-municipality`}><span>{text('Местен данък', 'Local acquisition tax')}</span><select id={`${id}-municipality`} value={assumptions.municipality} onChange={(event) => updateAssumptions({ municipality: event.target.value })}><option value="sofia">{text('Столична община · 3%', 'Sofia municipality · 3%')}</option><option value="other">{text('Друга община · моя ставка', 'Other municipality · my rate')}</option></select></label>
          {assumptions.municipality === 'other' && field('acquisitionTaxPercent', text('Ставка на другата община · %', 'Other municipality rate · %'), assumptions.acquisitionTaxPercent, (value) => updateAssumptions({ acquisitionTaxPercent: value }))}
          {field('brokerPercent', text('Брокерска комисиона · %', 'Broker commission · %'), assumptions.brokerPercent, (value) => updateAssumptions({ brokerPercent: value }))}
          <label className="purchase-cost-field" htmlFor={`${id}-brokerVat`}><span>{text('ДДС на комисионата', 'Commission VAT')}</span><select id={`${id}-brokerVat`} value={assumptions.brokerVat} onChange={(event) => updateAssumptions({ brokerVat: event.target.value })}><option value="included">{text('Включен в избрания процент', 'Included in selected percentage')}</option><option value="excluded">{text('Добавя се 20% към комисионата', 'Add 20% to commission')}</option></select></label>
          <label className="purchase-cost-field" htmlFor={`${id}-unknownSeller`}><span>{text('При неустановен продавач', 'When seller is unknown')}</span><select id={`${id}-unknownSeller`} value={assumptions.unknownSeller} onChange={(event) => updateAssumptions({ unknownSeller: event.target.value })}><option value="agency">{text('Предвиждам комисиона', 'Budget for commission')}</option><option value="private">{text('Приемам без комисиона', 'Assume no commission')}</option></select></label>
          {field('buyerFeesSharePercent', text('Моят дял нотариус / вписване · %', 'My notary / registration share · %'), assumptions.buyerFeesSharePercent, (value) => updateAssumptions({ buyerFeesSharePercent: value }))}
        </div>
        <label className="purchase-cost-check"><input type="checkbox" checked={assumptions.notaryVat} onChange={(event) => updateAssumptions({ notaryVat: event.target.checked })} /><span>{text('Добави 20% ДДС към нотариалната такса', 'Add 20% VAT to the notary fee')}</span></label>
        <label className="purchase-cost-check"><input type="checkbox" checked={assumptions.includeDrafting} onChange={(event) => updateAssumptions({ includeDrafting: event.target.checked })} /><span>{text('Добави проект на нотариалния акт · т. 20 (още една такса по т. 8)', 'Add deed drafting · item 20 (one additional item 8 fee)')}</span></label>
        <p className="purchase-cost-scope">{text('Ставката 3% важи за Столична община. Обявите включват и други населени места — проверете общината. Комисионата е лично допускане, не установена оферта на агенцията; начисляваме я върху пълната покупна цена. Дяловете от таксите и допълнителните услуги зависят от уговорката.', 'The 3% rate applies to Sofia municipality. Listings include other settlements: confirm the municipality. Commission is your assumption, not an agency quote, and is applied to the full purchase price. Fee shares and additional services depend on agreement.')}</p>
      </details>
      <details className="purchase-cost-sources">
        <summary>{text('Правила и официални източници', 'Rules and official sources')}<ChevronDown size={14} aria-hidden="true" /></summary>
        <p>{text('Проверени на', 'Checked on')} {PURCHASE_RULES.checkedAt}. {text('Основата е по-високата от пълната договорена цена и въведената данъчна оценка. Потвърдете с нотариуса приложимата основа, включително третирането на ДДС. Тарифата по т. 8 е прогресивна, с таван 6000 лв. преди ДДС; превалутираме по пълния курс 1,95583 и закръгляме до евроцент. Вписване: 0,1%, минимум 5,11 €.', 'The higher of full consideration and entered tax valuation is used. Confirm the legally applicable base, including VAT treatment, with the notary. Item 8 is progressive and capped at BGN 6,000 before VAT; conversion uses the full 1.95583 rate and rounds to euro cents. Registration: 0.1%, minimum €5.11.')}</p>
        <p>{text('Бюджетът е ориентир при тези допускания. Не включва годишния данък, такса смет, бъдещи лихви, ремонт, паркомясто или доплащания, освен ако ги добавите. Не е окончателна сметка от нотариус.', 'This is a budget under the selected assumptions. Annual property/waste taxes, future interest, renovation, parking and additional payments are excluded unless entered. It is not a final notary invoice.')}</p>
        <ul>{PURCHASE_RULES.sources.map((source) => <li key={source.key}><a href={source.url} target="_blank" rel="noreferrer">{bg ? source.labelBg : source.labelEn}<ExternalLink size={12} aria-hidden="true" /></a></li>)}</ul>
      </details>
    </details>
  </section>;
}
