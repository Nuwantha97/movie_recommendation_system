import { searchMovies } from "../api";
import { canSubmit } from "../query";
import AsyncCombobox from "./AsyncCombobox";
import MoviePoster from "./MoviePoster";
import ChipList from "./ChipList";
import bgGoldenHorizon from "../assets/images/bg_golden_horizon.jpg";
import bgEmeraldRainforest from "../assets/images/bg_emerald_rainforest.jpg";

const FEATURED_SEEDS = [
  { id: 16254, title: "Inception", year: 2010, poster_path: "/xlaY2zyzMfkhk0HSC5VUwzoZPU1.jpg" },
  { id: 95519, title: "Interstellar", year: 2014, poster_path: "/yQvGrMoipbRoddT0ZR8tPoR7NfX.jpg" },
  { id: 117, title: "The Dark Knight", year: 2008, poster_path: "/qJ2tW6WMUDux911r6m7haRef0WH.jpg" },
  { id: 478, title: "The Matrix", year: 1999, poster_path: "/dXNAPwY7VrqMAo51EKhhCJfaGb5.jpg" },
  { id: 429, title: "Fight Club", year: 1999, poster_path: "/jSziioSwPVrOy9Yow3XhWIBDjq1.jpg" },
  { id: 551, title: "Pulp Fiction", year: 1994, poster_path: "/vQWk5YBFWF4bZaofAbv0tShwBvQ.jpg" },
];

const PLOT_PROMPTS = [
  "A high-stakes heist within layered dreams where physics and reality collapse.",
  "Atmospheric neo-noir detective chasing answers in a neon cyberpunk metropolis.",
  "Deep space expedition testing the boundaries of time, love, and human survival.",
  "A razor-sharp psychological chess match between a detective and an enigmatic criminal.",
];

