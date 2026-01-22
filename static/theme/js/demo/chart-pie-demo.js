// Wait until DOM is fully loaded
document.addEventListener("DOMContentLoaded", function() {

    // Set default font and color (modern Chart.js 3+ syntax)
    Chart.defaults.font.family = 'Nunito, -apple-system, system-ui, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';
    Chart.defaults.color = '#858796';

    // Get canvas context safely
    var ctx = document.getElementById("myPieChart");
    if (!ctx) {
        console.error("Canvas element with id 'myPieChart' not found.");
        return;
    }
    ctx = ctx.getContext("2d");

    // Create Pie/Doughnut Chart
    var myPieChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ["Direct", "Referral", "Social"],
            datasets: [{
                data: [55, 30, 15],
                backgroundColor: ['#4e73df', '#1cc88a', '#36b9cc'],
                hoverBackgroundColor: ['#2e59d9', '#17a673', '#2c9faf'],
                hoverBorderColor: "rgba(234, 236, 244, 1)",
            }],
        },
        options: {
            maintainAspectRatio: false,
            plugins: {
                tooltip: {
                    backgroundColor: "rgb(255,255,255)",
                    titleColor: "#858796",
                    bodyColor: "#858796",
                    borderColor: '#dddfeb',
                    borderWidth: 1,
                    padding: 15,
                    displayColors: false,
                    caretPadding: 10,
                },
                legend: {
                    display: false
                }
            },
            cutout: '80%', // replaces cutoutPercentage in Chart.js 3+
        },
    });

});