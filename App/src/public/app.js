"use strict";

const searchInput = document.querySelector("#series-search");
const searchBox = document.querySelector(".search-box");
const suggestions = document.querySelector("#suggestions");
const searchStatus = document.querySelector("#search-status");
const seriesGrid = document.querySelector("#series-grid");
const catalogStatus = document.querySelector("#catalog-status");
const selectedSeries = document.querySelector("#wybrany-serial");
const genreFilter = document.querySelector("#genre-filter");
const platformFilter = document.querySelector("#platform-filter");

let searchTimer;
let searchController;
let highlightedSuggestion = -1;
let catalogSort = "popular";

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}

function initials(title) {
  return title
    .replace(/[^\p{L}\p{N} ]/gu, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0])
    .join("")
    .toUpperCase() || "?";
}

function plural(count, one, few, many) {
  const lastTwo = count % 100;
  const last = count % 10;
  if (count === 1) return one;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return few;
  return many;
}

function yearText(series) {
  return series.years || (series.premiereYear ? String(series.premiereYear) : "Rok nieznany");
}

function seriesMeta(series) {
  const parts = [];
  if (series.seasons) parts.push(`${series.seasons} ${plural(series.seasons, "sezon", "sezony", "sezonów")}`);
  if (series.episodes) parts.push(`${series.episodes} odc.`);
  parts.push(yearText(series));
  return parts.join(" · ");
}

function renderCards(items) {
  if (!items.length) {
    seriesGrid.innerHTML = '<div class="empty-state">Nie znaleziono seriali dla wybranych filtrów.</div>';
    return;
  }

  seriesGrid.innerHTML = items.map((series, index) => {
    const title = escapeHtml(series.title);
    const platformCount = series.platforms.length;
    const platformText = `${platformCount} ${plural(platformCount, "platforma", "platformy", "platform")}`;
    const color = ["#1e2433", "#2e3445", "#3a4256", "#474f64", "#565e73"][index % 5];
    return `
      <a class="series-card" href="#serial/${encodeURIComponent(series.id)}" data-series-id="${escapeHtml(series.id)}">
        <span class="poster" style="--poster-color:${color}">
          <span class="poster-initials" aria-hidden="true">${escapeHtml(initials(series.title))}</span>
          <span class="poster-platforms">${platformText}</span>
        </span>
        <span class="card-copy">
          <strong>${title}</strong>
          <span class="card-meta">${escapeHtml(seriesMeta(series))}</span>
          <span class="card-link">Sprawdź dostępność →</span>
        </span>
      </a>`;
  }).join("");
}

async function loadCatalog() {
  const params = new URLSearchParams({ sort: catalogSort, limit: "12" });
  if (genreFilter.value) params.set("genre", genreFilter.value);
  if (platformFilter.value) params.set("platform", platformFilter.value);
  catalogStatus.textContent = "Wczytuję katalog…";

  try {
    const response = await fetch(`/api/series?${params}`);
    if (!response.ok) throw new Error(`Nie udało się pobrać katalogu (${response.status}).`);
    const data = await response.json();
    renderCards(data.items);
    catalogStatus.textContent = `${data.total} seriali w katalogu`;
  } catch (error) {
    catalogStatus.textContent = error.message || "Nie udało się wczytać katalogu.";
    seriesGrid.innerHTML = '<div class="empty-state">Odśwież stronę, aby spróbować ponownie.</div>';
  }
}

async function loadFilters() {
  try {
    const response = await fetch("/api/filters");
    if (!response.ok) throw new Error(`Nie udało się pobrać filtrów (${response.status}).`);
    const filters = await response.json();
    for (const genre of filters.genres) {
      genreFilter.add(new Option(genre, genre));
    }
    for (const platform of filters.platforms) {
      platformFilter.add(new Option(platform, platform));
    }
  } catch (error) {
    catalogStatus.textContent = error.message || "Nie udało się wczytać filtrów katalogu.";
  }
}

function closeSuggestions() {
  suggestions.hidden = true;
  suggestions.replaceChildren();
  searchInput.setAttribute("aria-expanded", "false");
  searchBox.classList.remove("has-suggestions");
  highlightedSuggestion = -1;
}

function showSuggestions(items) {
  highlightedSuggestion = -1;
  if (!items.length) {
    suggestions.innerHTML = '<div class="suggestions-empty">Nie znaleziono serialu. Sprawdź pisownię tytułu.</div>';
  } else {
    suggestions.innerHTML = items.map((series) => `
      <button class="suggestion" type="button" role="option" aria-selected="false" data-series-id="${escapeHtml(series.id)}">
        <span class="poster-mini" aria-hidden="true">${escapeHtml(initials(series.title))}</span>
        <span class="suggestion-copy">
          <strong>${escapeHtml(series.title)}</strong>
          <span class="suggestion-meta">${escapeHtml(series.originalTitle || seriesMeta(series))}</span>
        </span>
        <span class="suggestion-platforms">${series.platforms.length} ${plural(series.platforms.length, "platforma", "platformy", "platform")}</span>
      </button>`).join("");
  }
  suggestions.hidden = false;
  searchInput.setAttribute("aria-expanded", "true");
  searchBox.classList.add("has-suggestions");
}

