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

function updateTickerDisplay() {
    const container = document.getElementById("selected-stocks");
    container.innerHTML = "";
    selectedTickers.forEach(ticker => {
        const span = document.createElement("span");
        span.textContent = ticker;
        span.style.cursor = "pointer";
        span.onclick = () => showSummary(ticker);

        const btn = document.createElement("button");
        btn.textContent = "x";
        btn.onclick = (e) => {
            e.stopPropagation();
            removeTicker(ticker);
        };
        span.appendChild(btn);
        container.appendChild(span);
    });
}

async function showSummary(ticker) {
    const res = await fetch("/get_summary", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: ticker })
    });

    const data = await res.json();
    if (data.error) {
        alert("Could not fetch summary.");
        return;
    }

    document.getElementById("modalTitle").innerText = `${ticker} - ${data.name}`;
    document.getElementById("modalIndustry").innerText = `Industry: ${data.industry}`;
    document.getElementById("modalBody").innerText =
        `${data.summary}\n\nAnalyst Recommendation: ${data.recommendation}`;

    drawStockStatsCharts(data);
    document.getElementById("summaryModal").style.display = "flex";
}

let currentChart;
let chartDataGlobal = {};

function drawChart(type) {
  const ctx = document.getElementById("summaryChart").getContext("2d");
  const data = chartDataGlobal;
  const labels = Object.keys(data.revenue).map(date => new Date(date).getFullYear());
  let datasetLabel = "", values = [], chartType = "bar", color = "#4e79a7", yLabel = "USD";

  switch (type) {
    case "revenue":
      datasetLabel = "Revenue";
      values = Object.values(data.revenue).map(v => v / 1e9);
      yLabel = "Billions USD";
      break;
    case "eps":
      datasetLabel = "Earnings Per Share";
      values = Object.values(data.eps);
      color = "#9c27b0";
      break;
    case "dividends":
      datasetLabel = "Dividend per Share";
      values = Object.values(data.dividends);
      color = "#f28e2b";
      break;
    case "gross_margin":
      datasetLabel = "Gross Margin (%)";
      values = Object.values(data.gross_margin);
      chartType = "line";
      color = "#e15759";
      yLabel = "%";
      break;
  }

  // Destroy previous chart
  if (currentChart) currentChart.destroy();

  currentChart = new Chart(ctx, {
    type: chartType,
    data: {
      labels,
      datasets: [{
        label: datasetLabel,
        data: values,
        backgroundColor: color,
        borderColor: color,
        fill: chartType !== "line",
        tension: 0.2
      }]
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        y: {
          beginAtZero: true,
          title: { display: true, text: yLabel }
        }
      }
    }
  });
}

function drawStockStatsCharts(data) {
  chartDataGlobal = data; // Save for switching
  drawChart("revenue");   // Initial chart

  // Handle button clicks
  document.querySelectorAll(".chart-btn").forEach(btn => {
    btn.classList.remove("active");
    if (btn.dataset.chart === "revenue") btn.classList.add("active"); // default

    btn.onclick = () => {
      document.querySelectorAll(".chart-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      drawChart(btn.dataset.chart);
    };
  });
}


function closeModal() {
    document.getElementById('summaryModal').style.display = 'none';
}