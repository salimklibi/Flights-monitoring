# Version finale du code
# Auteur : Salim Klibi
# Date : 11/02/2025

import requests
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime, timedelta
import pytz
from dateutil import parser

import os

FR24_API_KEY = os.getenv("FR24_API_KEY")  
if not FR24_API_KEY:
    print("Erreur : La clé API est absente. Définissez FR24_API_KEY dans les variables d'environnement.")
    exit(1)


DB_PARAMS = {
    "dbname": "aviation",
    "user": "salim",
    "password": "mon_mot_de_passe",
    "host": "localhost",
    "port": "5432"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

def get_flight_data(registration):
    url = "https://api.flightradar24.com/common/v1/flight/list.json"
    params = {
        "query": registration,  
        "fetchBy": "reg", 
        "limit": 10,
        "token": FR24_API_KEY 
    }

    try:
        response = requests.get(url, headers=HEADERS, params=params, timeout=10)


        if response.status_code == 451:
            print("Erreur 451 : Accès bloqué. Essayez un VPN ou un proxy.")
            return None

        if response.status_code != 200:
            print(f"Erreur API {response.status_code} : {response.text}")
            return None

        data = response.json()
        last_10_data = data["result"]["response"]["data"][-10:]
        return last_10_data

    except requests.exceptions.RequestException as e:
        print(f"Erreur lors de la requête API : {e}")
        return None
    except Exception as e:
        print(f"Erreur inattendue : {e}")
        return None

def convert_to_trajectory(flight):
    
    scheduled_dep = flight.get("time", {}).get("scheduled", {}).get("departure", None)
    scheduled_arr = flight.get("time", {}).get("scheduled", {}).get("arrival", None)
    real_dep = flight.get("time", {}).get("real", {}).get("departure", scheduled_dep)
    real_arr = flight.get("time", {}).get("real", {}).get("arrival", scheduled_arr)
    duration = flight.get("time", {}).get("other", {}).get("duration", None)

    if not real_dep or not real_arr or not duration:
        return {"trajectory": []}

    real_dep_dt = datetime.utcfromtimestamp(real_dep)
    real_arr_dt = datetime.utcfromtimestamp(real_arr)

    taxi_out = real_dep_dt - timedelta(minutes=15)
    takeoff = real_dep_dt
    cruise = real_dep_dt + timedelta(seconds=duration // 2)
    landing = real_arr_dt - timedelta(minutes=15)
    taxi_in = real_arr_dt

    trajectory = [
        {"timestamp": int(taxi_out.timestamp()), "altitude": 0},
        {"timestamp": int(takeoff.timestamp()), "altitude": 500},
        {"timestamp": int(cruise.timestamp()), "altitude": 35000},
        {"timestamp": int(landing.timestamp()), "altitude": 1000},
        {"timestamp": int(taxi_in.timestamp()), "altitude": 0}
    ]

    return {"trajectory": trajectory}

def convert_to_french_time(ts):    
    if isinstance(ts, int):
        if ts > 10**10:
            ts = ts / 1000
        utc_time = datetime.utcfromtimestamp(ts).replace(tzinfo=pytz.utc)

    elif isinstance(ts, str):
        utc_time = datetime.fromisoformat(ts.replace("Z", "+00:00")) 

    else:
        raise ValueError("Ungültiges Format für Timestamp!")

    french_tz = pytz.timezone("Europe/Paris")
    french_time = utc_time.astimezone(french_tz)

    return french_time.strftime('%d.%m.%Y %H:%M:%S')

def detect_phases(flight_data):
    phases = []
    current_phase = None
    prev_alt = 0

    for point in sorted(flight_data.get("trajectory", []), key=lambda x: x.get("timestamp", 0)):
        alt = point.get("altitude", 0)
        ts = point.get("timestamp", 0)
        normal_date = convert_to_french_time(ts)

        # Taxi-Out 
        if alt == 0 and current_phase is None:
            current_phase = ("taxi-out", normal_date)

        # Takeoff 
        elif alt > 0 and (current_phase is None or current_phase[0] == "taxi-out"):
            phases.append((current_phase[0], current_phase[1], normal_date))
            current_phase = ("takeoff", normal_date)

        # Cruise 
        elif alt > prev_alt and current_phase[0] == "takeoff":
            phases.append((current_phase[0], current_phase[1], normal_date))
            current_phase = ("cruise", normal_date)

        # Landing 
        elif alt < prev_alt and current_phase[0] == "cruise":
            phases.append((current_phase[0], current_phase[1], normal_date))
            current_phase = ("landing", normal_date)

        # Taxi-In 
        elif alt == 0 and current_phase[0] == "landing":
            phases.append((current_phase[0], current_phase[1], normal_date))
            current_phase = ("taxi-in", normal_date)

        prev_alt = alt  

    if current_phase:
        phases.append((current_phase[0], current_phase[1], normal_date))

    return phases

def save_to_db(registration, flight_number, phases):
    """Enregistre les phases de vol dans PostgreSQL."""
    conn = None
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur = conn.cursor()


        insert_query = """
            INSERT INTO flight_phases 
            (flight_registration, flight_number, phase, phase_name) 
            VALUES %s
            ON CONFLICT (flight_registration, phase) DO NOTHING;
        """

        values = [
            (registration, flight_number, f"[{start},{end}]", phase_name)
            for phase_name, start, end in phases
        ]
        
        execute_values(cur, insert_query, values)
        conn.commit()

    except Exception as e:
        print(f"Erreur lors de l'insertion : {e}")

    finally:
        if conn:
            conn.close()

def main():
    registration = "F-GSQA"
    flights = get_flight_data(registration)

    if not flights: 
        print("Aucun vol récupéré, fin du programme.")
        return

    for flight in flights:

        flight_data = convert_to_trajectory(flight)
        phases = detect_phases(flight_data)
        
        flight_number = flight.get("identification", {}).get("number", {}).get("default", "UNKNOWN")
        registration = flight.get("aircraft", {}).get("registration", "UNKNOWN")
        
        save_to_db(registration, flight_number, phases)

if __name__ == "__main__":
    main()