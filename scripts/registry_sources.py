"""Source identities and historical column labels for Sofia register exports."""

SOURCES = {
    "building_permits": {
        "label_bg": "Регистър на разрешенията за строеж",
        "label_en": "Building permits register",
        "source_url": "https://nag.sofia.bg/RegisterBuildingPermitsPortal/Index",
        "form_id": "RegisterBuildingPermitsPortalSearchForms",
        "required_headers": ["№", "Издател", "Район", "Обхват"],
        "columns": ["Разрешение за строеж", "Поле 2", "Поле 3", "Влязло в сила на", "Издател", "Възложител", "Обект", "Район", "Местоположение"],
    },
    "exploitation_certificates": {
        "label_bg": "Регистър на удостоверенията за въвеждане в експлоатация",
        "label_en": "Certificates for putting buildings into use",
        "source_url": "https://nag.sofia.bg/RegisterCertificateForExploitationBuildings",
        "form_id": "RegisterCertificateForExploitationBuildingsSearchForms",
        "required_headers": ["№", "Издател", "Надзор", "Район", "Обхват"],
        "columns": ["Удостоверение", "Поле 2", "Издател", "Строителен надзор", "Обект", "Район", "Местоположение"],
    },
    "projecting_visas": {
        "label_bg": "Регистър на визите за проектиране",
        "label_en": "Design visas register",
        "source_url": "https://nag.sofia.bg/RegisterVisasOfProection",
        "form_id": "RegisterVisasOfProectionSearchForms",
        "required_headers": ["Номер", "Дата", "Издател", "Район", "Обхват"],
        "columns": ["Дата", "Виза", "Основание", "Издател", "Район", "Местоположение"],
    },
    "exploitation_certificates_legacy": {
        "label_bg": "Архивен регистър на удостоверенията за въвеждане в експлоатация",
        "label_en": "Archived certificates for putting buildings into use",
        "source_url": "http://up.gis-sofia.bg/",
        "columns": ["Удостоверение", "Издател", "Възложител", "Обект", "Район", "Местност", "Квартал", "УПИ", "Пл. №", "Адрес"],
    },
}
CORE_CODES = ("building_permits", "exploitation_certificates", "projecting_visas")


def labelled_fields(source_code: str, fields: dict) -> dict:
    """Give index-only historical exports labels without changing cell values."""
    labels = SOURCES[source_code]["columns"]
    result = {}
    for label, value in fields.items():
        if label.startswith("Column ") and label[7:].isdigit():
            index = int(label[7:]) - 1
            label = labels[index] if index < len(labels) else f"Поле {index + 1}"
        result[label] = value
    return result
