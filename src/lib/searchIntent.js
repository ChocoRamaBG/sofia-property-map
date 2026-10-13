const CADASTRAL_ID = /(?:^|[^\d])\d{5}\.\d+\.\d+(?:\.\d+){0,2}(?=$|[^\d])/u;
const LEGAL_FORM = /(?:^|[^\p{L}\p{N}])(?:еоод|оод|еад|ад|ет|eood|ood|ead|ad|et|ltd|llc|inc)(?=$|[^\p{L}\p{N}])/u;
const DOCUMENT_TERM = /(?:^|[^\p{L}\p{N}])(?:акт(?:\s*\d+)?|act(?:\s*\d+)?|акт\s*№\s*\d+|разрешени[ея]|разрешително|удостоверени[ея]|сертификат(?:и)?|документ(?:и)?|заповед(?:и)?|протокол(?:и)?|виза|визи|нотариален|рс|рнс|уве|днск|permit(?:s)?|certificate(?:s)?|document(?:s)?|protocol(?:s)?|order)(?=$|[^\p{L}])/u;
const ROAD_PREFIX = /^(?:улица|булевард|площад|street|str|blvd|boulevard|avenue|ave|road|rd|ulitsa|ulica|ul|bulevard|bul|ploshtad|pl|ул|бул|пл)[.\s]+(?=.*[\p{L}\p{N}])/u;
const DISTRICT_PREFIX = /^(?:ж\s*\.\s*к\s*\.?|жк|жилищен\s+комплекс|квартал|кв\.?|блок|бл\.?|zh\s*\.?\s*k\s*\.?|zhk|kvartal|kv|block)(?:[.\s]+|(?=\d))(?=.*[\p{L}\p{N}])/u;
const BLOCK_NUMBER = /(?:^|[^\p{L}\p{N}])(?:блок|бл\.?|block|bl\.?)[.\s]*\d{1,4}(?:\s*[a-zа-я])?(?=$|[^\p{L}\p{N}])/u;
const ROAD_SUFFIX = /[\s,](?:street|str\.?|blvd\.?|boulevard|avenue|ave\.?|road|rd\.?)$/u;
const DATE = /(?:^|[^\d])\d{1,2}[./-]\d{1,2}[./-]\d{2,4}(?=$|[^\d])/u;
const YEAR_DOCUMENT_NUMBER = /\d+\s*\/\s*\d{4}(?=$|[^\d])/u;
const HOUSE_AT_END = /[,\s]*(\d{1,4}(?:\s*[a-zа-я])?(?:\s*[-/]\s*\d{1,4}(?:\s*[a-zа-я])?)?)$/u;

/**
 * Routes recognizable address submissions to map navigation, without treating
 * every text search as an address. Bare street names remain ambiguous: the UI
 * must also offer an explicit address-search choice.
 */
export function isAddressQuery(value) {
  if (typeof value !== 'string') return false;
  const query = value.normalize('NFKC').toLocaleLowerCase('bg')
    .replace(/[\u2018\u2019\u201c\u201d\u201e\u00ab\u00bb"]/gu, ' ')
    .replace(/\s+/gu, ' ').trim();
  if (!query || CADASTRAL_ID.test(query) || LEGAL_FORM.test(query) || DOCUMENT_TERM.test(query)) return false;

  // City qualifiers aid the provider, but do not themselves identify an address.
  const local = query
    .replace(/^(?:гр\.?\s*)?(?:софия|sofia)\s*[,;]\s*/u, '')
    .replace(/[,;\s]+(?:гр\.?\s*)?(?:софия|sofia)\s*$/u, '')
    .trim();
  if (!local) return false;

  // An explicit road type also permits numbered/date-based street names.
  if (ROAD_PREFIX.test(local) || DISTRICT_PREFIX.test(local)) return true;
  if (DATE.test(local) || YEAR_DOCUMENT_NUMBER.test(local)) return false;
  if (BLOCK_NUMBER.test(local)) return true;
  if (ROAD_SUFFIX.test(local) && /\p{L}{2}/u.test(local.replace(ROAD_SUFFIX, ''))) return true;

  const house = HOUSE_AT_END.exec(local);
  if (!house) return false;
  // A bare name plus a year is commonly a company or document phrase.
  if (/^(?:19|20)\d{2}$/u.test(house[1])) return false;
  const name = local.slice(0, house.index).replace(/[,\s]+$/u, '');
  // Compact forms such as "Алабин20" work; a number alone cannot be an address.
  return /\p{L}{2}/u.test(name) && !/\d/u.test(name) && !/[#№]/u.test(name);
}
