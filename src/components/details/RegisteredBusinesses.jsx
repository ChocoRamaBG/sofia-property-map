import React, { useEffect, useId, useRef, useState } from 'react';
import { ArrowUpRight, Building2, ChevronDown, Loader2 } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import './RegisteredBusinesses.css';

const CADASTRAL_ID = /^68134\.\d{1,6}\.\d{1,6}$/;
const ADDRESS_ID = /^address-[a-f0-9]{24}$/;

async function readBusinessData(action, params, signal) {
  const url = new URL('./business-data.php', window.location.href);
  url.searchParams.set('action', action);
  Object.entries(params).forEach(([key, value]) => url.searchParams.set(key, String(value)));
  const response = await fetch(url, { signal, headers: { Accept: 'application/json' } });
  const payload = await response.json();
  if (!response.ok || payload.error) throw new Error('Business address data unavailable');
  return payload;
}

function officialCompanyUrl(company) {
  if (!/^\d{9}$/.test(String(company.uic || ''))) return null;
  return `https://portal.registryagency.bg/CR/Reports/ActiveConditionTabResult?uic=${company.uic}`;
}

function dateLabel(value, lang) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(value)) return null;
  const date = new Date(value.length === 10 ? `${value}T12:00:00Z` : value);
  return Number.isFinite(date.getTime()) ? date.toLocaleDateString(lang === 'bg' ? 'bg-BG' : 'en-GB') : null;
}

function CompanyCard({ company, addressOnly, lang }) {
  const pick = (bg, en) => lang === 'bg' ? bg : en;
  const method = company.match_method || (addressOnly ? 'municipal_address' : 'cadastre_address');
  return <li>
    <h4>{company.name}</h4>
    <div className="registered-businesses-identity"><span>{pick('ЕИК', 'UIC')} {company.uic}</span><span>{pick('Към', 'As of')} {dateLabel(company.as_of, lang) || pick('неизвестна дата', 'date unknown')}</span></div>
    {company.registered_address && <p className="registered-businesses-address">{company.registered_address}</p>}
    <p className="registered-businesses-match">{method === 'municipal_address' ? pick('Официален адрес · парцелът не е установен', 'Official address · parcel not established') : method === 'municipal_parcel' ? pick('Общински адрес · всички точки са в един парцел', 'Municipal address · all points are inside one parcel') : pick('Точно съвпадение с кадастрален адрес', 'Exact cadastral address match')}</p>
    {company.status && <p className="registered-businesses-verification">{company.status === 'not_verified' ? pick('Състоянието на фирмата не е проверено.', 'Company status has not been verified.') : company.status}</p>}
    {officialCompanyUrl(company) && <a className="registered-businesses-source" href={officialCompanyUrl(company)} target="_blank" rel="noreferrer">{pick('Фирмена партида · Търговски регистър', 'Company profile · Commercial Register')}<ArrowUpRight size={13} aria-hidden="true" /></a>}
    <details className="registered-businesses-activity"><summary>{pick('Правна форма и предмет на дейност', 'Legal form and registered activity')}<ChevronDown size={13} aria-hidden="true" /></summary><dl>{company.legal_form && <div><dt>{pick('Правна форма', 'Legal form')}</dt><dd>{company.legal_form}</dd></div>}{company.status && <div><dt>{pick('Състояние в извлечението', 'State in the extract')}</dt><dd>{company.status === 'not_verified' ? pick('Не е проверено — вижте фирмената партида', 'Not verified — check the company profile') : company.status}</dd></div>}<div><dt>{pick('Състояние към', 'Report as of')}</dt><dd>{dateLabel(company.as_of, lang) || pick('Няма посочена дата', 'Date not stated')}</dd></div></dl>{company.activity && <p>{company.activity}</p>}</details>
  </li>;
}

