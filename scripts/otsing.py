import os  # Loeb .env failist API tokenit
import sys  # Loeb käsurealt kaasa antud märksõnu
from urllib.parse import urlparse  # Võtab EPD uri-st konkreetse node'i aadressi
from datetime import datetime, timezone  # Teisendab millisekundites timestampi kuupäevaks

import requests  # Teeb API päringuid
import pandas as pd  # Teeb tulemused tabeliks
from dotenv import load_dotenv  # Laeb .env faili muutujad


load_dotenv()  # Loeb .env faili sisse


TOKEN = os.getenv("TOKEN")  # Võtab .env failist TOKEN väärtuse


if not TOKEN:  # Kontrollib, kas token on olemas
    raise ValueError("TOKEN puudub .env failist")  # Annab vea, kui token puudub


if len(sys.argv) < 2:  # Kontrollib, kas kasutaja andis vähemalt ühe märksõna
    raise ValueError("Kasuta näiteks: python fetch_epd_selected_fields.py steel rebar scrap")  # Annab kasutusjuhise


keywords = sys.argv[1:]  # Võtab kõik käsurealt antud sõnad otsisõnadeks


headers = {"Authorization": f"Bearer {TOKEN}"}  # Loob API autentimise headeri


SEARCH_URL = "https://portal.eco-platform.org/resource/processes"  # ECO Platformi otsingu endpoint


OUTPUT_FILE = "epd_selected_fields.csv"  # Lõpptabeli CSV faili nimi


LCA_UUIDS = {
    "GWPtotal_A1A3": [
        # EN15804+A2 EF 3.1
        "a7ea142a-9749-11ed-a8fc-0242ac120002",
        # EN15804+A2 EF 3.0
        "6a37f984-a4b3-458a-a20a-64418c145fa2",
    ],
    "GWPbiogenic_A1A3": [
        "a7ea186c-9749-11ed-a8fc-0242ac120002",
        "2356e1ab-0185-4db5-86e5-16de51c7485c",
    ],
    "GWPfossil_A1A3": [
        "a7ea19c0-9749-11ed-a8fc-0242ac120002",
        "5f635281-343e-44fb-83df-1971b155e6b6",
    ],
    "GWPluluc_A1A3": [
        "a7ea1ae2-9749-11ed-a8fc-0242ac120002",
        "4331bbdb-978a-490d-8707-eeb047f01a55",
    ],
    "HTPnc_A1A3": [
        "3af763a5-b7a1-48c9-9cee-1f223481fcef",
        "93a60a56-a3c8-17da-a746-0800200c9a66"
    ],
}


def get_nested(data, path, default=None):  # Abifunktsioon nested dict väärtuse võtmiseks
    current = data  # Alustab algsest objektist
    for key in path:  # Käib võtmete tee läbi
        if not isinstance(current, dict):  # Kui praegune tase pole dict
            return default  # Tagastab vaikeväärtuse
        current = current.get(key)  # Võtab järgmise taseme väärtuse
        if current is None:  # Kui väärtus puudub
            return default  # Tagastab vaikeväärtuse
    return current  # Tagastab leitud väärtuse


def first_short_description(ref):  # Võtab reference objekti esimese shortDescription väärtuse
    descriptions = ref.get("shortDescription", []) if isinstance(ref, dict) else []  # Võtab shortDescription listi
    if not descriptions:  # Kui list on tühi
        return None  # Tagastab None
    return descriptions[0].get("value")  # Tagastab esimese kirjelduse väärtuse


def localized_name(name_obj, lang):  # Võtab EPD nime etteantud keeles
    base_names = name_obj.get("baseName", []) if isinstance(name_obj, dict) else []  # Võtab baseName listi
    for item in base_names:  # Käib kõik nimed läbi
        if item.get("lang") == lang:  # Kontrollib, kas keelekood sobib
            return item.get("value", "").strip()  # Tagastab nime ilma liigsete tühikuteta
    return None  # Kui sellises keeles nime pole, tagastab None


def timestamp_ms_to_date(value):  # Teisendab millisekundites timestampi ISO kuupäevaks
    if not isinstance(value, (int, float)):  # Kontrollib, kas väärtus on number
        return None  # Kui ei ole number, tagastab None
    if value < 0:  # Negatiivne timestamp tähendab siin sisuliselt puuduvat väärtust
        return None  # Tagastab None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date().isoformat()  # Tagastab kuupäeva kujul YYYY-MM-DD


