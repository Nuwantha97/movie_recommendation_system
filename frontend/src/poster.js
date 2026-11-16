export function getPosterUrl(posterPath, size = "w500") {
  if (!posterPath || typeof posterPath !== "string") return null;
  const trimmed = posterPath.trim();
  if (!trimmed) return null;
  if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
    return trimmed;
  }
  const cleanPath = trimmed.replace(/^\/+/, "");
  return `https://image.tmdb.org/t/p/${size}/${cleanPath}`;
}
