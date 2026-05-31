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

Oodatav tulemus: [Kirjelda, mida töötav süsteem väljastab]
