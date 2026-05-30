import argparse
import os
import sys
import uuid as uuid_lib
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import pandas as pd
import requests
from dotenv import load_dotenv
from psycopg2 import connect
from psycopg2.extras import execute_values


SEARCH_URL = "https://portal.eco-platform.org/resource/processes"
DEFAULT_OUTPUT_FILE = "epd_selected_fields.csv"
SOURCE_NAME = "eco-platform"

# Matches columns in 00_create_objects.sql -> staging.eco_epd_raw
STAGING_COLUMNS = [
    "run_id",
    "uuid",
    "version",
    "location_code",
    "name_no",
    "name_en",
    "name_da",
    "name_sv",
    "compliance",
    "reference_year",
    "valid_until",
    "declaration_owner",
    "publication_date",
    "registration_number",
    "registration_authority",
    "ref_quantity",
    "ref_unit",
    "mass_kg",
    "carbon_content_biogenic_kg",
    "carbon_content_biogenic_packaging_kg",
    "gwp_total_a1a3",
    "gwp_biogenic_a1a3",
    "gwp_fossil_a1a3",
    "gwp_luluc_a1a3",
    "fetched_at",
    "source_url",
]

NUMERIC_COLUMNS = {
    "ref_quantity",
    "mass_kg",
    "carbon_content_biogenic_kg",
    "carbon_content_biogenic_packaging_kg",
    "gwp_total_a1a3",
    "gwp_biogenic_a1a3",
    "gwp_fossil_a1a3",
    "gwp_luluc_a1a3",
}

LCA_UUIDS = {
    "gwp_total_a1a3": [
        # EN15804+A2 EF 3.1
        "a7ea142a-9749-11ed-a8fc-0242ac120002",
        # EN15804+A2 EF 3.0
        "6a37f984-a4b3-458a-a20a-64418c145fa2",
    ],
    "gwp_biogenic_a1a3": [
        "a7ea186c-9749-11ed-a8fc-0242ac120002",
        "2356e1ab-0185-4db5-86e5-16de51c7485c",
    ],
    "gwp_fossil_a1a3": [
        "a7ea19c0-9749-11ed-a8fc-0242ac120002",
        "5f635281-343e-44fb-83df-1971b155e6b6",
    ],
    "gwp_luluc_a1a3": [
        "a7ea1ae2-9749-11ed-a8fc-0242ac120002",
        "4331bbdb-978a-490d-8707-eeb047f01a55",
    ],
}


def get_nested(data, path, default=None):
    current = data
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def to_decimal(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def to_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def timestamp_ms_to_date(value):
    if not isinstance(value, (int, float)):
        return None
    if value < 0:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date()


def normalize_date(value):
    if value is None or value == "":
        return None

    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, (int, float)):
        if value > 10_000_000_000:  # epoch milliseconds
            return timestamp_ms_to_date(value)
        if 1900 <= int(value) <= 2200:  # year only
            return date(int(value), 12, 31)
        return None

    text = str(value).strip()

    if text.isdigit() and len(text) == 4:
        return date(int(text), 12, 31)

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            pass

    return None


def first_short_description(ref):
    descriptions = ref.get("shortDescription", []) if isinstance(ref, dict) else []
    if isinstance(descriptions, dict):
        descriptions = [descriptions]
    if not descriptions:
        return None

    for desc in descriptions:
        if desc.get("lang") == "en":
            return desc.get("value")

    return descriptions[0].get("value")


def localized_name(name_obj, lang):
    base_names = name_obj.get("baseName", []) if isinstance(name_obj, dict) else []
    for item in base_names:
        if item.get("lang") == lang:
            return item.get("value", "").strip()
    return None


def get_publication_date(data):
    anies = get_nested(data, ["processInformation", "time", "other", "anies"], [])
    for item in anies:
        if item.get("name") == "publicationDateOfEPD":
            return timestamp_ms_to_date(item.get("value"))
    return None


def get_location_code(data):
    geography = get_nested(data, ["processInformation", "geography"], {})
    location = get_nested(
        geography,
        ["locationOfOperationSupplyOrProduction", "location"],
    )
    if isinstance(location, str) and location.strip():
        return location.strip()
    return None


