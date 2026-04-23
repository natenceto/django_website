import re

with open('renew_website/templates/deye/dashboard.html', 'r') as f:
    content = f.read()

new_js = """async function getChargingRecommendation() {
    const content = document.getElementById('charging-content');
    
    // Show loading
    content.innerHTML = '<div class="text-center py-4"><div class="spinner-border text-primary" role="status"></div><p class="mt-2 text-muted">Анализиране на системата...</p></div>';
    
    try {
        const data = await window.EVPlatformAPI.getChargingRecommendation();
        
        let sc1 = data.scenario_1_ev;
        let sc2 = data.scenario_2_ev;
        let p_mode = sc1.mode; // Algorithm selected mode
        
        content.innerHTML = `
            <div class="alert alert-info">
                <p class="mb-0"><i class="fas fa-info-circle"></i> <strong>Информация:</strong> ${data.context}</p>
            </div>
            
            <div class="row">
                <div class="col-md-6 mb-3">
                    <div class="card border-left-success h-100">
                        <div class="card-body py-2">
                            <h6 class="font-weight-bold text-success mb-1">Сценарий 1 (Един автомобил - 11kW)</h6>
                            <p class="small mb-1 text-gray-800">${sc1.advice}</p>
                            <p class="mb-0 small"><strong>Отпусната мощност:</strong> ${sc1.power_allowed} kW</p>
                        </div>
                    </div>
                </div>
                <div class="col-md-6 mb-3">
                    <div class="card border-left-primary h-100">
                        <div class="card-body py-2">
                            <h6 class="font-weight-bold text-primary mb-1">Сценарий 2 (Два автомобила - 22kW)</h6>
                            <p class="small mb-1 text-gray-800">${sc2.advice}</p>
                            <p class="mb-0 small"><strong>Отпусната мощност:</strong> ${sc2.power_allowed} kW</p>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="alert alert-secondary mt-2 mb-0">
                <i class="fas fa-microchip"></i> <strong>Препоръчан базов режим на инвертора:</strong> 
                <span class="badge badge-dark p-2">${p_mode}</span>
            </div>
        `;
        
    } catch (error) {
        content.innerHTML = `
            <div class="alert alert-danger">
                <i class="fas fa-exclamation-circle"></i> Грешка при получаването на препоръка от алгоритъма. API-то не отговори.
            </div>
        `;
        console.error('Charging recommendation error:', error);
    }
}"""

pattern = re.compile(r'async function getChargingRecommendation\(\)\s*\{.*?\}\n\nfunction startCharging\(\)', re.DOTALL)
if re.search(pattern, content):
    new_content = re.sub(pattern, new_js + "\n\nfunction startCharging()", content)
    with open('renew_website/templates/deye/dashboard.html', 'w') as f:
        f.write(new_content)
    print("Templete patched")
else:
    print("Could not patch template automatically")
