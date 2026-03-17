/**
 * Weather API Client
 * Extends EVPlatformAPI to handle weather-related endpoints and UI.
 */

// Add weather methods to the main API class prototype
if (typeof EVPlatformAPI !== 'undefined') {
    EVPlatformAPI.prototype.getCurrentWeather = async function() {
        return this.request('/weather/current/');
    };
    
    EVPlatformAPI.prototype.fetchWeather = async function() {
        return this.request('/weather/fetch/', {
            method: 'POST'
        });
    };
}

/**
 * Initialize weather widget in dashboard
 */
async function loadWeatherWidget(containerId = 'weather-widget') {
    const container = document.getElementById(containerId);
    if (!container) return;

    // Show loading state
    container.innerHTML = `
        <div class="col-12 text-center py-4">
            <div class="spinner-border text-primary" role="status"></div>
            <p class="mt-2 text-muted">Loading weather data...</p>
        </div>
    `;

    try {
        const weather = await window.EVPlatformAPI.getCurrentWeather();
        renderWeatherCards(weather, container);
    } catch (error) {
        console.error('Weather load failed:', error);
        container.innerHTML = `
            <div class="col-12">
                <div class="alert alert-warning">
                    <i class="fas fa-cloud-rain"></i> Unable to load weather data
                </div>
            </div>
        `;
    }
}

/**
 * Render weather information cards
 */
function renderWeatherCards(data, container) {
    if (!data) return;

    // Format date and time
    const now = new Date();
    const dateOptions = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
    const dateStr = now.toLocaleDateString('en-US', dateOptions);
    const timeStr = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });

    // Determine icon based on conditions (simple mapping)
    let iconClass = 'fa-sun';
    let bgClass = 'border-left-warning';
    
    if (data.precipitation_mm > 0.5) {
        iconClass = 'fa-cloud-rain';
        bgClass = 'border-left-info';
    } else if (data.cloud_cover > 60) {
        iconClass = 'fa-cloud';
        bgClass = 'border-left-secondary';
    } else if (data.cloud_cover > 20) {
        iconClass = 'fa-cloud-sun';
        bgClass = 'border-left-primary';
    }

    const html = `
        <!-- Location & Time -->
        <div class="col-xl-3 col-md-6 mb-4">
            <div class="card border-left-primary shadow h-100 py-2">
                <div class="card-body">
                    <div class="row no-gutters align-items-center">
                        <div class="col mr-2">
                            <div class="text-xs font-weight-bold text-primary text-uppercase mb-1">
                                Sofia, Bulgaria</div>
                            <div class="h5 mb-0 font-weight-bold text-gray-800">${timeStr}</div>
                            <div class="text-xs text-muted mt-1">${dateStr}</div>
                        </div>
                        <div class="col-auto">
                            <i class="fas fa-map-marker-alt fa-2x text-gray-300"></i>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Temperature & Conditions -->
        <div class="col-xl-3 col-md-6 mb-4">
            <div class="card ${bgClass} shadow h-100 py-2">
                <div class="card-body">
                    <div class="row no-gutters align-items-center">
                        <div class="col mr-2">
                            <div class="text-xs font-weight-bold text-warning text-uppercase mb-1">
                                Conditions</div>
                            <div class="h5 mb-0 font-weight-bold text-gray-800">${data.temp_c}°C</div>
                            <div class="text-xs text-muted mt-1">
                                Clouds: ${data.cloud_cover}% | ${data.cloud_cover > 50 ? 'Cloudy' : 'Sunny'}
                            </div>
                        </div>
                        <div class="col-auto">
                            <i class="fas ${iconClass} fa-2x text-gray-300"></i>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Wind & Pressure -->
        <div class="col-xl-3 col-md-6 mb-4">
            <div class="card border-left-success shadow h-100 py-2">
                <div class="card-body">
                    <div class="row no-gutters align-items-center">
                        <div class="col mr-2">
                            <div class="text-xs font-weight-bold text-success text-uppercase mb-1">
                                Wind & Pressure</div>
                            <div class="h5 mb-0 font-weight-bold text-gray-800">${data.wind_kph} km/h</div>
                            <div class="text-xs text-muted mt-1">
                                Pressure: ${data.pressure_hpa ? data.pressure_hpa + ' hPa' : 'N/A'}
                            </div>
                        </div>
                        <div class="col-auto">
                            <i class="fas fa-wind fa-2x text-gray-300"></i>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- PV Potential (Irradiance) -->
        <div class="col-xl-3 col-md-6 mb-4">
            <div class="card border-left-danger shadow h-100 py-2">
                <div class="card-body">
                    <div class="row no-gutters align-items-center">
                        <div class="col mr-2">
                            <div class="text-xs font-weight-bold text-danger text-uppercase mb-1">
                                Solar Irradiance</div>
                            <div class="h5 mb-0 font-weight-bold text-gray-800">${data.irradiance_wm2 || 0} W/m²</div>
                            <div class="text-xs text-muted mt-1">PV Potential</div>
                        </div>
                        <div class="col-auto">
                            <i class="fas fa-sun fa-2x text-gray-300"></i>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;

    container.innerHTML = html;
}
