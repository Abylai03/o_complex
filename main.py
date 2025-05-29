import sqlite3
from datetime import datetime
from fastapi import FastAPI, HTTPException, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List
import httpx
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

# Регистрация адаптера для datetime
def adapt_datetime(dt):
    return dt.isoformat()

sqlite3.register_adapter(datetime, adapt_datetime)

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="your-secret-key")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Database initialization
def init_db():
    with sqlite3.connect("weather.db") as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                city TEXT,
                search_time TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE
            )
        """)

init_db()

class CitySuggestion(BaseModel):
    name: str

# @app.get("/", response_class=HTMLResponse)
# async def home(request: Request):
#     user_id = request.session.get("user_id", str(datetime.now().timestamp()))
#     request.session["user_id"] = user_id
    
#     with sqlite3.connect("weather.db") as conn:
#         cursor = conn.execute(
#             "SELECT city FROM search_history WHERE user_id = ? ORDER BY search_time DESC LIMIT 1",
#             (user_id,)
#         )
#         last_city = cursor.fetchone()
    
#     return templates.TemplateResponse(
#         "index.html",
#         {"request": request, "last_city": last_city[0] if last_city else None}
#     )

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user_id = request.session.get("user_id", str(datetime.now().timestamp()))
    request.session["user_id"] = user_id
    
    with sqlite3.connect("weather.db") as conn:
        cursor = conn.execute(
            "SELECT city FROM search_history WHERE user_id = ? ORDER BY search_time DESC LIMIT 1",
            (user_id,)
        )
        last_city = cursor.fetchone()
    
    return templates.TemplateResponse(
        request=request,  # Первый аргумент - request
        name="index.html",
        context={"last_city": last_city[0] if last_city else None}
    )

@app.post("/weather")
async def get_weather(request: Request, city: str = Form(...)):
    user_id = request.session.get("user_id", str(datetime.now().timestamp()))
    request.session["user_id"] = user_id

    async with httpx.AsyncClient() as client:
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&language=ru"
        geo_response = await client.get(geo_url)
        
        if geo_response.status_code != 200 or not geo_response.json().get("results"):
            raise HTTPException(status_code=404, detail="City not found")
        
        geo_data = geo_response.json()["results"][0]
        lat, lon = geo_data["latitude"], geo_data["longitude"]
        
        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            "&hourly=temperature_2m,weathercode&forecast_days=1"
        )
        weather_response = await client.get(weather_url)
        
        if weather_response.status_code != 200:
            raise HTTPException(status_code=500, detail="Weather API error")
        
        weather_data = weather_response.json()
        
        with sqlite3.connect("weather.db") as db:
            db.execute(
                "INSERT INTO search_history (user_id, city, search_time) VALUES (?, ?, ?)",
                (user_id, city, datetime.now())
            )
            db.execute("INSERT OR IGNORE INTO cities (name) VALUES (?)", (city,))
            db.commit()
        
        formatted_data = []
        for time, temp, code in zip(
            weather_data["hourly"]["time"],
            weather_data["hourly"]["temperature_2m"],
            weather_data["hourly"]["weathercode"]
        ):
            formatted_data.append({
                "time": time,
                "temperature": temp,
                "weather_code": code
            })
        
        return {"city": city, "forecast": formatted_data[:24]}

# @app.get("/autocomplete", response_model=List[CitySuggestion])
# async def autocomplete(query: str):
#     async with httpx.AsyncClient() as client:
#         geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={query}&count=5&language=ru"
#         geo_response = await client.get(geo_url)
        
#         if geo_response.status_code != 200 or not geo_response.json().get("results"):
#             return []
        
#         cities = [
#             {"name": f"{result['name']}, {result['country']}"}
#             for result in geo_response.json()["results"]
#         ]
#         return cities

@app.get("/autocomplete", response_model=List[CitySuggestion])
async def autocomplete(query: str):
    async with httpx.AsyncClient() as client:
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={query}&count=5&language=ru"
        geo_response = await client.get(geo_url)
        
        if geo_response.status_code != 200 or not geo_response.json().get("results"):
            return []
        
        cities = [
            {"name": f"{result['name']}, {result.get('country', 'Unknown')}"}
            for result in geo_response.json()["results"]
        ]
        return cities

@app.get("/search-stats")
async def search_stats():
    with sqlite3.connect("weather.db") as db:
        cursor = db.execute(
            "SELECT city, COUNT(*) as count FROM search_history GROUP BY city ORDER BY count DESC"
        )
        stats = [{"city": row[0], "count": row[1]} for row in cursor.fetchall()]
    return stats