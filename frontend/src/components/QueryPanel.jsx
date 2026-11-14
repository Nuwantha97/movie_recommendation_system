import AsyncCombobox from "./AsyncCombobox";
import ChipList from "./ChipList";
import MoviePoster from "./MoviePoster";
import { searchLanguages, searchMovies, searchTags } from "../api";
import { GENRES, TAG_LABELS, languageName } from "../constants";
import { canSubmit, dateRangeInvalid, getPlotTextError } from "../query";

const tagKey = (t) => `${t.tag_type}:${t.name}`;
const tagName = (t) => (t.tag_type === "spoken_languages" ? languageName(t.name) : t.name);
const tagLabel = (t) => `${TAG_LABELS[t.tag_type] ?? t.tag_type}: ${tagName(t)}`;
const movieYear = (m) => m.year ?? m.release_year ?? "";

function toggle(list, value) {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

function ToggleGroup({ legend, options, selected, onToggle }) {
  return (
    <fieldset className="field">
      <legend>{legend}</legend>
      <div className="toggles">
        {options.map((o) => {
          const value = typeof o === "string" ? o : o.value;
          const label = typeof o === "string" ? o : o.label;
          const on = selected.includes(value);
          return (
            <button
              key={value}
              type="button"
              className={on ? "toggle on" : "toggle"}
              aria-pressed={on}
              onClick={() => onToggle(value)}
            >
              {label}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

export default function QueryPanel({
  query,
  setQuery,
  onSubmit,
  loading,
  backendErrors = {},
  onClearBackendError,
}) {
  const set = (patch) => setQuery((q) => ({ ...q, ...patch }));

  const plotText = query.plotText || "";
  const charCount = plotText.length;
  const collapsedPlot = plotText.trim().replace(/\s+/g, " ");
  const inlinePlotError = getPlotTextError(plotText);
  const backendPlotError = backendErrors.plot_text;

  const hasPlotQuery = query.movies.length > 0 || collapsedPlot.length > 0;
  const noPlotQuery = !hasPlotQuery;
  const tagPct = Math.round(query.tagWeight * 100);
  const badRange = dateRangeInvalid(query);

  const activeFiltersCount =
    (query.languages?.length || 0) +
    (query.genres?.length || 0) +
    (query.dateFrom ? 1 : 0) +
    (query.dateTo ? 1 : 0);

  return (
    <form
      className="panel"
      onSubmit={(e) => {
        e.preventDefault();
        if (canSubmit(query) && !loading) onSubmit();
      }}
    >
      <div className="field">
        <label htmlFor="movie-search-input">Movies you like</label>
        <AsyncCombobox
          id="movie-search-input"
          label="Search movies"
          placeholder="Search by title"
          minChars={3}
          fetchOptions={searchMovies}
          onSelect={(m) => set({ movies: [...query.movies, m] })}
          getKey={(m) => String(m.id)}
          isSelected={(m) => query.movies.some((x) => x.id === m.id)}
          renderOption={(m) => (
            <div className="combo-option-content">
              <MoviePoster
                path={m.poster_path}
                title={m.title}
                size="w92"
                className="thumb"
                width={40}
                height={60}
              />
              <div className="opt-text">
                <span className="opt-title">{m.title}</span>
                {movieYear(m) ? <span className="opt-meta">({movieYear(m)})</span> : null}
              </div>
            </div>
          )}
        />
        <ChipList
          items={query.movies}
          getKey={(m) => String(m.id)}
          getLabel={(m) => (movieYear(m) ? `${m.title} (${movieYear(m)})` : m.title)}
          renderLabel={(m) => (
            <>
              <MoviePoster
                path={m.poster_path}
                title={m.title}
                size="w92"
                className="chip-poster"
                width={24}
                height={36}
              />
              <span className="chip-meta">
                <span className="chip-title">{m.title}</span>
                {movieYear(m) ? <span className="chip-year">({movieYear(m)})</span> : null}
              </span>
            </>
          )}
          onRemove={(m) => set({ movies: query.movies.filter((x) => x.id !== m.id) })}
        />
      </div>

      <div className="field">
        <div className="field-header">
          <label htmlFor="plot-text">Describe the plot you want (optional)</label>
          <span className={`char-counter ${charCount > 1000 ? "error" : ""}`}>
            {charCount}/1000
          </span>
        </div>
        <textarea
          id="plot-text"
          rows={3}
          placeholder="e.g. A retired detective is drawn into one last case when an enigmatic code surfaces..."
          value={plotText}
          onChange={(e) => {
            set({ plotText: e.target.value });
            if (backendPlotError && onClearBackendError) {
              onClearBackendError("plot_text");
            }
          }}
        />
        {backendPlotError ? (
          <p className="note error">{backendPlotError}</p>
        ) : inlinePlotError ? (
          <p className="note error">{inlinePlotError}</p>
        ) : (
          <p className="note">Minimum 30 characters when specified.</p>
        )}
      </div>

      <div className="field">
        <label htmlFor="tag-search-input">People, keywords and more</label>
        <AsyncCombobox
          id="tag-search-input"
          label="Search tags"
          placeholder="Director, cast, keyword, country"
          fetchOptions={searchTags}
          onSelect={(t) => set({ tags: [...query.tags, t] })}
          getKey={tagKey}
          isSelected={(t) => query.tags.some((x) => tagKey(x) === tagKey(t))}
          renderOption={(t) => (
            <>
              <span className="opt-title">{tagName(t)}</span>
              <span className="opt-badge">{TAG_LABELS[t.tag_type] ?? t.tag_type}</span>
            </>
          )}
        />
        <ChipList
          items={query.tags}
          getKey={tagKey}
          getLabel={tagLabel}
          onRemove={(t) => set({ tags: query.tags.filter((x) => tagKey(x) !== tagKey(t)) })}
        />
      </div>

      <div className="divider" />

      {/* Collapsible Filters Section for Tablet & Mobile (stays expanded on Desktop) */}
      <details className="filters-details">
        <summary className="filters-summary">
          <div className="filters-summary-left">
            <span>Filters</span>
            {activeFiltersCount > 0 && (
              <span className="filters-badge" aria-label={`${activeFiltersCount} filters active`}>
                {activeFiltersCount}
              </span>
            )}
          </div>
          <span className="note">Language, genres, dates</span>
        </summary>
        <div className="filters-content">
          <p className="note">
            Language, genre and date are hard filters. Tags only nudge similarity, so they do not
            guarantee a person's films appear.
          </p>

          <div className="field">
            <label htmlFor="lang-search-input">Original language</label>
            <AsyncCombobox
              id="lang-search-input"
              label="Search original language"
              placeholder="Search by name or code, e.g. tamil or ta"
              fetchOptions={searchLanguages}
              onSelect={(l) => set({ languages: [...query.languages, l.name] })}
              getKey={(l) => l.name}
              isSelected={(l) => query.languages.includes(l.name)}
              renderOption={(l) => (
                <>
                  <span className="opt-title">{languageName(l.name)}</span>
                  <span className="opt-meta">{l.name}</span>
                </>
              )}
            />
            <ChipList
              items={query.languages}
              getKey={(code) => code}
              getLabel={(code) => `${languageName(code)} (${code})`}
              onRemove={(code) => set({ languages: query.languages.filter((c) => c !== code) })}
            />
          </div>

          <ToggleGroup
            legend="Genres (any of)"
            options={GENRES}
            selected={query.genres}
            onToggle={(v) => set({ genres: toggle(query.genres, v) })}
          />

          <fieldset className="field">
            <legend>Release date</legend>
            <div className="dates">
              <label>
                <span>From</span>
                <input
                  type="date"
                  value={query.dateFrom}
                  onChange={(e) => set({ dateFrom: e.target.value })}
                />
              </label>
              <label>
                <span>To</span>
                <input
                  type="date"
                  value={query.dateTo}
                  onChange={(e) => set({ dateTo: e.target.value })}
                />
              </label>
            </div>
            {badRange ? (
              <p className="note error">The start date must be on or before the end date.</p>
            ) : (
              <p className="note">Movies with no release date are left out when you set a date.</p>
            )}
          </fieldset>
        </div>
      </details>

      <div className="divider" />

      <div className="field">
        <label htmlFor="weight">Match on</label>
        <input
          id="weight"
          type="range"
          min="0"
          max="1"
          step="0.05"
          value={noPlotQuery ? 1 : query.tagWeight}
          disabled={noPlotQuery}
          aria-label="Match on plot or tags"
          aria-valuemin="0"
          aria-valuemax="1"
          aria-valuenow={noPlotQuery ? 1 : query.tagWeight}
          aria-valuetext={
            noPlotQuery
              ? "Tags only"
              : `${tagPct}% tags, ${100 - tagPct}% plot`
          }
          onChange={(e) => set({ tagWeight: Number(e.target.value) })}
        />
        <div className="slider-labels" aria-hidden="true">
          <span>Plot</span>
          <span>Tags</span>
        </div>
        <p className="note">
          {noPlotQuery
            ? "Tags only. Pick at least one movie or describe a plot to compare plots."
            : `${tagPct}% tags, ${100 - tagPct}% plot`}
        </p>
      </div>

      <button className="primary" type="submit" disabled={!canSubmit(query) || loading}>
        {loading ? "Finding movies…" : "Find movies"}
      </button>
      {!canSubmit(query) && !badRange && !inlinePlotError && (
        <p className="note">Add at least one movie, tag, or plot description to start.</p>
      )}
    </form>
  );
}
