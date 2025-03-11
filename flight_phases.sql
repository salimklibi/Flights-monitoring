CREATE TABLE flight_phases (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    phase_type VARCHAR(20) NOT NULL,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL
);