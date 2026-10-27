import React, { useEffect, useId, useRef, useState } from 'react';
import { ArrowUpRight, Building2, ChevronDown, Loader2 } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import './RegisteredBusinesses.css';

const CADASTRAL_ID = /^68134\.\d{1,6}\.\d{1,6}$/;

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

export default function RegisteredBusinesses({ cadastralId, lang: language }) {
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
    if (!CADASTRAL_ID.test(cadastralId || '')) {
      setState({ key: null, loading: false, companies: [], total: 0, coverage: null, error: false });
      return undefined;
    }
    const controller = new AbortController();
    requestRef.current = controller;
    setState({ key: cadastralId, loading: true, companies: [], total: 0, coverage: null, error: false });
    readBusinessData('plot', { id: cadastralId, offset: 0, limit: 20 }, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        if (!Array.isArray(data.companies) || !Number.isSafeInteger(data.total) || data.total < data.companies.length) throw new Error('Invalid company response');
        setState({ key: cadastralId, loading: false, companies: data.companies, total: data.total, coverage: data.coverage || null, snapshotId: data.snapshot_id, error: false });
      })
      .catch(() => { if (!controller.signal.aborted) setState({ key: cadastralId, loading: false, companies: [], total: 0, coverage: null, error: true }); });
    return () => { controller.abort(); requestRef.current?.abort(); };
  }, [cadastralId]);

  async function loadMore() {
    if (state.key !== cadastralId || loadingMore || state.companies.length >= state.total) return;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    const key = cadastralId;
    setLoadingMore(true);
    setMoreError(false);
    try {
      const data = await readBusinessData('plot', { id: key, offset: state.companies.length, limit: 20 }, controller.signal);
      if (controller.signal.aborted) return;
      if (!Array.isArray(data.companies) || !Number.isSafeInteger(data.total) || !data.companies.length || (state.snapshotId && data.snapshot_id !== state.snapshotId) || data.total !== state.total) throw new Error('Invalid or changed company page');
      setState((previous) => previous.key === key ? { ...previous, companies: [...previous.companies, ...data.companies], total: data.total, coverage: data.coverage || previous.coverage } : previous);
    } catch {
      if (!controller.signal.aborted) setMoreError(true);
    } finally {
      if (!controller.signal.aborted) setLoadingMore(false);
    }
  }

  if (!CADASTRAL_ID.test(cadastralId || '')) return null;
  const current = state.key === cadastralId ? state : { loading: true, companies: [], total: 0 };
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
      <div className="registered-businesses-heading"><Building2 size={18} aria-hidden="true" /><h3 id={titleId}>{pick('Фирми с регистриран адрес тук', 'Companies registered at this address')}</h3>{!current.loading && !current.error && <span>{current.total.toLocaleString(lang === 'bg' ? 'bg-BG' : 'en-GB')}</span>}</div>
      <p className="registered-businesses-explanation">{pick('Адресът на управление съвпада еднозначно с кадастрален адрес. Това не установява собственост върху имота или реална дейност на място.', 'The registered office matches one unambiguous cadastral address. This establishes neither property ownership nor actual activity at the location.')}</p>
      {current.loading ? <p className="registered-businesses-status" role="status"><Loader2 size={15} className="animate-spin" aria-hidden="true" />{pick('Проверка на регистрираните адреси…', 'Checking registered addresses…')}</p> : current.error ? <p className="registered-businesses-status" role="status">{pick('Фирмените адреси временно не са достъпни.', 'Business addresses are temporarily unavailable.')}</p> : <>
        {current.total === 0 ? <p className="registered-businesses-status">{pick('Няма еднозначно свързан фирмен адрес в наличното извлечение. Това не означава, че тук няма регистрирани фирми.', 'No company address is unambiguously linked in this extract. This does not establish that no companies are registered here.')}</p> : <>
          <ul className="registered-businesses-list">{current.companies.map((company) => <li key={company.uic}>
            <h4>{company.name}</h4>
            <div className="registered-businesses-identity"><span>{pick('ЕИК', 'UIC')} {company.uic}</span>{company.legal_form && <span>{company.legal_form}</span>}</div>
            {company.registered_address && <p className="registered-businesses-address">{company.registered_address}</p>}
            <dl>{company.status && <div><dt>{pick('Състояние в извлечението', 'State in the extract')}</dt><dd>{company.status === 'not_verified' ? pick('Не е проверено — вижте фирмената партида', 'Not verified — check the company profile') : company.status}</dd></div>}<div><dt>{pick('Състояние към', 'Report as of')}</dt><dd>{dateLabel(company.as_of, lang) || pick('Няма посочена дата', 'Date not stated')}</dd></div></dl>
            {company.activity && <details className="registered-businesses-activity"><summary>{pick('Предмет на дейност', 'Registered business activity')}<ChevronDown size={13} aria-hidden="true" /></summary><p>{company.activity}</p></details>}
            {officialCompanyUrl(company) && <a className="registered-businesses-source" href={officialCompanyUrl(company)} target="_blank" rel="noreferrer">{pick('Фирмена партида · Търговски регистър', 'Company profile · Commercial Register')}<ArrowUpRight size={13} aria-hidden="true" /></a>}
          </li>)}</ul>
          {current.companies.length < current.total && <button className="registered-businesses-more" type="button" onClick={loadMore} disabled={loadingMore}>{loadingMore && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}{pick('Покажи още фирми', 'Show more companies')}<span>{current.companies.length} / {current.total}</span></button>}
          {moreError && <p className="registered-businesses-status" role="status">{pick('Следващите записи не се заредиха. Опитайте отново.', 'The next records could not be loaded. Please try again.')}</p>}
        </>}
        <details className="registered-businesses-method"><summary>{pick('Източник и свързване', 'Source and matching')}<ChevronDown size={13} aria-hidden="true" /></summary><p>{pick('Фирмени извлечения от Търговския регистър, предоставени чрез проекта на ChocoRamaBG, и адреси от отворените данни на АГКК за София. Свързването изисква точно име на улица и номер; нееднозначните и непълните адреси остават несвързани. Наборът има ограничено покритие.', 'Commercial Register extracts supplied through the ChocoRamaBG project, matched to addresses in AGKK Sofia open data. Exact street names and house numbers are required; ambiguous and incomplete addresses remain unlinked. Dataset coverage is limited.')}</p>{generatedDate && <p>{pick('Подготвено извлечение:', 'Prepared snapshot:')} {generatedDate}</p>}{sourceDate && <p>{pick('Версия на фирмените извлечения:', 'Company export revision:')} {sourceDate}</p>}{cadastreDate && <p>{pick('Кадастрални данни, изтеглени на:', 'Cadastral data captured:')} {cadastreDate}</p>}{sourceLink && <a href={sourceLink} target="_blank" rel="noreferrer">{pick('Версия на предоставените данни', 'Supplied data revision')} · {commit.slice(0, 7)}<ArrowUpRight size={13} aria-hidden="true" /></a>}<a href="https://kais.cadastre.bg/bg/OpenData" target="_blank" rel="noreferrer">{pick('Кадастрален източник · АГКК', 'Cadastral source · AGKK')}<ArrowUpRight size={13} aria-hidden="true" /></a></details>
      </>}
    </section>
  );
}
