import os  # Impordib os mooduli, et saaks lugeda .env failist TOKEN väärtust
import sys  # Impordib sys mooduli, et saaks käsurealt märksõnu kaasa anda
import requests  # Impordib requests mooduli API päringute tegemiseks
from dotenv import load_dotenv  # Impordib load_dotenv funktsiooni .env faili laadimiseks


load_dotenv()  # Laeb .env failis olevad muutujad Pythonisse


TOKEN = os.getenv("TOKEN")  # Loeb .env failist TOKEN väärtuse


if not TOKEN:  # Kontrollib, kas TOKEN leiti
    raise ValueError("TOKEN puudub .env failist")  # Annab vea, kui TOKEN puudub


if len(sys.argv) < 2:  # Kontrollib, kas kasutaja andis vähemalt ühe märksõna
    raise ValueError("Kasuta näiteks: python fetch_epd_count.py steel rebar scrap")  # Annab juhise, kui märksõnu pole


keywords = sys.argv[1:]  # Võtab käsurealt kõik märksõnad, nt steel rebar scrap


BASE_URL = "https://portal.eco-platform.org/resource/"  # ECO Platform API baas-URL


PROCESS_ENDPOINT = "processes"  # Endpoint EPD process dataset’ide otsimiseks


headers = {  # Loob API päringu päised
    "Authorization": f"Bearer {TOKEN}"  # Lisab API tokeni Bearer tokenina
}


def fetch_ids_for_keyword(keyword):  # Defineerib funktsiooni ühe märksõna järgi EPD-de otsimiseks
    page_size = 500  # Määrab, mitu tulemust ühe päringuga küsida
    start_index = 0  # Määrab, millisest tulemusest alustada
    ids = set()  # Loob tühja hulga UUID-de kogumiseks

    while True:  # Käivitab tsükli, et vajadusel võtta mitu lehekülge tulemusi
        params = {  # Loob API päringu parameetrid
            "search": True,  # Aktiveerib ECO juhendi järgi otsingurežiimi
            "distributed": True,  # Kaasab distributed dataset’id
            "virtual": True,  # Kaasab virtual dataset’id
            "pageSize": page_size,  # Määrab ühe lehekülje suuruse
            "startIndex": start_index,  # Määrab, millisest kirjest alustada
            "format": "JSON",  # Küsib vastuse JSON kujul
            "name": keyword,  # Otsib serveri poolel EPD nimest antud märksõna
        }

        response = requests.get(  # Teeb API päringu
            f"{BASE_URL}{PROCESS_ENDPOINT}",  # Paneb kokku täieliku endpointi URL-i
            headers=headers,  # Lisab autentimise päised
            params=params,  # Lisab päringu parameetrid
        )

        response.raise_for_status()  # Katkestab programmi veaga, kui API vastus ei ole 200 OK

        result = response.json()  # Muudab API vastuse Python dict objektiks

        rows = result.get("data", [])  # Võtab vastusest EPD kirjete nimekirja

        for row in rows:  # Käib kõik saadud kirjed läbi
            ids.add(row["uuid"])  # Lisab iga kirje UUID hulka

        total_count = result.get("totalCount", 0)  # Loeb, mitu tulemust API järgi kokku olemas on

        start_index += page_size  # Nihutab järgmise päringu algust järgmisele leheküljele

        if start_index >= total_count:  # Kontrollib, kas kõik leheküljed on läbi käidud
            break  # Lõpetab tsükli, kui rohkem tulemusi pole

    return ids  # Tagastab selle märksõnaga leitud UUID-de hulga


result_sets = []  # Loob nimekirja, kuhu pannakse iga märksõna tulemuste UUID hulk


for keyword in keywords:  # Käib kõik kasutaja antud märksõnad läbi
    ids = fetch_ids_for_keyword(keyword)  # Otsib API-st selle märksõnaga sobivad EPD-d
    result_sets.append(ids)  # Lisab tulemuste hulga nimekirja
    print(f"Märksõna '{keyword}' tulemusi: {len(ids)}")  # Kuvab, mitu EPD-d selle sõnaga leiti


common_ids = set.intersection(*result_sets)  # Leiab ainult need UUID-d, mis esinesid kõigi märksõnade tulemustes


print("\nKõigile märksõnadele sobivate EPD-de arv:", len(common_ids))  # Kuvab lõpliku sobivate EPD-de arvu