import { useState } from "react";
import { getPosterUrl } from "../poster";

export default function MoviePoster({
  path,
  title,
  size = "w500",
  className = "",
  width,
  height,
}) {
  const [hasError, setHasError] = useState(false);
  const url = getPosterUrl(path, size);
  const isCompact = className.includes("thumb") || className.includes("chip-poster");

  const imgWidth =
    width ??
    (className.includes("thumb") ? 40 : className.includes("chip-poster") ? 24 : undefined);
  const imgHeight =
    height ??
    (className.includes("thumb") ? 60 : className.includes("chip-poster") ? 36 : undefined);

  if (!url || hasError) {
    return (
      <div
        className={`card-poster placeholder ${className}`.trim()}
        aria-label={title ? `No poster for ${title}` : "No poster available"}
        style={imgWidth && imgHeight ? { width: imgWidth, height: imgHeight } : undefined}
      >
        <svg
          className="poster-fallback-icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          aria-hidden="true"
        >
          <rect x="2" y="3" width="20" height="18" rx="2" />
          <line x1="7" y1="3" x2="7" y2="21" />
          <line x1="17" y1="3" x2="17" y2="21" />
          <line x1="2" y1="12" x2="22" y2="12" />
          <line x1="2" y1="7" x2="7" y2="7" />
          <line x1="2" y1="17" x2="7" y2="17" />
          <line x1="17" y1="17" x2="22" y2="17" />
          <line x1="17" y1="7" x2="22" y2="7" />
        </svg>
        {!isCompact && <span className="poster-fallback-text">No poster</span>}
      </div>
    );
  }

  return (
    <div
      className={`card-poster ${className}`.trim()}
      style={imgWidth && imgHeight ? { width: imgWidth, height: imgHeight } : undefined}
    >
      <img
        src={url}
        alt={title ? `${title} poster` : "Movie poster"}
        className="poster-img"
        width={imgWidth}
        height={imgHeight}
        loading="lazy"
        decoding="async"
        onError={() => setHasError(true)}
      />
    </div>
  );
}