async function searchSeries(query) {
  if (searchController) searchController.abort();
  searchController = new AbortController();
  searchStatus.textContent = "Szukam…";

  try {
    const params = new URLSearchParams({ q: query, sort: "popular", limit: "8" });
    const response = await fetch(`/api/series?${params}`, { signal: searchController.signal });
    if (!response.ok) throw new Error(`Wyszukiwanie nie powiodło się (${response.status}).`);
    const data = await response.json();
    showSuggestions(data.items);
    searchStatus.textContent = data.total
      ? `${data.total} ${plural(data.total, "wynik", "wyniki", "wyników")}`
      : "Brak wyników.";
  } catch (error) {
    if (error.name === "AbortError") return;
    closeSuggestions();
    searchStatus.textContent = error.message || "Nie udało się połączyć z katalogiem.";
  }
}

async function showSeries(id) {
  selectedSeries.hidden = false;
  selectedSeries.innerHTML = '<p class="catalog-status">Wczytuję informacje o serialu…</p>';
  selectedSeries.scrollIntoView({ behavior: "smooth", block: "start" });
  selectedSeries.dataset.seriesId = id;

  try {
    const response = await fetch(`/api/series/${encodeURIComponent(id)}`);
    if (!response.ok) {
      const message = response.status === 404 ? "Nie znaleziono serialu." : `Nie udało się pobrać informacji (${response.status}).`;
      throw new Error(message);
    }
    const series = await response.json();
    const availabilities = series.availabilities.map((availability) => {
      const audio = availability.polishAudio === null ? "brak danych" : availability.polishAudio ? "tak" : "nie";
      const subtitles = availability.polishSubtitles === null ? "brak danych" : availability.polishSubtitles ? "tak" : "nie";
      const link = availability.url && /^https:\/\//i.test(availability.url)
        ? `<a href="${escapeHtml(availability.url)}" target="_blank" rel="noopener noreferrer">Przejdź do platformy ↗</a>`
        : "";
      return `
        <article class="availability">
          <strong>${escapeHtml(availability.service)}</strong>
          <p>Polski dźwięk: ${audio}</p>
          <p>Polskie napisy: ${subtitles}</p>
          <p>Maks. jakość: ${escapeHtml(availability.maxQuality || "brak danych")}</p>
          ${link}
        </article>`;
    }).join("");

    selectedSeries.innerHTML = `
      <div class="detail-top">
        <div>
          <h2>${escapeHtml(series.title)}</h2>
          <p>${escapeHtml(series.originalTitle || "")}${series.originalTitle ? " · " : ""}${escapeHtml(seriesMeta(series))}</p>
        </div>
        <button class="detail-close" type="button" data-close-detail>Zamknij</button>
      </div>
      <section class="watch-controls" aria-label="Ustawienia oglądania">
        <label>Tempo oglądania
          <select id="watch-profile">
            <option value="binging">Binging — 4 odcinki dziennie</option>
            <option value="daily">Daily — 1 odcinek dziennie</option>
            <option value="weekly">Weekly — 1 odcinek tygodniowo</option>
            <option value="custom">Własny — odcinki tygodniowo</option>
          </select>
          <input id="episodes-per-week" type="number" min="1" max="70" value="2" aria-label="Liczba odcinków tygodniowo" hidden>
        </label>
      </section>
      <div id="comparison-status" class="detail-note"></div>
      <div id="plan-comparison" class="plan-comparison"></div>
      <div class="availability-list">${availabilities || '<p>Brak potwierdzonych informacji o dostępności.</p>'}</div>
      <p class="detail-note">Brak danych nie oznacza potwierdzonego braku. Dane cenowe pochodzą z Plany_Streamingowe.xlsx; data weryfikacji nie została podana w arkuszu.</p>`;
    await loadComparison(id);
  } catch (error) {
    selectedSeries.innerHTML = `<p role="alert">${escapeHtml(error.message || "Nie udało się wczytać serialu.")}</p>`;
  }
}