export default function HeroExplore({ query, setQuery, onSubmit, loading }) {
  const plotLength = (query.plotText || "").length;
  const isPlotValid = plotLength === 0 || (plotLength >= 30 && plotLength <= 1000);
  const readyToSubmit = canSubmit(query) && isPlotValid && !loading;

  function set(patch) {
    setQuery((prev) => ({ ...prev, ...patch }));
  }

  function toggleMovie(movie) {
    const exists = query.movies.some((m) => m.id === movie.id);
    if (exists) {
      set({ movies: query.movies.filter((m) => m.id !== movie.id) });
    } else {
      set({ movies: [...query.movies, movie] });
    }
  }

  function movieYear(m) {
    return m.year ?? m.release_year ?? (m.release_date ? m.release_date.slice(0, 4) : "");
  }

  return (
    <div className="hero-explore-container">
      {/* Cinematic Banner with Vibrant Widescreen Backdrop Image */}
      <div className="hero-banner">
        <div className="hero-banner-bg" aria-hidden="true">
          <img
            src={bgGoldenHorizon}
            alt=""
            className="hero-banner-img"
            referrerPolicy="no-referrer"
          />
        </div>
        <div className="hero-banner-overlay" />
        <div className="hero-banner-content">
          <p className="hero-kicker">Dual-Signal Cinema Intelligence</p>
          <h2 className="hero-headline">Discover Movies You&apos;ll Truly Love</h2>
          <p className="hero-subheading">
            DualLens synthesizes <strong>thematic metadata tags</strong> with <strong>semantic plot narratives</strong> to deliver calibrated, personalized recommendations with zero guesswork.
          </p>
        </div>
      </div>

      {/* Prominent Search Console for Desktop */}
      <div className="hero-search-console">
        <div className="hero-console-head">
          <h3 className="hero-section-title">Configure Your Cinema Signals</h3>
          <p className="hero-section-sub">Choose anchor movies you enjoy or describe a specific storyline you're in the mood for.</p>
        </div>

        <div className="hero-console-fields">
          {/* Movie Search Dropdown */}
          <div className="hero-field">
            <label htmlFor="hero-movie-search" className="hero-field-label">
              <span>Movies you like</span>
              <span className="hero-field-hint">Anchor signals</span>
            </label>
            <AsyncCombobox
              id="hero-movie-search"
              label="Search movies"
              placeholder="Search by title (e.g. Inception, Interstellar, The Matrix...)"
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
            {query.movies.length > 0 && (
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
            )}
          </div>

          {/* Plot Textarea */}
          <div className="hero-field">
            <div className="hero-field-header">
              <label htmlFor="hero-plot-text" className="hero-field-label">
                <span>Describe the plot you want (optional)</span>
              </label>
              <span className={`char-counter ${plotLength > 1000 ? "error" : ""}`}>
                {plotLength}/1000
              </span>
            </div>
            <textarea
              id="hero-plot-text"
              name="heroPlotText"
              rows={3}
              placeholder="Describe a plot premise, atmosphere, or twist (e.g. A retired investigator takes one last case that leads into a digital conspiracy...)"
              value={query.plotText || ""}
              onChange={(e) => set({ plotText: e.target.value })}
            />
            
            {/* Quick Plot Inspiration Prompts */}
            <div className="hero-prompt-suggestions">
              <span className="hero-prompts-label">Try an idea:</span>
              <div className="hero-prompts-list">
                {PLOT_PROMPTS.map((prompt, idx) => (
                  <button
                    key={idx}
                    type="button"
                    className="hero-prompt-chip"
                    onClick={() => set({ plotText: prompt })}
                  >
                    "{prompt}"
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Action Button */}
        <div className="hero-action-row">
          <button
            type="button"
            className="primary hero-submit-btn"
            disabled={!readyToSubmit}
            onClick={() => {
              if (readyToSubmit) onSubmit?.();
            }}
          >
            {loading ? "Computing Dual Signals…" : "Find Movies with DualLens →"}
          </button>
          {!canSubmit(query) && (
            <span className="hero-action-hint">
              Select at least one movie seed above or describe a plot to start.
            </span>
          )}
        </div>
      </div>

      {/* Featured Movie Photo Seeds */}
      <div className="hero-featured-section">
        <div className="featured-backdrop-wrap" aria-hidden="true">
          <img
            src={bgEmeraldRainforest}
            alt=""
            className="featured-backdrop-img"
            referrerPolicy="no-referrer"
          />
          <div className="featured-backdrop-scrim" />
        </div>
        <div className="featured-section-header">
          <div>
            <h3 className="hero-section-title">Popular Anchor Seeds</h3>
            <p className="hero-section-sub">Click any poster to instantly add or remove it from your recommendation anchors.</p>
          </div>
        </div>

        <div className="featured-movie-grid">
          {FEATURED_SEEDS.map((movie) => {
            const isSelected = query.movies.some((m) => m.id === movie.id);
            return (
              <button
                key={movie.id}
                type="button"
                className={`featured-movie-card ${isSelected ? "selected" : ""}`}
                onClick={() => toggleMovie(movie)}
                aria-pressed={isSelected}
              >
                <div className="featured-poster-wrap">
                  <MoviePoster
                    path={movie.poster_path}
                    title={movie.title}
                    size="w500"
                    className="featured-poster"
                  />
                  <div className="featured-badge-indicator">
                    {isSelected ? "✓ Added" : "+ Add"}
                  </div>
                </div>
                <div className="featured-movie-info">
                  <span className="featured-movie-title">{movie.title}</span>
                  <span className="featured-movie-year">{movie.year}</span>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* How Dual Signals Work Explainer Bar */}
      <div className="hero-dual-signals-explainer">
        <div className="explainer-item">
          <div className="explainer-icon tag-signal-icon">
            <span>#1</span>
          </div>
          <div className="explainer-text">
            <strong>Thematic Tags Signal</strong>
            <p>Analyzes director styles, cast chemistry, subgenres, and keywords.</p>
          </div>
        </div>

        <div className="explainer-divider" />

        <div className="explainer-item">
          <div className="explainer-icon plot-signal-icon">
            <span>#2</span>
          </div>
          <div className="explainer-text">
            <strong>Semantic Plot Signal</strong>
            <p>Compares narrative arcs, pacing, emotional tone, and premise embeddings.</p>
          </div>
        </div>

        <div className="explainer-divider" />

        <div className="explainer-item">
          <div className="explainer-icon combined-signal-icon">
            <span>★</span>
          </div>
          <div className="explainer-text">
            <strong>DualLens Match Score</strong>
            <p>Weighted convergence delivering accurate, transparent recommendations.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