def get_compliance(data):
    compliances = get_nested(
        data,
        ["modellingAndValidation", "complianceDeclarations", "compliance"],
        [],
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


def get_reference_exchange(data):
    exchanges = get_nested(data, ["exchanges", "exchange"], [])
    for exchange in exchanges:
        if exchange.get("referenceFlow") is True:
            return exchange
    return None


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


def get_flow_property_value(reference_exchange, english_name):
    if not reference_exchange:
        return None

    for prop in reference_exchange.get("flowProperties", []):
        for name in prop.get("name", []):
            if name.get("lang") == "en" and name.get("value") == english_name:
                return prop.get("meanValue")

    return None


def get_mass_kg(reference_exchange):
    for english_name in ("Mass", "Mass in kg", "Weight", "Net weight"):
        value = get_flow_property_value(reference_exchange, english_name)
        if value is not None:
            return value
    return None


def get_module_value(result, module_name):
    anies = get_nested(result, ["other", "anies"], [])

    for entry in anies:
        # Variant 1: {"module": "A1-A3", "value": "..."}
        if entry.get("module") == module_name:
            return entry.get("value")

        value_obj = entry.get("value")

        # Variant 2: {"value": {"module": "A1-A3", "amount": "..."}}
        if isinstance(value_obj, dict):
            if value_obj.get("module") == module_name:
                return value_obj.get("amount") or value_obj.get("value")

        # Variant 3: {"value": [{"module": "A1-A3", "amount": "..."}]}
        if isinstance(value_obj, list):
            for item in value_obj:
                if item.get("module") == module_name:
                    return item.get("amount") or item.get("value")

    return None


def get_lca_a1a3_values(data):
    lcia_results = get_nested(data, ["LCIAResults", "LCIAResult"], [])
    values = {column: None for column in LCA_UUIDS}

    for result in lcia_results:
        ref_id = get_nested(result, ["referenceToLCIAMethodDataSet", "refObjectId"])
        value = get_module_value(result, "A1-A3")

        for column, uuid_list in LCA_UUIDS.items():
            if ref_id in uuid_list:
                values[column] = value

    return values


def search_epds_by_keyword(keyword, headers):
    page_size = 500
    start_index = 0
    results = {}

    while True:
        params = {
            "search": True,
            "distributed": True,
            "virtual": True,
            "pageSize": page_size,
            "startIndex": start_index,
            "format": "JSON",
            "name": keyword,
        }

        response = requests.get(SEARCH_URL, headers=headers, params=params, timeout=60)
        response.raise_for_status()
        json_data = response.json()

        for row in json_data.get("data", []):
            key = (row.get("uuid"), row.get("version"))
            results[key] = row

        start_index += page_size

        if start_index >= json_data.get("totalCount", 0):
            break

    return results


def fetch_extended_epd(metadata, headers):
    epd_uuid = metadata.get("uuid")
    version = metadata.get("version")
    uri = metadata.get("uri")

    parsed_uri = urlparse(uri)
    node_base_url = f"{parsed_uri.scheme}://{parsed_uri.netloc}"
    detail_url = f"{node_base_url}/resource/processes/{epd_uuid}"

    params = {
        "version": version,
        "format": "JSON",
        "view": "extended",
    }

    response = requests.get(detail_url, headers=headers, params=params, timeout=60)

    if response.status_code != 200:
        print("Detailpäring ebaõnnestus")
        print("UUID:", epd_uuid)
        print("URL:", response.url)
        print("Status:", response.status_code)
        print("Vastus:", response.text[:500])
        return None, response.url

    return response.json(), response.url


def build_row(metadata, detail, source_url, run_id, fetched_at):
    name_obj = get_nested(detail, ["processInformation", "dataSetInformation", "name"], {})
    publication = get_nested(detail, ["administrativeInformation", "publicationAndOwnership"], {})
    reference_exchange = get_reference_exchange(detail)

    row = {
        "run_id": str(run_id),
        "uuid": get_nested(detail, ["processInformation", "dataSetInformation", "UUID"]) or metadata.get("uuid"),
        "version": get_nested(detail, ["administrativeInformation", "publicationAndOwnership", "dataSetVersion"]) or metadata.get("version"),
        "location_code": get_location_code(detail),
        "name_no": localized_name(name_obj, "no"),
        "name_en": localized_name(name_obj, "en"),
        "name_da": localized_name(name_obj, "da"),
        "name_sv": localized_name(name_obj, "sv"),
        "compliance": get_compliance(detail),
        "reference_year": to_int(get_nested(detail, ["processInformation", "time", "referenceYear"])),
        "valid_until": normalize_date(get_nested(detail, ["processInformation", "time", "dataSetValidUntil"])),
        "declaration_owner": first_short_description(publication.get("referenceToOwnershipOfDataSet", {})),
        "publication_date": get_publication_date(detail),
        "registration_number": publication.get("registrationNumber"),
        "registration_authority": first_short_description(publication.get("referenceToRegistrationAuthority", {})),
        "ref_quantity": get_declared_quantity(reference_exchange),
        "ref_unit": get_declared_unit(reference_exchange),
        "mass_kg": get_mass_kg(reference_exchange),
        "carbon_content_biogenic_kg": get_flow_property_value(reference_exchange, "Carbon content (biogenic)"),
        "carbon_content_biogenic_packaging_kg": get_flow_property_value(reference_exchange, "Carbon content (biogenic) - packaging"),
        "fetched_at": fetched_at,
        "source_url": source_url or metadata.get("uri"),
    }

    row.update(get_lca_a1a3_values(detail))

    for column in NUMERIC_COLUMNS:
        row[column] = to_decimal(row.get(column))

    return {column: row.get(column) for column in STAGING_COLUMNS}


def get_db_connection():
    missing = [
        name
        for name in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
        if not os.getenv(name)
    ]
    if missing:
        raise ValueError(f"Puuduvad .env muutujad: {', '.join(missing)}")

    host = os.getenv("POSTGRES_HOST") or os.getenv("DB_HOST") or "localhost"

    # NB! Dockeris on kaks erinevat porti:
    # - DB_PORT_HOST on host-masina port, nt localhost:55432 -> container:5432
    # - konteinerite vahel tuleb tavaliselt kasutada service name'i + sisemist porti 5432
    # Kui Python töötab eraldi Docker containeris ja host on nt "db", siis 55432 ei sobi.
    explicit_port = os.getenv("POSTGRES_PORT") or os.getenv("DB_PORT_CONTAINER")
    if explicit_port:
        port = explicit_port
    elif host in {"localhost", "127.0.0.1", "host.docker.internal"}:
        port = os.getenv("DB_PORT_HOST") or "5432"
    else:
        port = "5432"

    return connect(
        host=host,
        port=port,
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )


def insert_to_staging(rows, run_id, fetched_at, message):
    if not rows:
        raise ValueError("Andmebaasi lisamiseks pole ühtegi rida.")

    pipeline_sql = """
        INSERT INTO staging.pipeline_runs
            (run_id, fetched_at, source_name, forecast_days, status, message)
        VALUES
            (%s, %s, %s, %s, %s, %s)
    """

    staging_sql = f"""
        INSERT INTO staging.eco_epd_raw ({", ".join(STAGING_COLUMNS)})
        VALUES %s
    """

    values = [tuple(row.get(column) for column in STAGING_COLUMNS) for row in rows]

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                pipeline_sql,
                (str(run_id), fetched_at, SOURCE_NAME, 0, "success", message),
            )
            execute_values(cur, staging_sql, values, page_size=500)