def get_publication_date(data):  # Otsib publicationDateOfEPD väärtust
    anies = get_nested(data, ["processInformation", "time", "other", "anies"], [])  # Võtab time.other.anies listi
    for item in anies:  # Käib listi kirjed läbi
        if item.get("name") == "publicationDateOfEPD":  # Otsib õige nimega kirjet
            return timestamp_ms_to_date(item.get("value"))  # Teisendab timestampi kuupäevaks
    return None  # Kui publicationDateOfEPD puudub, tagastab None


def get_compliance(data):
    compliances = get_nested(
        data,
        ["modellingAndValidation", "complianceDeclarations", "compliance"],
        []
    )

    if isinstance(compliances, dict):
        compliances = [compliances]

    parts = []

    for item in compliances:
        system = item.get("referenceToComplianceSystem", {})

        descriptions = system.get("shortDescription", [])

        if isinstance(descriptions, dict):
            descriptions = [descriptions]

        value = None

        for desc in descriptions:
            if desc.get("lang") == "en":
                value = desc.get("value")
                break

        if value is None and descriptions:
            value = descriptions[0].get("value")

        if value:
            parts.append(value)

    return "; ".join(parts) if parts else None


def get_reference_exchange(data):  # Leiab reference flow exchange kirje
    exchanges = get_nested(data, ["exchanges", "exchange"], [])  # Võtab exchanges.exchange listi
    for exchange in exchanges:  # Käib exchange kirjed läbi
        if exchange.get("referenceFlow") is True:  # Otsib kirjet, kus referenceFlow on True
            return exchange  # Tagastab reference flow kirje
    return None  # Kui reference flow puudub, tagastab None


def get_declared_quantity(reference_exchange):
    if not reference_exchange:
        return None

    return reference_exchange.get("meanAmount")


def get_declared_unit(reference_exchange):
    if not reference_exchange:
        return None

    flow_properties = reference_exchange.get("flowProperties", [])

    for prop in flow_properties:
        if prop.get("referenceFlowProperty") is True:
            return prop.get("referenceUnit")

    return None


def get_flow_property_value(reference_exchange, english_name):  # Võtab reference flow property väärtuse ingliskeelse nime järgi
    if not reference_exchange:  # Kui reference exchange puudub
        return None  # Tagastab None
    for prop in reference_exchange.get("flowProperties", []):  # Käib flowProperties kirjed läbi
        for name in prop.get("name", []):  # Käib property nimed läbi
            if name.get("lang") == "en" and name.get("value") == english_name:  # Kontrollib ingliskeelset nimetust
                return prop.get("meanValue")  # Tagastab meanValue
    return None  # Kui propertyt ei leitud, tagastab None


def get_a1a3_value(lcia_result):  # Võtab ühest LCIAResult kirjest A1-A3 väärtuse
    anies = get_nested(lcia_result, ["other", "anies"], [])  # Võtab LCIAResult.other.anies listi
    for item in anies:  # Käib kõik moodulikirjed läbi
        if item.get("module") == "A1-A3":  # Otsib ainult moodulit A1-A3
            return item.get("value")  # Tagastab A1-A3 väärtuse
    return None  # Kui A1-A3 puudub, tagastab None


def get_lca_a1a3_values(data):
    lcia_results = get_nested(
        data,
        ["LCIAResults", "LCIAResult"],
        []
    )

    values = {column: None for column in LCA_UUIDS}

    for result in lcia_results:

        ref_id = get_nested(
            result,
            ["referenceToLCIAMethodDataSet", "refObjectId"]
        )

        # Võtab A1-A3 väärtuse välja
        value = get_module_value(result, "A1-A3")

        for column, uuid_list in LCA_UUIDS.items():

            if ref_id in uuid_list:
                values[column] = value

    # if values.get("GWPtotal_A1A3") is None: #diagnostika, kui GWP puudu
        # print("\n--- GWP-TOTAL PUUDUB ---")
        # print("UUID:", get_nested(data, ["processInformation", "dataSetInformation", "UUID"]))
        # print("Name:", get_nested(data, ["processInformation", "dataSetInformation", "name"]))

        # print("\nLCIA RESULTS:")
        # for result in get_nested(data, ["LCIAResults", "LCIAResult"], []):
            # ref_id = get_nested(result, ["referenceToLCIAMethodDataSet", "refObjectId"])
            # desc = get_nested(result, ["referenceToLCIAMethodDataSet", "shortDescription"], [])
            # value_a1a3 = get_module_value(result, "A1-A3")

            # print(ref_id, "|", desc, "| A1-A3:", value_a1a3)

    return values


