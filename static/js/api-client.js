/**
 * EV Charging Platform API Client
 * Лесен за използване JavaScript клиент за API-то на платформата
 */
class EVPlatformAPI {
    constructor() {
        this.baseURL = '';
        this.token = this.getCookie('authToken') || null;
    }

    /**
     * Взима token от cookie
     */
    getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    /**
     * Прави AJAX заявка към API
     */
    async request(endpoint, options = {}) {
        const url = `${this.baseURL}/api${endpoint}`;
        const config = {
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCookie('csrftoken'),
                ...options.headers
            },
            ...options
        };

        if (this.token) {
            config.headers['Authorization'] = `Token ${this.token}`;
        }

        try {
            const response = await fetch(url, config);
            
            if (!response.ok) {
                throw new Error(`API Error: ${response.status} ${response.statusText}`);
            }
            
            return await response.json();
        } catch (error) {
            console.error('API Request failed:', error);
            throw error;
        }
    }

    // ========== ENERGY MANAGEMENT API ==========
    
    /**
     * Взима текущия статус на инверторите
     */
    async getInverterStatus() {
        return this.request('/energy/inverters/status/');
    }

    /**
     * Взима история на инвертор
     */
    async getInverterHistory(deviceSn, hours = 24) {
        return this.request(`/energy/inverters/${deviceSn}/history/?hours=${hours}`);
    }

    /**
     * Взима данни за dashboard
     */
    async getDashboardData() {
        return this.request('/energy/dashboard/api/');
    }

    /**
     * Взима препоръка за зареждане
     */
    async getChargingRecommendation(vehicleId, targetSoc, currentSoc, maxPower) {
        return this.request('/energy/charging/recommendation/', {
            method: 'POST',
            body: JSON.stringify({
                vehicle_id: vehicleId,
                target_soc: targetSoc,
                current_soc: currentSoc,
                max_power: maxPower
            })
        });
    }

    /**
     * Събира данни от инвертори
     */
    async collectEnergyData() {
        return this.request('/energy/data/collect/', {
            method: 'POST'
        });
    }

    // ========== STATIONS API ==========
    
    /**
     * Взима списък със станции
     */
    async getStations() {
        return this.request('/stations/');
    }

    /**
     * Стартира зарядна сесия
     */
    async startCharging(stationId, connectorId, rfidTag) {
        return this.request(`/stations/${stationId}/start/`, {
            method: 'POST',
            body: JSON.stringify({
                connector_id: connectorId,
                rfid_tag: rfidTag
            })
        });
    }

    /**
     * Спира зарядна сесия
     */
    async stopCharging(stationId, transactionId) {
        return this.request(`/stations/${stationId}/stop/`, {
            method: 'POST',
            body: JSON.stringify({
                transaction_id: transactionId
            })
        });
    }

    // ========== DEYE API ==========
    
    /**
     * Взима списък със станции от DeyeCloud
     */
    async getDeyeStations() {
        return this.request('/deye/stations/');
    }

    /**
     * Взима данни от инвертори
     */
    async getDeyeDevices() {
        return this.request('/deye/devices/');
    }

    // ========== Helper методи ==========
    
    /**
     * Показва loading състояние
     */
    showLoading(elementId) {
        const element = document.getElementById(elementId);
        if (element) {
            element.innerHTML = `
                <div class="text-center">
                    <div class="spinner-border text-primary" role="status">
                        <span class="sr-only">Loading...</span>
                    </div>
                    <p class="mt-2">Loading data...</p>
                </div>
            `;
        }
    }

    /**
     * Показва грешка
     */
    showError(elementId, message) {
        const element = document.getElementById(elementId);
        if (element) {
            element.innerHTML = `
                <div class="alert alert-danger" role="alert">
                    <i class="fas fa-exclamation-triangle"></i>
                    <strong>Error:</strong> ${message}
                </div>
            `;
        }
    }

    /**
     * Форматира мощност
     */
    formatPower(watts) {
        if (watts >= 1000) {
            return `${(watts / 1000).toFixed(2)} kW`;
        }
        return `${watts.toFixed(0)} W`;
    }

    /**
     * Форматира процент
     */
    formatPercentage(value) {
        return `${value.toFixed(1)}%`;
    }

    /**
     * Форматира време
     */
    formatTime(timestamp) {
        return new Date(timestamp).toLocaleString();
    }
}

