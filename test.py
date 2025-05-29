import pytest
from fastapi.testclient import TestClient
from main import app, init_db
import sqlite3
import responses
from unittest.mock import Mock

@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "test_weather.db")
    
    original_connect = sqlite3.connect
    def mocked_connect(*args, **kwargs):
        if args and args[0] == "weather.db":
            return original_connect(db_path, **kwargs)
        return original_connect(*args, **kwargs)
    
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("main.sqlite3.connect", mocked_connect)
        init_db()
        yield TestClient(app)

@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test_weather.db"
    conn = sqlite3.connect(db_path)
    try:
        yield conn
    finally:
        conn.close()

@pytest.fixture
def mock_open_meteo():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            "https://geocoding-api.open-meteo.com/v1/search",
            json={
                "results": [
                    {"name": "Lo", "latitude": 51.123, "longitude": 4.567, "country": "Бельгия"},
                    {"name": "Lo", "latitude": 7.890, "longitude": 4.123, "country": "Нигерия"},
                    {"name": "Lo", "latitude": 12.345, "longitude": -1.234, "country": "Буркина-Фасо"},
                    {"name": "Lo", "latitude": 9.876, "longitude": 2.345, "country": "Бенин"},
                    {"name": "Lo", "latitude": 45.678, "longitude": 8.901, "country": "Unknown"}
                ]
            },
            status=200
        )
        rsps.add(
            responses.GET,
            "https://api.open-meteo.com/v1/forecast",
            json={
                "hourly": {
                    "time": [f"2025-05-30T{i:02d}:00" for i in range(24)],
                    "temperature_2m": [15.0 + i * 0.1 for i in range(24)],
                    "weathercode": [0 if i % 2 == 0 else 1 for i in range(24)]
                }
            },
            status=200
        )
        yield rsps

def test_get_home(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Weather App" in response.text
    assert "Enter city name" in response.text

def test_get_weather_valid_city(client, db, mock_open_meteo):
    response = client.post("/weather", data={"city": "London"})
    assert response.status_code == 200
    assert response.json()["city"] == "London"
    assert len(response.json()["forecast"]) == 24
    assert all(
        "time" in forecast and "temperature" in forecast and "weather_code" in forecast
        for forecast in response.json()["forecast"]
    )
    
    cursor = db.execute("SELECT city, user_id, search_time FROM search_history WHERE city = 'London'")
    result = cursor.fetchone()
    assert result is not None
    assert result[0] == "London"
    assert result[1] is not None

def test_get_weather_invalid_city(client):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            "https://geocoding-api.open-meteo.com/v1/search",
            json={"results": []},
            status=200
        )
        response = client.post("/weather", data={"city": "NonExistentCity123"})
        assert response.status_code == 404
        assert response.json()["detail"] == "City not found"

def test_autocomplete(client, mock_open_meteo):
    response = client.get("/autocomplete?query=Lo")
    assert response.status_code == 200
    assert len(response.json()) == 5
    assert any(city["name"] == "Lo, Бельгия" for city in response.json())
    assert any(city["name"] == "Lo, Нигерия" for city in response.json())

def test_search_stats(client, db):
    db.execute(
        "INSERT INTO search_history (user_id, city, search_time) VALUES (?, ?, ?)",
        ("test_user", "London", "2025-05-30T00:00:00")
    )
    db.execute(
        "INSERT INTO search_history (user_id, city, search_time) VALUES (?, ?, ?)",
        ("test_user", "London", "2025-05-30T01:00:00")
    )
    db.execute(
        "INSERT INTO search_history (user_id, city, search_time) VALUES (?, ?, ?)",
        ("test_user", "Paris", "2025-05-30T02:00:00")
    )
    db.commit()
    
    response = client.get("/search-stats")
    assert response.status_code == 200
    assert any(stat["city"] == "London" and stat["count"] == 2 for stat in response.json())
    assert any(stat["city"] == "Paris" and stat["count"] == 1 for stat in response.json())