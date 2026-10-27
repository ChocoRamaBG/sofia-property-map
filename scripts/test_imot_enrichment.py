"""Evidence and privacy regression fixtures for public advert enrichment."""
from copy import deepcopy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from imot_enrichment import (
    ANALYSIS_METHOD_VERSION, CACHE_VERSION, _valid_cache, agency_details,
    analyze_text, card_fingerprint, detail_property_facts, enrich_capture, merge_agency, merge_features,
    professional_url, property_features, public_website, seller_claim,
)
from imot_scraper import cards, structural_row

CHECKED = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
IDENTIFIER = "1b123456789012"


def soup(value):
    return BeautifulSoup(value, "html.parser")


class FeatureTests(unittest.TestCase):
    def test_advertised_brick_furnished_year_floor_and_lift(self):
        features = property_features("Тухла, напълно обзаведен, построен 2008 г., 3-ти ет. от 7, с асансьор", checked_at=CHECKED)
        self.assertEqual({key: features[key] for key in ["construction_type", "furnishing", "building_year", "year_basis", "floor_number", "total_floors", "elevator"]},
                         {"construction_type": "brick", "furnishing": "furnished", "building_year": 2008, "year_basis": "built", "floor_number": 3, "total_floors": 7, "elevator": "yes"})

    def test_panel_partial_without_lift(self):
        features = property_features("Панел, частично обзаведен, ет. 5 от 8, без асансьор")
        self.assertEqual(features["construction_type"], "panel")
        self.assertEqual(features["furnishing"], "partial")
        self.assertEqual(features["elevator"], "no")
        self.assertEqual((features["floor_number"], features["total_floors"]), (5, 8))

    def test_negated_and_conflicting_facts_remain_unknown(self):
        features = property_features("Не е панел, тухла. Обзаведен, продава се без обзавеждане. Има асансьор, без асансьор.")
        self.assertEqual(features["construction_type"], "brick")
        self.assertEqual(features["furnishing"], "unknown")
        self.assertEqual(features["elevator"], "unknown")
        self.assertEqual(property_features("Тухла или панел")["construction_type"], "unknown")

    def test_explicit_unfurnished_and_ground_basement(self):
        for text in ["Необзаведен", "Не е обзаведен", "Без мебели", "Без обзавеждане"]:
            self.assertEqual(property_features(text)["furnishing"], "unfurnished", text)
        self.assertEqual(property_features("Партер")["floor_number"], 0)
        self.assertEqual(property_features("Сутерен")["floor_number"], -1)

    def test_planned_year_not_presented_as_existing_building_age(self):
        features = property_features("Ще бъде въведен в експлоатация 2028 г.")
        self.assertEqual((features["building_year"], features["year_basis"]), (2028, "planned"))
        self.assertEqual(property_features("Въведен в експлоатация 2008 - 2010 г.")["building_year"], None)
        self.assertEqual(property_features("Построен 2000 г. Построен 2001 г.")["building_year"], None)

    def test_known_card_facts_survive_sparse_description_but_conflicts_do_not(self):
        card = property_features("Тухла, обзаведен, с асансьор, 3-ти ет. от 7")
        merged = merge_features(card, property_features("След ремонт", source="description"))
        self.assertEqual((merged["construction_type"], merged["furnishing"], merged["floor_number"]), ("brick", "furnished", 3))
        merged = merge_features(card, property_features("Панел, необзаведен", source="description"))
        self.assertEqual((merged["construction_type"], merged["furnishing"]), ("unknown", "unknown"))

    def test_bad_floor_or_unknown_text_never_fabricates_facts(self):
        self.assertIsNone(property_features("20-ти ет. от 8")["floor_number"])
        unknown = property_features("Прекрасен слънчев апартамент близо до училище")
        self.assertEqual(unknown["construction_type"], "unknown")
        self.assertEqual(unknown["furnishing"], "unknown")
        self.assertIsNone(unknown["building_year"])

    def test_modern_property_fields_supply_structure_and_labelled_year(self):
        document = soup('<div class="adParams">Строителство: ЕПК, 1988 г. Етаж: 4 от 12</div><div class="carExtri"><div class="items"><span>Асансьор</span><span>Обзаведен</span></div></div><div class="contactsBox">Панел</div>')
        features = property_features(detail_property_facts(document), source="description")
        self.assertEqual((features["construction_type"], features["building_year"], features["year_basis"]), ("epk", 1988, "built"))
        self.assertEqual((features["furnishing"], features["elevator"]), ("furnished", "yes"))


