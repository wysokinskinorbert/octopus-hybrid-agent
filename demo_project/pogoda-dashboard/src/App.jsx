import React, { useState, useEffect } from 'react';
import './App.css';

function App() {
  const [weather, setWeather] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchWeather = async () => {
      try {
        const apiKey = 'YOUR_API_KEY'; // Replace with actual API key
        const city = 'London';
        const url = `https://api.openweathermap.org/data/2.5/weather?q=${city}&appid=${apiKey}&units=metric`;
        
        const response = await fetch(url);
        if (!response.ok) {
          throw new Error('Failed to fetch weather data');
        }
        
        const data = await response.json();
        setWeather({
          temperature: data.main.temp,
          humidity: data.main.humidity,
          windSpeed: data.wind.speed,
          description: data.weather[0].description,
          city: data.name
        });
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchWeather();
  }, []);

  if (loading) return <div className='App'>Loading weather data...</div>;
  if (error) return <div className='App'>Error: {error}</div>;
  if (!weather) return <div className='App'>No weather data available</div>;

  return (
    <div className='App'>
      <h1>Weather Dashboard</h1>
      <h2>{weather.city}</h2>
      <div className='weather-info'>
        <p>Temperature: {weather.temperature}°C</p>
        <p>Humidity: {weather.humidity}%</p>
        <p>Wind Speed: {weather.windSpeed} m/s</p>
        <p>Conditions: {weather.description}</p>
      </div>
    </div>
  );
}

export default App;
