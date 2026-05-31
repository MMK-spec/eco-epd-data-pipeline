# Edenemisraport

## Mis on valmis

- [x] Docker Compose käivitab PostgreSQL-i, töövoo konteineri, scheduleri ja näidikulaua
- [x] ECO EPD API-st saab kätte EPD andmed toodete kaupa
- [x] Andmed laetakse `staging` kihti
- [x] Vähemalt üks transformatsioon toimib
- [x] Vähemalt üks näidikulaud on nähtaval
- [x] Vähemalt üks andmekvaliteedi test läbib

### Lisainfo:
- Docker Compose käivitab PostgreSQL-i, töövoo konteineri, scheduleri ja Superset näidikulaua;
- Andmed päritakse ECO Portal API kaudu ja salvestatakse .csv faili ja `staging` kihti;
- `01_transform.sql` muundab andmed `staging` kihist `mart` kihti;
- `02_quality_tests` kontrollib andmete täielikkust ja sobivust;
- `run_pypeline.py` orkestreerib käivitust;
- Näidikulaud kuvab kirjete arvu ja keskmisi jalajälje väärtusi dimensioonide (riik, ühik) kaupa;

## Järgmised sammud

- Scheduleri lisamine projektile;
- Andmete kogumise skriptide täiustamine, et andmebaasist saaks kätte võimalikult palju soovitud andmevälju;
- Tranformatsiooni muudatused andmekvaliteedi tõstmiseks;
- Näidikulaua täiustamine äriküsimusele vastamiseks.

## Mis takistab

- Probleem 1 — ECO Portali andmebaas on väga keerulise struktuuriga ja andmed võivad olla esitatud eri failiformaatides. Kõigi soovitud andmeväljade kättesaamine on keerukas. 
- Probleem 2 — ECO Portali andmebaas kogub omakorda infot teistest andmebaasidest. Kui mõni neist ei ole kättesaadav, pole tulemused idempotentsed.

## Kontrollpunkt

Käsk, millega saab kontrollida, et töövoog töötab:

```bash
docker compose run --rm pipeline python scripts/run_pipeline.py run-all rebar --init-db -y
```

Oodatav tulemus:

- Märksõna 'rebar' tulemusi: 175
- Kõigile märksõnadele sobivate EPD-de arv: 175
- Tulemused salvestatud faili: /app/scripts/epd_selected_fields.csv
- CSV ridu: 175
- Andmed lisatud tabelisse staging.eco_epd_raw. run_id=81b00018-4879-47c9-8d36-af41bb02a403
- Finished API load
- Starting mart transformation: /app/scripts/01_transform.sql
- Finished mart transformation
- Starting quality tests: /app/scripts/02_quality_tests.sql
- Finished quality tests
- Latest pipeline run: 
- Latest successful run counts: 
- mart.latest_eco_epd sample rows: 10

Quality test results:
- FAILED | eco_epd_biogenic_not_negative | failed_rows=8 | Biogeenne GWP ei tohi olla negatiivne.
- FAILED | eco_epd_no_empty_rows | failed_rows=27 | EPD kirjetel ei tohi puududa põhiandmed.
- PASSED | eco_epd_gwp_control_within_tolerance | failed_rows=0 | GWP kontrollväärtus peab olema 0 või jääma 2% piiresse kogumõjust.
- PASSED | eco_epd_mart_has_rows | failed_rows=0 | Viimasel edukal laadimisel peab olema vähemalt üks mart-rida.
- PASSED | eco_epd_raw_has_rows | failed_rows=0 | Viimasel edukal laadimisel peab olema vähemalt üks staging-rida.
