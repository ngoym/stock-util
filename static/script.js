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

function selectPeriod(button, period) {
    currentPeriod = period;
    document.querySelectorAll(".time-buttons button").forEach(btn => btn.classList.remove("active"));
    button.classList.add("active");
    fetchData();
}

async function fetchData() {
    if (selectedTickers.length === 0) {
        // Clear all charts if no tickers are selected
        document.getElementById('stockChart').style.display = 'block';
        if (window.barChart) window.barChart.destroy();

        document.getElementById('priceTargetChart').style.display = 'none';
        document.getElementById('priceTargetMessage').style.display = 'none';
        if (window.priceTargetChart) window.priceTargetChart.destroy();

        document.getElementById('epsGrowthChart').style.display = 'none';
        document.getElementById('epsGrowthMessage').style.display = 'none';
        if (window.epsGrowthChart) window.epsGrowthChart.destroy();
        return;
    }

    // Fetch historical price change data
    const response = await fetch("/get_stock_data", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbols: selectedTickers, period: currentPeriod })
    });
    const data = await response.json();
    drawBarChart(data);

    // Fetch analysis data for the new charts
    const analysisResponse = await fetch("/get_analysis_data", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbols: selectedTickers })
    });
    const analysisData = await analysisResponse.json();
    console.log(analysisData);
    drawPriceTargetChart(analysisData.price_target_upside, analysisData.sectors);
    drawRevenueGrowthChart(analysisData.revenue_growth_next_year, analysisData.sectors);
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
            },
            plugins: {
                title: {
                    display: true,
                    text: 'Stock Price Performance'
                }
            }
        }
    });
}

function getColorsForSymbols(symbols, sectors) {
    return symbols.map(sym => {
        const sector = sectors[sym] || "Other";
        return sectorColors[sector] || sectorColors["Other"];
    });
}

function drawPriceTargetChart(data, sectors) {
    const canvas = document.getElementById("priceTargetChart");
    const ctx = canvas.getContext("2d");

    const entries = Object.entries(data)
        .filter(([_, v]) => v !== null);

    // Safely destroy previous chart
    if (window.priceTargetChart && typeof window.priceTargetChart.destroy === "function") {
        window.priceTargetChart.destroy();
    }

    if (entries.length === 0) {
        canvas.style.display = "none";
        return;
    }

    // --- SECTOR COLORS ---
    const sectorColors = {
        "Technology": "#4e79a7",
        "Semiconductors": "#f28e2b",
        "Communication Services": "#59a14f",
        "Consumer Cyclical": "#e15759",
        "Consumer Defensive": "#76b7b2",
        "Financial Services": "#edc949",
        "Healthcare": "#af7aa1",
        "Energy": "#ff9da7",
        "Industrials": "#9c755f",
        "Real Estate": "#bab0ab",
        "Other": "#cfcfcf"
    };

    // --- GROUP BY SECTOR ---
    const grouped = {};
    for (let [symbol, value] of entries) {
        const sector = sectors[symbol] || "Other";
        if (!grouped[sector]) grouped[sector] = [];
        grouped[sector].push({ symbol, value });
    }

    // --- SORT WITHIN EACH SECTOR ---
    for (let sector in grouped) {
        grouped[sector].sort((a, b) => b.value - a.value);
        // ↑ Descending by upside
        // Change to: (a.value - b.value) for ascending
    }

    // Flatten into chart arrays
    const labels = [];
    const values = [];
    const colors = [];
    const borderColors = [];
    const sectorBands = [];

    let index = 0;
    for (let [sector, stocks] of Object.entries(grouped)) {
        sectorBands.push({
            sector,
            start: index,
            end: index + stocks.length - 1
        });

        const color = sectorColors[sector] || sectorColors["Other"];

        stocks.forEach(item => {
            labels.push(item.symbol);
            values.push(item.value);
            colors.push(color);
            borderColors.push(color);
            index++;
        });
    }

    window.priceTargetChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                label: "Price Target Upside (%)",
                data: values,
                backgroundColor: colors,
                borderColor: borderColors,
                borderWidth: 1
            }]
        },
        options: {
            plugins: {
                title: { display: true, text: "Price Target Upside (Grouped by Sector)" },
                annotation: {
                    annotations: sectorBands.map(band => ({
                        type: "box",
                        xMin: band.start - 0.5,
                        xMax: band.end + 0.5,
                        backgroundColor: "rgba(0,0,0,0.04)",
                        label: {
                            enabled: true,
                            content: band.sector,
                            position: "start",
                            yAdjust: -20
                        }
                    }))
                }
            },
            scales: {
                y: { beginAtZero: false, title: { display: true, text: "Upside (%)" } }
            }
        }
    });
}

