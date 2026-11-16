import Logo from "./Logo";

const SPONSOR_URL = "https://github.com/sponsors/Nuwantha97";
const GITHUB_REPO_URL = "https://github.com/";

export default function Footer({ hasStickySubmit = false }) {
  return (
    <footer className={`site-footer ${hasStickySubmit ? "with-sticky-bar" : ""}`.trim()}>
      <div className="footer-inner">
        <div className="footer-brand">
          <div className="footer-brand-title">
            <Logo size={26} className="footer-logo" />
            <strong>DualLens</strong>
          </div>
          <p className="footer-tagline">
            Dual-Signal Movie Recommendation System.
          </p>
        </div>

        <p className="footer-credit">
          This product uses the{" "}
          <a href="https://www.themoviedb.org" target="_blank" rel="noopener noreferrer">
            TMDB
          </a>{" "}
          API but is not endorsed or certified by TMDB.
        </p>

        <div className="footer-actions">
          {/* Official alternative: <iframe src="https://github.com/sponsors/Nuwantha97/button" title="Sponsor Nuwantha97" height="32" width="114" loading="lazy" style="border:0;border-radius:6px;"> */}
          <a
            href={SPONSOR_URL}
            className="sponsor-btn"
            target="_blank"
            rel="noopener noreferrer"
          >
            <svg
              className="heart-icon"
              viewBox="0 0 16 16"
              width="14"
              height="14"
              fill="currentColor"
              aria-hidden="true"
            >
              <path d="M8 14.25l-1.04-.96C3.28 9.96 1 7.89 1 5.34 1 3.27 2.61 1.75 4.65 1.75c1.16 0 2.27.54 3.35 1.48 1.08-.94 2.19-1.48 3.35-1.48 2.04 0 3.65 1.52 3.65 3.59 0 2.55-2.28 4.62-5.96 7.95L8 14.25z" />
            </svg>
            <span>Sponsor</span>
          </a>
          <a
            href={GITHUB_REPO_URL}
            className="github-btn"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="View on GitHub"
          >
            <svg
              className="github-icon"
              viewBox="0 0 16 16"
              width="14"
              height="14"
              fill="currentColor"
              aria-hidden="true"
            >
              <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
            </svg>
            <span>GitHub</span>
          </a>
        </div>
      </div>
    </footer>
  );
}
