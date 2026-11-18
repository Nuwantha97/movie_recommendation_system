# app/services/query_builder.py
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
import scipy.sparse as sp
from sklearn.preprocessing import normalize

from app.config import settings
from app.db import queries
from app.schemas import RecommendRequest
from app.stores import artifacts, chroma, text_embedder
from app.services.soup import TIERS, build_tier_docs, squash

log = logging.getLogger(__name__)

CHIP_WEIGHT = 1.0   # relative weight of the tag-chip part vs the movie part


class EmptyQueryError(ValueError):
    """No usable tag or plot signal could be built. Map to HTTP 422."""


@dataclass
class Query:
    tag_sparse: sp.csr_matrix | None      # (1, V) L2-normalized, exact scoring
    tag_ann: np.ndarray | None            # (n_components,) float32 L2-normalized, ANN
    plot_centroid: np.ndarray | None      # (384,) float32 L2-normalized plot query vector
    movie_ids: list[int]
    chips: list[dict]
    missing_tag_ids: list[int] = field(default_factory=list)    # selected movies with no tag row
    missing_plot_ids: list[int] = field(default_factory=list)   # selected movies with no plot embedding
    plot_text: str | None = None
    tag_full_sims: np.ndarray | None = None
    exact_tags: tuple[np.ndarray, np.ndarray] | None = None  # movie IDs and matched fractions
    exact_tag_weight: float = 0.0


def _movie_tag_part(movie_ids: list[int]):
    if not movie_ids:
        return None, []
    rows = artifacts.tag_rows_for(movie_ids)
    usable = rows >= 0
    usable[usable] = artifacts.row_norms()[rows[usable]] > 0
    missing = [mid for mid, ok in zip(movie_ids, usable) if not ok]
    rows = rows[usable]
    if not len(rows):
        return None, missing
    m = normalize(artifacts.tag_matrix()[rows], norm="l2")        # per-movie unit rows
    mean = sp.csr_matrix(np.full((1, len(rows)), 1.0 / len(rows))) @ m
    mean = normalize(mean, norm="l2")
    return (mean if mean.nnz else None), missing


def _chip_part(chips: list[dict]):
    if not chips:
        return None
    fields: dict[str, list[str]] = defaultdict(list)
    for c in chips:
        fields[c["tag_type"]].append(c["name"])

    docs = build_tier_docs(fields)                                # same code path as offline
    blocks = [v.transform([d]) for v, d in zip(artifacts.vectorizers(), docs)]
    vec = sp.hstack(blocks, format="csr")
    if vec.nnz == 0:                                              # chips not in vocabulary
        return None
    return normalize(vec, norm="l2")


def _exact_tag_part(chips: list[dict], has_movie_tags: bool):
    """Resolve chips missing from the fitted vocabulary against the catalog."""
    if not chips:
        return None, 0.0
    vocab = {f: v.vocabulary_ for tier, v in zip(TIERS, artifacts.vectorizers()) for f in tier}
    missing = defaultdict(set)
    for chip in chips:
        field, name = chip["tag_type"], chip["name"]
        if squash(name) not in vocab[field]:
            missing[field].add(name.strip().lower())
    if not missing:
        return None, 0.0
    hits = queries.exact_tag_hits(missing)
    if not hits:
        return None, 0.0
    count = sum(len(names) for names in missing.values())
    ids = np.fromiter(hits, dtype=np.int64, count=len(hits))
    fractions = np.fromiter(hits.values(), dtype=np.float32, count=len(hits)) / count
    # Split the tag signal proportionally between model inputs and catalog-only chips.
    weight = count / (len(chips) + int(has_movie_tags))
    return (ids, fractions), weight


