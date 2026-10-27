import React, { useEffect, useId, useMemo, useRef, useState } from 'react';
import { ArrowDown, ArrowUpRight, Building2, Check, Copy } from 'lucide-react';
import { displayDate } from '@/lib/registerUi';

const REGISTER_HOME = 'https://portal.registryagency.bg/home-cr';
const REGISTER_COMPANY = 'https://portal.registryagency.bg/CR/Reports/ActiveConditionTabResult';
const SOURCES = new Set(['building_permits', 'projecting_visas', 'exploitation_certificates', 'exploitation_certificates_legacy']);
const ROLE_FIELDS = new Map([['възложител', 'applicant'], ['contracting authority', 'applicant'], ['инвеститор', 'investor'], ['investor', 'investor']]);
const LEGAL_FORM = '(?:ЕООД|ООД|ЕАД|АД|КД|СД)';
const QUOTED_COMPANY = new RegExp('(?:^|[\\s,;:(])(["„“«]([^"„“”«»]{2,160})["“”»]\\s*(' + LEGAL_FORM + '))(?=$|[\\s,;.)])', 'giu');
const BARE_COMPANY = new RegExp('^[\\p{L}\\p{N} .„“”"\\-–&()]{2,160}\\s' + LEGAL_FORM + '$', 'iu');
const PUBLIC_ORGANIZATION = /^(?:Столична община|Община\s|СО\s*[-–]|Министерство\s|Агенция\s)[\p{L}\p{N} .„“”"\-–()]{0,160}$/iu;
const PRIVATE_OR_CONTACT = /(?:\[\s*скрит|ЕГН|ЛНЧ|(?:^|[^\p{L}])ЕТ(?:$|[^\p{L}])|ДЗЗД|@|https?:\/\/|\+359|(?:^|\s)тел(?:ефон)?\s*[.:]|(?<!\d)\d{10}(?!\d))/iu;
const AMBIGUOUS_NAME = /(?:\sи\s|заедно\s+с|чрез\s|представляван|съсобствен|физическ)/iu;
const LABELLED_UIC = /(?:ЕИК|EIK|UIC)[\s:№-]*(\d{9})(?!\d)/giu;
const PREVIEW_GROUPS = 3;

function normalized(value) { return String(value).normalize('NFC').replace(/["„“”«»]/g, '').replace(/\s+/g, ' ').trim().toLocaleLowerCase('bg-BG'); }
function displayName(value) { return value.replace(/\s+/g, ' ').trim(); }
function sourceUrl(value) {
  try {
    const url = new URL(value);
    if (url.username || url.password || url.port || !['nag.sofia.bg', 'sofia.bg', 'www.sofia.bg', 'up.gis-sofia.bg'].includes(url.hostname)) return null;
    return url.protocol === 'https:' || (url.protocol === 'http:' && url.hostname === 'up.gis-sofia.bg') ? url.href : null;
  } catch { return null; }
}
function validUic(value) {
  if (!/^\d{9}$/.test(value) || value === '000000000') return false;
  const digits = [...value].map(Number);
  let check = digits.slice(0, 8).reduce((sum, digit, index) => sum + digit * (index + 1), 0) % 11;
  if (check === 10) {
    check = digits.slice(0, 8).reduce((sum, digit, index) => sum + digit * (index + 3), 0) % 11;
    if (check === 10) check = 0;
  }
  return check === digits[8];
}

function fieldCompanies(text) {
  const found = new Map();
  const add = (name, kind) => {
    name = displayName(name);
    if (PRIVATE_OR_CONTACT.test(name)) return;
    const key = normalized(name);
    if (key) found.set(key, { name, normalizedName: key, kind });
  };
  // Quoted legal-company names can be isolated without retaining neighboring
  // personal applicants or contact details in a mixed source field.
  for (const match of text.matchAll(QUOTED_COMPANY)) add(match[1], 'company');
  for (const raw of text.split(/[,;\n]+/u)) {
    const segment = displayName(raw);
    if (PRIVATE_OR_CONTACT.test(segment) || AMBIGUOUS_NAME.test(segment)) continue;
    if (BARE_COMPANY.test(segment)) add(segment, 'company');
    else if (PUBLIC_ORGANIZATION.test(segment)) add(segment, 'public_organization');
  }
  const entities = [...found.values()];
  const uicTokens = [...text.matchAll(LABELLED_UIC)];
  const codes = uicTokens.map((match) => match[1]);
  const forms = [...text.matchAll(new RegExp('(?:^|[^\\p{L}\\p{N}])' + LEGAL_FORM + '(?=$|[^\\p{L}\\p{N}])', 'giu'))];
  const company = entities.length === 1 && entities[0].kind === 'company' ? entities[0] : null;
  // Unmatched words can be a private applicant, address or another entity.
  // Only a field wholly accounted for by the company and explicit EIK may
  // produce a company-specific registry link.
  const remainder = company && uicTokens.length === 1 ? displayName(text).replace(company.name, '').replace(displayName(uicTokens[0][0]), '') : null;
  const fullyAccounted = remainder !== null && /^[\p{P}\p{Z}\s]*$/u.test(remainder);
  if (company && fullyAccounted && forms.length === 1 && codes.length === 1 && validUic(codes[0]) && !PRIVATE_OR_CONTACT.test(text)) company.uic = codes[0];
  return entities;
}

export function collectDocumentCompanies(sources = []) {
  const groups = new Map();
  for (const source of Array.isArray(sources) ? sources : []) {
    if (!SOURCES.has(source?.code)) continue;
    for (const document of Array.isArray(source.documents) ? source.documents : []) {
      for (const [field, value] of Object.entries(document?.raw_fields || {})) {
        const role = ROLE_FIELDS.get(field.replace(/\s+/g, ' ').trim().toLocaleLowerCase('bg-BG'));
        if (!role || typeof value !== 'string') continue;
        for (const entity of fieldCompanies(value)) {
          const key = `${entity.normalizedName}:${role}`;
          if (!groups.has(key)) groups.set(key, { key, name: entity.name, normalizedName: entity.normalizedName, kind: entity.kind, role, evidence: [], evidenceKeys: new Set(), codes: new Set() });
          const group = groups.get(key);
          const evidence = {
            sourceCode: source.code, sourceLabelBg: source.label_bg, sourceLabelEn: source.label_en,
            sourceUrl: sourceUrl(source.source_url), documentId: document.id || null,
            recordKey: document.record_key || null, issuedAt: document.issued_at || null,
            snapshotDate: Object.prototype.hasOwnProperty.call(document, 'snapshot_date') ? document.snapshot_date || null : source.snapshot_date || null,
            statedRole: field, statedName: entity.name, uic: entity.uic || null,
          };
          const evidenceKey = JSON.stringify([evidence.sourceCode, evidence.documentId, evidence.recordKey, evidence.issuedAt, evidence.snapshotDate, field, entity.name]);
          if (!group.evidenceKeys.has(evidenceKey)) { group.evidenceKeys.add(evidenceKey); group.evidence.push(evidence); }
          if (entity.uic) group.codes.add(entity.uic);
        }
      }
    }
  }
  return [...groups.values()].map(({ evidenceKeys, codes, ...group }) => ({
    ...group, uic: codes.size === 1 ? [...codes][0] : null, conflictingCodes: codes.size > 1,
    evidence: group.evidence.sort((a, b) => String(b.issuedAt || '').localeCompare(String(a.issuedAt || '')) || String(b.snapshotDate || '').localeCompare(String(a.snapshotDate || ''))),
  })).sort((a, b) => a.normalizedName.localeCompare(b.normalizedName, 'bg-BG') || a.role.localeCompare(b.role));
}

function CompanyEvidence({ group, lang, onOpenSource, onCopy, copied }) {
  const bg = lang === 'bg';
  const companyUrl = group.kind === 'company' && group.uic ? `${REGISTER_COMPANY}?uic=${encodeURIComponent(group.uic)}` : REGISTER_HOME;
  return <article className="mt-3 rounded-md border border-slate-200 bg-white p-3">
    <div className="flex items-start gap-2"><div className="min-w-0 flex-1"><h4 className="break-words text-sm font-semibold text-emerald-900">{group.name}</h4><p className="mt-1 text-xs text-slate-600">{group.role === 'investor' ? (bg ? 'Инвеститор, посочен в документ' : 'Investor stated in a document') : (bg ? 'Възложител, посочен в документ' : 'Contracting authority stated in a document')}</p>{group.uic && <p className="mt-1 text-xs text-slate-600">{bg ? 'Публикуван ЕИК:' : 'Published UIC:'} <span className="font-mono">{group.uic}</span></p>}</div><button type="button" className="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-md border border-slate-200 text-emerald-800 hover:bg-emerald-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-700" onClick={() => onCopy(group)} aria-label={`${bg ? 'Копирай посоченото име:' : 'Copy the stated name:'} ${group.name}`} title={bg ? 'Копирай името' : 'Copy name'}>{copied === group.key ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}</button></div>
    {group.conflictingCodes && <p className="mt-2 text-xs leading-relaxed text-slate-600">{bg ? 'В документите има различни ЕИК за това име. Проверете всеки източник отделно.' : 'The documents state different UICs for this name. Check each source separately.'}</p>}
    {group.kind === 'company' && <a className="mt-2 inline-flex min-h-11 items-center gap-1 text-xs font-semibold text-emerald-800 underline underline-offset-2" href={companyUrl} target="_blank" rel="noreferrer">{group.kind === 'company' && group.uic ? (bg ? 'Провери дружеството по ЕИК' : 'Check the company by UIC') : (bg ? 'Отвори Търговския регистър за проверка' : 'Open the Commercial Register to check')}<ArrowUpRight size={13} aria-hidden="true" /></a>}
    {!group.uic && <p className="text-xs leading-relaxed text-slate-600">{group.kind === 'public_organization' ? (bg ? 'Посочена публична организация; не я представяме като търговско дружество.' : 'A stated public organization; it is not presented as an incorporated company.') : (bg ? 'Няма еднозначно посочен ЕИК. Проверете името и идентификатора преди да свързвате дружество.' : 'No unambiguous UIC is stated. Check the name and identifier before identifying a company.')}</p>}
    <details className="evidence-details"><summary>{bg ? `Източникови записи (${group.evidence.length})` : `Source observations (${group.evidence.length})`}</summary>
      {group.evidence.map((entry, index) => <div className="mt-3 border-t border-slate-200 pt-3 text-xs leading-relaxed text-slate-600" key={`${entry.sourceCode}:${entry.documentId || index}:${entry.statedRole}:${index}`}>
        <p className="font-semibold text-slate-700">{(bg ? entry.sourceLabelBg : entry.sourceLabelEn) || entry.sourceLabelBg || entry.sourceCode}</p>
        <dl className="mt-2 grid gap-1"><div><dt className="inline">{bg ? 'Поле:' : 'Field:'} </dt><dd className="inline">{entry.statedRole}</dd></div><div><dt className="inline">{bg ? 'Документ:' : 'Document:'} </dt><dd className="inline break-words">{entry.recordKey || (bg ? 'номерът не е посочен' : 'number not stated')}</dd></div><div><dt className="inline">{bg ? 'Издаден:' : 'Issued:'} </dt><dd className="inline">{entry.issuedAt ? displayDate(entry.issuedAt, lang) : (bg ? 'датата не е установена' : 'date unknown')}</dd></div><div><dt className="inline">{bg ? 'Извлечение:' : 'Snapshot:'} </dt><dd className="inline">{entry.snapshotDate ? displayDate(entry.snapshotDate, lang) : (bg ? 'датата не е установена' : 'date unknown')}</dd></div>{entry.uic && <div><dt className="inline">{bg ? 'ЕИК в този запис:' : 'UIC in this observation:'} </dt><dd className="inline font-mono">{entry.uic}</dd></div>}</dl>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">{entry.sourceUrl && <a className="inline-flex min-h-11 items-center gap-1 text-emerald-800 underline underline-offset-2" href={entry.sourceUrl} target="_blank" rel="noreferrer">{bg ? 'Официален източник' : 'Official source'}<ArrowUpRight size={12} aria-hidden="true" /></a>}{onOpenSource && <button type="button" className="inline-flex min-h-11 items-center gap-1 text-emerald-800 underline underline-offset-2" onClick={() => onOpenSource(entry.sourceCode)}>{bg ? 'Към документа в досието' : 'Open the document group'}<ArrowDown size={12} aria-hidden="true" /></button>}</div>
      </div>)}
    </details>
  </article>;
}

export default function CompaniesInDocuments({ sources = [], lang = 'bg', onOpenSource }) {
  const bg = lang === 'bg';
  const id = useId();
  const groups = useMemo(() => collectDocumentCompanies(sources), [sources]);
  const [copied, setCopied] = useState(null);
  const [copyFailed, setCopyFailed] = useState(false);
  const timer = useRef(null);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  if (!groups.length) return null;
  async function copyName(group) {
    try {
      await navigator.clipboard.writeText(group.name);
      setCopied(group.key); setCopyFailed(false); window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(null), 1800);
    } catch { setCopyFailed(true); }
  }
  return <section className="cadastre-summary" aria-labelledby={id + '-title'}>
    <div className="cadastre-summary-heading"><Building2 size={18} aria-hidden="true" /><div><h3 id={id + '-title'}>{bg ? 'Компании в строителните документи' : 'Companies named in construction documents'}</h3><p>{bg ? 'Публикувани възложители и инвеститори' : 'Published contracting authorities and investors'}</p></div></div>
    <p className="cadastre-note">{bg ? 'Посочената роля е от съответния документ и дата. Тя не потвърждава кой притежава имота сега.' : 'Each stated role comes from its document and date. It does not confirm who currently owns the property.'}</p>
    <p className="mt-2 text-xs text-slate-600">{bg ? `Групи по име и роля: ${groups.length}.` : `Groups by stated name and role: ${groups.length}.`}</p>
    {groups.slice(0, PREVIEW_GROUPS).map((group) => <CompanyEvidence key={group.key} group={group} lang={lang} onOpenSource={onOpenSource} onCopy={copyName} copied={copied} />)}
    {groups.length > PREVIEW_GROUPS && <details className="evidence-details"><summary>{bg ? `Още ${groups.length - PREVIEW_GROUPS} групи по име и роля` : `${groups.length - PREVIEW_GROUPS} more groups by name and role`}</summary>{groups.slice(PREVIEW_GROUPS).map((group) => <CompanyEvidence key={group.key} group={group} lang={lang} onOpenSource={onOpenSource} onCopy={copyName} copied={copied} />)}</details>}
    <p className="sr-only" role="status">{copied ? (bg ? 'Името е копирано.' : 'Name copied.') : ''}</p>
    {copyFailed && <p className="mt-2 text-xs text-slate-600" role="status">{bg ? 'Можете да маркирате името и да го копирате ръчно.' : 'You can select the name and copy it manually.'}</p>}
  </section>;
}
