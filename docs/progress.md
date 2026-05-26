# Edenemisraport

## Mis on valmis

- [ ] Docker Compose käivitab PostgreSQL-i, töövoo konteineri, scheduleri ja näidikulaua
- [ ] ECO EPD API-st saab kätte EPD andmed toodete kaupa
- [ ] Andmed laetakse `staging` kihti
- [ ] Vähemalt üks transformatsioon toimib
- [ ] Vähemalt üks näidikulaud on nähtaval
- [ ] Vähemalt üks andmekvaliteedi test läbib

[Täpsusta lühidalt, mis täpselt valmis on]

## Järgmised sammud

- Andmete kogumise skriptide täiustamine, et andmebaasist saaks kätte võimalikult palju soovitud andmevälju
- [Teine tegevus]
- [Kolmas tegevus]

## Mis takistab

- Probleem 1 — ECO Portali andmebaas on väga keerulise struktuuriga ja andmed võivad olla esitatud eri failiformaatides. Kõigi soovitud andmeväljade kättesaamine on keerukas. 
- Probleem 2 — ECO Portali andmebaas kogub omakorda infot teistest andmebaasidest. Kui mõni neist ei ole kättesaadav, pole tulemused idempotentsed.

## Kontrollpunkt

Käsk, millega saab kontrollida, et töövoog töötab:

```bash
# [Lisa siia käsk, mis näitab, et andmed liiguvad allikast näidikulauani]
# Näiteks:
docker compose exec pipeline python scripts/run_pipeline.py check
```

Oodatav tulemus: [Kirjelda, mida töötav süsteem väljastab]
