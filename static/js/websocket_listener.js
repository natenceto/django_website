// EV Charging Platform - General UI WebSocket Listener

function initPlatformWebSockets() {
    // 1. Establish connection to main UI WebSocket consumer via WSS or WS depending on protocol
    const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
    const wsUrl = protocol + window.location.host + '/ws/stations/status/';
    
    // Check if we are on dashboard or a place to use WS
    if (!document.getElementById('algo-status-badge')) {
        console.log("WebSocket client inactive: Not on dashboard.");
        return;
    }

    console.log("Connecting to Platform UI WebSocket: " + wsUrl);
    const socket = new WebSocket(wsUrl);

    socket.onopen = function(e) {
        console.log("[WebSocket] Connection established. Listening for events...");
    };

    socket.onmessage = function(e) {
        const data = JSON.parse(e.data);
        console.log("[WebSocket] Received real-time update:", data);

        if (data.type === 'station_power_changed') {
            // Update station visual power (if tables exist)
            const stationCell = document.querySelector(`.station-power[data-station="${data.station_id}"]`);
            if (stationCell) {
                stationCell.textContent = data.power_kw + " kW";
                stationCell.classList.add('bg-warning');
                setTimeout(() => stationCell.classList.remove('bg-warning'), 1000);
            }
            addAuditLog(" Зарядна Станция", `Станция ${data.station_id} промени мощността си на ${data.power_kw}kW.`);
        }
        else if (data.type === 'algorithm_status') {
            // Update badge (Усилено слънце, Лошо време/Еко, Критична батерия)
            const badge = document.getElementById('algo-status-badge');
            if (badge) {
                badge.textContent = `Активен: ${data.mode}`;
                badge.className = 'badge px-2 py-1 text-white';
                
                if (data.mode.includes('Слънце')) badge.classList.add('bg-warning');
                else if (data.mode.includes('Критична')) badge.classList.add('bg-danger');
                else badge.classList.add('bg-success'); // Balanced
            }
            
            if (data.reason) {
                addAuditLog("🧠 Енергиен Алгоритъм", data.reason);
            }
        }
        else if (data.type === 'inverter_telemetry') {
            // Update Live Inverter Data
            const pwrCard = document.getElementById('live-generate-power');
            const batCard = document.getElementById('live-battery-soc');
            
            if (pwrCard) pwrCard.textContent = data.power + " W";
            if (batCard) batCard.textContent = data.soc + " %";
        }
        else if (data.type === 'weather_update') {
            const radEl = document.getElementById('weather-solar-rad');
            const descEl = document.getElementById('weather-desc');
            if (radEl) radEl.innerHTML = `${data.radiation} <small style="font-size: 1rem;">W/m²</small>`;
            if (descEl) descEl.textContent = data.summary;
        }
    };

    socket.onclose = function(e) {
        console.error('[WebSocket] Connection closed unexpectedly. Reconnecting in 5s...');
        setTimeout(initPlatformWebSockets, 5000);
    };
    
    socket.onerror = function(err) {
        console.error('WebSocket Error: ', err);
    };
}

// Audit log helper
function addAuditLog(category, message) {
    const container = document.getElementById('audit-log-container');
    if (!container) return;

    const timeString = new Date().toLocaleTimeString();
    
    const entry = document.createElement('div');
    entry.className = "activity-item border-left-info pl-2 mb-2";
    entry.innerHTML = `
        <span class="text-muted" style="font-size: 10px;">${timeString}</span><br>
        <strong>${category}:</strong> ${message}
    `;
    
    container.prepend(entry);
    
    // Keep only last 10 entries to avoid DOM bloat
    if (container.children.length > 10) {
        container.removeChild(container.lastChild);
    }
}

// Init on DOM Load
document.addEventListener("DOMContentLoaded", initPlatformWebSockets);
