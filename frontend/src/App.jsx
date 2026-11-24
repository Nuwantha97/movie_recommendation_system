import { useEffect, useRef, useState } from "react";
import QueryPanel from "./components/QueryPanel";
import HeroBanner from "./components/HeroBanner";
import Results from "./components/Results";
import MovieDetail from "./components/MovieDetail";
import Logo from "./components/Logo";
import Footer from "./components/Footer";
import bgFestivalTerrace from "./assets/images/bg_festival_terrace.jpg";
import { isAbort, recommend, recommendPage, recommendExplanations } from "./api";
import { INITIAL_QUERY, SELECTION_LIMITS, addSelection, buildRequest, canSubmit, withinSelectionLimits } from "./query";

const STORAGE_PREFIX = "mf_movie_";
const RESULTS_KEY = "mf_last_results";
const PAGE_SIZE = 20;

function getRouteFromLocation() {
  // Check hash first: #/movie/123 or #movie/123
  const hash = window.location.hash.replace(/^#\/?/, "");
  if (hash.startsWith("movie/")) {
    const id = hash.replace("movie/", "").trim();
    if (id) return { page: "movie", movieId: id };
  }

  // Check pathname: /movie/123
  const path = window.location.pathname;
  const match = path.match(/\/movie\/([^/?#]+)/);
  if (match) {
    return { page: "movie", movieId: match[1] };
  }

  return { page: "home", movieId: null };
}

function saveMovieToCache(id, data) {
  try {
    sessionStorage.setItem(`${STORAGE_PREFIX}${id}`, JSON.stringify(data));
  } catch {
    /* ignore storage errors */
  }
}

function getMovieFromCache(id) {
  try {
    const raw = sessionStorage.getItem(`${STORAGE_PREFIX}${id}`);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function saveResultsToCache(data) {
  try {
    sessionStorage.setItem(RESULTS_KEY, JSON.stringify(data));
    if (data?.pages) {
      for (const pageItems of Object.values(data.pages)) {
        if (Array.isArray(pageItems)) {
          for (const item of pageItems) {
            const id = item.movie?.id ?? item.movie_id ?? item.id;
            if (id) saveMovieToCache(id, item);
          }
        }
      }
    }
  } catch {
    /* ignore */
  }
}

function getResultsFromCache() {
  try {
    const raw = sessionStorage.getItem(RESULTS_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export default function App() {
  const [route, setRoute] = useState(() => getRouteFromLocation());
  const [selectedMovie, setSelectedMovie] = useState(() => {
    const r = getRouteFromLocation();
    return r.movieId ? getMovieFromCache(r.movieId) : null;
  });

  const [query, setQuery] = useState(INITIAL_QUERY);
  const [backendErrors, setBackendErrors] = useState({});
  const [state, setState] = useState(() => {
    // If we have cached results in session, initialize with them
    const cached = getResultsFromCache();
    if (cached && cached.total > 0) {
      return {
        status: "done",
        error: "",
        requestId: cached.requestId ?? null,
        total: cached.total ?? 0,
        body: cached.body ?? null,
        warnings: cached.warnings ?? [],
        page: cached.page ?? 1,
        pages: cached.pages ?? {},
        pageLoading: false,
        explaining: {},
      };
    }
    return {
      status: "idle",
      error: "",
      requestId: null,
      total: 0,
      body: null,
      page: 1,
      pages: {},
      pageLoading: false,
      explaining: {},
    };
  });

  const abortRef = useRef(null);
  const resultsRef = useRef(null);

  // Listen for browser Back/Forward buttons and Hash changes
  useEffect(() => {
    function handleLocationChange() {
      const nextRoute = getRouteFromLocation();
      setRoute(nextRoute);

      if (nextRoute.page === "movie" && nextRoute.movieId) {
        const cached = getMovieFromCache(nextRoute.movieId);
        if (cached) setSelectedMovie(cached);
      } else {
        setSelectedMovie(null);
      }
    }

    window.addEventListener("popstate", handleLocationChange);
    window.addEventListener("hashchange", handleLocationChange);
    return () => {
      window.removeEventListener("popstate", handleLocationChange);
      window.removeEventListener("hashchange", handleLocationChange);
    };
  }, []);

  // Persist when status is "done" and pages/page change
  useEffect(() => {
    if (state.status === "done") {
      saveResultsToCache({
        requestId: state.requestId,
        total: state.total,
        body: state.body,
        warnings: state.warnings,
        page: state.page,
        pages: state.pages,
      });
    }
  }, [state.status, state.requestId, state.total, state.body, state.warnings, state.page, state.pages]);

  function navigateToMovie(movieItem) {
    const id = movieItem.movie?.id ?? movieItem.movie_id ?? movieItem.id;
    if (!id) return;

    saveMovieToCache(id, movieItem);
    setSelectedMovie(movieItem);
    setRoute({ page: "movie", movieId: String(id) });

    const newUrl = `/movie/${id}`;
    if (window.location.pathname !== newUrl) {
      window.history.pushState({ page: "movie", movieId: id }, "", newUrl);
    }
  }

  function navigateToHome() {
    setSelectedMovie(null);
    setRoute({ page: "home", movieId: null });

    if (window.location.pathname !== "/" || window.location.hash) {
      window.history.pushState({ page: "home" }, "", "/");
    }
  }

  function handleSeedMovie(movie) {
    if (!movie?.id) return;
    setQuery((q) => {
      if (q.movies.some((m) => String(m.id) === String(movie.id))) {
        return q;
      }
      return addSelection(q, "movies", {
        id: movie.id,
        title: movie.title || "Movie",
        year: movie.year ?? movie.release_year ?? null,
        poster_path: movie.poster_path ?? movie.movie?.poster_path ?? null,
      });
    });
    navigateToHome();
  }

  async function loadExplanations(p, requestId, items, signal, body) {
    if (items.every((m) => m.explanation)) return;
    setState((s) => ({ ...s, explaining: { ...s.explaining, [p]: true } }));
    try {
      const map = await recommendExplanations(requestId, (p - 1) * PAGE_SIZE, PAGE_SIZE, signal);
      if (signal.aborted) return;
      setState((s) => ({
        ...s,
        explaining: { ...s.explaining, [p]: false },
        pages: {
          ...s.pages,
          [p]: (s.pages[p] ?? items).map((m) => ({
            ...m,
            explanation: m.explanation ?? map[m.movie_id] ?? map[m.movie?.id] ?? null,
          })),
        },
      }));
    } catch (err) {
      if (signal.aborted || isAbort(err)) return;
      if (err.status === 410) {
        await submit(body);
        return;
      }
      setState((s) => ({ ...s, explaining: { ...s.explaining, [p]: false } }));
    }
  }

  async function goToPage(p) {
    // Restored sessions get a controller on their first page request.
    abortRef.current ??= new AbortController();
    const { signal } = abortRef.current;
    resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    const have = state.pages[p];
    if (have) {
      // revisit: no request unless explanations failed earlier
      setState((s) => ({ ...s, page: p }));
      loadExplanations(p, state.requestId, have, signal, state.body);
      return;
    }
    setState((s) => ({ ...s, page: p, pageLoading: true }));
    try {
      const r = await recommendPage(state.requestId, (p - 1) * PAGE_SIZE, PAGE_SIZE, signal);
      if (signal.aborted) return;
      setState((s) => ({ ...s, pageLoading: false, pages: { ...s.pages, [p]: r.items } }));
      loadExplanations(p, state.requestId, r.items, signal, state.body);
    } catch (err) {
      if (signal.aborted || isAbort(err)) return;
      if (err.status === 410) {
        await submit(state.body);
        return;
      } // cache expired: rebuild from page 1
      setState((s) => ({ ...s, pageLoading: false }));
    }
  }

  async function submit(customBody) {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setBackendErrors({});
    setState((s) => ({ ...s, status: "loading", error: "" }));

    if (window.matchMedia("(max-width: 900px)").matches) {
      resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    try {
      const isCustom =
        customBody &&
        typeof customBody === "object" &&
        !customBody.nativeEvent &&
        !customBody._reactName;
      const body = isCustom
        ? customBody
        : (canSubmit(query) ? buildRequest(query) : state.body) || buildRequest(query);
      if (!withinSelectionLimits({ ...body, movies: body.movie_ids, languages: body.original_language })) {
        throw new Error("This search exceeds the selection limits. Choose fewer items and search again.");
      }
      const r = await recommend(body, controller.signal);
      if (controller.signal.aborted) return;
      setState({
        status: "done",
        error: "",
        requestId: r.requestId,
        total: r.total,
        warnings: r.warnings,
        body,
        page: 1,
        pages: { 1: r.items },
        pageLoading: false,
        explaining: {},
      });
      loadExplanations(1, r.requestId, r.items, controller.signal, body);
    } catch (err) {
      if (controller.signal.aborted || isAbort(err)) return;
      if (err.fieldErrors) {
        setBackendErrors(err.fieldErrors);
      }
      setState((s) => ({
        ...s,
        status: "error",
        error: err.message || "Something went wrong.",
      }));
    }
  }

  function clearResults() {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setState({
      status: "idle",
      error: "",
      requestId: null,
      total: 0,
      body: null,
      page: 1,
      pages: {},
      pageLoading: false,
      explaining: {},
    });
    try {
      sessionStorage.removeItem(RESULTS_KEY);
    } catch {
      /* ignore */
    }
  }

  function clearFilters() {
    setQuery((q) => ({ ...q, languages: [], genres: [], dateFrom: "", dateTo: "" }));
    clearResults();
  }

  return (
    <div className="app">
      <div className="app-backdrop" aria-hidden="true">
        <img
          src={bgFestivalTerrace}
          alt=""
          className="app-backdrop-img"
          referrerPolicy="no-referrer"
        />
        <div className="app-backdrop-scrim" />
      </div>

      <header className="site-header">
        <div className="header-inner">
          <div className="header-brand-group">
            <h1>
              <a
                href="/"
                className="brand-link"
                onClick={(e) => {
                  e.preventDefault();
                  navigateToHome();
                }}
              >
                <Logo size={40} />
                <div className="brand-titles">
                  <span className="brand-wordmark">DualLens</span>
                  <span className="brand-subtitle">Dual-Signal Movie Recommendation System</span>
                </div>
              </a>
            </h1>
          </div>
          <div className="header-signals-legend" aria-label="Recommendation signals">
            <span className="legend-tag">Tags Signal</span>
            <span className="legend-sep" aria-hidden="true">·</span>
            <span className="legend-plot">Plot Signal</span>
          </div>
        </div>
      </header>

      {route.page === "movie" ? (
        <main className="layout-detail">
          <MovieDetail
            key={route.movieId}
            movieId={route.movieId}
            initialMovie={selectedMovie}
            onBack={navigateToHome}
            onSeedMovie={handleSeedMovie}
            seedDisabled={query.movies.length >= SELECTION_LIMITS.movies}
          />
        </main>
      ) : (
        <main className="layout">
          {state.status === "idle" && <HeroBanner />}
          <QueryPanel
            query={query}
            setQuery={setQuery}
            onClearAll={() => {
              setQuery(INITIAL_QUERY);
              setBackendErrors({});
            }}
            onSubmit={submit}
            loading={state.status === "loading"}
            backendErrors={backendErrors}
            onClearBackendError={(field) =>
              setBackendErrors((prev) => {
                const next = { ...prev };
                delete next[field];
                return next;
              })
            }
          />
          <section className="results" ref={resultsRef} aria-live="polite">
            {state.status === "done" && state.warnings?.map((warning) => (
              <p key={warning} className="note">{warning}</p>
            ))}
            <Results
              state={state}
              query={query}
              setQuery={setQuery}
              onSubmit={submit}
              loading={state.status === "loading"}
              onClearResults={clearResults}
              onClearFilters={clearFilters}
              onRetry={submit}
              onSelectMovie={navigateToMovie}
              onPageChange={goToPage}
            />
          </section>
        </main>
      )}
      <Footer hasStickySubmit={route.page !== "movie"} />
    </div>
  );
}
