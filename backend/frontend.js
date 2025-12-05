// src/App.jsx
import { useEffect, useState } from "react";

export default function App() {
  const [alerts, setAlerts] = useState([]);

  useEffect(() => {
    const ws = new WebSocket("ws://localhost:8000/api/ws");
    ws.onmessage = (msg) => {
      const data = JSON.parse(msg.data);
      setAlerts(prev => [data,...prev].slice(0,50));
    };
  }, []);

  return (
    <div className="p-4">
      <h1 className="text-xl font-bold mb-4">ETH Degen Sniper Alerts</h1>
      <ul>
        {alerts.map((a,i) => (
          <li key={i} className="mb-2 border p-2 rounded">
            <strong>{a.pair?.baseToken?.symbol || "???"}</strong> - {a.safety} - {a.pair?.liquidity?.usd || 0}$
            <br />
            🐦 {a.twitter} 💬 {a.telegram} 🌐 {a.web}
          </li>
        ))}
      </ul>
    </div>
  );
}