def get_module_value(result, module_name):
    anies = get_nested(result, ["other", "anies"], [])

    for entry in anies:

        # Variant 1: {"module": "A1-A3", "value": "..."}
        if entry.get("module") == module_name:
            return entry.get("value")

        # Variant 2: {"value": {"module": "A1-A3", "amount": "..."}}
        value_obj = entry.get("value")

        if isinstance(value_obj, dict):
            if value_obj.get("module") == module_name:
                return value_obj.get("amount") or value_obj.get("value")

        # Variant 3: {"value": [{"module": "A1-A3", "amount": "..."}]}
        if isinstance(value_obj, list):
            for item in value_obj:
                if item.get("module") == module_name:
                    return item.get("amount") or item.get("value")

    return None


def search_epds_by_keyword(keyword):  # Otsib ühe märksõna järgi EPD metadata kirjed
    page_size = 500  # Määrab ühe päringu lehekülje suuruse
    start_index = 0  # Alustab esimesest tulemusest
    results = {}  # Siia salvestatakse tulemused võtmega uuid+version

    while True:  # Käib läbi kõik tulemuste leheküljed
        params = {  # Loob otsingupäringu parameetrid
            "search": True,  # Aktiveerib otsingu
            "distributed": True,  # Kaasab distributed dataset’id
            "virtual": True,  # Kaasab virtual dataset’id
            "pageSize": page_size,  # Määrab korraga küsitavate tulemuste arvu
            "startIndex": start_index,  # Määrab päringu alguspunkti
            "format": "JSON",  # Küsib JSON formaadi
            "name": keyword,  # Otsib serveri poolel EPD nimest antud märksõna
        }

        response = requests.get(SEARCH_URL, headers=headers, params=params)  # Teeb otsingupäringu

        response.raise_for_status()  # Annab vea, kui päring ebaõnnestus

        json_data = response.json()  # Muudab API vastuse Python dict objektiks

        for row in json_data.get("data", []):  # Käib leitud metadata read läbi
            key = (row.get("uuid"), row.get("version"))  # Loob unikaalse võtme uuid+version põhjal
            results[key] = row  # Salvestab metadata rea

        start_index += page_size  # Liigub järgmisele leheküljele

        if start_index >= json_data.get("totalCount", 0):  # Kontrollib, kas kõik leheküljed on läbi käidud
            break  # Lõpetab tsükli

    return results  # Tagastab märksõna tulemused


def fetch_extended_epd(metadata):

    uuid = metadata.get("uuid")
    version = metadata.get("version")
    uri = metadata.get("uri")

    parsed_uri = urlparse(uri)

    node_base_url = f"{parsed_uri.scheme}://{parsed_uri.netloc}"

    detail_url = f"{node_base_url}/resource/processes/{uuid}"

    params = {
        "version": version,
        "format": "JSON",
        "view": "extended"
    }

    response = requests.get(
        detail_url,
        headers=headers,
        params=params
    )

    if response.status_code != 200:
        print("Detailpäring ebaõnnestus")
        print("UUID:", uuid)
        # print("Version:", version)
        print("URL:", response.url)
        print("Status:", response.status_code)
        print("Vastus:", response.text[:500])
        return None

    detail = response.json()
    
    return detail


all_sets = []  # Siia lähevad iga märksõna tulemuste võtmed


all_metadata = {}  # Siia kogutakse kõigi märksõnade metadata read


for keyword in keywords:  # Käib kõik sisestatud märksõnad läbi
    found = search_epds_by_keyword(keyword)  # Otsib ühe märksõna tulemused
    all_sets.append(set(found.keys()))  # Lisab selle märksõna võtmed ühisosa arvutamiseks
    all_metadata.update(found)  # Lisab metadata read ühisesse sõnastikku
    print(f"Märksõna '{keyword}' tulemusi: {len(found)}")  # Kuvab märksõna tulemuste arvu