export default function RegisteredBusinesses({ cadastralId, addressId, lang: language }) {
  const addressOnly = Boolean(addressId);
  const resourceId = addressOnly ? addressId : cadastralId;
  const validId = (addressOnly ? ADDRESS_ID : CADASTRAL_ID).test(resourceId || '');
  const action = addressOnly ? 'address' : 'plot';
  const i18n = useI18n();
  const lang = language || i18n.lang;
  const pick = (bg, en) => lang === 'bg' ? bg : en;
  const titleId = useId();
  const requestRef = useRef(null);
  const [state, setState] = useState({ key: null, loading: false, companies: [], total: 0, coverage: null, error: false });
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState(false);

  useEffect(() => {
    requestRef.current?.abort();
    setLoadingMore(false);
    setMoreError(false);
    if (!validId) {
      setState({ key: null, loading: false, companies: [], total: 0, coverage: null, error: false });
      return undefined;
    }
    const controller = new AbortController();
    requestRef.current = controller;
    setState({ key: resourceId, loading: true, companies: [], total: 0, coverage: null, error: false });
    readBusinessData(action, { id: resourceId, offset: 0, limit: 20 }, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        if (!Array.isArray(data.companies) || !Number.isSafeInteger(data.total) || data.total < data.companies.length) throw new Error('Invalid company response');
        setState({ key: resourceId, loading: false, companies: data.companies, total: data.total, coverage: data.coverage || null, snapshotId: data.snapshot_id, error: false });
      })
      .catch(() => { if (!controller.signal.aborted) setState({ key: resourceId, loading: false, companies: [], total: 0, coverage: null, error: true }); });
    return () => { controller.abort(); requestRef.current?.abort(); };
  }, [resourceId, action, validId]);

  async function loadMore() {
    if (state.key !== resourceId || loadingMore || state.companies.length >= state.total) return;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    const key = resourceId;
    setLoadingMore(true);
    setMoreError(false);
    try {
      const data = await readBusinessData(action, { id: key, offset: state.companies.length, limit: 20 }, controller.signal);
      if (controller.signal.aborted) return;
      if (!Array.isArray(data.companies) || !Number.isSafeInteger(data.total) || !data.companies.length || (state.snapshotId && data.snapshot_id !== state.snapshotId) || data.total !== state.total) throw new Error('Invalid or changed company page');
      setState((previous) => previous.key === key ? { ...previous, companies: [...previous.companies, ...data.companies], total: data.total, coverage: data.coverage || previous.coverage } : previous);
    } catch {
      if (!controller.signal.aborted) setMoreError(true);
    } finally {
      if (!controller.signal.aborted) setLoadingMore(false);
    }
  }

  if (!validId) return null;
  const current = state.key === resourceId ? state : { loading: true, companies: [], total: 0 };
  const coverage = current.coverage || {};
  const generatedDate = dateLabel(coverage.generated_at, lang);
  const sourceDate = dateLabel(coverage.source?.committed_at || coverage.source?.commit_date, lang);
  const cadastreFrom = dateLabel(coverage.cadastre?.captured_from, lang);
  const cadastreTo = dateLabel(coverage.cadastre?.captured_to, lang);
  const cadastreDate = cadastreFrom && cadastreTo && cadastreFrom !== cadastreTo ? `${cadastreFrom} – ${cadastreTo}` : (cadastreFrom || cadastreTo || dateLabel(coverage.cadastre?.captured_at, lang));
  const commit = coverage.source?.commit;
  const sourceLink = /^[a-f0-9]{40}$/.test(commit || '')
    ? `https://github.com/ChocoRamaBG/register-of-outpatient-care-facilities-and-hospices/tree/${commit}/registry_agency_scraper/registry_agency_outputs`
    : null;
  return (
    <section className="registered-businesses" aria-labelledby={titleId} aria-busy={current.loading || loadingMore}>
      <div className="registered-businesses-heading"><Building2 size={18} aria-hidden="true" /><h3 id={titleId}>{addressOnly ? pick('Фирми на този официален адрес', 'Companies at this official address') : pick('Фирми с регистриран адрес тук', 'Companies registered at this address')}</h3>{!current.loading && !current.error && <span>{current.total.toLocaleString(lang === 'bg' ? 'bg-BG' : 'en-GB')}</span>}</div>
      <p className="registered-businesses-explanation">{addressOnly ? pick('Официален фирмен адрес без установен парцел. Адресът не доказва собственост или реална дейност тук.', 'An official company address without an established parcel. It proves neither ownership nor actual activity here.') : pick('Адресна връзка с парцела — не доказва собственост или реална дейност тук.', 'An address association with this parcel — it proves neither ownership nor actual activity here.')}</p>
      {current.loading ? <p className="registered-businesses-status" role="status"><Loader2 size={15} className="animate-spin" aria-hidden="true" />{pick('Проверка на регистрираните адреси…', 'Checking registered addresses…')}</p> : current.error ? <p className="registered-businesses-status" role="status">{pick('Фирмените адреси временно не са достъпни.', 'Business addresses are temporarily unavailable.')}</p> : <>
        {current.total === 0 ? <p className="registered-businesses-status">{pick('Няма еднозначно свързан фирмен адрес в наличното извлечение. Това не означава, че тук няма регистрирани фирми.', 'No company address is unambiguously linked in this extract. This does not establish that no companies are registered here.')}</p> : <>
          <ul className="registered-businesses-list">{current.companies.slice(0, 2).map((company) => <CompanyCard key={company.uic} company={company} addressOnly={addressOnly} lang={lang} />)}</ul>
          {current.total > 2 && <details className="registered-businesses-remainder" key={resourceId}><summary><span>{pick('Още фирми на този адрес', 'More companies at this address')}</span><strong>{current.total - 2}</strong><ChevronDown size={15} aria-hidden="true" /></summary><ul className="registered-businesses-list">{current.companies.slice(2).map((company) => <CompanyCard key={company.uic} company={company} addressOnly={addressOnly} lang={lang} />)}</ul>{current.companies.length < current.total && <button className="registered-businesses-more" type="button" onClick={loadMore} disabled={loadingMore}>{loadingMore && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}{pick('Зареди още фирми', 'Load more companies')}<span>{current.companies.length} / {current.total}</span></button>}{moreError && <p className="registered-businesses-status" role="status">{pick('Следващите записи не се заредиха. Опитайте отново.', 'The next records could not be loaded. Please try again.')}</p>}</details>}
        </>}
        <details className="registered-businesses-method"><summary>{pick('Източник и свързване', 'Source and matching')}<ChevronDown size={13} aria-hidden="true" /></summary><p>{pick('Фирмени извлечения от Търговския регистър, предоставени чрез проекта на ChocoRamaBG, кадастрални данни на АГКК и официални адреси на Столична община. Методите за адрес и за парцел се показват отделно. Наборът има ограничено покритие; нееднозначните парцели не се избират приблизително.', 'Commercial Register extracts supplied through the ChocoRamaBG project, AGKK cadastral data and official Sofia Municipality addresses. Address and parcel matching are stated separately. Coverage is limited; ambiguous parcels are never selected approximately.')}</p>{generatedDate && <p>{pick('Подготвено извлечение:', 'Prepared snapshot:')} {generatedDate}</p>}{sourceDate && <p>{pick('Версия на фирмените извлечения:', 'Company export revision:')} {sourceDate}</p>}{cadastreDate && <p>{pick('Кадастрални данни, изтеглени на:', 'Cadastral data captured:')} {cadastreDate}</p>}{sourceLink && <a href={sourceLink} target="_blank" rel="noreferrer">{pick('Версия на предоставените данни', 'Supplied data revision')} · {commit.slice(0, 7)}<ArrowUpRight size={13} aria-hidden="true" /></a>}<a href="https://kais.cadastre.bg/bg/OpenData" target="_blank" rel="noreferrer">{pick('Кадастрален източник · АГКК', 'Cadastral source · AGKK')}<ArrowUpRight size={13} aria-hidden="true" /></a>{coverage.municipal_source && <div className="registered-businesses-municipal-source"><a href="https://urbandata.sofia.bg/dataset/address_sofia-zip" target="_blank" rel="noreferrer">{pick('Столична община · официални адреси', 'Sofia Municipality · official addresses')}<ArrowUpRight size={13} aria-hidden="true" /></a><a href="https://urbandata.sofia.bg/dataset/streets_names_new_old-zip" target="_blank" rel="noreferrer">{pick('Официални стари и нови имена на улици', 'Official former and current street names')}<ArrowUpRight size={13} aria-hidden="true" /></a><p>{pick('Адресни данни: Столична община,', 'Address data: Sofia Municipality,')} <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer">CC BY 4.0</a>. {pick('Адресите са нормализирани и съпоставени за този сайт.', 'Addresses were normalized and matched for this website.')}</p></div>}</details>
      </>}
    </section>
  );
}