// Глобален инстанс на API клиента
window.EVPlatformAPI = new EVPlatformAPI();

// Helper функции за лесно използване
window.loadEnergyData = async function(elementId = 'energy-data') {
    try {
        window.EVPlatformAPI.showLoading(elementId);
        const data = await window.EVPlatformAPI.getDashboardData();
        
        // Update UI с данните
        updateEnergyUI(data, elementId);
        
    } catch (error) {
        window.EVPlatformAPI.showError(elementId, error.message);
    }
};

window.startChargingSession = async function(stationId, connectorId, rfidTag) {
    try {
        const result = await window.EVPlatformAPI.startCharging(stationId, connectorId, rfidTag);
        
        // Show success message
        showNotification('Charging started successfully!', 'success');
        
        // Refresh station status
        loadStationData();
        
        return result;
    } catch (error) {
        showNotification(`Failed to start charging: ${error.message}`, 'error');
        throw error;
    }
};

function updateEnergyUI(data, containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.innerHTML = `
        <div class="row">
            <div class="col-md-3">
                <div class="card bg-primary text-white">
                    <div class="card-body">
                        <h5 class="card-title">Solar Generation</h5>
                        <h3>${window.EVPlatformAPI.formatPower(data.current.total_generation_watts)}</h3>
                        <small>Real-time output</small>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card bg-success text-white">
                    <div class="card-body">
                        <h5 class="card-title">Battery Level</h5>
                        <h3>${window.EVPlatformAPI.formatPercentage(data.current.average_battery_soc)}</h3>
                        <small>Average SOC</small>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card bg-info text-white">
                    <div class="card-body">
                        <h5 class="card-title">Active Inverters</h5>
                        <h3>${data.current.active_inverters}/2</h3>
                        <small>Devices online</small>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card bg-warning text-white">
                    <div class="card-body">
                        <h5 class="card-title">Today's Energy</h5>
                        <h3>${data.daily_stats.total_energy_kwh} kWh</h3>
                        <small>Total generated</small>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="row mt-4">
            <div class="col-12">
                <h5>Inverter Details</h5>
                <div class="row">
                    ${data.current.readings.map(inverter => `
                        <div class="col-md-6 mb-3">
                            <div class="card">
                                <div class="card-body">
                                    <h6 class="card-title">${inverter.device_sn}</h6>
                                    <p class="card-text">
                                        <strong>Generation:</strong> ${window.EVPlatformAPI.formatPower(inverter.generation_power)}<br>
                                        <strong>Battery:</strong> ${window.EVPlatformAPI.formatPercentage(inverter.battery_soc)}<br>
                                        <strong>Status:</strong> ${inverter.connect_status === 1 ? 'Online' : 'Offline'}<br>
                                        <small>Last update: ${window.EVPlatformAPI.formatTime(inverter.timestamp)}</small>
                                    </p>
                                </div>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        </div>
    `;
}

function showNotification(message, type = 'info') {
    // Ensure notification container exists
    let container = document.getElementById('notification-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'notification-container';
        container.style.cssText = 'position: fixed; top: 20px; right: 20px; z-index: 9999; display: flex; flex-direction: column; gap: 10px; pointer-events: none;';
        document.body.appendChild(container);
    }

    // Create notification element
    const notification = document.createElement('div');
    notification.className = `alert alert-${type} alert-dismissible fade show shadow`;
    notification.style.cssText = 'min-width: 300px; pointer-events: auto; margin-bottom: 0;';
    notification.innerHTML = `
        <div class="d-flex align-items-center justify-content-between">
            <span>${message}</span>
            <button type="button" class="btn-close" data-bs-dismiss="alert" style="position: relative; padding: 0.5rem;"></button>
        </div>
    `;
    
    // Add to container
    container.appendChild(notification);
    
    // Auto remove after 5 seconds
    setTimeout(() => {
        // Check if still in DOM
        if (notification.parentNode) {
            // Fade out effect manually if bootstrap js doesn't handle it well or trigger remove
            notification.classList.remove('show');
            setTimeout(() => {
                if (notification.parentNode) notification.parentNode.removeChild(notification);
                // Remove container if empty
                if (container.children.length === 0 && container.parentNode) {
                   // container.parentNode.removeChild(container); // distinct usage might prefer keeping it
                }
            }, 150);
        }
    }, 5000);
}