def _plot_centroid(movie_ids: list[int]):
    if not movie_ids:
        return None, []
    embs = chroma.get_plot_embeddings(movie_ids)                  # {id: np.ndarray}
    missing = [i for i in movie_ids if i not in embs]

    # Suppress boilerplate plots from centroid calculation
    if settings.suppress_boilerplate_plots and embs:
        suppressed_mask = artifacts.plot_suppressed()
        plot_idx = artifacts.plot_index()
        suppressed_ids = []
        for mid in list(embs.keys()):
            row = plot_idx.get(mid)
            if row is not None and suppressed_mask[row]:
                suppressed_ids.append(mid)
                del embs[mid]
        if suppressed_ids:
            missing.extend(suppressed_ids)
            log.warning("suppressed %d boilerplate seed plot(s): %s",
                        len(suppressed_ids), suppressed_ids)

    if not embs:
        return None, missing
    c = np.mean(np.stack(list(embs.values())), axis=0, keepdims=True)
    c = normalize(c, norm="l2")[0].astype(np.float32)
    return c, missing


def build(req: RecommendRequest, timings: dict | None = None) -> Query:
    movie_ids = list(dict.fromkeys(req.movie_ids))                # dedupe, keep order
    chips = [{"tag_type": t.tag_type, "name": t.name} for t in req.tags]

    # tag_part: movie sparse mean + chips + SVD transform
    t0 = time.perf_counter()
    movie_part, missing_tag = _movie_tag_part(movie_ids)
    chip_part = _chip_part(chips)
    exact_tags, exact_weight = _exact_tag_part(chips, has_movie_tags=movie_part is not None)

    tag_sparse = None
    parts = []
    if movie_part is not None:
        parts.append(movie_part)
    if chip_part is not None:
        parts.append(chip_part * CHIP_WEIGHT)
    if parts:
        tag_sparse = normalize(sum(parts[1:], parts[0]), norm="l2")

    tag_ann = None
    if tag_sparse is not None and not settings.use_matvec_tag_candidates:
        red = artifacts.svd_transform_sparse(tag_sparse)          # (1, n_components) float64
        tag_ann = normalize(red, norm="l2")[0].astype(np.float32)
    tag_time = round(time.perf_counter() - t0, 4)
    if timings is not None:
        timings["tag_part"] = tag_time
    log.debug("timing tag_part=%.4fs", tag_time)

    # plot_centroid
    t0 = time.perf_counter()
    movie_centroid, missing_plot = _plot_centroid(movie_ids)
    centroid_time = round(time.perf_counter() - t0, 4)
    if timings is not None:
        timings["plot_centroid"] = centroid_time
    log.debug("timing plot_centroid=%.4fs", centroid_time)

    # embed_plot_text
    t0 = time.perf_counter()
    text_emb = None
    if req.plot_text:
        text_emb = text_embedder.embed_plot_text(req.plot_text)
    plot_text_time = round(time.perf_counter() - t0, 4)
    if timings is not None:
        timings["embed_plot_text"] = plot_text_time
    log.debug("timing embed_plot_text=%.4fs", plot_text_time)

    plot_query = None
    if text_emb is not None and movie_centroid is not None:
        combo = 0.5 * text_emb + 0.5 * movie_centroid
        plot_query = normalize(combo.reshape(1, -1), norm="l2")[0].astype(np.float32)
    elif text_emb is not None:
        plot_query = text_emb
    elif movie_centroid is not None:
        plot_query = movie_centroid

    if tag_sparse is None and plot_query is None and exact_tags is None:
        raise EmptyQueryError(
            "No usable signal: selected movies have no tags/plot data, "
            "no plot text was provided, and the tag chips matched nothing in the vocabulary."
        )

    return Query(
        tag_sparse=tag_sparse,
        tag_ann=tag_ann,
        plot_centroid=plot_query,
        movie_ids=movie_ids,
        chips=chips,
        missing_tag_ids=missing_tag,
        missing_plot_ids=missing_plot,
        plot_text=req.plot_text,
        exact_tags=exact_tags,
        exact_tag_weight=exact_weight,
    )