common_keys = set.intersection(*all_sets)  # Võtab ainult need EPD-d, mis esinevad kõigi märksõnade tulemustes

result_count = len(common_keys)

print(f"Kõigile märksõnadele sobivate EPD-de arv: {len(common_keys)}")  # Kuvab lõpliku EPD-de arvu

if result_count > 200:
    answer = input(
        f"\nLeiti {result_count} sobivat EPD-d. "
        "Analüüs võib võtta kaua aega. Kas jätkan? (jah/ei): "
    )

    if answer.lower() not in ["jah", "j", "yes", "y"]:
        print("Katkestatud. Kitsenda otsingut.")
        sys.exit()


rows = []  # Siia kogutakse lõpptabeli read


for key in common_keys:  # Käib kõik sobivad EPD-d läbi
    metadata = all_metadata[key]  # Võtab selle EPD metadata

    detail = fetch_extended_epd(metadata)  # Küsib API-st selle EPD detailandmed
    if detail is None:
        row = {
            "UUID": metadata.get("uuid"),
            "Version": metadata.get("version"),
            "Error": "Detail query failed"
        }

        rows.append(row)
    
        continue

    name_obj = get_nested(detail, ["processInformation", "dataSetInformation", "name"], {})  # Võtab nimeobjekti

    publication = get_nested(detail, ["administrativeInformation", "publicationAndOwnership"], {})  # Võtab publicationAndOwnership ploki

    reference_exchange = get_reference_exchange(detail)  # Leiab reference flow exchange kirje

    row = {  # Loob ühe lõpptabeli rea
        "UUID": get_nested(detail, ["processInformation", "dataSetInformation", "UUID"]),  # Võtab EPD UUID
        "Version": get_nested(detail, ["administrativeInformation", "publicationAndOwnership", "dataSetVersion"]),  # Võtab dataset version
        "Name (no)": localized_name(name_obj, "no"),  # Võtab norra keelse nime
        "Name (en)": localized_name(name_obj, "en"),  # Võtab inglise keelse nime
        "Name (da)": localized_name(name_obj, "da"),  # Võtab taani keelse nime
        "Name (sv)": localized_name(name_obj, "sv"),  # Võtab rootsi keelse nime
        "Compliance": get_compliance(detail),  # Võtab compliance info
        "Reference year": get_nested(detail, ["processInformation", "time", "referenceYear"]),  # Võtab reference year
        "Valid until": get_nested(detail, ["processInformation", "time", "dataSetValidUntil"]),  # Võtab valid until
        "Declaration owner": first_short_description(publication.get("referenceToOwnershipOfDataSet", {})),  # Võtab declaration owner
        "Publication date": get_publication_date(detail),  # Võtab publication date
        "Registration number": publication.get("registrationNumber"),  # Võtab registration number
        "Registration authority": first_short_description(publication.get("referenceToRegistrationAuthority", {})),  # Võtab registration authority
        "Ref. quantity": get_declared_quantity(reference_exchange),  # Võtab reference quantity
        "Ref. unit": get_declared_unit(reference_exchange),  # Võtab reference unit
        "Carbon content (biogenic) in kg": get_flow_property_value(reference_exchange, "Carbon content (biogenic)"),  # Võtab biogenic carbon content
        "Carbon content (biogenic) - packaging in kg": get_flow_property_value(reference_exchange, "Carbon content (biogenic) - packaging"),  # Võtab packaging biogenic carbon
    }

    row.update(get_lca_a1a3_values(detail))  # Lisab reale GWP-total, GWP-biogenic, GWP-fossil ja GWP-luluc A1-A3 väärtused

    rows.append(row)  # Lisab rea lõpptabelisse


df = pd.DataFrame(rows)  # Muudab read pandas tabeliks


# tulemuste print terminalis: print(df.to_string(index=False))  # Kuvab tulemuse terminalis


# Salvestab tulemuse CSV failina, eraldajaks semikoolon
df.to_csv(
    OUTPUT_FILE,
    index=False,
    encoding="utf-8-sig",
    sep=";",
    decimal="."
)


print(f"Tulemused salvestatud faili: {OUTPUT_FILE}")  # Kuvab faili nime