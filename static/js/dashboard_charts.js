document.addEventListener('DOMContentLoaded', function() {
    const ctx = document.getElementById('energyConsumptionChart');
    if (!ctx) return;

    const timeRangeSelect = document.getElementById('timeRangeSelect');
    const specificDateInput = document.getElementById('specificDateInput');

    if(timeRangeSelect) {
        timeRangeSelect.addEventListener('change', function() {
            if(this.value === 'specificDay') {
                specificDateInput.style.display = 'block';
                if (specificDateInput.value) {
                    fetchChartData();
                }
            } else {
                specificDateInput.style.display = 'none';
                fetchChartData();
            }
        });
    }

    if(specificDateInput) {
        specificDateInput.addEventListener('change', fetchChartData);
    }

    // Create export buttons dynamically, or hook onto existing ones
    // We will append buttons next to the selector
    const chartHeader = document.querySelector('.card-header .dropdown.no-arrow').parentNode;
    
    // Add Export Buttons
    const btnContainer = document.createElement('div');
    btnContainer.className = 'btn-group ml-2';
    btnContainer.innerHTML = `
        <button class="btn btn-sm btn-outline-primary" id="exportCsvBtn" title="Export CSV">
            <i class="fas fa-file-csv"></i> CSV
        </button>
        <button class="btn btn-sm btn-outline-secondary" id="exportImgBtn" title="Export Image">
            <i class="fas fa-image"></i> Image
        </button>
    `;
    chartHeader.appendChild(btnContainer);

    const customCanvasBackgroundColor = {
        id: 'customCanvasBackgroundColor',
        beforeDraw: (chart, args, options) => {
            const {ctx} = chart;
            ctx.save();
            ctx.globalCompositeOperation = 'destination-over';
            ctx.fillStyle = options.color || '#ffffff';
            ctx.fillRect(0, 0, chart.width, chart.height);
            ctx.restore();
        }
    };

    let energyChart = new Chart(ctx, {
        type: 'line',
        plugins: [customCanvasBackgroundColor],
        data: {
            labels: [],
            datasets: [
                {
                    label: 'PV Generation (kW)',
                    data: [],
                    borderColor: '#1cc88a', // Green
                    backgroundColor: 'rgba(28, 200, 138, 0.05)',
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    fill: true,
                    tension: 0.3
                },
                {
                    label: 'Building Load (kW)',
                    data: [],
                    borderColor: '#e74a3b', // Red
                    backgroundColor: 'rgba(231, 74, 59, 0.05)',
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    fill: true,
                    tension: 0.3
                },
                {
                    label: 'Battery SOC (%)',
                    data: [],
                    borderColor: '#f6c23e', // Yellow
                    backgroundColor: 'transparent',
                    borderDash: [5, 5],
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    fill: false,
                    tension: 0.3,
                    yAxisID: 'y-soc'
                }
            ]
        },
        options: {
            maintainAspectRatio: false,
            responsive: true,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            scales: {
                x: {
                    grid: { display: false, drawBorder: false },
                    ticks: { maxTicksLimit: 10 }
                },
                y: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    title: { display: true, text: 'Power (kW)' },
                    grid: { color: 'rgb(234, 236, 244)', drawBorder: false }
                },
                'y-soc': {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    title: { display: true, text: 'SOC (%)' },
                    min: 0,
                    max: 100,
                    grid: { drawOnChartArea: false }
                }
            },
            plugins: {
                legend: { display: true, position: 'top' },
                tooltip: {
                    backgroundColor: 'rgb(255,255,255)',
                    bodyColor: '#858796',
                    titleColor: '#6e707e',
                    borderColor: '#dddfeb',
                    borderWidth: 1,
                    padding: 15
                }
            }
        }
    });

    function fetchChartData() {
        let range = '24h';
        let dateQuery = '';
        if (timeRangeSelect) {
            range = timeRangeSelect.value;
            if (range === 'specificDay' && specificDateInput && specificDateInput.value) {
                dateQuery = `&date=${specificDateInput.value}`;
            }
        }
        fetch(`/api/energy/chart-data/?range=${range}${dateQuery}`)
            .then(res => res.json())
            .then(data => {
                if(data.error) {
                    console.error("Error fetching chart data:", data.error);
                    return;
                }
                energyChart.data.labels = data.labels;
                energyChart.data.datasets[0].data = data.datasets.pv_generation;
                energyChart.data.datasets[1].data = data.datasets.building_load;
                energyChart.data.datasets[2].data = data.datasets.battery_soc;
                energyChart.update();
            })
            .catch(err => console.error("Error drawing chart:", err));
    }

    // Initial fetch
    fetchChartData();

    // Auto-refresh every 30 seconds
    setInterval(fetchChartData, 30000);

    document.getElementById('exportCsvBtn').addEventListener('click', function(e) {
        e.preventDefault();
        let range = '24h';
        let dateQuery = '';
        if (timeRangeSelect) {
            range = timeRangeSelect.value;
            if (range === 'specificDay' && specificDateInput && specificDateInput.value) {
                dateQuery = `&date=${specificDateInput.value}`;
            }
        }
        window.location.href = `/api/energy/chart-data/export/?range=${range}${dateQuery}`;
    });

    document.getElementById('exportImgBtn').addEventListener('click', function(e) {
        e.preventDefault();
        const imgData = energyChart.toBase64Image('image/jpeg', 1.0);
        const link = document.createElement('a');
        link.href = imgData;
        link.download = `energy_chart_${new Date().toISOString().slice(0,10)}.jpeg`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    });
});