class AgencyTests(unittest.TestCase):
    def test_only_professional_scoped_contacts(self):
        document = soup('''<div class="seller"><div class="sInfo"><div class="name"><a href="https://exampleagency.imot.bg/">Примерна агенция</a></div></div><div class="phone">0888 123 456</div><a class="website" href="https://agency.bg/">Сайт</a></div><div class="description"><a href="tel:0899999999">Друг телефон</a></div>''')
        agency = agency_details(document, checked_at=CHECKED)
        self.assertEqual(agency["name"], "Примерна агенция")
        self.assertEqual(agency["phone"], "0888123456")
        self.assertEqual(agency["website"], "https://agency.bg/")
        self.assertNotIn("0899999999", str(agency))

    def test_private_and_main_site_profile_rejected(self):
        for url in ["https://www.imot.bg/", "https://imot.bg/", "http://agency.imot.bg/", "https://agency.imot.bg.evil.test/", "https://user:secret@agency.imot.bg/", "https://agency.imot.bg:444/", "https://agency.imot.bg:443/", "https://nested.agency.imot.bg/"]:
            document = soup(f'<div class="seller"><div class="sInfo"><div class="name"><a href="{url}">Собственик</a></div></div><a href="tel:0888123456">Телефон</a></div>')
            self.assertIsNone(agency_details(document), url)

    def test_public_urls_have_safe_lowercase_dns_hosts(self):
        self.assertEqual(professional_url("https://AGENCY.imot.bg/"), "https://agency.imot.bg/")
        self.assertEqual(public_website("https://WWW.AGENCY.BG/"), "https://www.agency.bg/")
        for url in ["https://agency.bg:443/", "https://127.0.0.1/", "https://localhost/", "https://bad..agency.bg/", "https://-bad.bg/", "https://agency.bg/has space", "https://agency.bg/line\nbreak"]:
            self.assertIsNone(public_website(url), url)
        self.assertIsNone(professional_url("https://agency.imot.bg/line\nbreak"))

    def test_detail_block_does_not_read_generic_footer_or_maps_url(self):
        document = soup('''<div class="AG"><a class="name" href="https://agency.imot.bg/">Агенция</a><a href="https://maps.google.com/">Адрес</a><a href="tel:+359 2 1234567">Контакт</a></div><footer><a href="tel:0899999999">Телефон</a></footer>''')
        agency = agency_details(document, detail=True)
        self.assertEqual(agency["phone"], "+35921234567")
        self.assertIsNone(agency["website"])

    def test_duplicate_identity_and_sparse_detail_preserve_card_contact(self):
        card = agency_details(soup('<div class="AG"><a class="name" href="https://agency.imot.bg/">Агенция</a><a href="tel:0888123456">Телефон</a></div>'), detail=True)
        detail = dict(card, phone=None)
        self.assertEqual(merge_agency(card, detail)["phone"], "0888123456")
        self.assertIsNone(merge_agency(card, dict(detail, profile_url="https://other.imot.bg/")))

    def test_current_modern_dealer_requires_same_observed_professional_identity(self):
        known = {"name": "Професионална агенция", "profile_url": "https://agency.imot.bg/"}
        document = soup('<div class="dealer2023 borderBox broker MB20"><div class="infoBox"><div><div class="more"><a href="https://agency.imot.bg/">Всички обяви</a><a href="https://agency.imot.bg/?act=contacts">Контакти</a></div></div></div><div class="phone">02 1234567</div></div><div class="contactsBox"><div class="phone">0899999999</div></div>')
        agency = agency_details(document, detail=True, known_agency=known)
        self.assertEqual(agency["name"], known["name"])
        self.assertEqual(agency["phone"], "021234567")
        self.assertIsNone(agency_details(document, detail=True))
        self.assertIsNone(agency_details(document, detail=True, known_agency=dict(known, profile_url="https://different.imot.bg/")))