function drawRevenueGrowthChart(data, sectors) {
    const canvas = document.getElementById("revenueGrowthChart");
    const messageEl = document.getElementById("revenueGrowthMessage");
    const ctx = canvas.getContext("2d");

    // Filter out null values
    const entries = Object.entries(data).filter(([_, v]) => v !== null);

    // Safely destroy previous chart
    if (window.epsGrowthChart && typeof window.epsGrowthChart.destroy === "function") {
        window.epsGrowthChart.destroy();
    }

    if (entries.length === 0) {
        canvas.style.display = 'none';
        messageEl.style.display = 'block';
        messageEl.textContent = 'Revenue growth estimate data is not available for the selected tickers.';
        return;
    }

    //messageEl.style.display = "none";
    canvas.style.display = "block";

    // --- SECTOR COLORS ---
    const sectorColors = {
        "Technology": "#4e79a7",
        "Semiconductors": "#f28e2b",
        "Communication Services": "#59a14f",
        "Consumer Cyclical": "#e15759",
        "Consumer Defensive": "#76b7b2",
        "Financial Services": "#edc949",
        "Healthcare": "#af7aa1",
        "Energy": "#ff9da7",
        "Industrials": "#9c755f",
        "Real Estate": "#bab0ab",
        "Other": "#cfcfcf"
    };

    // --- GROUP BY SECTOR ---
    const grouped = {};
    for (let [symbol, value] of entries) {
        const sector = sectors[symbol] || "Other";
        if (!grouped[sector]) grouped[sector] = [];
        grouped[sector].push({ symbol, value });
    }

    // --- SORT WITHIN EACH SECTOR (DESC) ---
    for (let sector in grouped) {
        grouped[sector].sort((a, b) => b.value - a.value);
    }

    // Flatten for chart
    const labels = [];
    const values = [];
    const colors = [];
    const borders = [];
    const sectorBands = [];

    let index = 0;
    for (let [sector, stocks] of Object.entries(grouped)) {
        const baseColor = sectorColors[sector] || sectorColors["Other"];

        sectorBands.push({
            sector,
            start: index,
            end: index + stocks.length - 1
        });

        stocks.forEach(item => {
            labels.push(item.symbol);
            values.push(item.value);
            colors.push(baseColor);
            borders.push(baseColor);
            index++;
        });
    }

    window.epsGrowthChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                label: "EPS Growth + Revenue Growth Next Year (%)",
                data: values,
                backgroundColor: colors,
                borderColor: borders,
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            scales: {
                y: {
                    beginAtZero: false,
                    title: { display: true, text: 'Growth (%)' }
                }
            },
            plugins: {
                title: {
                    display: true,
                    text: "Revenue + EPS Growth Next Year (Grouped by Sector)"
                },
                annotation: {
                    annotations: sectorBands.map(band => ({
                        type: "box",
                        xMin: band.start - 0.5,
                        xMax: band.end + 0.5,
                        backgroundColor: "rgba(0,0,0,0.04)",
                        label: {
                            enabled: true,
                            content: band.sector,
                            position: "start",
                            yAdjust: -20
                        }
                    }))
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

