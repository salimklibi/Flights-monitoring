import requests
import psycopg2
from datetime import datetime

# Configuration de la base de données PostgreSQL
connection = psycopg2.connect(
    host="localhost",       
    database="mydb",        
    user="salim"
    )

# URL de l'API OpenSky Network
OPEN_SKY_API_URL = "https://opensky-network.org/api/flights/aircraft"


import time

def get_last_10_flights(icao24):
    """Récupère les 10 derniers vols d'un avion via OpenSky Network."""
    params = {
        'icao24': icao24,
        'begin': int(datetime.timestamp(datetime.utcnow()) - 7 * 24 * 3600),  # 7 derniers jours
        'end': int(datetime.timestamp(datetime.utcnow()))
    }
    response = requests.get(OPEN_SKY_API_URL, params=params)
    
    time.sleep(1)
    
    response.raise_for_status()
    flights = response.json()
    
    print(f"Réponse API : {flights}")  # Débogage

    return sorted(flights, key=lambda x: x.get('firstSeen', 0), reverse=True)[:10]


def get_flight_track(icao24, start, end):
    """Récupère la trajectoire d'un vol spécifique."""
    TRACK_API_URL = f"https://opensky-network.org/api/tracks/all?icao24={icao24}&time={start}"
    response = requests.get(TRACK_API_URL)
    response.raise_for_status()
    track_data = response.json()
    
    if not track_data.get('states'):
        print(f"Pas de données de trajectoire trouvées pour l'avion {icao24}")
        return []
    
    print(f"Réponse API Track : {track_data}")  # Débogage

    return track_data['states']


def detect_phases(callsign):
    """Détecte les phases de vol à partir des données de trajectoire."""
    sorted_track = sorted(callsign, key=lambda x: x['timestamp'])
    phases = []
    
    if not sorted_track:
        return []
    
    # Taxi-out
    taxi_out_start = sorted_track[0]['timestamp']
    taxi_out_end = next((p['timestamp'] for p in sorted_track if p['altitude'] > 0), None)
    if not taxi_out_end:
        return []
    phases.append(('taxi-out', taxi_out_start, taxi_out_end))
    
    # Takeoff
    takeoff_start = taxi_out_end
    takeoff_end = None
    max_alt = 0
    for i, p in enumerate(sorted_track):
        if p['timestamp'] < takeoff_start:
            continue
        if p['altitude'] > max_alt:
            max_alt = p['altitude']
        else:
            if all(sp['altitude'] <= max_alt for sp in sorted_track[i:i+3]):
                takeoff_end = p['timestamp']
                break
    takeoff_end = takeoff_end or sorted_track[-1]['timestamp']
    phases.append(('takeoff', takeoff_start, takeoff_end))
    
    # Cruise
    cruise_start = takeoff_end
    cruise_end = None
    for i, p in enumerate(sorted_track):
        if p['timestamp'] < cruise_start:
            continue
        if i > 0 and p['altitude'] < sorted_track[i-1]['altitude']:
            cruise_end = sorted_track[i-1]['timestamp']
            break
    cruise_end = cruise_end or sorted_track[-1]['timestamp']
    phases.append(('cruise', cruise_start, cruise_end))
    
    # Landing
    landing_start = cruise_end
    landing_end = next((p['timestamp'] for p in sorted_track if p['timestamp'] >= landing_start and p['altitude'] <= 0), sorted_track[-1]['timestamp'])
    phases.append(('landing', landing_start, landing_end))
    
    # Taxi-in
    taxi_in_start = landing_end
    taxi_in_end = sorted_track[-1]['timestamp']
    phases.append(('taxi-in', taxi_in_start, taxi_in_end))
    
    return [{
        'type': phase[0],
        'start': datetime.fromtimestamp(phase[1]),
        'end': datetime.fromtimestamp(phase[2])
    } for phase in phases]


def save_to_db(icao24, phases):
    """Sauvegarde les phases de vol dans PostgreSQL."""
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    for phase in phases:
        cursor.execute("""
            INSERT INTO flight_phases (icao24, phase_type, start_time, end_time)
            VALUES (%s, %s, %s, %s)
        """, (icao24, phase['type'], phase['start'], phase['end']))
    conn.commit()
    cursor.close()
    conn.close()


def main(icao24):
    flights = get_last_10_flights(icao24)
    for flight in flights:
        try:
            if 'callsign' not in flight:
                print(f"Le vol {flight.get('icao24', 'N/A')} ne contient pas de 'callsign'")
                continue

            # Récupérer la trajectoire pour ce vol
            track_data = get_flight_track(flight['icao24'], flight['firstSeen'], flight['lastSeen'])
            phases = detect_phases(track_data)
            
            if phases:
                save_to_db(flight['icao24'], phases)
        except Exception as e:
            print(f"Erreur lors du traitement du vol {flight.get('icao24', 'N/A')}: {e}")



if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python flight_phases.py <icao24>")
        sys.exit(1)
    main(sys.argv[1])