async function loadComparison(id) {
  const status = document.querySelector("#comparison-status");
  const container = document.querySelector("#plan-comparison");
  const profile = document.querySelector("#watch-profile")?.value || "binging";
  const episodesPerWeek = document.querySelector("#episodes-per-week")?.value;
  if (!status || !container) return;
  status.textContent = "Wyliczam koszt oglądania…";

  try {
    const params = new URLSearchParams({ profile });
    if (profile === "custom") params.set("episodesPerWeek", episodesPerWeek || "1");
    const response = await fetch(`/api/series/${encodeURIComponent(id)}/compare?${params}`);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.error || `Nie udało się wyliczyć kosztu (${response.status}).`);
    }
    const comparison = await response.json();
    status.textContent = `${comparison.episodes} odc. · ${comparison.scheduleUnit} · około ${comparison.watchingDays} dni oglądania`;

    if (!comparison.items.length) {
      container.innerHTML = '<div class="empty-state">Brak planów cenowych dla platform z potwierdzoną dostępnością.</div>';
      return;
    }

    container.innerHTML = comparison.items.map((item, index) => `
      <article class="plan-result ${index === 0 ? "is-best" : ""}">
        ${index === 0 ? '<span class="best-label">Najtańsza opcja</span>' : ""}
        <div class="plan-result-main">
          <strong>${escapeHtml(item.platform)} · ${escapeHtml(item.plan)}</strong>
          <span>${escapeHtml(item.quality)} · ${item.ads ? "z reklamami" : "bez reklam"} · ${item.screens} ${item.screens === 1 ? "ekran" : "ekrany"}</span>
        </div>
        <div class="plan-cost">
          <strong>${item.total.toLocaleString("pl-PL", { style: "currency", currency: "PLN" })}</strong>
          <span>${item.billing === "yearly"
            ? `${item.cycles} ${item.cycles === 1 ? "cykl roczny" : "cykle roczne"}`
            : `${item.cycles} ${item.cycles === 1 ? "miesiąc" : "miesiące"}`}</span>
        </div>
        ${item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">Przejdź do platformy ↗</a>` : ""}
      </article>`).join("");
  } catch (error) {
    status.textContent = "";
    container.innerHTML = `<p role="alert">${escapeHtml(error.message || "Nie udało się wyliczyć kosztu.")}</p>`;
  }
}

function routeFromHash() {
  const match = window.location.hash.match(/^#serial\/(.+)$/);
  if (match) {
    showSeries(decodeURIComponent(match[1]));
  } else {
    selectedSeries.hidden = true;
  }
}

searchInput.addEventListener("input", () => {
  const query = searchInput.value.trim();
  window.clearTimeout(searchTimer);
  searchStatus.textContent = "";
  if (!query) {
    closeSuggestions();
    return;
  }
  searchTimer = window.setTimeout(() => searchSeries(query), 180);
});

searchInput.addEventListener("keydown", (event) => {
  const options = Array.from(suggestions.querySelectorAll(".suggestion"));
  if (suggestions.hidden || !options.length) {
    if (event.key === "Escape") closeSuggestions();
    return;
  }

  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    const direction = event.key === "ArrowDown" ? 1 : -1;
    highlightedSuggestion = (highlightedSuggestion + direction + options.length) % options.length;
    options.forEach((option, index) => option.setAttribute("aria-selected", String(index === highlightedSuggestion)));
  } else if (event.key === "Enter" && highlightedSuggestion >= 0) {
    event.preventDefault();
    options[highlightedSuggestion].click();
  } else if (event.key === "Escape") {
    closeSuggestions();
  }
});

document.addEventListener("click", (event) => {
  const option = event.target.closest("[data-series-id]");
  if (option) {
    event.preventDefault();
    searchInput.value = option.querySelector("strong")?.textContent || searchInput.value;
    closeSuggestions();
    window.location.hash = `serial/${encodeURIComponent(option.dataset.seriesId)}`;
    return;
  }

  if (event.target.closest("[data-close-detail]")) {
    window.location.hash = "";
    return;
  }

  if (!event.target.closest(".search-wrap")) closeSuggestions();
});

document.addEventListener("change", (event) => {
  if (event.target.id === "watch-profile" && selectedSeries.dataset.seriesId) {
    const customInput = document.querySelector("#episodes-per-week");
    if (customInput) customInput.hidden = event.target.value !== "custom";
    loadComparison(selectedSeries.dataset.seriesId);
  }
  if (event.target.id === "episodes-per-week" && selectedSeries.dataset.seriesId) {
    loadComparison(selectedSeries.dataset.seriesId);
  }
});

document.querySelectorAll("[data-sort]").forEach((button) => {
  button.addEventListener("click", () => {
    catalogSort = button.dataset.sort;
    document.querySelectorAll("[data-sort]").forEach((chip) => {
      const active = chip === button;
      chip.classList.toggle("is-active", active);
      chip.setAttribute("aria-pressed", String(active));
    });
    document.querySelector("#catalog-title").textContent = catalogSort === "new" ? "Najnowsze seriale" : "Popularne seriale";
    loadCatalog();
  });
});

genreFilter.addEventListener("change", loadCatalog);
platformFilter.addEventListener("change", loadCatalog);
window.addEventListener("hashchange", routeFromHash);

loadFilters();
loadCatalog();
routeFromHash();
