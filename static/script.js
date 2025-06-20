let selectedTickers = [];
let currentPeriod = '1d';

window.onload = async function () {
    const response = await fetch("/get_saved_tickers");
    selectedTickers = await response.json();
    updateTickerDisplay();
    fetchData();
};

function addTicker() {
    const input = document.getElementById("tickerInput");
    const ticker = input.value.trim().toUpperCase();
    if (ticker && !selectedTickers.includes(ticker)) {
        selectedTickers.push(ticker);
        input.value = "";
        updateTickerDisplay();
        fetchData();
        saveTickerToDB(ticker);
    }
}

function removeTicker(ticker) {
    selectedTickers = selectedTickers.filter(t => t !== ticker);
    updateTickerDisplay();
    fetchData();
    removeTickerFromDB(ticker);
}

function updateTickerDisplay() {
    const container = document.getElementById("selected-stocks");
    container.innerHTML = "";
    selectedTickers.forEach(ticker => {
        const span = document.createElement("span");
        span.textContent = ticker;
        const btn = document.createElement("button");
        btn.textContent = "x";
        btn.onclick = () => removeTicker(ticker);
        span.appendChild(btn);
        container.appendChild(span);
    });
}

function selectPeriod(button, period) {
    currentPeriod = period;
    document.querySelectorAll(".time-buttons button").forEach(btn => btn.classList.remove("active"));
    button.classList.add("active");
    fetchData();
}

async function fetchData() {
    if (selectedTickers.length === 0) return;

    const response = await fetch("/get_stock_data", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbols: selectedTickers, period: currentPeriod })
    });

    const data = await response.json();
    drawBarChart(data);
}

function drawBarChart(data) {
    const ctx = document.getElementById("stockChart").getContext("2d");

    const labels = Object.keys(data);
    const values = labels.map(label => data[label]);

    const chartData = {
        labels,
        datasets: [{
            label: `Change (${currentPeriod})`,
            data: values,
            backgroundColor: 'rgba(54, 162, 235, 0.6)',
            borderColor: 'rgba(54, 162, 235, 1)',
            borderWidth: 1
        }]
    };

    if (window.barChart) window.barChart.destroy();

    window.barChart = new Chart(ctx, {
        type: 'bar',
        data: chartData,
        options: {
            responsive: true,
            scales: {
                y: {
                    beginAtZero: false,
                    title: {
                        display: true,
                        text: 'Change (%)'
                    }
                }
            }
        }
    });
}

async function saveTickerToDB(ticker) {
    await fetch("/save_ticker", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: ticker })
    });
}

async function removeTickerFromDB(ticker) {
    await fetch("/remove_ticker", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: ticker })
    });
}
