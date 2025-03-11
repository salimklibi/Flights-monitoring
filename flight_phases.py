import requests
import psycopg2
from datetime import datetime
import sys
import logging

# Configuration de la base de données PostgreSQL
DB_CONFIG = {
    'dbname': 'mydb',  
    'user': 'salim',  
    'password': 'password',  
    'host': 'localhost'  
}

# URL de l'API Flightradar24 (À VÉRIFIER ET ADAPTER)
FLIGHTRADAR_API_URL = "https://data-live.flightradar24.com/clickhandler/"
FLIGHTRADAR_API_KEY = '9e2fd92b-d40f-49e6-b944-1b261904f9d3|Ec25hB0bXA9QnRMebS5dhhKHZdOfKBLNGvdfhZ3F3a5c1113'


def get_last_10_flights(registration):
    """Récupère les 10 derniers vols d'un avion via Flightradar24."""
    headers = {'Authorization': f'Bearer {FLIGHTRADAR_API_KEY}'}
    try:
        response = requests.get(f"{FLIGHTRADAR_API_URL}?flight={registration}", headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if 'trail' in data:
            return data['trail']  # Liste des points de trajectoire
        else:
            logging.error("Aucune donnée de vol trouvée dans la réponse API.")
            return []
    except requests.exceptions.RequestException as err:
        logging.error(f"Erreur lors de l'accès à l'API : {err}")
        return []


def detect_phases(trail):
    """Détecte les phases de vol à partir des données de trajectoire."""
    phases = []
    if not trail:
        return phases

    previous_altitude = 0
    current_phase = None
    start_time = None
    
    for point in trail:
        timestamp = datetime.utcfromtimestamp(point['ts'])
        altitude = point.get('alt', 0)
        
        if current_phase is None:  # Début du vol (taxi-out)
            current_phase = 'taxi-out'
            start_time = timestamp
        elif current_phase == 'taxi-out' and altitude > 0:
            phases.append({'type': 'taxi-out', 'start': start_time, 'end': timestamp})
            current_phase = 'takeoff'
            start_time = timestamp
        elif current_phase == 'takeoff' and altitude > previous_altitude:
            continue  # Montée
        elif current_phase == 'takeoff' and altitude <= previous_altitude:
            phases.append({'type': 'takeoff', 'start': start_time, 'end': timestamp})
            current_phase = 'cruise'
            start_time = timestamp
        elif current_phase == 'cruise' and altitude < previous_altitude:
            phases.append({'type': 'cruise', 'start': start_time, 'end': timestamp})
            current_phase = 'landing'
            start_time = timestamp
        elif current_phase == 'landing' and altitude == 0:
            phases.append({'type': 'landing', 'start': start_time, 'end': timestamp})
            current_phase = 'taxi-in'
            start_time = timestamp
        previous_altitude = altitude
    
    if current_phase == 'taxi-in':
        phases.append({'type': 'taxi-in', 'start': start_time, 'end': timestamp})
    
    return phases


def save_to_db(registration, flight_number, departure_date, phases):
    """Sauvegarde les phases de vol dans PostgreSQL."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        for phase in phases:
            cursor.execute("""
                INSERT INTO flight_phases (icao24, interval, name, type)
                VALUES (%s, tstzrange(%s, %s, '[]'), %s, %s)
            """, (registration, phase['start'], phase['end'], f"{registration}_{flight_number}_{departure_date}", phase['type']))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logging.error(f"Erreur lors de la connexion ou de l'insertion dans la base de données : {e}")


def main(registration):
    track = get_last_10_flights(registration)
    if not track:
        logging.error(f"Aucun vol trouvé pour l'immatriculation {registration}.")
        return
    
    logging.info(f"Récupération de la trajectoire pour {registration}.")
    phases = detect_phases(track)
    
    if phases:
        save_to_db(registration, "UNKNOWN", "UNKNOWN", phases)
    else:
        logging.warning("Aucune phase détectée.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) != 2:
        logging.error("Usage: python flight_phases.py <immatriculation>")
        sys.exit(1)
    
    registration = sys.argv[1]
    main(registration)