class CaptureTests(unittest.TestCase):
    def test_list_card_keeps_allowlisted_claims_not_description_or_private_contacts(self):
        document = soup(f'''<div class="item" id="ida{IDENTIFIER}"><a class="title" href="https://www.imot.bg/obiava-{IDENTIFIER}-prodava">Продава 2-СТАЕН<location>град София, Банишора</location></a><div class="price"><div>200 000 EUR</div>Не се начислява ДДС</div><div class="text"><div class="info">80 кв.м, 3-ти ет. от 7, Тухла, обзаведен, Въведен в експлоатация 2008 г., с асансьор. Телефон: 0899999999</div></div><div class="seller"><div class="sInfo"><div class="name"><a href="https://agency.imot.bg/">Агенция</a></div></div><a href="tel:0888123456">Контакт</a></div></div>''')
        row = cards(document, {"label_bg": "Банишора"}, {"label_bg": "2-СТАЕН"}, 0, None)[0]
        self.assertEqual(row["agency"]["phone"], "0888123456")
        self.assertEqual(row["property_features"]["construction_type"], "brick")
        self.assertEqual(row["property_features"]["building_year"], 2008)
        self.assertNotIn("0899999999", str(row))
        self.assertEqual(row["analysis_method_version"], 3)
        later = deepcopy(row)
        for field in ["agency", "property_features", "analysis"]:
            later[field]["checked_at"] = "2026-10-28T00:00:00Z"
        self.assertEqual(structural_row(row), structural_row(later))

    def test_old_capture_unknowns_and_explicit_retained_facts_without_requests(self):
        row = {"id": IDENTIFIER, "construction_label_bg": "Въведен в експлоатация 2008 г.", "floor_bg": "3-ти ет. от 7", "seller_type": "unknown", "analysis_method_version": 2, "analysis": {"area_basis": "net"}, "observed_at": CHECKED}
        result, cache, report = enrich_capture({"version": 1, "capture": {"complete": True}, "listings": [row]}, limit=0)
        features = result["listings"][0]["property_features"]
        self.assertEqual((features["building_year"], features["floor_number"]), (2008, 3))
        self.assertEqual(features["furnishing"], "unknown")
        self.assertIsNone(result["listings"][0]["agency"])
        self.assertEqual(result["listings"][0]["analysis"]["area_basis"], "net")
        self.assertEqual(report["attempted"], 0)

    def test_detail_merge_cache_reuse_and_closed_claims(self):
        row = {"id": IDENTIFIER, "url": f"https://www.imot.bg/obiava-{IDENTIFIER}-prodava", "construction_label_bg": None, "floor_bg": "3-ти ет. от 7", "observed_at": CHECKED,
               **seller_claim(True, "", CHECKED), **analyze_text("Тухла", checked_at=CHECKED),
               "agency": {"name": "Агенция", "profile_url": "https://agency.imot.bg/", "phone": None, "website": None, "checked_at": CHECKED, "evidence": "professional_profile"},
               "property_features": property_features("Тухла", checked_at=CHECKED)}
        row["enrichment_card_sha256"] = card_fingerprint(row, "Тухла", True)
        capture = {"version": 1, "capture": {"complete": True}, "listings": [row]}
        class FixtureReader:
            requests = 0
            def __init__(self, config):
                self.config = config
            def check_robots(self):
                pass
            def get(self, url):
                self.requests += 1
                return soup('<div class="moreInfo"><span class="blockTitle"><h2>Описание на имота</h2></span><div class="text">Обзаведен, без асансьор. Телефон: 0899999999</div></div><div class="adParams">Строителство: Тухла, 2008 г.</div><div class="dealer2023 broker"><div class="infoBox"><div class="more"><a href="https://agency.imot.bg/">Обяви</a></div></div><div class="phone">0888123456</div></div>'), url
        with patch('imot_scraper.Reader', FixtureReader):
            enriched, cache, report = enrich_capture(capture, limit=1)
        result = enriched["listings"][0]
        self.assertEqual((result["property_features"]["furnishing"], result["property_features"]["building_year"]), ("furnished", 2008))
        self.assertEqual(result["agency"]["phone"], "0888123456")
        self.assertNotIn("0899999999", str(cache))
        self.assertNotIn("Обзаведен, без", str(cache))
        self.assertTrue(_valid_cache(cache[IDENTIFIER], row["enrichment_card_sha256"], datetime.now(timezone.utc)))
        reused, _, report = enrich_capture(capture, {"enrichment_cache": cache}, limit=0)
        self.assertEqual(report["reused"], 1)
        self.assertEqual(reused["listings"][0]["agency"]["phone"], "0888123456")
        bad = deepcopy(cache[IDENTIFIER]); bad["property_features"]["raw_description"] = "forbidden"
        self.assertFalse(_valid_cache(bad, row["enrichment_card_sha256"], datetime.now(timezone.utc)))

    def test_optional_daily_bounds(self):
        capture = {"version": 1, "capture": {"complete": True}, "listings": [{"id": IDENTIFIER}]}
        for settings in [{"limit": 1201}, {"maximum_seconds": 3601}, {"maximum_seconds": 0}]:
            with self.assertRaises(ValueError):
                enrich_capture(capture, **settings)
        _, _, report = enrich_capture(capture, limit=1200, maximum_seconds=2700)
        self.assertEqual(report["limit"], 1200)


if __name__ == "__main__":
    unittest.main()
