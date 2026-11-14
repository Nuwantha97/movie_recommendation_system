import { hasFilters } from "../query";
import MoviePoster from "./MoviePoster";
import ScoreBar from "./ScoreBar";
import Pagination from "./Pagination";
import HeroExplore from "./HeroExplore";

const tagName = (t) => (typeof t === "string" ? t : t?.name ?? "");

function MovieCard({ movie, rank, explaining, onSelect }) {
  const overlap = (movie.overlapping_tags ?? []).map(tagName).filter(Boolean);
  const title = movie.movie?.title ?? movie.title ?? "Untitled";
  const rawYear = movie.movie?.release_date ? movie.movie.release_date.slice(0, 4) : null;
  const year = rawYear ?? movie.release_year ?? movie.year ?? movie.movie?.release_year;
  const posterPath = movie.movie?.poster_path ?? movie.poster_path;

  function handleClick(e) {
    if (e.target.closest("details") || e.target.closest("button")) {
      return;
    }
    onSelect?.(movie);
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect?.(movie);
    }
  }

  return (
    <li
      className="card card-clickable"
      tabIndex={0}
      role="button"
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      aria-label={`View details for ${title}`}
    >
      <MoviePoster path={posterPath} title={title} />
      <div className="card-body">
        <div className="card-head">
          <div className="card-title-group">
            <span className="rank">{rank}</span>
            <h3 className="card-title-link">{title}</h3>
            {year ? <span className="year">({year})</span> : null}
          </div>
          {typeof movie.final_score === "number" && (
            <span className="final">{movie.final_score.toFixed(2)}</span>
          )}
        </div>
        <div className="scores">
          <ScoreBar label="Tags" value={movie.tag_score} kind="tag" />
          <ScoreBar label="Plot" value={movie.plot_score} kind="plot" />
        </div>
        {movie.explanation
          ? <p className="explanation">{movie.explanation}</p>
          : explaining ? <div className="sk sk-text" /> : null}
        {overlap.length > 0 && (
          <details onClick={(e) => e.stopPropagation()}>
            <summary>Shared tags ({overlap.length})</summary>
            <p className="overlap">{overlap.join(", ")}</p>
          </details>
        )}
        <div className="card-action-bar">
          <span className="card-action-text">
            View details &amp; plot <span aria-hidden="true">&rarr;</span>
          </span>
        </div>
      </div>
    </li>
  );
}

function Skeleton() {
  return (
    <ul className="cards" aria-busy="true" aria-label="Loading recommendations">
      {Array.from({ length: 5 }).map((_, i) => (
        <li key={i} className="card skeleton">
          <div className="sk sk-poster" />
          <div className="card-body">
            <div className="sk sk-title" />
            <div className="sk sk-bar" />
            <div className="sk sk-bar short" />
            <div className="sk sk-text" />
          </div>
        </li>
      ))}
    </ul>
  );
}

export default function Results({
  state,
  query,
  setQuery,
  onSubmit,
  loading,
  onClearResults,
  onClearFilters,
  onRetry,
  onSelectMovie,
  onPageChange,
}) {
  const { status, error, pages, page, total, pageLoading, explaining } = state;
  const items = pages?.[page] ?? [];
  const totalPages = Math.ceil((total || 0) / 20);

  if (status === "idle") {
    if (setQuery) {
      return (
        <HeroExplore
          query={query}
          setQuery={setQuery}
          onSubmit={onSubmit}
          loading={loading}
        />
      );
    }
    return (
      <div className="empty">
        <h2>Find something you have not seen</h2>
        <p>
          Pick a few movies you like, or search for a director, actor or keyword. Then choose how
          much plot and tags should count.
        </p>
      </div>
    );
  }

  if (status === "loading") return <Skeleton />;

  if (status === "error") {
    return (
      <div className="empty error-box" role="alert">
        <h2>Could not get recommendations</h2>
        <p>{error}</p>
        <button type="button" className="secondary" onClick={onRetry}>
          Try again
        </button>
      </div>
    );
  }

  if (total === 0) {
    return (
      <div className="empty">
        <h2>No movies match</h2>
        <p>
          {hasFilters(query)
            ? "Your filters left nothing to rank. Widen the date range or remove a language or genre."
            : "Nothing came back. Try different movies or tags."}
        </p>
        <div style={{ display: "flex", gap: "8px", justifyContent: "center", marginTop: "12px", flexWrap: "wrap" }}>
          {hasFilters(query) && (
            <button type="button" className="secondary" onClick={onClearFilters}>
              Clear filters
            </button>
          )}
          {onClearResults && (
            <button type="button" className="secondary" onClick={onClearResults}>
              Clean results
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="results-header">
        <h2 className="results-title">
          <span className="results-count-badge">{total}</span>
          <span>recommendations</span>
          <span className="results-page-badge">Page {page} of {totalPages}</span>
        </h2>
        {onClearResults && (
          <button
            type="button"
            className="clean-results-btn"
            onClick={onClearResults}
            aria-label="Clean results and return to explore"
            title="Clean results and return to explore"
          >
            <svg
              className="clean-icon"
              viewBox="0 0 20 20"
              width="14"
              height="14"
              fill="currentColor"
              aria-hidden="true"
            >
              <path
                fillRule="evenodd"
                d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
                clipRule="evenodd"
              />
            </svg>
            <span>Clean results</span>
          </button>
        )}
      </div>
      {pageLoading ? <Skeleton /> : (
        <ul className="cards">
          {items.map((m, i) => (
            <MovieCard
              key={m.movie_id}
              movie={m}
              rank={(page - 1) * 20 + i + 1}
              explaining={explaining?.[page]}
              onSelect={onSelectMovie}
            />
          ))}
        </ul>
      )}
      <Pagination page={page} totalPages={totalPages} onChange={onPageChange} disabled={pageLoading} />
    </>
  );
}