def write_csv(rows, output_file):
    df = pd.DataFrame(rows, columns=STAGING_COLUMNS)
    df.to_csv(
        output_file,
        index=False,
        encoding="utf-8-sig",
        sep=";",
        decimal=".",
        date_format="%Y-%m-%d",
    )
    return df


def parse_args():
    parser = argparse.ArgumentParser(
        description="Search ECO Platform EPDs, write CSV, and load rows into staging.eco_epd_raw."
    )
    parser.add_argument("keywords", nargs="+", help="Search keywords, e.g. steel rebar scrap")
    parser.add_argument(
        "--output",
        default=None,
        help="CSV output path. Default: epd_selected_fields.csv next to this script.",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="Only create the CSV file; do not insert into PostgreSQL.",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Continue without confirmation if more than 200 EPDs are found.",
    )
    return parser.parse_args()


def main():
    load_dotenv()
    args = parse_args()

    token = os.getenv("TOKEN")
    if not token:
        raise ValueError("TOKEN puudub .env failist")

    headers = {"Authorization": f"Bearer {token}"}
    run_id = uuid_lib.uuid4()
    fetched_at = datetime.now(timezone.utc)

    all_sets = []
    all_metadata = {}

    for keyword in args.keywords:
        found = search_epds_by_keyword(keyword, headers)
        all_sets.append(set(found.keys()))
        all_metadata.update(found)
        print(f"Märksõna '{keyword}' tulemusi: {len(found)}")

    common_keys = set.intersection(*all_sets) if all_sets else set()
    result_count = len(common_keys)
    print(f"Kõigile märksõnadele sobivate EPD-de arv: {result_count}")

    if result_count > 200 and not args.yes:
        answer = input(
            f"\nLeiti {result_count} sobivat EPD-d. "
            "Analüüs võib võtta kaua aega. Kas jätkan? (jah/ei): "
        )
        if answer.lower() not in ["jah", "j", "yes", "y"]:
            print("Katkestatud. Kitsenda otsingut.")
            sys.exit(0)

    rows = []
    failed_details = 0

    for key in common_keys:
        metadata = all_metadata[key]
        detail, source_url = fetch_extended_epd(metadata, headers)

        if detail is None:
            failed_details += 1
            continue

        rows.append(build_row(metadata, detail, source_url, run_id, fetched_at))

    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_file = args.output or os.path.join(base_dir, DEFAULT_OUTPUT_FILE)

    df = write_csv(rows, output_file)
    print(f"Tulemused salvestatud faili: {output_file}")
    print(f"CSV ridu: {len(df)}")

    message = (
        f"keywords={args.keywords}; matched={result_count}; "
        f"loaded={len(rows)}; failed_detail_queries={failed_details}; csv={output_file}"
    )

    if args.no_db:
        print("Andmebaasi laadimine jäeti vahele (--no-db).")
        return

    insert_to_staging(rows, run_id, fetched_at, message)
    print(f"Andmed lisatud tabelisse staging.eco_epd_raw. run_id={run_id}")


if __name__ == "__main__":
    main()
